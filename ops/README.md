# 运维辅助工具

本目录存放面向运行期操作的辅助材料，例如批量抓取投递、契约校验、staging/production 观察和应急 runbook。

目录边界：

- `ops/`：运行期操作、批量投递、观测、排障和人工验证辅助。
- `deploy/`：镜像构建、K8s manifest 渲染、环境配置和发布相关脚本。

当前入口：

- `scale-fetching-runbook.md`：基于当前系统能力开展最小规模化抓取的操作说明。
- `scripts/generate-fetch-command-jsonl.py`：从 URL 列表生成 Fetch Command JSONL。
- `scripts/validate-fetch-command-jsonl.py`：按 executor 当前契约校验 Fetch Command JSONL。
- `scripts/enqueue-fetch-commands-via-k8s.sh`：通过 K8s Pod 内环境向 Redis Stream 投递命令，适合跳板机执行。
