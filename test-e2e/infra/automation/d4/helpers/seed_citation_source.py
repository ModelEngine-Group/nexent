from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conversation-id", type=int, required=True)
    parser.add_argument("--message-id", type=int, required=True)
    args = parser.parse_args()

    automation_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(automation_root))
    from shared.config import repo_root

    repo = repo_root()
    sys.path.insert(0, str(repo / "backend"))

    # Product DB modules resolve POSTGRES_* at import time.
    from shared.postgres import apply_product_postgres_env

    apply_product_postgres_env()
    from database.conversation_db import create_source_search

    common = {
        "message_id": args.message_id,
        "conversation_id": args.conversation_id,
        "source_type": "url",
        "source_content": "第一句内容的批次内固定引用证据。",
        "source_location": "https://example.invalid/nexent-d4-citation",
        "search_type": "web_search",
        "score_overall": 1,
        "score_accuracy": 1,
        "score_semantic": 1,
        "retrieval_highlight_terms": ["第一句内容"],
    }
    first = create_source_search({
        **common,
        "source_title": "D4 composite citation source",
        "cite_index": 1,
        "tool_sign": "a",
    })
    second = create_source_search({
        **common,
        "source_title": "D4 legacy numeric citation source",
        "cite_index": 1,
        "tool_sign": "",
    })
    print(f"seeded citation sources search_ids={first},{second}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
