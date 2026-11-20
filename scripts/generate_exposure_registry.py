# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compile the Gateway exposure snapshot from service-side declarations.

The snapshot (``backend/gateway/exposure/registry.json``) is the Gateway's
single routing truth: every request is matched against it and anything
unlisted returns 404. This generator is the *only* producer of the northbound
section, so the snapshot can never drift from the gate code:

* it imports the gate routers, reads every ``@nb_exposed`` declaration and
  emits one row per **enabled** capability (dark capabilities emit nothing:
  the Gateway 404 stays indistinguishable from nonexistent, AC-R4);
* path, methods and target are derived from the router itself (prefix +
  decorator + gate location), so the row cannot contradict the route it
  describes;
* ``route_id`` is ``sha256("METHOD PATH TRANSPORT")[:16]`` — the same
  deterministic scheme the existing snapshot rows use, so regenerated rows
  are byte-compatible with hand-written ones;
* rows for pre-existing northbound routes (northbound.py legacy section)
  are **preserved as-is**: this generator owns the capability-gate section,
  it does not rewrite history.

Fail-fast at commit time: duplicate ids or rows, audit=True without the
audit_hook dependency, collisions with preserved rows, forbidden path forms.

Usage:
    python scripts/generate_exposure_registry.py            # regenerate
    python scripts/generate_exposure_registry.py --check    # CI: fail if stale
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT))  # infrastructure/ lives at the repo root

SNAPSHOT = REPO_ROOT / "backend" / "gateway" / "exposure" / "registry.json"
GATE_PACKAGE = "management.api.northbound_gates"
LEGACY_PREFIXES = ("/nb/a2a/",)  # preserved sections owned elsewhere

# Gate module prefix -> the real microservice the gate lives in. The gateway
# snapshot must record the true owning service, never a logical alias: a
# future runtime-side gate (voice etc.) routes directly to the runtime
# container without ever entering management.
SERVICE_OWNERSHIP = {
    "management": "management",
    "runtime": "runtime",
    "ops": "ops",
}


def _gate_service(module_name: str) -> str:
    """Resolve the owning microservice from the gate module path.

    ``management.api.northbound_gates.*`` -> management; a future
    ``runtime.api.northbound_gates.*`` -> runtime. Fails loud on unknown
    owners so a new service cannot ride the wrong prefix silently.
    """
    root = module_name.split(".", 1)[0]
    if root not in SERVICE_OWNERSHIP:
        raise SystemExit(
            f"[exposure] gate module {module_name} belongs to no known service "
            f"(known: {sorted(SERVICE_OWNERSHIP)}); add it to SERVICE_OWNERSHIP first"
        )
    return SERVICE_OWNERSHIP[root]


def _route_id(method: str, path: str, transport: str) -> str:
    digest = hashlib.sha256(f"{method} {path} {transport}".encode()).hexdigest()
    return f"route-{digest[:16]}"


def _audit_dependency_present(endpoint) -> bool:
    import inspect

    try:
        signature = inspect.signature(endpoint)
    except (TypeError, ValueError):
        return False
    parameter = signature.parameters.get("audit")
    if parameter is None:
        return False
    default = parameter.default
    return hasattr(default, "dependency") and "audit_hook" in repr(default.dependency)


def _collect_gate_rows():
    """Import the gate routers and derive one snapshot row per capability."""
    module = __import__(GATE_PACKAGE, fromlist=["nb_capability_routers"])
    routers = module.nb_capability_routers()

    rows, seen_ids, seen_keys = [], {}, {}
    for router in routers:
        prefix = router.prefix
        for route in router.routes:
            meta = getattr(route.endpoint, "nb_capability", None)
            if meta is None:
                continue  # a gate without a declaration cannot be exposed
            capability = meta.capability_id
            # route.path may already embed the router prefix.
            path = route.path if route.path.startswith(prefix) else prefix + route.path
            owner = _gate_service(route.endpoint.__module__)
            for method in sorted(route.methods - {"HEAD"}):
                key = (method, path)
                if capability in seen_ids:
                    raise SystemExit(
                        f"[exposure] duplicate capability id {capability!r} on "
                        f"{seen_ids[capability]} and {path}"
                    )
                if key in seen_keys:
                    raise SystemExit(
                        f"[exposure] duplicate {method} {path} declared by both "
                        f"{seen_keys[key]} and {capability}"
                    )
                seen_ids[capability] = path
                seen_keys[key] = capability
                if not meta.enabled:
                    continue  # dark: code exists, row does not, Gateway 404
                if meta.audit and not _audit_dependency_present(route.endpoint):
                    raise SystemExit(
                        f"[exposure] {capability} declares audit=True but the gate "
                        f"signature lacks the audit_hook dependency"
                    )
                rows.append(
                    {
                        "method": method,
                        "path": path,
                        "transport": "http",
                        "target": owner,
                        "source": f"{route.endpoint.__module__}.{route.endpoint.__qualname__}",
                        "route_id": _route_id(method, path, "http"),
                        "capability_id": capability,
                        "credential_kinds": (
                            ["anonymous"] if meta.auth == "public" else ["api_key"]
                        ),
                    }
                )
    return rows


def _validate_row(row, known_keys):
    path = row["path"]
    if any(path.startswith(p) for p in LEGACY_PREFIXES):
        raise SystemExit(
            f"[exposure] gate capability {row['path']} collides with a preserved "
            f"legacy section ({', '.join(LEGACY_PREFIXES)}*)"
        )
    key = (row["method"], row["path"])
    if key in known_keys:
        raise SystemExit(
            f"[exposure] gate row {row['method']} {row['path']} collides with an "
            f"existing snapshot row ({known_keys[key]})"
        )
    lowered = path.lower().encode()
    if any(marked in lowered for marked in (b"%2f", b"%5c", b"%25", b"%00")):
        raise SystemExit(f"[exposure] gate path {path} contains a forbidden escape")
    if any(part.lower() in {".", "..", "internal"} for part in path.split("/")):
        raise SystemExit(f"[exposure] gate path {path} contains a forbidden segment")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the committed snapshot is stale instead of regenerating",
    )
    args = parser.parse_args()

    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    existing_rows = snapshot["routes"]

    def _is_gate_row(r):
        expected = _route_id(r["method"], r["path"], r.get("transport", "http"))
        return r["route_id"] == expected and "northbound_gates" in r.get("source", "")

    kept = [r for r in existing_rows if not _is_gate_row(r)]
    # Check collisions against preserved rows only (idempotent regeneration).
    known_keys = {(r["method"], r["path"]): r["route_id"] for r in kept}

    gate_rows = _collect_gate_rows()
    for row in gate_rows:
        _validate_row(row, known_keys)

    merged = kept + gate_rows
    merged.sort(key=lambda r: (r["path"], r["method"]))

    merged_document = {
        "version": snapshot["version"],
        "revision": f"generated-{len(merged)}-rows",
        "routes": merged,
    }
    rendered = json.dumps(merged_document, indent=2, ensure_ascii=False) + "\n"

    if args.check:
        current = SNAPSHOT.read_text(encoding="utf-8")
        if current == rendered:
            print(f"[exposure] snapshot is fresh ({len(merged)} rows, {len(gate_rows)} gate rows)")
            return 0
        print(
            "[exposure] snapshot is stale: gate declarations changed without "
            "regenerating. Run: python scripts/generate_exposure_registry.py",
            file=sys.stderr,
        )
        return 1

    SNAPSHOT.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"[exposure] wrote {len(merged)} rows ({len(gate_rows)} from gates) -> {SNAPSHOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
