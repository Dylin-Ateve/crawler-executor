from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, List

import scrapy


class ContentPersistenceSpider(scrapy.Spider):
    name = "content_persistence"
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
                        "p1_candidate": True,
                        "handle_httpstatus_all": True,
                    },
                )

    def parse(self, response):
        content_type = self._content_type(response)
        item = {
            "p1_candidate": True,
            "url": response.url,
            "status_code": response.status,
            "content_type": content_type,
            "response_headers": self._headers(response),
            "body": response.body or b"",
            "outlinks": response.css("a::attr(href)").getall() if self._is_html(content_type) else [],
            "egress_local_ip": response.meta.get("egress_local_ip"),
            "observed_egress_ip": None,
            "fetched_at_dt": datetime.now(timezone.utc),
        }
        self.logger.info(
            "p1_response_observed url=%s status=%s content_type=%s local_ip=%s",
            response.url,
            response.status,
            content_type,
            response.meta.get("egress_local_ip"),
        )
        yield item

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
    def _content_type(response) -> str:
        try:
            value = response.headers.get(b"Content-Type", b"")
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="ignore")
            return str(value)
        except Exception:
            return ""

    @staticmethod
    def _headers(response):
        headers = {}
        for key, values in response.headers.items():
            name = key.decode("utf-8", errors="ignore") if isinstance(key, bytes) else str(key)
            value = values[-1] if isinstance(values, list) else values
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="ignore")
            headers[name] = str(value)
        return headers

    @staticmethod
    def _is_html(content_type: str) -> bool:
        return (content_type or "").split(";", 1)[0].strip().lower() in {"text/html", "application/xhtml+xml"}
