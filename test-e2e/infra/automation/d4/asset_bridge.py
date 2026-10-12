#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AUTO_TEST = Path(__file__).resolve().parents[1]
if str(AUTO_TEST) not in sys.path:
    sys.path.insert(0, str(AUTO_TEST))

from shared.asset_registry import register_asset, resolve_asset  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    register = sub.add_parser("register")
    register.add_argument("--section", required=True)
    register.add_argument("--key", required=True)
    register.add_argument("--value", required=True)
    register.add_argument("--owner", required=True)
    register.add_argument("--cleanup-json", default="")
    resolve = sub.add_parser("resolve")
    resolve.add_argument("--section", required=True)
    resolve.add_argument("--key", required=True)
    resolve.add_argument("--consumer", required=True)
    args = parser.parse_args()
    if args.command == "register":
        cleanup = json.loads(args.cleanup_json) if args.cleanup_json else None
        register_asset(args.section, args.key, args.value, owner_case_id=args.owner, cleanup=cleanup)
        print(json.dumps({"value": args.value, "state": "READY"}, ensure_ascii=False))
        return 0
    value = resolve_asset(args.section, args.key, consumer_case_id=args.consumer)
    print(json.dumps({"value": value, "state": "READY"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
