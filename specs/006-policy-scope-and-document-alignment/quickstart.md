# 快速验证：策略作用域与文档 / 命名校准

## 本地验证

```bash
.venv/bin/pytest
```

## 文本审计

```bash
rg -n "KAFKA_TOPIC_PAGE_METADATA|build_page_metadata_publisher|PageMetadataPublisher|scrapy-distributed-crawler-p0" src deploy pyproject.toml setup.py README.md

rg -n "HostGroup|scrapy-redis" .specify/memory state/roadmap.md README.md
```

期望：

- 当前代码主路径不再出现历史 producer 兼容入口。
- `.specify/memory/`、`state/roadmap.md` 和 `README.md` 不再把旧分组概念或外置 scheduler 写作未来目标。
- `HostGroup` / `scrapy-redis` 只允许出现在历史研究、历史 spec 或“不采纳”ADR 上下文。
- 当前代码主路径不再出现 `page_metadata` publisher 兼容入口。
