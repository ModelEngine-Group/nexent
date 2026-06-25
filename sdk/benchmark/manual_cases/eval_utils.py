from dataclasses import dataclass


@dataclass
class EvalResult:
    passed: bool
    score: float
    details: dict


def contains_all(text: str, keywords: list[str]) -> bool:
    text = text.lower()
    return all(k.lower() in text for k in keywords)


def contains_any(text: str, keywords: list[str]) -> bool:
    text = text.lower()
    return any(k.lower() in text for k in keywords)


def count_matches(text: str, keywords: list[str]) -> int:
    """Count how many keywords are present in the text (case-insensitive)."""
    text = text.lower()
    return sum(1 for k in keywords if k.lower() in text)


def eval_text(text: str, check: dict) -> EvalResult:
    """Evaluate text against keyword checks with partial scoring.

    Scoring rules:
    - must_contain: score = matched_count / total_keywords
      (1.0 if all present, 0.6 if 3/5 present, etc.)
    - must_contain_any: score = 1.0 if any present, 0.0 otherwise
    - When both are present, score is the average of both sub-scores.
    - passed is True only when all checks fully pass (backward compatible).
    """
    passed = True
    details = {}
    scores = []

    if "must_contain" in check:
        keywords = check["must_contain"]
        matched = count_matches(text, keywords)
        ok = matched == len(keywords)
        details["must_contain"] = {
            "matched": matched,
            "total": len(keywords),
            "ok": ok,
        }
        scores.append(matched / len(keywords) if keywords else 1.0)
        passed = passed and ok

    if "must_contain_any" in check:
        keywords = check["must_contain_any"]
        ok = contains_any(text, keywords)
        matched = count_matches(text, keywords)
        details["must_contain_any"] = {
            "matched": matched,
            "total": len(keywords),
            "ok": ok,
        }
        scores.append(1.0 if ok else 0.0)
        passed = passed and ok

    score = sum(scores) / len(scores) if scores else (1.0 if passed else 0.0)

    return EvalResult(
        passed=passed,
        score=score,
        details=details,
    )


def average_score(results: list[EvalResult]) -> float:
    if not results:
        return 0.0
    return sum(r.score for r in results) / len(results)