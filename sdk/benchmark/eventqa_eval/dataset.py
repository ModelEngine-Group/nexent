"""Dataset loader for EventQA (MemoryAgentBench).

Loads the ``eventqa_full.jsonl`` produced by ``download_data.py``. Each line is
one novel: the full text plus 100 six-choice "what happens next" questions.

Each raw question string embeds the candidate events as a Python list literal:

    These are the events that have already occurred:

    1. <prior event>

    Below is a list of possible subsequent events:

    ['event A', 'event B', ..., 'event F']

    Your task is to choose from the above events which event happens next ...

This module parses that structure into EventQAItem objects so the runner can
feed the raw question to the agent and score the answer against the gold option.
"""
import ast
import json
from dataclasses import dataclass, field
from typing import List

# Markers that delimit the three parts of a raw EventQA question.
_PRIOR_MARKER = "These are the events that have already occurred:"
_OPTIONS_MARKER = "Below is a list of possible subsequent events:"
_TASK_MARKER = "Your task is to choose"


@dataclass
class EventQAItem:
    """A single six-choice "what happens next" question."""
    qid: str
    question: str            # raw question text, fed verbatim to the agent
    options: List[str]       # the six candidate subsequent events
    gold: str                # exact text of the correct option
    prior_events: str = ""   # the "events that have already occurred" block


@dataclass
class EventQABook:
    """One novel with its 100 EventQA questions."""
    book_index: int
    book_id: str
    book_title: str
    context: str             # full novel text
    items: List[EventQAItem] = field(default_factory=list)


def _parse_question(raw: str) -> tuple[str, List[str]]:
    """Extract the prior-events block and the six candidate options.

    Returns (prior_events_text, options). Either may be empty if the question
    does not follow the expected structure.
    """
    prior = ""
    options: List[str] = []

    prior_idx = raw.find(_PRIOR_MARKER)
    opts_idx = raw.find(_OPTIONS_MARKER)
    task_idx = raw.find(_TASK_MARKER)

    if prior_idx != -1 and opts_idx != -1:
        prior = raw[prior_idx + len(_PRIOR_MARKER):opts_idx].strip()

    if opts_idx != -1:
        seg_end = task_idx if task_idx != -1 else len(raw)
        segment = raw[opts_idx + len(_OPTIONS_MARKER):seg_end]
        lb = segment.find("[")
        rb = segment.rfind("]")
        if lb != -1 and rb > lb:
            try:
                parsed = ast.literal_eval(segment[lb:rb + 1])
                if isinstance(parsed, (list, tuple)):
                    options = [str(x) for x in parsed]
            except (ValueError, SyntaxError):
                options = []

    return prior, options


def _gold_answer(raw_answer) -> str:
    """Normalize the answer field to the gold option's text.

    The dataset stores answers as a one-element list, e.g. ['the correct event'].
    """
    if isinstance(raw_answer, (list, tuple)):
        return str(raw_answer[0]) if raw_answer else ""
    return str(raw_answer)


def load_books(jsonl_path: str) -> List[EventQABook]:
    """Load all EventQA books from a downloaded ``*.jsonl`` file."""
    books: List[EventQABook] = []

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)

            questions = row.get("questions") or []
            answers = row.get("answers") or []
            qa_ids = row.get("qa_pair_ids") or []

            items: List[EventQAItem] = []
            for i, raw_q in enumerate(questions):
                prior, options = _parse_question(str(raw_q))
                gold = _gold_answer(answers[i]) if i < len(answers) else ""
                qid = qa_ids[i] if i < len(qa_ids) else f"{row.get('book_id', 'book')}_no{i}"
                items.append(EventQAItem(
                    qid=str(qid),
                    question=str(raw_q),
                    options=options,
                    gold=gold,
                    prior_events=prior,
                ))

            books.append(EventQABook(
                book_index=row.get("book_index", len(books)),
                book_id=row.get("book_id", f"book{len(books)}"),
                book_title=row.get("book_title", f"book{len(books)}"),
                context=row.get("context") or "",
                items=items,
            ))

    return books
