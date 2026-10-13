"""Write one deterministic output for the owned fast-path acceptance run."""

import argparse
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--value", type=int, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{32}", args.nonce) or not 1 <= args.value <= 1000:
        parser.error("Expected an owned nonce and a bounded numeric value")
    filename = f"tfp-{args.nonce}.txt"
    Path(filename).write_text(f"TFP_REPORT_{args.nonce}:{args.value}\n", encoding="utf-8")
    print(filename)


if __name__ == "__main__":
    main()
