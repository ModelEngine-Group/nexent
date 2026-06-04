"""In-memory store for offloaded step content, keyed by UUID handle."""

import re
import uuid
import logging
import threading
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("agent_context.offload_store")


class _Entry:
    """A single offloaded entry: original content plus a short description.

    The description is a human/LLM-readable hint about what was archived
    (e.g. the observation's first line). It lets the model judge, from the
    active-handle listing alone, whether a given archived item is relevant
    to the current question and therefore worth reloading.
    """

    __slots__ = ("content", "description", "tokens")

    def __init__(self, content: str, description: str = "", tokens: set = None):
        self.content = content
        self.description = description
        # Pre-computed token set for keyword-overlap scoring.
        # Computed once at store() time to avoid re-tokenizing on every
        # build_reload_inventory call.  None means "not yet computed".
        self.tokens = tokens or set()


class OffloadStore:
    """In-memory store for offloaded step content, keyed by UUID handle.

    Each entry keeps the original ``content`` and a short ``description``.
    The store is the single source of truth for "what can currently be
    reloaded": ``list_active()`` returns exactly the (handle, description)
    pairs for which ``reload(handle)`` is guaranteed to succeed right now
    (i.e. evicted entries never appear). This is what lets a fresh run
    re-list reloadable archives without relying on handles surviving
    inside compressed/summarized conversation history.
    """

    def __init__(self, max_entries: int = 200, max_total_chars: int = 2_000_000, max_entry_chars: int = 30000):
        self._store: Dict[str, _Entry] = {}
        self._max_entries = max_entries
        self._max_total_chars = max_total_chars
        self._max_entry_chars = max_entry_chars
        self._current_total = 0
        self._lock = threading.Lock()
        # Diagnostics: count successful reloads so tests/metrics can verify
        # the reload path was actually exercised (not inferred from streamed text).
        self._reload_hits = 0
        self._reload_misses = 0

    def store(self, content: str, description: str = "") -> Optional[str]:
        """Store content (+ optional description) and return a UUID handle.

        Returns None if the content exceeds ``max_entry_chars`` and cannot
        be stored.
        """
        if len(content) > self._max_entry_chars:
            logger.warning(
                f"Content exceeds max_entry_chars ({self._max_entry_chars}), "
                f"skipping offload for {len(content)} chars"
            )
            return None

        handle = uuid.uuid4().hex
        with self._lock:
            # Evict oldest entries if total chars would exceed budget
            while (self._current_total + len(content) > self._max_total_chars
                   and self._store):
                oldest = next(iter(self._store))
                self._current_total -= len(self._store[oldest].content)
                del self._store[oldest]

            # Evict oldest entry if count budget exceeded
            if len(self._store) >= self._max_entries:
                oldest = next(iter(self._store))
                self._current_total -= len(self._store[oldest].content)
                del self._store[oldest]

            # Pre-compute tokens at store time so build_reload_inventory
            # never re-tokenizes descriptions during scoring.
            entry_tokens = OffloadStore._tokenize(description)
            self._store[handle] = _Entry(content, description, tokens=entry_tokens)
            self._current_total += len(content)
        return handle

    def reload(self, handle: str) -> Optional[str]:
        """Retrieve offloaded content by handle. Returns None if not found."""
        with self._lock:
            entry = self._store.get(handle)
            if entry is None:
                self._reload_misses += 1
                return None
            self._reload_hits += 1
            return entry.content

    def list_active(self) -> List[Tuple[str, str]]:
        """Return (handle, description) for every entry currently reloadable.

        The returned set is exactly the handles for which ``reload`` would
        succeed right now: evicted entries are absent. Callers can render
        this into a per-run, ephemeral inventory of reloadable archives.
        """
        with self._lock:
            return [(h, e.description) for h, e in self._store.items()]

    # Common English stop words filtered during tokenization to reduce
    # spurious partial matches from high-frequency short tokens like "in",
    # "is", "all", etc.
    _STOP_WORDS: set = {
        "the", "a", "an", "in", "on", "at", "to", "for", "of", "is", "are",
        "was", "were", "be", "been", "and", "or", "not", "it", "its", "this",
        "that", "with", "from", "all", "has", "have", "do", "does", "did",
        "will", "would", "can", "could", "should", "may", "might", "shall",
        "but", "if", "then", "else", "when", "up", "so", "no",
    }

    # CJK Unified Ideographs range (U+4E00–U+9FFF).  Matched via ord() range
    # rather than a regex Unicode-escape so the logic is self-documenting.
    _CJK_LO = 0x4E00
    _CJK_HI = 0x9FFF

    @staticmethod
    def _tokenize(text: str) -> set:
        """Tokenize text for keyword-overlap scoring, supporting CJK + Latin.

        CJK text (Chinese / Japanese / Korean hanzi) is split into overlapping
        character bigrams so that multi-character words like "数据库" become
        {"数据", "据库"} and can match against query bigrams.

        Latin text is lowercased, punctuation-stripped, split on whitespace,
        and filtered for stop-words, single-character tokens, and pure-digits.
        """
        tokens: set = set()
        text_lower = text.lower()

        # ── CJK character bigrams ──────────────────────────────
        cjk_run: list = []
        for ch in text_lower:
            if OffloadStore._CJK_LO <= ord(ch) <= OffloadStore._CJK_HI:
                cjk_run.append(ch)
            else:
                if len(cjk_run) >= 2:
                    for i in range(len(cjk_run) - 1):
                        tokens.add(cjk_run[i] + cjk_run[i + 1])
                cjk_run.clear()
        if len(cjk_run) >= 2:
            for i in range(len(cjk_run) - 1):
                tokens.add(cjk_run[i] + cjk_run[i + 1])

        # ── Latin word tokens ──────────────────────────────────
        latin_part = re.sub(r'[^\w\s]', ' ', text_lower)
        for t in latin_part.split():
            if (len(t) >= 2
                    and not t.isdigit()
                    and t not in OffloadStore._STOP_WORDS):
                tokens.add(t)

        return tokens

    def _score_description(self, desc_tokens: set, query_tokens: set) -> float:
        """Score pre-computed *desc_tokens* against *query_tokens*.

        Exact token matches count 1.0; substring containment (e.g. "db" in
        "database", "download" in "downloaded") counts 0.5.  The overlap is
        squared before dividing by the capped denominator so that entries
        with multiple matches are amplified relative to single-match noise
        (2 matches → 4× weight, 3 → 9×).
        """
        if not desc_tokens:
            return 0.0

        # Exact matches
        overlap = float(len(desc_tokens & query_tokens))

        # Partial matches: one token contains the other (min 2 chars)
        remaining_desc = desc_tokens - query_tokens
        remaining_query = query_tokens - desc_tokens
        for dt in remaining_desc:
            for qt in remaining_query:
                if len(dt) >= 2 and len(qt) >= 2 and (qt in dt or dt in qt):
                    overlap += 0.5
                    break  # count each desc token at most once

        # Square the overlap to amplify multi-match entries vs single-match
        # noise (common in CJK bigram matching).
        return (overlap * overlap) / min(len(desc_tokens), 8)

    def build_reload_inventory(
        self,
        enable_reload: bool,
        query: Optional[str] = None,
        max_items: int = 10,
    ) -> Optional[str]:
        """Build a per-run inventory listing reloadable archives.

        When ``query`` is provided, entries are scored by keyword overlap
        and sorted by relevance (highest first), capped at ``max_items``.
        Entries with zero overlap are dropped so the LLM only sees items
        with at least some lexical connection to the query.

        When ``query`` is None the most recent entries are used (FIFO tail).

        Args:
            enable_reload: If False, returns None immediately.
            query: Optional user query for relevance scoring.
            max_items: Maximum entries to include in the inventory.

        Returns:
            Inventory text, or None if nothing to list or reload is disabled.
        """
        if not enable_reload:
            return None
        active = self.list_active()
        if not active:
            return None

        # When a query is provided, score entries by keyword overlap and
        # keep only the top max_items with non-zero scores.  Fall back to
        # recency (FIFO tail) when the query is empty or nothing matched.
        if query:
            query_tokens = self._tokenize(query)
            if query_tokens:
                scored = [
                    (handle, desc, self._score_description(
                        self._store[handle].tokens, query_tokens))
                    for handle, desc in active
                ]
                scored.sort(key=lambda x: x[2], reverse=True)
                matching = [(h, d) for h, d, s in scored if s > 0]
                if matching:
                    active = matching[:max_items]
                else:
                    active = active[-max_items:]

        if len(active) > max_items:
            active = active[-max_items:]

        lines = [
            f"- handle={handle}: {description}"
            for handle, description in active
        ]
        return (
            "[System Notice - Not User Input] The following content was archived "
            "(offloaded) earlier in this session. You can retrieve the full "
            "original text by calling reload_original_context_messages with the "
            "corresponding handle. If any of these are relevant to answering the "
            "user's question below, decide whether to reload them; do not guess "
            "based on truncated display text.\n"
            + "\n".join(lines)
        )

    @property
    def reload_hits(self) -> int:
        """Number of successful reload() calls (diagnostics)."""
        with self._lock:
            return self._reload_hits

    @property
    def reload_misses(self) -> int:
        """Number of reload() calls that missed (evicted/unknown handle)."""
        with self._lock:
            return self._reload_misses

    def __len__(self) -> int:
        """Return the number of stored entries. Thread-safe."""
        with self._lock:
            return len(self._store)

    def items(self):
        """Return a thread-safe snapshot of all (handle, content) pairs."""
        with self._lock:
            return [(h, e.content) for h, e in self._store.items()]

    def clear(self) -> None:
        """Clear all offloaded content."""
        with self._lock:
            self._store.clear()
            self._current_total = 0
