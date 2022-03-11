import os
import json
import aiohttp
import aio_pika
import asyncio
from distutils.util import strtobool
from aio_pika.pool import Pool
from aio_pika import DeliveryMode
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

    async def _publish(message, channel, exchange, routing_key):
        ex = await channel.get_exchange(exchange)
        await ex.publish(
            message=aio_pika.Message(message.encode("utf-8"), delivery_mode=DeliveryMode.PERSISTENT),
            routing_key=routing_key
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

    async def _query_solr_and_push(channel_pool, worker_id, query, last_index_date):
        async with channel_pool.acquire() as channel:
            queue = await channel.declare_queue(
                config.get("mq_pagination_queue"), durable=config.get("mq_queue_durable"), auto_delete=False
            )
            template = Template(template_format, enable_async=True)

            if logger:
                logger.info(f"Worker-{worker_id} started.")

            async with aiohttp.ClientSession() as session:
                while True:
                    try:
                        m = await queue.get(timeout=300)
                        offset = m.body.decode('utf-8')
                        url = f"{config.get('solr_collection_url')}"

                        if last_index_date:
                            url += f"?fq={config.get('solr_indexdate_field')}:[{last_index_date} TO *]"
                            url += f"&rows={config.get('solr_fetch_size')}"
                        else:
                            url += f"?rows={config.get('solr_fetch_size')}"

                        url += f"&start={offset}"
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
                                            rendered_data = await template.render_async(doc=doc, json=json)
                                        except Exception as e:
                                            logger.error(
                                                f"Error when rendering template: {e}. Solr document was: {doc}")
                                        await _publish(rendered_data,
                                                       channel,
                                                       config.get("mq_data_exchange"),
                                                       config.get("mq_data_routing_key"))

                            await m.ack()
                        except Exception as e:
                            logger.error(f"Solr query or connection error: {e}")

                    except aio_pika.exceptions.QueueEmpty:
                        if logger:
                            logger.info("Consumer %s: Queue empty. Stopping." % worker_id)
                        break

    async def _publish_paginator(channel_pool, worker_id, fetch_size, step, left=None):
        async with channel_pool.acquire() as channel:
            start = worker_id * step * fetch_size
            end = (worker_id + 1) * step * fetch_size

            for i in range(start, end, fetch_size):
                await _publish(str(i),
                               channel,
                               config.get("mq_pagination_exchange"),
                               config.get("mq_pagination_routing_key"))
            if left:
                for i in range(end, end + left, fetch_size):
                    await _publish(str(i),
                                   channel,
                                   config.get("mq_pagination_exchange"),
                                   config.get("mq_pagination_routing_key"))

    async def _run_consumer_mode(channel_pool):
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
                _query_solr_and_push(channel_pool=channel_pool,
                                     worker_id=i,
                                     query=json.loads(solr_query),
                                     last_index_date=last_index_date)
            )
        await asyncio.gather(*worker_pool)

    async def _run_paginator_mode(channel_pool):

        record_number = 0

        with open(config.get("solr_json_query_file_path")) as f:
            solr_query = f.read()
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    f"{config.get('solr_collection_url')}?rows=0",
                    json=json.loads(solr_query)
            ) as resp:
                r = await resp.json()
                record_number = r["response"]["numFound"]

        fetch_size = config.get("solr_fetch_size")

        bucket_size = fetch_size * worker_pool_size
        round_step = record_number // bucket_size
        round_left = record_number % bucket_size

        for i in range(worker_pool_size):
            if i == worker_pool_size - 1:
                worker_pool.append(_publish_paginator(channel_pool, i, fetch_size, round_step, round_left))
            else:
                worker_pool.append(_publish_paginator(channel_pool, i, fetch_size, round_step))

        await asyncio.gather(*worker_pool)

    rabbitmq_connection_pool = Pool(_get_rabbitmq_connection, max_size=worker_pool_size, loop=loop)
    rabbitmq_channel_pool = Pool(_get_rabbitmq_channel, max_size=worker_pool_size, loop=loop)

    if config is None:
        config = {
            "mq_host": os.environ.get('MQ_HOST'),
            "mq_port": int(os.environ.get('MQ_PORT', '5672')),
            "mq_vhost": os.environ.get('MQ_VHOST'),
            "mq_user": os.environ.get('MQ_USER'),
            "mq_pass": os.environ.get('MQ_PASS'),
            "mq_data_exchange": os.environ.get('MQ_DATA_EXCHANGE'),
            "mq_data_routing_key": os.environ.get("MQ_DATA_ROUTING_KEY"),
            "mq_pagination_exchange": os.environ.get('MQ_PAGINATION_EXCHANGE'),
            "mq_pagination_routing_key": os.environ.get("MQ_PAGINATION_ROUTING_KEY"),
            "mq_pagination_queue": os.environ.get("MQ_PAGINATION_QUEUE"),
            "mq_queue_durable": bool(strtobool(os.environ.get('MQ_QUEUE_DURABLE', 'True'))),
            "solr_collection_url": os.environ.get("SOLR_COLLECTION_URL"),
            "solr_fetch_size": int(os.environ.get("SOLR_FETCH_SIZE")),
            "solr_indexdate_field": os.environ.get("SOLR_INDEXDATE_FIELD"),
            "solr_json_query_file_path": os.environ.get("SOLR_JSON_QUERY_FILE_PATH"),
            "data_template_file_path": os.environ.get("DATA_TEMPLATE_FILE_PATH"),
            "last_index_date_file_path": os.environ.get("LAST_INDEX_DATE_FILE_PATH"),
            "worker_pool_size": os.environ.get("WORKER_POOL_SIZE"),
            "mode": os.environ.get("MODE")
        }

    template_format = open(config.get("data_template_file_path")).read()

    if "worker_pool_size" in config:
        if config.get("worker_pool_size"):
            try:
                worker_pool_size = int(config.get("worker_pool_size"))
            except TypeError as e:
                if logger:
                    logger.error("Invalid pool size: %s" % (worker_pool_size,))
                raise e

    async with rabbitmq_connection_pool, rabbitmq_channel_pool:
        worker_pool = []
        if logger:
            logger.info("Workers started")

        if config.get("mode") == "PAGINATOR":
            await _run_paginator_mode(rabbitmq_channel_pool)
        elif config.get("mode") == "CONSUMER":
            await _run_consumer_mode(rabbitmq_channel_pool)
        else:
            await _run_paginator_mode(rabbitmq_channel_pool)
            worker_pool.clear()
            await _run_consumer_mode(rabbitmq_channel_pool)

