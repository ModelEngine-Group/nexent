from typing import List


class JSONChunkProcessor:
    """
    JSON-aware chunk processor.

    Responsible for splitting JSON or plain-text content into chunks
    without breaking top-level key-value semantics when possible.
    """

    def __init__(self, max_characters: int):
        """
        Initialize JSON chunk processor.

        Args:
            max_characters: Maximum length per chunk
        """
        self._max = max_characters

    def split(self, file_data: bytes) -> List[str]:
        """
        Split input bytes into text chunks.

        - If input is valid JSON, apply JSON-aware chunking
        - Otherwise, fallback to plain-text chunking

        Args:
            file_data: Raw file bytes

        Returns:
            List of text chunks
        """
        import orjson

        try:
            data = orjson.loads(file_data)
        except Exception:
            return self._split_plain(
                file_data.decode("utf-8", errors="ignore")
            )

        def dump(v): return orjson.dumps(v).decode("utf-8")
        chunks: List[str] = []

        if isinstance(data, dict):
            for k, v in data.items():
                chunks.extend(self._split_json_text(f"{k}: {dump(v)}"))
        elif isinstance(data, list):
            for item in data:
                chunks.extend(self._split_json_text(dump(item)))
        else:
            chunks.extend(self._split_json_text(dump(data)))

        return chunks

    def _split_plain(self, text: str) -> List[str]:
        """
        Split plain text by max length, preferring punctuation boundaries.

        Args:
            text: Input text

        Returns:
            List of text chunks
        """
        out: List[str] = []
        PUNCTS = set(",.(){}[]，。\"' ")

        while len(text) > self._max:
            i = self._max
            while i > 0 and text[i - 1] not in PUNCTS:
                i -= 1
            i = i or self._max
            out.append(text[:i])
            text = text[i:]

        if text:
            out.append(text)

        return out

    def _split_json_text(self, text: str) -> List[str]:
        """
        Split JSON-derived text while preserving top-level key-value integrity.

        Args:
            text: JSON-derived string

        Returns:
            List of text chunks
        """
        out: List[str] = []
        cur = text

        while len(cur) > self._max:
            cut = self._find_last_top_kv(cur[: self._max])
            if cut is None:
                return out + self._split_plain(cur)

            out.append(cur[:cut])
            cur = cur[cut:]

        if cur:
            out.append(cur)

        return out

    def _find_last_top_kv(self, text: str) -> int | None:
        """
        Find the split position of the last top-level key-value pair.

        Args:
            text: JSON substring (prefix)

        Returns:
            Index after the last complete top-level KV pair,
            or None if no safe split point exists.
        """
        depth = 0
        in_str = False
        esc = False

        for i in range(len(text) - 1, -1, -1):
            c = text[i]

            if esc:
                esc = False
                continue
            if c == "\\":
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue

            if c in "}]":
                depth += 1
            elif c in "{[":
                depth -= 1
            elif c == "," and depth == 1:
                return i + 1

        return None
