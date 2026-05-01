ARG PYTHON_BASE_IMAGE=python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src/crawler

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml setup.py README.md ./
COPY src ./src
COPY deploy/scripts/inspect-k8s-ip-pool.sh ./deploy/scripts/inspect-k8s-ip-pool.sh

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && chmod +x /app/deploy/scripts/inspect-k8s-ip-pool.sh

WORKDIR /app/src/crawler

EXPOSE 9410 9411

CMD ["python", "-m", "scrapy", "crawl", "fetch_queue"]
