"""Dataset loader for LongMemEval (S*) from MemoryAgentBench.

Loads the ``longmemeval_s_star.jsonl`` produced by ``download_data.py``. Each
line is one long multi-session dialogue: 60 "session groups" (each a list of
1-3 atomic sessions, ~100-120 atomic sessions total) plus 60 free-text
questions tagged with one of six categories.

The released ``haystack_sessions`` field has a nested shape::

    haystack_sessions: list[60]                 # one entry per question slot
        -> list[N]                              # 1-3 chronological sessions
            -> list[turn]                       # the turns of one session
                -> {role, content, has_answer}  # role is "user"|"assistant"

This module flattens that to a single ordered list of atomic sessions for
ingest, and exposes the per-question metadata (question_type, question_date)
so the runner can group retention by ability category.
"""
import ast
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class LongMemEvalTurn:
    """One conversation turn inside a haystack session."""
    role: str           # "user" or "assistant"
    content: str
    has_answer: bool = False  # True if this turn carries evidence for some Q


@dataclass
class LongMemEvalSession:
    """One atomic chat session (list of turns)."""
    turns: List[LongMemEvalTurn]


@dataclass
class LongMemEvalItem:
    """One free-text question with its gold answer and ability category."""
    qid: str
    question: str         # raw question text, fed verbatim to the agent
    answer: str           # gold answer, unwrapped from the stringified list
    question_type: str    # one of: single-session-user / -assistant /
                          # -preference / multi-session / knowledge-update /
                          # temporal-reasoning  (no "_abs" in S*)
    question_date: str = ""  # "Current Date" anchor; already in question text


@dataclass
class LongMemEvalDialogue:
    """One LongMemEval (S*) dialogue: shared haystack + its 60 questions."""
    dialogue_index: int
    dialogue_id: str
    context: str                       # flattened-text haystack (for baseline)
    sessions: List[LongMemEvalSession] = field(default_factory=list)
    items: List[LongMemEvalItem] = field(default_factory=list)


def _unwrap_answer(raw) -> str:
    """The dataset stores answers as a stringified list, e.g. "['50']".

    Parse it back to the bare string. Falls back to ``str(raw)`` if the field
    is already a plain string or any other shape.
    """
    if isinstance(raw, (list, tuple)):
        return str(raw[0]) if raw else ""
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = ast.literal_eval(s)
                if isinstance(parsed, (list, tuple)) and parsed:
                    return str(parsed[0])
            except (ValueError, SyntaxError):
                pass
        return s
    return str(raw)


def _flatten_sessions(haystack_sessions: List[Any]) -> List[LongMemEvalSession]:
    """Flatten the nested ``list[group] -> list[session] -> list[turn]`` shape
    into a single chronological list of atomic sessions.

    The outer 60 groups are indexed by question slot but are also the natural
    chronological order of the dialogue, so concatenating their inner sessions
    preserves chronology.
    """
    flat: List[LongMemEvalSession] = []
    for group in haystack_sessions or []:
        if not isinstance(group, list):
            continue
        for session in group:
            if not isinstance(session, list):
                continue
            turns: List[LongMemEvalTurn] = []
            for t in session:
                if not isinstance(t, dict):
                    continue
                turns.append(LongMemEvalTurn(
                    role=str(t.get("role", "")),
                    content=str(t.get("content", "")),
                    has_answer=bool(t.get("has_answer", False)),
                ))
            if turns:
                flat.append(LongMemEvalSession(turns=turns))
    return flat


def load_dialogues(jsonl_path: str) -> List[LongMemEvalDialogue]:
    """Load all LongMemEval (S*) dialogues from a downloaded ``*.jsonl`` file."""
    dialogues: List[LongMemEvalDialogue] = []

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)

            questions = row.get("questions") or []
            answers = row.get("answers") or []
            qtypes = row.get("question_types") or []
            qdates = row.get("question_dates") or []
            qids = row.get("question_ids") or []

            items: List[LongMemEvalItem] = []
            for i, q in enumerate(questions):
                items.append(LongMemEvalItem(
                    qid=str(qids[i]) if i < len(qids) else f"q{i}",
                    question=str(q),
                    answer=_unwrap_answer(answers[i] if i < len(answers) else ""),
                    question_type=str(qtypes[i]) if i < len(qtypes) else "",
                    question_date=str(qdates[i]) if i < len(qdates) else "",
                ))

            dialogues.append(LongMemEvalDialogue(
                dialogue_index=int(row.get("dialogue_index", len(dialogues))),
                dialogue_id=str(row.get("dialogue_id", f"dialogue{len(dialogues)}")),
                context=str(row.get("context") or ""),
                sessions=_flatten_sessions(row.get("haystack_sessions") or []),
                items=items,
            ))

    return dialogues
