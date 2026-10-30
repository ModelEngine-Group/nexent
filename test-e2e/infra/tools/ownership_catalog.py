# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Validate responsibility coverage and export non-executable current routing metadata."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

from jsonschema import ValidationError
import yaml

from report_ownership import load_rules, route
from test_asset_lib import ValidationIssue, case_index, discover_documents, feature_index, render_issues


def catalog(root):
    rules = load_rules(root)
    features, _, feature_issues = feature_index(discover_documents(root, 'features'))
    cases, case_issues = case_index(discover_documents(root, 'cases'))
    if feature_issues or case_issues:
        raise ValueError('Invalid responsibility catalog')
    if any(case['feature_id'] not in features for _, case, _ in cases.values()):
        raise ValueError('Case references an unknown Feature')
    feature_routes = {fid: route({'case_id': '', 'feature_id': fid}, feature, rules)
                      for fid, feature in features.items()}
    case_routes = {cid: {'feature_id': case['feature_id'],
                        **route({'case_id': cid, 'feature_id': case['feature_id']}, features.get(case['feature_id'], {}), rules)}
                   for cid, (_, case, _) in cases.items()}
    return features, cases, feature_routes, case_routes


def validate(root):
    try:
        features, cases, feature_routes, case_routes = catalog(root)
    except (OSError, ValueError, KeyError, TypeError, re.error, yaml.YAMLError, ValidationError) as error:
        return [ValidationIssue(root / 'test-e2e/infra/config/report-ownership.yaml', '',
                                'Responsibility configuration is unavailable or invalid: ' + type(error).__name__)]
    issues = []
    for fid, feature in features.items():
        if feature.get('status') in {'active', 'planned'} and feature_routes[fid]['status'] != 'ASSIGNED':
            issues.append(ValidationIssue(root / f'test-e2e/features/{fid}/feature.yaml', 'responsibility',
                          'Feature requires one responsibility domain; maintain report-ownership.yaml'))
    for cid, (_, case, path) in cases.items():
        if case.get('status') != 'retired' and case_routes[cid]['status'] != 'ASSIGNED':
            issues.append(ValidationIssue(path, 'responsibility',
                          'Non-retired Case requires one responsibility domain; use a Feature mapping or Case override'))
    return issues


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def export_current(root, output):
    issues = validate(root)
    if issues:
        raise ValueError(render_issues(root, issues))
    _, _, features, cases = catalog(root)
    payload = {'features': features, 'cases': cases}
    config = root / 'test-e2e/infra/config/report-ownership.yaml'
    head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True, timeout=30).strip()
    dirty = subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain', '--',
             'test-e2e/infra/config/report-ownership.yaml', 'test-e2e/infra/config/report-ownership.schema.json',
             'test-e2e/infra/tools/report_ownership.py', 'test-e2e/infra/tools/ownership_catalog.py',
             'test-e2e/features', 'test-e2e/cases'], text=True, timeout=30).strip()
    result = {'schema_version': 1, 'source': {'head': head, 'uncommitted': bool(dirty),
              'config_sha256': hashlib.sha256(config.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
              'generated_at': datetime.now(timezone.utc).isoformat()},
              'payload_sha256': hashlib.sha256(canonical(payload)).hexdigest(), 'routing': payload}
    root_abs, out_abs = root.resolve(), output.resolve()
    if out_abs == root_abs or root_abs in out_abs.parents:
        raise ValueError('Export must stay outside the product repository')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(output)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--export', type=Path)
    args = parser.parse_args()
    issues = validate(args.root)
    if issues:
        print(render_issues(args.root, issues))
        return 1
    if args.export:
        value = export_current(args.root, args.export)
        print(json.dumps({'status': 'EXPORTED', 'uncommitted': value['source']['uncommitted'],
                          'features': len(value['routing']['features']), 'cases': len(value['routing']['cases']),
                          'payload_sha256': value['payload_sha256']}))
    else:
        print('Responsibility coverage is valid.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
