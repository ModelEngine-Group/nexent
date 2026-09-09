# -*- coding: utf-8 -*-
"""Keyword match evaluator - checks if expected keywords appear in the answer."""


def keyword_match_evaluator(*, input, output, expected_output, metadata=None, **kwargs):
    if isinstance(output, dict):
        pred = output.get("final_answer", "") or output.get("answer", "") or str(output)
    else:
        pred = str(output) if output else ""

    if isinstance(expected_output, dict):
        keywords = expected_output.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [keywords]
    elif isinstance(expected_output, list):
        keywords = [str(k) for k in expected_output]
    else:
        keywords = [str(expected_output)]

    if not keywords:
        return {"name": "keyword_match", "value": 0.0}

    pred_lower = pred.lower()
    hits = sum(1 for kw in keywords if kw.lower() in pred_lower)
    return {"name": "keyword_match", "value": round(hits / len(keywords), 4)}
