"""Provision and verify original static fixtures without changing their bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import wave


REPO = Path(__file__).resolve().parents[3]
CATALOG = REPO / "test-e2e/infra/assets/catalog.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as content:
        for chunk in iter(lambda: content.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def entries(catalog: Path = CATALOG) -> list[dict]:
    document = json.loads(catalog.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1 or not isinstance(document.get("assets"), list):
        raise ValueError("Invalid static asset catalog")
    seen_ids, seen_paths = set(), set()
    for item in document["assets"]:
        name = item.get("path")
        relative = PurePosixPath(name) if isinstance(name, str) else PurePosixPath(".")
        if (relative.is_absolute() or not relative.parts or
                any(part in {".", "..", ""} or ":" in part or "\\" in part for part in relative.parts)):
            raise ValueError("Unsafe static asset path")
        if (not isinstance(item.get("asset_id"), str) or item["asset_id"] in seen_ids or
                name in seen_paths or not isinstance(item.get("bytes"), int) or item["bytes"] < 0 or
                not isinstance(item.get("sha256"), str) or len(item["sha256"]) != 64):
            raise ValueError("Invalid or duplicate static asset catalog entry")
        seen_ids.add(item["asset_id"])
        seen_paths.add(name)
    return document["assets"]


def safe_file(root: Path, relative: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative).parts)
    if path.resolve() == root.resolve() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Static asset path escapes its root")
    current = path
    while current != root and current != current.parent:
        if current.is_symlink():
            raise ValueError("Static asset symlink is not permitted")
        current = current.parent
    return path


def media_error(path: Path) -> str | None:
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as audio:
                if audio.getnframes() == 0 or audio.getnchannels() < 1 or audio.getframerate() < 8000:
                    return "Invalid WAV dimensions"
        except (EOFError, OSError, wave.Error):
            return "Invalid WAV header"
    elif path.suffix.lower() == ".pcm":
        if path.stat().st_size == 0 or path.stat().st_size % 2:
            return "PCM length is not valid for 16-bit samples"
    elif path.name == "stt_expected.json":
        try:
            if not json.loads(path.read_text(encoding="utf-8")):
                return "Empty STT oracle"
        except (UnicodeError, json.JSONDecodeError):
            return "Invalid STT oracle JSON"
    return None


def check(path: Path, item: dict) -> str:
    if not path.is_file():
        return "MISSING"
    if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
        return "DIFFERENT"
    return media_error(path) or "READY"


def inventory(home: Path, selected: set[str] | None = None, source: Path | None = None,
              catalog: Path = CATALOG) -> list[dict]:
    rows = []
    for item in entries(catalog):
        if selected is not None and item["asset_id"] not in selected and item["path"] not in selected:
            continue
        destination = safe_file(home / "assets", item["path"])
        row = {"asset_id": item["asset_id"], "path": item["path"], "destination": check(destination, item),
               "sha256": item["sha256"]}
        if source is not None:
            row["source"] = check(safe_file(source, item["path"]), item)
        rows.append(row)
    if selected is not None:
        known = {item["asset_id"] for item in rows} | {item["path"] for item in rows}
        unknown = selected - known
        if unknown:
            raise ValueError("Unknown static asset selection: " + ", ".join(sorted(unknown)))
    return rows


def apply(home: Path, source: Path, catalog: Path = CATALOG) -> list[dict]:
    rows = inventory(home, source=source, catalog=catalog)
    receipt = home / "state/static-asset-provision.json"
    previous = json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else {}
    managed = {row["path"]: row.get("sha256") for row in previous.get("assets", [])}
    replaceable = {row["path"] for row in rows if row["destination"] == "DIFFERENT" and
                   managed.get(row["path"]) and sha256(safe_file(home / "assets", row["path"])) == managed[row["path"]]}
    errors = [row for row in rows if row["source"] != "READY" or
              (row["destination"] not in {"READY", "MISSING"} and row["path"] not in replaceable)]
    if errors:
        raise ValueError("Static assets differ or source is incomplete; inspect plan before applying")
    catalog_items = {entry["asset_id"]: entry for entry in entries(catalog)}
    for row in rows:
        if row["destination"] == "READY":
            continue
        item = catalog_items[row["asset_id"]]
        origin = safe_file(source, item["path"])
        destination = safe_file(home / "assets", item["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".nexent-asset-", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "wb") as output, origin.open("rb") as input_file:
                shutil.copyfileobj(input_file, output)
                output.flush()
                os.fsync(output.fileno())
            if check(Path(temporary), item) != "READY":
                raise RuntimeError("Source changed while copying")
            if row["path"] in replaceable:
                if sha256(destination) != managed[row["path"]]:
                    raise RuntimeError("Managed destination changed while copying")
                backup = safe_file(home / "state/static-asset-backups" / managed[row["path"]], row["path"])
                backup.parent.mkdir(parents=True, exist_ok=True)
                if not backup.exists():
                    shutil.copy2(destination, backup)
                if sha256(backup) != managed[row["path"]]:
                    raise RuntimeError("Managed asset backup verification failed")
                os.replace(temporary, destination)
            else:
                os.link(temporary, destination)  # Fails if another process created it.
            row["destination"] = check(destination, item)
        finally:
            Path(temporary).unlink(missing_ok=True)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    temporary_receipt = receipt.with_suffix(".json.next")
    temporary_receipt.write_text(json.dumps({"schema_version": 1, "assets": rows}, indent=2) + "\n", encoding="utf-8")
    temporary_receipt.replace(receipt)
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "verify", "apply"))
    parser.add_argument("--test-home", type=Path, required=True)
    parser.add_argument("--source-assets", type=Path)
    args = parser.parse_args(argv)
    home = args.test_home.resolve()
    if home == REPO or home.is_relative_to(REPO) or REPO.is_relative_to(home):
        parser.error("Test home must be outside the repository")
    if args.mode == "apply" and args.source_assets is None:
        parser.error("apply requires --source-assets")
    try:
        rows = (apply(home, args.source_assets.resolve()) if args.mode == "apply" else
                inventory(home, source=args.source_assets.resolve() if args.source_assets else None))
    except (ValueError, RuntimeError, OSError) as exc:
        print(json.dumps({"ready": False, "reason": str(exc)}))
        return 2
    ready = all(row["destination"] == "READY" for row in rows)
    print(json.dumps({"ready": ready, "assets": rows}, indent=2))
    return 0 if ready or args.mode == "plan" else 2


if __name__ == "__main__":
    raise SystemExit(main())
