# Canonical URL 契约

## 目的

Canonical URL 是爬虫系统内用于 URL 去重、页面身份识别、`url_hash` 和 `dedupe_key` 计算的统一契约。该规则应保持独立，不依赖 Scrapy、Redis、Kafka 或存储实现，后续可以抽取为系统群共享契约。

## 输入要求

- 输入必须是绝对 URL，必须包含 scheme 和 host。
- 空字符串、相对路径或无法解析 host 的 URL 必须视为非法输入。

## 归一化规则

- scheme 小写。
- Host 小写。
- 移除 fragment。
- 移除默认端口：`http:80`、`https:443`。
- 保留非默认端口。
- query 参数按 `(key, value)` 排序，忽略原始参数顺序。
- 保留重复 query 参数，但按 `(key, value)` 排序。
- 根路径 `/` 与空路径视为相同。
- 非根路径移除尾斜杠。
- path 大小写保持不变。

## 输出字段

- `canonical_url`：归一化后的 URL 字符串。
- `url_hash`：`sha256(canonical_url)` 的十六进制字符串。
- `dedupe_key`：当前与 `url_hash` 相同，用于 URL 任务去重。

## 示例

| 原始 URL | canonical URL |
|----------|---------------|
| `HTTPS://Example.COM:443/a/b/?b=2&a=1#section` | `https://example.com/a/b?a=1&b=2` |
| `https://example.com/` | `https://example.com` |
| `https://example.com:8443/Path` | `https://example.com:8443/Path` |
| `https://example.com/?tag=b&tag=a` | `https://example.com?tag=a&tag=b` |

## 当前代码位置

- Python 契约模块：`src/crawler/crawler/contracts/canonical_url.py`
- 单元测试：`tests/unit/test_canonical_url.py`

