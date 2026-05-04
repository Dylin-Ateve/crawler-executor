#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "src" / "crawler"))

from crawler.queues import FetchCommandError, parse_fetch_command  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Fetch Command JSONL.")
    parser.add_argument("command_file", help="JSONL file. '-' reads stdin.")
    parser.add_argument(
        "--require-context",
        action="store_true",
        help="Require at least one of tier/site_id/host_id/politeness_key/policy_scope_id.",
    )
    return parser.parse_args()


def read_lines(path: str) -> list[str]:
    if path == "-":
        return sys.stdin.read().splitlines()
    return Path(path).read_text(encoding="utf-8").splitlines()


def main() -> int:
    args = parse_args()
    errors: list[str] = []
    seen_attempt_inputs: Counter[tuple[str, str]] = Counter()
    valid_count = 0

    for line_number, raw in enumerate(read_lines(args.command_file), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: JSON 解析失败: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"line {line_number}: 每行必须是 JSON object")
            continue
        if args.require_context and not any(
            payload.get(key)
            for key in ("tier", "site_id", "host_id", "politeness_key", "policy_scope_id")
        ):
            errors.append(f"line {line_number}: 缺少执行上下文字段")
            continue
        try:
            command = parse_fetch_command(payload)
        except FetchCommandError as exc:
            errors.append(f"line {line_number}: {exc}")
            continue
        seen_attempt_inputs[(command.job_id, command.canonical_url)] += 1
        valid_count += 1

    duplicate_inputs = [
        (job_id, canonical_url, count)
        for (job_id, canonical_url), count in seen_attempt_inputs.items()
        if count > 1
    ]
    for job_id, canonical_url, count in duplicate_inputs:
        errors.append(
            f"duplicate attempt input: job_id={job_id} canonical_url={canonical_url} count={count}"
        )

    if errors:
        print("fetch_command_jsonl_invalid")
        for error in errors:
            print(error)
        return 1

    print(f"fetch_command_jsonl_valid count={valid_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
