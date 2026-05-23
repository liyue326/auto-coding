#!/usr/bin/env python3
"""从已有 output/run_xxx 离线导入修复经验（需 summary 含 test.passed 且存在 BugFix 产出）。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import config as cfg


def main() -> int:
    parser = argparse.ArgumentParser(description="离线灌入 Chroma 修复经验库")
    parser.add_argument(
        "runs",
        nargs="*",
        help="run 目录路径，默认扫描 output/",
    )
    args = parser.parse_args()

    if not cfg.MEMORY_ENABLED:
        print("MEMORY_ENABLED=false，请在 .env 开启")
        return 1

    from memory.ingest import ingest_successful_run
    from memory.store import collection_count

    roots: list[Path] = []
    if args.runs:
        roots = [Path(p) for p in args.runs]
    else:
        out = cfg.DEFAULT_OUTPUT_DIR
        roots = sorted(out.glob("run_*"), key=lambda p: p.name, reverse=True)

    total = 0
    for run_dir in roots:
        summary_path = run_dir / "reports" / "summary.json"
        if not summary_path.exists():
            continue
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        test = data.get("test") or {}
        if not test.get("passed"):
            print(f"跳过 {run_dir.name}: 测试未通过")
            continue
        agent_dir = run_dir / "reports"
        # 简化：无 fix_experiences 历史则跳过
        print(f"跳过 {run_dir.name}: 需新流水线产生的 fix_experiences（旧 run 无此字段）")
        continue

    print(f"库内案例数: {collection_count()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
