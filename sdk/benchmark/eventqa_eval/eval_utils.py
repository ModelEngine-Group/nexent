"""Scoring utilities for EventQA six-choice questions.

The agent is asked to answer a "what happens next" question by returning one of
six candidate events. Scoring maps the agent's free-text answer back to one of
the six options, then checks whether that option is the gold option.

Matching strategy (most to least reliable):
  1. exact        — normalized answer equals a normalized option
  2. containment  — a normalized option is a substring of the normalized answer
                    (or vice versa); the agent wrapped the option in extra words
  3. fuzzy        — highest token-F1 option, used only as a last resort
"""
import re
import string
from dataclasses import dataclass
from typing import List


@dataclass
class MCQResult:
    correct: bool
    score: float            # 1.0 if correct, else 0.0
    selected_index: int     # index of the option the agent chose, -1 if none
    selected: str           # text of the chosen option ("" if none)
    gold_index: int         # index of the gold option, -1 if gold not in options
    match_type: str         # "exact" | "containment" | "fuzzy" | "none"


def _normalize(s: str) -> str:
    """Lowercase, drop punctuation and articles, collapse whitespace."""
    s = s.lower()
    s = s.translate(str.maketrans("", "", string.punctuation))
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    return " ".join(s.split())


def _token_f1(pred: str, gold: str) -> float:
    """SQuAD-style token-overlap F1 between two normalized strings."""
    pred_tokens = pred.split()
    gold_tokens = gold.split()
    if not pred_tokens or not gold_tokens:
        return 0.0
    common: dict[str, int] = {}
    for t in pred_tokens:
        common[t] = common.get(t, 0) + 1
    overlap = 0
    for t in gold_tokens:
        if common.get(t, 0) > 0:
            overlap += 1
            common[t] -= 1
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_tokens)
    recall = overlap / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def score_mcq(answer: str, options: List[str], gold: str) -> MCQResult:
    """Map a free-text answer to one of the six options and score it."""
    gold_index = options.index(gold) if gold in options else -1

    norm_answer = _normalize(answer or "")
    norm_options = [_normalize(o) for o in options]

    selected_index = -1
    match_type = "none"

    if norm_answer:
        # 1. Exact normalized match.
        for i, norm_opt in enumerate(norm_options):
            if norm_opt and norm_opt == norm_answer:
                selected_index = i
                match_type = "exact"
                break

        # 2. Containment — prefer the longest contained option to avoid
        #    matching a short option that is a prefix of the intended one.
        if selected_index == -1:
            best_len = -1
            for i, norm_opt in enumerate(norm_options):
                if not norm_opt:
                    continue
                if norm_opt in norm_answer or norm_answer in norm_opt:
                    if len(norm_opt) > best_len:
                        best_len = len(norm_opt)
                        selected_index = i
                        match_type = "containment"

        # 3. Fuzzy — highest token-F1 option (last resort).
        if selected_index == -1:
            best_f1 = 0.0
            for i, norm_opt in enumerate(norm_options):
                f1 = _token_f1(norm_answer, norm_opt)
                if f1 > best_f1:
                    best_f1 = f1
                    selected_index = i
                    match_type = "fuzzy"

    correct = selected_index != -1 and selected_index == gold_index
    return MCQResult(
        correct=correct,
        score=1.0 if correct else 0.0,
        selected_index=selected_index,
        selected=options[selected_index] if selected_index != -1 else "",
        gold_index=gold_index,
        match_type=match_type,
    )
