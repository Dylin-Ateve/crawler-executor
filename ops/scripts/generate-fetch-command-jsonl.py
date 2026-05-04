#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "src" / "crawler"))

from crawler.contracts.canonical_url import canonicalize_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Redis Streams Fetch Command JSONL from a URL list."
    )
    parser.add_argument("url_file", help="Text file with one URL per line. '-' reads stdin.")
    parser.add_argument("--output", "-o", default="-", help="Output JSONL path. Default: stdout.")
    parser.add_argument("--job-id", required=True, help="Upstream batch/job id.")
    parser.add_argument("--command-prefix", default="", help="Command id prefix. Default: job id.")
    parser.add_argument("--trace-id", default="", help="Trace id. Default: generated batch trace id.")
    parser.add_argument("--tier", default="default", help="Fetch tier.")
    parser.add_argument("--site-id", default="", help="Optional site_id.")
    parser.add_argument("--host-id-prefix", default="", help="Optional host_id prefix; host is appended.")
    parser.add_argument("--politeness-prefix", default="host:", help="politeness_key prefix. Empty disables.")
    parser.add_argument("--policy-scope-id", default="", help="Optional policy_scope_id.")
    parser.add_argument("--max-retries", type=int, default=None, help="Optional command max_retries.")
    parser.add_argument(
        "--deadline-minutes",
        type=int,
        default=None,
        help="Optional deadline_at in minutes from now.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum URLs to emit. 0 means no limit.",
    )
    return parser.parse_args()


def read_urls(path: str) -> list[str]:
    if path == "-":
        lines = sys.stdin.read().splitlines()
    else:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    urls: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def host_for(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "unknown").lower()


def host_token(host: str) -> str:
    return host.replace(".", "_").replace("-", "_")


def main() -> int:
    args = parse_args()
    if args.max_retries is not None and args.max_retries < 0:
        raise SystemExit("--max-retries must be >= 0")
    if args.deadline_minutes is not None and args.deadline_minutes <= 0:
        raise SystemExit("--deadline-minutes must be > 0")

    urls = read_urls(args.url_file)
    if args.limit:
        urls = urls[: args.limit]

    trace_id = args.trace_id or f"trace:{args.job_id}:{uuid.uuid4().hex[:12]}"
    command_prefix = args.command_prefix or args.job_id
    deadline_at = None
    if args.deadline_minutes is not None:
        deadline_at = (
            datetime.now(timezone.utc) + timedelta(minutes=args.deadline_minutes)
        ).isoformat().replace("+00:00", "Z")

    output_lines: list[str] = []
    for index, url in enumerate(urls, start=1):
        canonical_url = canonicalize_url(url)
        host = host_for(canonical_url)
        command = {
            "url": url,
            "canonical_url": canonical_url,
            "job_id": args.job_id,
            "command_id": f"{command_prefix}:{index:08d}",
            "trace_id": trace_id,
            "tier": args.tier,
        }
        if args.site_id:
            command["site_id"] = args.site_id
        if args.host_id_prefix:
            command["host_id"] = f"{args.host_id_prefix}{host_token(host)}"
        if args.politeness_prefix:
            command["politeness_key"] = f"{args.politeness_prefix}{host}"
        if args.policy_scope_id:
            command["policy_scope_id"] = args.policy_scope_id
        if args.max_retries is not None:
            command["max_retries"] = args.max_retries
        if deadline_at:
            command["deadline_at"] = deadline_at
        output_lines.append(json.dumps(command, ensure_ascii=False, separators=(",", ":")))

    output = "\n".join(output_lines)
    if output:
        output += "\n"
    if args.output == "-":
        sys.stdout.write(output)
    else:
        Path(args.output).write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
