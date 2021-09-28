# solr2rabbitmq

solr2rabbitmq is a job/library that asynchronously format and publish data from Solr query to the RabbitMQ.  


## Installation

You can install this library easily with pip.
`pip install psql2rabbitmq` 

## Usage
### As a library
```py
import os
import asyncio
from psql2rabbitmq import run

if __name__ == '__main__':
    logger = logging.getLogger("solr2rabbitmq")
    logger.setLevel(os.environ.get('LOG_LEVEL', "DEBUG"))
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            os.environ.get('LOG_FORMAT', "%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
    )
    logger.addHandler(handler)
    
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
       "solr_fetch_size": int(os.environ.get("SOLR_FETCH_SIZE")),
       "solr_indexdate_field": os.environ.get("SOLR_INDEXDATE_FIELD"),
       "solr_json_query_file_path": os.environ.get("SOLR_JSON_QUERY_FILE_PATH"),
       "data_template_file_path": os.environ.get("DATA_TEMPLATE_FILE_PATH"),
       "last_index_date_file_path": os.environ.get("LAST_INDEX_DATE_FILE_PATH"),
       "worker_pool_size": os.environ.get("WORKER_POOL_SIZE")
   }

    loop = asyncio.get_event_loop()
    loop.run_until_complete(run(loop=loop, logger=logger, config=config))
```

This library uses [aio_pika](https://aio-pika.readthedocs.io/en/latest/), [aiohttp](https://docs.aiohttp.org/en/stable/) and [jinja2](https://jinja2docs.readthedocs.io/en/stable/) packages.

### Standalone
You can also call this library as standalone job command.  Just set required environment variables and run `psql2rabbitmq`. This usecase perfectly fits when you need run it on cronjobs or kubernetes jobs. 

**Required environment variables:**
- MQ_HOST
- MQ_PORT (optional)
- MQ_VHOST
- MQ_USER
- MQ_PASS
- MQ_TARGET_EXCHANGE
- MQ_TARGET_ROUTING_KEY
- MQ_QUEUE_DURABLE (optional, default value: True)
- SOLR_COLLECTION_URL (ex: `http://solr.local:8983/solr/publication/select`)
- SOLR_FETCH_SIZE (optional, default value: 20)
- SOLR_INDEXDATE_FIELD (field that stored last index datetime)
- SOLR_JSON_QUERY_FILE_PATH (File path contain solr query json Ex: `/home/user/solr_query.json`)
- DATA_TEMPLATE_FILE_PATH (File path contain reqested data template. Ex: `/home/user/template.tpl`)
- LAST_INDEX_DATE_FILE_PATH (File path for storing last indexed date. Ex: `/home/user/last_indexed_date.txt`)
- WORKER_POOL_SIZE (optional, default value: 10)
- LOG_LEVEL (Logging level. See: [Python logging module docs](https://docs.python.org/3/library/logging.html#logging-levels))

**Example Kubernetes job:** 
 You can see it to [kube.yaml](kube.yaml)