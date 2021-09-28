import os
import json
import aiohttp
import aio_pika
import asyncio
from distutils.util import strtobool
from aio_pika.pool import Pool
from jinja2 import Template


async def run(loop, logger=None, config=None, worker_pool_size=10):

    async def _get_rabbitmq_channel():
        async with rabbitmq_connection_pool.acquire() as connection:
            return await connection.channel()

    async def _get_rabbitmq_connection():
        return await aio_pika.connect(
            host=config.get("mq_host"),
            port=config.get("mq_port"),
            login=config.get("mq_user"),
            password=config.get("mq_pass"),
            virtualhost=config.get("mq_vhost"),
            loop=loop
        )

    async def _publish(message):
        async with rabbitmq_channel_pool.acquire() as channel:
            exchange = await channel.get_exchange(config.get("mq_target_exchange"))
            await exchange.publish(
                message=aio_pika.Message(message.encode("utf-8")),
                routing_key=config.get("mq_target_routing_key")
            )

            if logger:
                logger.debug(f"Document sent to queue: {message}")

    async def _save_last_index_date(query):
        with open(config.get("last_index_date_file_path"), "w+") as f:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                        f"{config.get('solr_collection_url')}?rows=1&sort={config.get('solr_indexdate_field')} desc",
                        json=query
                ) as resp:
                    r = await resp.json()
                    f.write(r["response"]["docs"][0][config.get('solr_indexdate_field')])

    async def _query_solr(worker_id, query, last_index_date):
        nonlocal offset
        template = Template(template_format, enable_async=True)

        if logger:
            logger.info(f"Worker-{worker_id} started.")

        async with aiohttp.ClientSession() as session:
            while True:
                local_offset = offset
                offset += config.get('solr_fetch_size')
                url = f"{config.get('solr_collection_url')}"

                if last_index_date:
                    url += f"?fq={config.get('solr_indexdate_field')}:[{last_index_date} TO *]"
                    url += f"&rows={config.get('solr_fetch_size')}"
                else:
                    url += f"?rows={config.get('solr_fetch_size')}"

                url += f"&start={local_offset}"
                url += f"&sort={config.get('solr_indexdate_field')} asc"

                try:
                    async with session.post(url=url, json=query) as resp:
                        r = await resp.json()
                        if len(r["response"]["docs"]) == 0:
                            logger.debug("Worker closed, saving last index date...")
                            await _save_last_index_date(query)
                            break
                        else:
                            for doc in r["response"]["docs"]:
                                try:
                                    rendered_data = await template.render_async(doc=doc)
                                except Exception as e:
                                    logger.error(f"Error when rendering template: {e}. Solr document was: {doc}")
                                await _publish(rendered_data)
                except Exception as e:
                    logger.error(f"Solr query or connection error")
                    raise e

    rabbitmq_connection_pool = Pool(_get_rabbitmq_connection, max_size=worker_pool_size, loop=loop)
    rabbitmq_channel_pool = Pool(_get_rabbitmq_channel, max_size=worker_pool_size, loop=loop)

    if config is None:
        config = {
            "mq_host": os.environ.get('MQ_HOST'),
            "mq_port": int(os.environ.get('MQ_PORT', '5672')),
            "mq_vhost": os.environ.get('MQ_VHOST'),
            "mq_user": os.environ.get('MQ_USER'),
            "mq_pass": os.environ.get('MQ_PASS'),
            "mq_target_exchange": os.environ.get('MQ_TARGET_EXCHANGE'),
            "mq_target_routing_key": os.environ.get("MQ_TARGET_ROUTING_KEY"),
            "mq_queue_durable": bool(strtobool(os.environ.get('MQ_QUEUE_DURABLE', 'True'))),
            "solr_collection_url": os.environ.get("SOLR_COLLECTION_URL"),
            "solr_fetch_size": int(os.environ.get("SOLR_FETCH_SIZE"), 20),
            "solr_indexdate_field": os.environ.get("SOLR_INDEXDATE_FIELD"),
            "solr_json_query_file_path": os.environ.get("SOLR_JSON_QUERY_FILE_PATH"),
            "data_template_file_path": os.environ.get("DATA_TEMPLATE_FILE_PATH"),
            "last_index_date_file_path": os.environ.get("LAST_INDEX_DATE_FILE_PATH"),
            "worker_pool_size": os.environ.get("WORKER_POOL_SIZE")
        }

    offset = 0
    template_format = open(config.get("data_template_file_path")).read()

    if "worker_pool_size" in config:
        if config.get("worker_pool_size"):
            try:
                worker_pool_size = int(config.get("worker_pool_size"))
            except TypeError as e:
                if logger:
                    logger.error(f"Invalid pool size: {config.get('worker_pool_size')}")
                raise e

    async with rabbitmq_connection_pool, rabbitmq_channel_pool:
        worker_pool = []
        if logger:
            logger.info("Workers started")

        for i in range(worker_pool_size):
            try:
                with open(config.get("solr_json_query_file_path")) as f:
                    solr_query = f.read()
            except Exception as e:
                raise e

            try:
                with open(config.get("last_index_date_file_path")) as f:
                    last_index_date = f.read()
            except Exception as e:
                last_index_date = None

            worker_pool.append(
                _query_solr(worker_id=i, query=json.loads(solr_query), last_index_date=last_index_date)
            )

        await asyncio.gather(*worker_pool)

