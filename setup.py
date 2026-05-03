from setuptools import find_packages, setup


setup(
    name="crawler-executor",
    version="0.1.0",
    description="Crawler executor for fetch commands, object snapshots, and crawl attempt events",
    package_dir={"": "src/crawler"},
    packages=find_packages(where="src/crawler"),
    python_requires=">=3.9",
    install_requires=[
        "Scrapy>=2.11",
        "Twisted>=23.0",
        "redis>=5.0",
        "prometheus-client>=0.19",
        "psutil>=5.9",
        "oci>=2.120",
        "confluent-kafka>=2.3",
    ],
    extras_require={
        "dev": [
            "pytest>=8.0",
        ],
    },
)
