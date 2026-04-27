from setuptools import find_packages, setup


setup(
    name="scrapy-distributed-crawler-p0",
    version="0.1.0",
    description="P0 PoC for Scrapy based multi-egress-IP crawler",
    package_dir={"": "src/crawler"},
    packages=find_packages(where="src/crawler"),
    python_requires=">=3.9",
    install_requires=[
        "Scrapy>=2.11",
        "Twisted>=23.0",
        "redis>=5.0",
        "prometheus-client>=0.19",
        "psutil>=5.9",
    ],
    extras_require={
        "dev": [
            "pytest>=8.0",
        ],
    },
)

