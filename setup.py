import setuptools

setuptools.setup(
    name="solr2rabbitmq",
    version="1.1.5",
    author="Furkan Kalkan",
    author_email="furkankalkan@mantis.com.tr",
    description="Asynchronous RabbitMQ transfer job library from Apache Solr",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    platforms="all",
    url="https://github.com/mantis-software-company/solr2rabbitmq",
    classifiers=[
        "License :: OSI Approved :: Apache Software License",
        "Topic :: Internet",
        "Topic :: Software Development",
        "Topic :: Software Development :: Libraries",
        "Topic :: Software Development :: Testing",
        "Intended Audience :: Developers",
        "Operating System :: MacOS",
        "Operating System :: POSIX",
        "Operating System :: Microsoft",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8"
    ],
    install_requires=['aiohttp', 'aio_pika', 'jinja2'],
    python_requires=">3.6.*, <4",
    packages=['solr2rabbitmq'],
    scripts=['bin/solr2rabbitmq']
)
