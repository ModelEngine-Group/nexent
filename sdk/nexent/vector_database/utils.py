# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import re
from datetime import datetime


HIGHLIGHT_PRE_TAG = "__nexent_hit_start__"
HIGHLIGHT_POST_TAG = "__nexent_hit_end__"


def extract_highlight_terms(highlights):
    """Turn trusted provider markers into unique plain matched terms."""
    pattern = re.compile(re.escape(HIGHLIGHT_PRE_TAG) + r"(.*?)" + re.escape(HIGHLIGHT_POST_TAG), re.DOTALL)
    terms = []
    for fragments in highlights.values():
        for fragment in fragments:
            for match in pattern.findall(fragment):
                term = match.strip()
                if term and term not in terms:
                    terms.append(term)
    return terms

def format_size(size_in_bytes):
    """Convert size in bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} PB"

def format_timestamp(timestamp_ms):
    """Convert millisecond timestamp to formatted date string"""
    dt = datetime.fromtimestamp(timestamp_ms / 1000.0)
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def build_weighted_query(text, term_weights, field_weights=None, boost_factor=2.0):
    """
    Build Elasticsearch weighted query DSL

    Parameters:
        text (str): Original query text
        term_weights (dict): Term weight dictionary {term: weight}
        field_weights (dict): Field weight dictionary {field_name: weight}, default {"title": 1, "content": 1}
        boost_factor (float): Weight amplification factor, default 2.0

    Returns:
        dict: Elasticsearch query DSL
    """
    if field_weights is None:
        field_weights = {"title": 1, "content": 1}

    # Convert English text to lowercase
    text = text.lower()

    # Build functions array for function_score
    functions = []
    for term, weight in term_weights.items():
        for field in field_weights:
            functions.append({
                # Create filter condition for each term
                "filter": {"term": {field: term}},
                # Actual weight = calculated weight * field weight * amplification factor
                "weight": weight * field_weights[field] * boost_factor
            })

    # Generate should clause
    should_clauses = []
    for field, weight in field_weights.items():
        should_clauses.extend([
            {
                "match_phrase": {
                    field: {
                        "query": text,
                        "slop": 3,
                        "boost": weight  # Set boost for match_phrase
                    }
                }
            },
            {
                "match": {
                    field: {
                        "query": text,
                        "minimum_should_match": "50%",
                        "fuzziness": "AUTO",
                        "boost": weight  # Set boost for match
                    }
                }
            }
        ])

    query_body = {
        "query": {
            "function_score": {
                "query": {
                    "bool": {
                        "should": should_clauses,
                        "minimum_should_match": 1
                    }
                },
                "functions": functions,
                "score_mode": "sum",
                "boost_mode": "multiply"
            }
        }
    }

    return query_body
