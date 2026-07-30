"""Fetch AI HOT data from aihot.virxact.com public API.

Usage:
    python fetch_aihot.py --endpoint items --mode selected --take 50
    python fetch_aihot.py --endpoint daily
    python fetch_aihot.py --endpoint daily --date 2026-05-07
    python fetch_aihot.py --endpoint dailies --take 14
    python fetch_aihot.py --endpoint items --mode all --take 100
    python fetch_aihot.py --endpoint items --category paper --take 30
    python fetch_aihot.py --endpoint items --q OpenAI --take 30
    python fetch_aihot.py --endpoint items --mode selected --since 2026-05-01T00:00:00Z

Output: JSON to stdout. Errors go to stderr with non-zero exit code.
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

BASE_URL = "https://aihot.virxact.com"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def fetch(url: str) -> dict:
    """Fetch JSON from URL with browser User-Agent."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def build_items_url(args) -> str:
    """Build items endpoint URL with query parameters."""
    params = []
    mode = args.mode or "selected"
    params.append(f"mode={mode}")
    if args.category:
        params.append(f"category={args.category}")
    if args.since:
        params.append(f"since={args.since}")
    elif args.hours_ago:
        dt = datetime.now(timezone.utc) - timedelta(hours=args.hours_ago)
        params.append(f"since={dt.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    elif args.days_ago:
        dt = datetime.now(timezone.utc) - timedelta(days=args.days_ago)
        params.append(f"since={dt.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    take = args.take or 50
    params.append(f"take={take}")
    if args.q:
        params.append(f"q={urllib.parse.quote(args.q)}")
    if args.cursor:
        params.append(f"cursor={urllib.parse.quote(args.cursor)}")
    return f"{BASE_URL}/api/public/items?{'&'.join(params)}"


def main():
    parser = argparse.ArgumentParser(description="Fetch AI HOT data")
    parser.add_argument("--endpoint", required=True,
                        choices=["items", "daily", "dailies"],
                        help="API endpoint to call")
    parser.add_argument("--mode", choices=["selected", "all"],
                        default=None, help="Items mode (default: selected)")
    parser.add_argument("--category", default=None,
                        help="Category filter: ai-models, ai-products, industry, paper, tip")
    parser.add_argument("--take", type=int, default=None,
                        help="Number of items (1-100)")
    parser.add_argument("--since", default=None,
                        help="ISO 8601 datetime for time window (max 7 days back)")
    parser.add_argument("--hours-ago", type=int, default=None,
                        help="Hours ago (alternative to --since)")
    parser.add_argument("--days-ago", type=int, default=None,
                        help="Days ago (alternative to --since)")
    parser.add_argument("--q", default=None,
                        help="Keyword search query")
    parser.add_argument("--cursor", default=None,
                        help="Pagination cursor from previous response")
    parser.add_argument("--date", default=None,
                        help="Date for daily endpoint (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.endpoint == "items":
        url = build_items_url(args)
    elif args.endpoint == "daily":
        if args.date:
            url = f"{BASE_URL}/api/public/daily/{args.date}"
        else:
            url = f"{BASE_URL}/api/public/daily"
    elif args.endpoint == "dailies":
        take = args.take or 30
        url = f"{BASE_URL}/api/public/dailies?take={take}"
    else:
        print(f"Unknown endpoint: {args.endpoint}", file=sys.stderr)
        sys.exit(1)

    data = fetch(url)
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import urllib.parse
    main()
