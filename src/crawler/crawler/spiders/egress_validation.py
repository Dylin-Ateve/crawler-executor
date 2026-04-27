import json
from pathlib import Path
from typing import Iterable, Iterator, List

import scrapy


class EgressValidationSpider(scrapy.Spider):
    name = "egress_validation"
    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "HTTPERROR_ALLOW_ALL": True,
    }

    def __init__(self, seed_file=None, urls=None, repeat=1, max_pages=0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seed_file = seed_file
        self.inline_urls = urls
        self.repeat = max(int(repeat or 1), 1)
        self.max_pages = int(max_pages or 0)
        self.seen_pages = 0

    async def start(self):
        for request in self._iter_requests():
            yield request

    def _iter_requests(self) -> Iterator[scrapy.Request]:
        urls = self._load_urls()
        for _ in range(self.repeat):
            for url in urls:
                if self.max_pages and self.seen_pages >= self.max_pages:
                    return
                self.seen_pages += 1
                yield scrapy.Request(
                    url=url,
                    callback=self.parse,
                    dont_filter=True,
                    meta={
                        "p0_validation": True,
                        "handle_httpstatus_all": True,
                    },
                )

    def parse(self, response):
        observed_ip = self._extract_observed_ip(response.text)
        egress_local_ip = response.meta.get("egress_local_ip")
        self.logger.info(
            "p0_egress_observed url=%s status=%s local_ip=%s observed_ip=%s",
            response.url,
            response.status,
            egress_local_ip,
            observed_ip,
        )
        yield {
            "url": response.url,
            "status": response.status,
            "egress_local_ip": egress_local_ip,
            "observed_ip": observed_ip,
        }

    def _load_urls(self) -> List[str]:
        urls: List[str] = []
        if self.inline_urls:
            urls.extend(url.strip() for url in self.inline_urls.split(",") if url.strip())
        if self.seed_file:
            urls.extend(self._load_seed_file(self.seed_file))
        if not urls:
            raise ValueError("seed_file or urls is required")
        return urls

    @staticmethod
    def _load_seed_file(seed_file: str) -> Iterable[str]:
        path = Path(seed_file)
        for line in path.read_text(encoding="utf-8").splitlines():
            url = line.strip()
            if url and not url.startswith("#"):
                yield url

    @staticmethod
    def _extract_observed_ip(text: str):
        stripped = text.strip()
        if not stripped:
            return None
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return stripped.splitlines()[0][:128]
        for key in ("ip", "origin", "query", "address"):
            if key in payload:
                return payload[key]
        return stripped[:128]
