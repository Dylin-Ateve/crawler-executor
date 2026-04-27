# Feature: 基于 Scrapy 的大规模分布式爬虫系统

## 1. 背景与目标

### 1.1 项目背景

当前基于 Heritrix 的爬虫方案存在以下问题：

- **单一出口 IP 风险**：所有爬取流量从单一公网 IP 出去，一旦被源站封禁，所有任务中断。
- **吞吐受限**：受 robots.txt 与默认 politeness 策略限制，单 host 速率被压制。
- **框架契合度低**：Heritrix 设计目标是"归档型爬取 + WARC 输出"，而本项目实际只需要"抓取 HTML + 持久化 + 下游 Python 解析"，Heritrix 的诸多能力（WARC、复杂 Processor 链路、Spring 配置）成为不必要的复杂度成本。
- **资源效率低**：JVM + 多线程模型在几十台节点规模下资源开销显著。

### 1.2 目标

1. **更换爬虫框架为 Scrapy**：与下游 Python 解析栈统一，最大化社区生态优势。
2. **多出口 IP 轮换**：充分利用每节点 ~44 个辅助 IP（已绑定独立 EIP），分散源站封禁风险。
3. **可控的 Politeness 策略**：摆脱 robots.txt 强制约束，提供细粒度速率控制。
4. **大规模持久化存储**：HTML 原文 + 爬取过程元数据，支持冷启动 10 亿 URL、稳态日增 1 亿 URL 的规模。
5. **Host 画像分析能力**：记录每次爬取的响应时间、状态、子链接数等，支持多维度聚合分析。
6. **可运维**：几十台节点 K8s 化部署，节点扩缩容自动化。

### 1.3 非目标

- 本期不涉及 JS 渲染、TLS 指纹对抗、浏览器指纹等高级反爬。
- 本期不涉及商业代理服务（住宅代理）接入。
- 本期不涉及 WARC 标准归档输出。
- 本期不涉及全文检索能力（如未来需要，元数据可同步至 ES，原文保留在对象存储）。

---

## 2. 数据规模评估

### 2.1 规模假设

| 阶段 | URL 总量 | 日增 URL | HTML 总量估算（压缩后） | 元数据行数 |
|---|---|---|---|---|
| **冷启动期** | 10 亿 | 5000 万 - 1 亿 | ~50 TB（按平均 50KB/页 gzip 后） | 10 亿 |
| **稳态期** | 持续增长 | 1 亿/日 | 日增 ~5 TB | 日增 1 亿 |

### 2.2 关键推论

- **HTML 数据量 → TB 级别，必须用对象存储**。直接放 DB 不可行（成本高 5-10 倍，性能受影响）。
- **元数据日增 1 亿行 → 必须分区表**，按日分区。年累计 365 亿行，单 PG 实例配合分区裁剪仍可承载，但需预留分库扩展能力。
- **爬取记录（含重试）日增可能 1.5-2 亿行 → 强烈建议双写 ClickHouse**，专门承载 host 画像聚合查询。
- **节点吞吐目标**：稳态 1 亿/日 ÷ 几十台节点 ÷ 86400 秒 ≈ **每节点 30-50 pages/sec**。Scrapy 异步模型轻松达到。

---

## 3. 整体架构

### 3.1 架构总览

```
                    ┌────────────────────────────────────┐
                    │         调度与任务管理              │
                    │  Redis（URL 队列 + 去重 + IP 状态） │
                    └──────────────┬─────────────────────┘
                                   │
            ┌──────────────────────┼──────────────────────┐
            │                      │                      │
      ┌─────▼──────┐         ┌─────▼──────┐         ┌─────▼──────┐
      │  Node-1    │         │  Node-2    │   ...   │  Node-N    │
      │ (DaemonSet)│         │ (DaemonSet)│         │ (DaemonSet)│
      │ hostNetwork│         │ hostNetwork│         │ hostNetwork│
      │ ┌────────┐ │         │ ┌────────┐ │         │ ┌────────┐ │
      │ │Scrapy  │ │         │ │Scrapy  │ │         │ │Scrapy  │ │
      │ │+44 IPs │ │         │ │+44 IPs │ │         │ │+44 IPs │ │
      │ └───┬────┘ │         │ └───┬────┘ │         │ └───┬────┘ │
      └─────┼──────┘         └─────┼──────┘         └─────┼──────┘
            │                      │                      │
            │ ① HTML 原文（gzip）    │                      │
            ├──────────────────────┼──────────────────────┤
            │                      │                      │
            ▼                      ▼                      ▼
       ┌──────────────────────────────────────────────────────┐
       │         对象存储（S3 / COS / OSS）                    │
       │  s3://crawl/{date}/{host_hash[:2]}/{host}/{url}.gz   │
       └──────────────────────────────────────────────────────┘
            
            │ ② 元数据 + 爬取记录
            ▼
       ┌──────────────────────────────────────────────────────┐
       │         Kafka（解耦缓冲，TTL 7 天）                    │
       │  topics: page-metadata, crawl-logs, parse-tasks       │
       └────────┬─────────────────────────────┬───────────────┘
                │                             │
                ▼                             ▼
       ┌─────────────────┐           ┌─────────────────┐
       │ PostgreSQL      │           │ ClickHouse      │
       │ (按日分区)       │           │ (host 画像分析)  │
       │ - pages         │           │ - crawl_events  │
       │ - crawl_logs    │           │                 │
       └─────────────────┘           └─────────────────┘
                │
                │ ③ 解析任务消费
                ▼
       ┌─────────────────────────────────────────┐
       │     下游 Python 解析服务（独立部署）       │
       │  从 Kafka 拿 storage_key → 拉 HTML → 解析 │
       └─────────────────────────────────────────┘
```

### 3.2 数据流时序

```
[爬虫节点]
  1. 从 Redis 拿 URL（按域名分桶，避免单 host 集中）
  2. 选择本地 IP（按 host 粘性策略）
  3. 发起 HTTP 请求
  4. 记录响应时间、状态码、字节数
  5. gzip 压缩 HTML → 上传对象存储 → 拿到 storage_key
  6. 抽取 outlinks，新 URL 推回 Redis 队列（去重后）
  7. 元数据 + 爬取记录写入 Kafka
  8. 更新 IP 健康状态（成功/失败计数）

[Kafka 消费者]
  9. 批量消费 → 写入 PostgreSQL（pages + crawl_logs）
  10. 同时双写 ClickHouse（crawl_events，用于画像）

[下游解析]
  11. 消费 parse-tasks topic 拿到 storage_key
  12. 从对象存储拉 HTML → 解析 → 写入业务存储
```

---

## 4. 框架选型：Scrapy

### 4.1 选型理由

| 维度 | 评价 |
|---|---|
| 生态成熟度 | ★★★★★ 爬虫领域最成熟的 Python 框架，插件生态丰富 |
| 异步性能 | ★★★★ 基于 Twisted，单进程几千并发 |
| 与下游栈一致性 | ★★★★★ 下游解析也是 Python，统一技术栈 |
| 多 IP 轮换支持 | ★★★★★ `Request.meta['bindaddress']` 原生支持 |
| Politeness 控制 | ★★★★★ 配置项细粒度可调 |
| 分布式扩展 | ★★★★★ scrapy-redis 成熟方案 |
| 团队学习曲线 | ★★★★ Python 工程师上手快 |

### 4.2 核心依赖

```
scrapy >= 2.11
scrapy-redis >= 0.7         # 分布式去重 + 任务队列
twisted >= 23.0
redis >= 5.0
boto3 / cos-python-sdk-v5    # 对象存储 SDK
confluent-kafka >= 2.3       # Kafka 客户端
psycopg2-binary >= 2.9       # PostgreSQL 驱动（用于运维脚本，非主流程）
prometheus-client >= 0.19   # 监控指标
```

---

## 5. 核心技术方案

### 5.1 多出口 IP 轮换

#### 5.1.1 IP 池初始化

启动时扫描 `ens3` 上所有 IPv4 地址，过滤主 IP 和回环：

```python
import netifaces

def discover_local_ips(interface='ens3', exclude_ips=None):
    exclude_ips = exclude_ips or set()
    addrs = netifaces.ifaddresses(interface).get(netifaces.AF_INET, [])
    return [a['addr'] for a in addrs if a['addr'] not in exclude_ips]
```

#### 5.1.2 IP 选择中间件

实现 Scrapy Downloader Middleware，按 host 粘性策略选择本地 IP：

```python
class LocalIpRotationMiddleware:
    """
    策略：
    - STICKY_BY_HOST：同一 host 复用同一本地 IP，降低源站异常检测
    - 检查 Redis 黑名单，跳过被拉黑 IP
    - 失败时切换到其他 IP 重试
    """
    def __init__(self, settings, redis_client):
        self.ip_pool = discover_local_ips(
            interface=settings.get('CRAWL_INTERFACE', 'ens3'),
            exclude_ips=set(settings.getlist('EXCLUDED_LOCAL_IPS')),
        )
        self.redis = redis_client
        self.host_ip_map = {}  # 内存缓存 host → ip 映射

    def process_request(self, request, spider):
        host = urlparse(request.url).netloc
        local_ip = self._select_ip_for_host(host)
        request.meta['bindaddress'] = (local_ip, 0)
        request.meta['egress_local_ip'] = local_ip  # 记录用
        return None

    def _select_ip_for_host(self, host):
        # 优先复用，但要检查黑名单
        if host in self.host_ip_map:
            ip = self.host_ip_map[host]
            if not self._is_blacklisted(ip, host):
                return ip
        # 选一个未被该 host 拉黑的 IP
        candidates = [ip for ip in self.ip_pool if not self._is_blacklisted(ip, host)]
        if not candidates:
            raise CloseSpider(f"All IPs blacklisted for {host}")
        ip = random.choice(candidates)
        self.host_ip_map[host] = ip
        return ip

    def _is_blacklisted(self, ip, host):
        return self.redis.exists(f"crawler:blacklist:{host}:{ip}")
```

#### 5.1.3 配置项

```python
# settings.py
CRAWL_INTERFACE = 'ens3'
EXCLUDED_LOCAL_IPS = ['10.0.12.196']  # 主 IP 保留给管理流量
IP_SELECTION_STRATEGY = 'STICKY_BY_HOST'  # ROUND_ROBIN / STICKY_BY_HOST
IP_FAILURE_THRESHOLD = 5
IP_COOLDOWN_SECONDS = 1800

DOWNLOADER_MIDDLEWARES = {
    'crawler.middlewares.LocalIpRotationMiddleware': 100,
    'crawler.middlewares.IpHealthCheckMiddleware': 200,
    # 关闭默认的 robots 中间件
    'scrapy.downloadermiddlewares.robotstxt.RobotsTxtMiddleware': None,
}
```

### 5.2 IP 健康检查与黑名单

#### 5.2.1 触发拉黑的信号

| 信号 | 触发条件 | 拉黑维度 |
|---|---|---|
| HTTP 403/429 | 连续 5 次 | (host, ip) |
| HTTP 503 | 连续 5 次 | (host, ip) |
| 连接超时 | 连续 5 次 | ip（全局） |
| TCP RST / Connection Refused | 连续 3 次 | ip（全局） |
| 响应体含 captcha 关键词 | 单次命中 | (host, ip) |

#### 5.2.2 Redis 数据结构

```
# 失败计数（滑动窗口）
Key: crawler:fail:{host}:{ip}
Type: Sorted Set（score=timestamp, member=fail_id）
Operation: ZADD + ZREMRANGEBYSCORE 维护时间窗口

# 黑名单
Key: crawler:blacklist:{host}:{ip}
Type: String
Value: 拉黑原因
TTL: 1800 秒（自动过期 = 自动恢复）

# 全局 IP 状态（跨 host 失败）
Key: crawler:ip:global:{ip}
Type: Hash
Fields: failure_count, last_failure_ts, status
```

#### 5.2.3 健康检查中间件

```python
class IpHealthCheckMiddleware:
    def process_response(self, request, response, spider):
        ip = request.meta.get('egress_local_ip')
        host = urlparse(request.url).netloc
        if response.status in (403, 429, 503):
            self._record_failure(host, ip, f"HTTP_{response.status}")
        elif self._contains_captcha(response):
            self._blacklist_immediately(host, ip, "CAPTCHA_DETECTED")
        else:
            self._record_success(host, ip)
        return response

    def process_exception(self, request, exception, spider):
        ip = request.meta.get('egress_local_ip')
        if isinstance(exception, (TimeoutError, ConnectionRefusedError)):
            self._record_global_failure(ip, type(exception).__name__)
```

### 5.3 Politeness 策略

```python
# settings.py

# 完全忽略 robots.txt
ROBOTSTXT_OBEY = False

# 全局并发
CONCURRENT_REQUESTS = 200

# 单 host 并发（关键参数，控制对源站压力）
CONCURRENT_REQUESTS_PER_DOMAIN = 8
CONCURRENT_REQUESTS_PER_IP = 4  # 配合多 IP，单 IP 对单 host 压力更小

# 请求间隔
DOWNLOAD_DELAY = 0.2          # 基础延迟
RANDOMIZE_DOWNLOAD_DELAY = True

# 自动节流（根据响应延迟动态调整）
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.1
AUTOTHROTTLE_MAX_DELAY = 5.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0
AUTOTHROTTLE_DEBUG = False

# 重试策略
RETRY_ENABLED = True
RETRY_TIMES = 2
RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524, 408]

# UA 随机化（基础反反爬）
DOWNLOADER_MIDDLEWARES.update({
    'scrapy_user_agents.middlewares.RandomUserAgentMiddleware': 400,
})

DOWNLOAD_TIMEOUT = 30
```

**重要原则**：即便忽略 robots.txt，也保留合理的请求间隔与并发上限，避免事实上对源站造成 DDoS——这既是降低被封概率的最佳姿势，也是法律/道德底线。

### 5.4 分布式调度

使用 `scrapy-redis` 实现跨节点的统一任务队列与去重：

```python
# settings.py

# 调度器替换
SCHEDULER = "scrapy_redis.scheduler.Scheduler"
DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"

# 优先级队列（高优先级先爬）
SCHEDULER_QUEUE_CLASS = 'scrapy_redis.queue.PriorityQueue'

# 持久化（中断后可恢复）
SCHEDULER_PERSIST = True

REDIS_URL = 'redis://redis-cluster:6379/0'

# 按域名分桶，避免单 host 集中在一个节点
SCHEDULER_QUEUE_KEY = '%(spider)s:requests:{host_bucket}'
```

---

## 6. 存储架构

### 6.1 HTML 原文：对象存储

#### 6.1.1 路径设计

```
s3://crawl-html/
  └── {YYYY-MM-DD}/                    # 按日分区，便于生命周期管理
      └── {host_hash[:2]}/              # 一级前缀打散，避免热点
          └── {host_hash[2:8]}/         # 二级前缀进一步打散
              └── {url_hash}.html.gz    # 单文件
```

示例：`s3://crawl-html/2026-04-27/3f/a5b2c8/d4e7a9f1b3c5e8.html.gz`

- `host_hash` = SHA-256(host)
- `url_hash` = SHA-256(url)
- 内容 gzip 压缩，平均压缩率 70-85%

#### 6.1.2 上传逻辑

```python
class ObjectStoragePipeline:
    """放在 Pipeline 里，确保 HTML 上传成功后再发 Kafka"""
    def process_item(self, item, spider):
        if not item.get('html'):
            return item
        compressed = gzip.compress(item['html'].encode('utf-8'))
        key = self._build_key(item['url'], item['fetched_at'])
        try:
            etag = self.s3_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=compressed,
                ContentEncoding='gzip',
                ContentType='text/html',
            )['ETag']
            item['storage_key'] = key
            item['storage_etag'] = etag
            item['compressed_size'] = len(compressed)
        except Exception as e:
            # 上传失败 → 死信队列，不进入下游
            self._send_to_dlq(item, str(e))
            raise DropItem(f"S3 upload failed: {e}")
        return item
```

#### 6.1.3 生命周期与冷热分层

利用对象存储原生的生命周期策略：

| 数据年龄 | 存储类型 | 单价（参考 S3 美东） |
|---|---|---|
| 0-30 天 | 标准存储 | $0.023/GB/月 |
| 30-90 天 | 低频访问（IA） | $0.0125/GB/月 |
| 90-365 天 | Glacier 即时检索 | $0.004/GB/月 |
| > 365 天 | Glacier 深度归档 | $0.00099/GB/月 |
| > N 年（按需） | 自动删除 | - |

**成本估算（稳态期）**：

- 日增 5 TB HTML，年增 ~1.8 PB
- 30 天热数据：150 TB × $0.023 = ~$3,450/月
- 60 天 IA：300 TB × $0.0125 = ~$3,750/月
- 1 年内 Glacier：1.5 PB × $0.004 = ~$6,000/月
- **稳态月度存储成本约 $1.3 万**（对比直接放 DB 至少 $10 万+）

### 6.2 元数据：PostgreSQL 分区表

#### 6.2.1 pages 表（页面元数据）

```sql
CREATE TABLE pages (
    id              BIGSERIAL,
    url             TEXT NOT NULL,
    url_hash        CHAR(64) NOT NULL,        -- SHA-256
    host            TEXT NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL,
    status_code     INT NOT NULL,
    content_length  INT,
    content_type    TEXT,
    storage_key     TEXT NOT NULL,            -- 对象存储路径
    storage_etag    TEXT,
    compressed_size INT,
    outlinks_count  INT DEFAULT 0,
    egress_ip       INET,
    PRIMARY KEY (id, fetched_at)
) PARTITION BY RANGE (fetched_at);

-- 按日分区（数据量大）
CREATE TABLE pages_2026_04_27 PARTITION OF pages
    FOR VALUES FROM ('2026-04-27') TO ('2026-04-28');

-- 索引（每个分区独立创建）
CREATE UNIQUE INDEX ON pages_2026_04_27 (url_hash);
CREATE INDEX ON pages_2026_04_27 (host, fetched_at DESC);
```

使用 [`pg_partman`](https://github.com/pgpartman/pg_partman) 自动管理分区生命周期：

```sql
SELECT partman.create_parent(
    p_parent_table => 'public.pages',
    p_control => 'fetched_at',
    p_type => 'native',
    p_interval=> 'daily',
    p_premake => 7  -- 提前创建 7 天分区
);

-- 自动 detach 60 天前的分区，转为冷归档
UPDATE partman.part_config
SET retention = '60 days',
    retention_keep_table = false
WHERE parent_table = 'public.pages';
```

#### 6.2.2 crawl_logs 表（爬取过程记录）

```sql
CREATE TABLE crawl_logs (
    id                BIGSERIAL,
    url_hash          CHAR(64) NOT NULL,
    host              TEXT NOT NULL,
    attempted_at      TIMESTAMPTZ NOT NULL,
    egress_ip         INET,
    response_time_ms  INT,
    status_code       INT,
    error_type        TEXT,         -- TIMEOUT/CONN_REFUSED/HTTP_ERROR/CAPTCHA/OK
    retry_count       INT DEFAULT 0,
    bytes_downloaded  BIGINT,
    PRIMARY KEY (id, attempted_at)
) PARTITION BY RANGE (attempted_at);
```

`pages` 和 `crawl_logs` 分开的理由：一个 URL 可能爬多次（重试、定期更新），`crawl_logs` 记录每次尝试，`pages` 记录最终成功的快照。

#### 6.2.3 单实例 vs 分库

**起步阶段：单 PG 实例 + 按日分区即可。**

判断升级到分库分表的信号：

- 写入 TPS 持续超过 1.5 万 → 考虑分库
- 单实例存储超过 3 TB → 考虑分库
- 跨机房部署有数据本地性需求 → 分库

**预留分库扩展点**：所有查询都强制带 `host` 字段，未来按 `host_hash % N` 分库改造成本最低。

### 6.3 Host 画像：ClickHouse

#### 6.3.1 为什么需要 ClickHouse

按你的需求"评估 host 爬取画像"，常见查询包括：

- 某 host 最近 N 天的成功率、平均/P95 响应时间
- 某 host 在不同出口 IP 上的表现差异
- 哪些 host 的 outlinks 增长率异常
- 错误类型在时间维度的分布

这类**多维度聚合查询**在 PG 上可能扫描几亿行，ClickHouse 比 PG 快 10-100 倍，且压缩率更高。

#### 6.3.2 表设计

```sql
CREATE TABLE crawl_events (
    event_time      DateTime,
    host            String,
    url_hash        FixedString(64),
    egress_ip       IPv4,
    status_code     Int16,
    response_time_ms UInt32,
    bytes_downloaded UInt64,
    error_type      LowCardinality(String),
    retry_count     UInt8,
    outlinks_count  UInt32,
    region          LowCardinality(String)  -- 节点所在 region
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_time)
ORDER BY (host, event_time)
TTL event_time + INTERVAL 180 DAY;
```

#### 6.3.3 host 画像查询示例

```sql
-- 最近 7 天 host 画像（秒级返回）
SELECT
    host,
    count() AS total_attempts,
    countIf(status_code = 200) / count() AS success_rate,
    avg(response_time_ms) AS avg_rt,
    quantile(0.95)(response_time_ms) AS p95_rt,
    countIf(error_type = 'TIMEOUT') AS timeout_count,
    uniq(egress_ip) AS distinct_ips,
    sum(outlinks_count) AS total_outlinks
FROM crawl_events
WHERE event_time >= now() - INTERVAL 7 DAY
  AND host = 'example.com'
GROUP BY host;

-- IP × host 维度健康度矩阵
SELECT
    host,
    egress_ip,
    countIf(status_code IN (403, 429)) AS blocked_count,
    avg(response_time_ms) AS avg_rt
FROM crawl_events
WHERE event_time >= now() - INTERVAL 1 DAY
GROUP BY host, egress_ip
HAVING blocked_count > 10
ORDER BY blocked_count DESC;
```

### 6.4 中间缓冲：Kafka

#### 6.4.1 Topic 设计

| Topic | 内容 | 分区数 | 保留时长 |
|---|---|---|---|
| `page-metadata` | 页面元数据，下游写 PG | 32 | 7 天 |
| `crawl-events` | 爬取记录，下游写 PG + CH | 32 | 7 天 |
| `parse-tasks` | 解析任务，下游 Python 消费 | 64 | 7 天 |
| `dlq-storage` | 对象存储上传失败的死信 | 4 | 30 天 |

#### 6.4.2 Kafka 的角色澄清

**Kafka 不是持久化方案，是中间缓冲层**。其作用：

- 解耦爬虫吞吐与下游写入吞吐
- 平滑写入峰值（爬虫突增不打爆 PG）
- 多消费者订阅同一份数据（PG 写入、CH 写入、解析服务）

**真正的持久化保证**：

- 爬虫端：HTML 上传对象存储成功后才发 Kafka（关键不变量）
- 消费端：写入 PG/CH 成功后才提交 offset
- 故障场景：DB 短暂不可用 → Kafka 缓冲；Kafka 不可用 → 爬虫本地磁盘 queue 缓冲

---

## 7. K8s 部署方案

### 7.1 部署形态

**DaemonSet + hostNetwork + nodeSelector**

理由：
- `hostNetwork: true` 是 Pod 能 bind 宿主机辅助 IP 的最简方案
- DaemonSet 保证节点扩缩容时爬虫自动跟随
- nodeSelector 隔离爬虫节点，便于灰度

### 7.2 完整 YAML

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: scrapy-crawler
  namespace: crawler
spec:
  selector:
    matchLabels:
      app: scrapy-crawler
  template:
    metadata:
      labels:
        app: scrapy-crawler
    spec:
      hostNetwork: true
      dnsPolicy: ClusterFirstWithHostNet
      nodeSelector:
        crawler-node: "true"
      tolerations:
        - key: dedicated
          operator: Equal
          value: crawler
          effect: NoSchedule
      containers:
        - name: scrapy
          image: registry.example.com/scrapy-crawler:v1.0.0
          imagePullPolicy: IfNotPresent
          env:
            - name: REDIS_URL
              value: "redis://redis-cluster.crawler.svc:6379/0"
            - name: KAFKA_BROKERS
              value: "kafka-0.kafka:9092,kafka-1.kafka:9092"
            - name: S3_BUCKET
              value: "crawl-html-prod"
            - name: NODE_NAME
              valueFrom:
                fieldRef:
                  fieldPath: spec.nodeName
          resources:
            requests:
              cpu: "2"
              memory: "4Gi"
            limits:
              cpu: "4"
              memory: "8Gi"
          ports:
            - containerPort: 9410
              hostPort: 9410
              name: metrics
          livenessProbe:
            httpGet:
              path: /health
              port: 9410
            initialDelaySeconds: 30
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /ready
              port: 9410
            periodSeconds: 10
          volumeMounts:
            - name: local-buffer
              mountPath: /var/lib/crawler/buffer
      volumes:
        - name: local-buffer
          hostPath:
            path: /var/lib/crawler/buffer
            type: DirectoryOrCreate
```

### 7.3 节点准备

打标签将节点纳入爬虫池：

```bash
kubectl label node <node-name> crawler-node=true
kubectl taint node <node-name> dedicated=crawler:NoSchedule
```

### 7.4 镜像构建要点

- 基础镜像用 `python:3.12-slim`，最终镜像 ~200 MB
- 使用 multi-stage build，构建依赖不进运行时层
- 应用代码放在 `/app`，scrapy 项目结构标准化

---

## 8. 云资源自动化

几十台节点 × ~44 个辅助 IP = 2000+ 个 EIP，必须自动化。

### 8.1 Terraform 管理

把以下资源全部纳入 IaC：

- 爬虫节点（VM 实例）
- 每节点的辅助私网 IP
- 每个辅助 IP 绑定的 EIP
- 共享带宽包（如适用，可显著降低成本）
- 安全组规则

### 8.2 节点初始化

cloud-init 脚本在节点首次启动时：

1. 通过云厂商 OpenAPI 申请 ~44 个辅助私网 IP 并绑定 EIP
2. 加入 K8s 集群
3. 打上 `crawler-node=true` 标签
4. 触发 DaemonSet 调度

### 8.3 成本控制

- **共享带宽包**：多个 EIP 共享带宽，按总带宽计费而非按 EIP 数量，可降低 30-50% 成本
- **闲置 EIP 监控**：节点缩容时自动释放 EIP，避免持续计费
- **按需 vs 包年包月**：稳态节点用包年包月（折扣大），临时扩容节点用按需

---

## 9. 监控与可观测性

### 9.1 Prometheus 指标

爬虫端暴露：

```python
# 爬取速率
crawler_pages_fetched_total{node, host, status}

# 响应时间分布
crawler_response_duration_seconds{node, host}

# IP 健康
crawler_ip_blacklist_count{node, ip}
crawler_ip_active_count{node}

# 资源
crawler_redis_queue_size{spider}
crawler_kafka_lag{topic}
```

### 9.2 Grafana 看板

核心面板：

1. **集群总览**：总 QPS、成功率、活跃节点数、总 IP 池健康度
2. **节点详情**：每节点 CPU/内存、请求并发、本地 IP 利用率
3. **Host 画像**：Top N 慢响应 host、Top N 失败率 host、新发现 host 趋势
4. **存储**：对象存储日增量、PG 分区大小、Kafka lag

### 9.3 告警

| 告警 | 阈值 | 严重度 |
|---|---|---|
| 单节点黑名单 IP 占比 > 50% | 持续 10 分钟 | P1 |
| 集群总 QPS 跌落 > 30% | 持续 5 分钟 | P1 |
| Kafka lag > 10 万 | 持续 5 分钟 | P2 |
| PG 单分区 > 500 GB | 单次 | P2 |
| 对象存储上传失败率 > 1% | 持续 5 分钟 | P2 |
| Redis 内存使用 > 80% | 持续 10 分钟 | P3 |

---

## 10. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 整段 VPC 子网被源站封禁 | 一台机器所有 IP 同时失效 | 长期：节点分散到多 region / 多云厂商，IP 的 ASN 真正分散 |
| 冷启动 10 亿 URL 导致 Redis 爆内存 | 队列写不进去 | 用 Redis Cluster，按域名 sharding；队列用磁盘队列做溢出（如 RocksDB-backed） |
| 对象存储小文件性能问题 | 上传/列举变慢 | 路径前缀打散；超热场景考虑批量打包（每小时一个 tar.gz） |
| PG 单分区数据量超预期 | 查询变慢 | 提前预估，必要时改为按小时分区 |
| 高并发 + 忽略 robots = 反爬指纹明显 | 整体被封概率上升 | 保留 politeness、host 粘性、UA 随机化 |
| Redis 单点故障 | 黑名单失效，IP 持续被消耗 | Redis Cluster + Sentinel；爬虫端本地 fallback 缓存 |
| Kafka 故障 | 元数据丢失或重复 | 爬虫本地磁盘 queue 缓冲；消费端幂等写入（按 url_hash + attempted_at 去重） |
| 法律 / ToS 风险 | 法律纠纷 | 商用项目走法务评估；优先公开数据；不爬登录后内容 |
| 冷启动期成本激增 | EIP + 对象存储费用突增 | 冷启动分批扩容；启用对象存储生命周期立即生效 |

---

## 11. 实施计划

### 阶段 1：PoC 验证（1 周）

- [ ] 单节点验证 hostNetwork DaemonSet 可正常 bind 辅助 IP
- [ ] 实现最小化 Scrapy 项目：多 IP 轮换 + Redis 黑名单
- [ ] 通过 ifconfig.me 验证多 IP 实际生效
- [ ] 跑 24 小时 vs 单 IP Heritrix 对比：吞吐、资源占用、被封率

**验收**：单节点稳定 30 pages/sec，CPU < 50%，内存 < 4GB

### 阶段 2：核心爬虫开发（2 周）

- [ ] 完整的中间件：IP 轮换、健康检查、UA 随机化、重试
- [ ] Pipeline：对象存储上传 + Kafka 投递
- [ ] scrapy-redis 集成，跨节点共享队列与去重
- [ ] Prometheus 指标暴露

### 阶段 3：存储与下游（2 周）

- [ ] PostgreSQL 集群部署 + pg_partman 自动分区
- [ ] ClickHouse 集群部署
- [ ] Kafka 消费者：写 PG + 写 CH + 死信处理
- [ ] 对象存储生命周期策略配置

### 阶段 4：自动化与规模化（2 周）

- [ ] Terraform 模块：节点 + 辅助 IP + EIP
- [ ] 节点 cloud-init 脚本
- [ ] 灰度发布：先 5 台节点观察 1 周
- [ ] 逐步扩至全量，关闭旧 Heritrix

### 阶段 5：观测与调优（持续）

- [ ] Grafana 看板上线
- [ ] 告警规则配置
- [ ] Host 画像分析报表
- [ ] 根据反爬反馈持续调优

### 阶段 6：迁移收尾（1 周）

- [ ] 旧 Heritrix 数据迁移评估（视业务需要决定是否迁）
- [ ] 旧服务下线
- [ ] 文档归档与团队培训

**总工期估算：8-9 周**（不含持续调优）

---

## 12. 验收标准

### 12.1 功能性

1. 单节点能稳定使用 ~44 个出口 IP 轮换爬取，源站观察到的公网 IP 分布均匀
2. 被封 IP 在配置时间内自动进入冷却，恢复期试探机制正常
3. 跨节点 IP 黑名单 5 秒内同步
4. HTML 完整持久化到对象存储，元数据持久化到 PG，无数据丢失
5. 下游 Python 解析服务能从 Kafka 消费 storage_key 并正常拉取 HTML
6. Host 画像查询能秒级返回（最近 7 天数据范围）

### 12.2 性能

1. **稳态期**：集群整体吞吐 ≥ 1 亿页面/日（每节点 30-50 pages/sec）
2. **冷启动期**：集群整体吞吐 ≥ 5000 万页面/日
3. 单节点资源占用：CPU < 70%（4 核），内存 < 8GB
4. P95 端到端延迟（请求发起 → 数据落库）< 5 秒

### 12.3 可运维

1. 新增节点从开机到接入爬取，全自动化（< 10 分钟）
2. DaemonSet 滚动更新全集群 < 5 分钟
3. 关键告警 5 分钟内触发，运维 SOP 完整
4. 月度 EIP + 存储成本控制在预算范围内（具体由 Terraform 估算给出）

---

## 13. 备选方案（不采纳但记录）

| 方案 | 不采纳原因 |
|---|---|
| 维持 Heritrix | 业务不需要 WARC，Heritrix 复杂度成本不值得 |
| Colly（Go） | 团队需配 Go 工程师；下游解析栈不一致；性能优势在当前规模下不构成瓶颈 |
| Crawlee + Playwright | 适合强反爬场景，本期目标站点不需要浏览器渲染 |
| HTML 直接放 PostgreSQL | 成本高 5-10 倍，性能受影响，不适合 TB 级数据 |
| HTML 放 MongoDB | 成本仍高于对象存储，且无法享受冷热分层 |
| HBase / Cassandra 存元数据 | 运维复杂度对当前规模过重，PG 分区表足够 |
| 全量数据进 ElasticSearch | ES 不是存储引擎；如未来需要全文检索，元数据进 ES，原文仍放对象存储 |
| 单 NAT 网关共享出口 IP | 已验证当前方案是私网 IP → EIP 一对一，NAT 方案违背设计前提 |

---

## 14. 参考资料

- Scrapy 官方文档：https://docs.scrapy.org/
- scrapy-redis 项目：https://github.com/rmax/scrapy-redis
- pg_partman 文档：https://github.com/pgpartman/pg_partman
- ClickHouse 官方文档：https://clickhouse.com/docs
- Twisted `bindAddress` 用法：Scrapy `Request.meta['bindaddress']`
- 云厂商 EIP / 共享带宽包文档（按实际厂商补充）
- K8s `hostNetwork` 与 DaemonSet 最佳实践
