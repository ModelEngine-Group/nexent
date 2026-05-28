
"""Dataset loader for ACON's 8-objective QA benchmark (nq_multi_8).

Adapted from ACON's experiments/smolagents/dataset.py.
Supports JSONL format with fields: id, question, answer.
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class QAExample:
    id: str
    question: str
    answer: Any  # str or list[list[str]] — each sub-answer is a list of acceptable variants
    contexts: Optional[List[str]] = None


class QALoader:
    def __init__(self, data_path: str):
        self.path = Path(data_path)
        if not self.path.exists():
            raise FileNotFoundError(f"Data file not found: {self.path}")
        self.is_jsonl = self.path.suffix.lower() in {".jsonl", ".jl"}

    def count(self, limit: Optional[int] = None) -> int:
        if self.is_jsonl:
            total = 0
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        total += 1
        else:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
            total = len(data)

        if limit is not None:
            total = min(total, limit)
        return total

    def _iter_jsonl(self) -> Iterable[Dict[str, Any]]:
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield json.loads(line)

    def _iter_json(self) -> Iterable[Dict[str, Any]]:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        for item in data:
            yield item

    def _normalize(self, raw: Dict[str, Any]) -> QAExample:
        qid = str(raw.get("id") or raw.get("qid") or raw.get("question_id") or "")
        question = raw.get("question") or raw.get("query") or ""
        answer = raw.get("answer")
        if answer is None:
            answer = raw.get("answers") or raw.get("final_answer") or ""
        contexts = raw.get("contexts") or raw.get("supporting_facts") or None
        return QAExample(id=qid, question=question, answer=answer, contexts=contexts)

    def iter(self, limit: Optional[int] = None) -> Iterable[QAExample]:
        it = self._iter_jsonl() if self.is_jsonl else self._iter_json()
        count = 0
        for raw in it:
            ex = self._normalize(raw)
            if not ex.question:
                continue
            yield ex
            count += 1
            if limit is not None and count >= limit:
                break
