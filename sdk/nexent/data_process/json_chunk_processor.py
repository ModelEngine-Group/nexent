from typing import List
import string
import orjson
import logging

logger = logging.getLogger(__name__)


class JSONChunkProcessor:
    """
    JSON-aware chunk processor.

    Responsible for splitting JSON or plain-text content into chunks
    without breaking top-level key-value semantics when possible,
    and without splitting escape sequences like \\", \\n, etc.
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
        try:
            data = orjson.loads(file_data)
        except orjson.JSONDecodeError:
            return self._split_plain(
                file_data.decode("utf-8", errors="ignore")
            )
        except TypeError:
            try:
                if isinstance(file_data, (bytes, bytearray)):
                    text_content = file_data.decode("utf-8", errors="ignore")
                elif isinstance(file_data, str):
                    text_content = file_data
                else:
                    text_content = str(file_data)
                return self._split_plain(text_content)

            except Exception as inner_e:
                logger.error(
                    f"Failed to fallback to plain text due to: {inner_e}")
                return []

        except Exception as e:
            logger.error(f"Unexpected error while parsing JSON: {e}")
            return self._split_plain(
                file_data.decode(
                    "utf-8", errors="ignore") if isinstance(file_data, bytes) else str(file_data)
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
        all_punct = set(string.punctuation)
        opening_punct = set("([{<'\"‘“")
        SAFE_BREAKS = (all_punct - opening_punct) | {" "}

        while len(text) > self._max:
            i = self._max

            while i > 0 and text[i - 1] not in SAFE_BREAKS:
                i -= 1

            if i == 0:
                i = self._max

            while i > 0 and self._ends_with_unescaped_backslash(text[:i]):
                i -= 1
                if i <= 1:
                    break

            if i == 0:
                i = 1

            chunk = text[:i]
            text = text[i:].lstrip()
            out.append(chunk)

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
            cut = self._find_last_top_kv(cur, self._max)
            if cut is None:
                # No safe top-level cut → use plain splitter (with escape safety)
                return out + self._split_plain(cur)

            chunk = cur[:cut]
            cur = cur[cut:].lstrip()
            out.append(chunk)

        if cur:
            out.append(cur)

        return out

    def _find_last_top_kv(self, text: str, max_len: int) -> int | None:
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
        last_safe_cut = None

        for i, c in enumerate(text):
            if i >= max_len:
                break

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

            # Process structural characters only outside strings
            if c in "{[":
                depth += 1
            elif c in "}]":
                depth -= 1
            elif c == ',' and depth == 1:
                candidate = i + 1
                # Only accept if prefix doesn't end with unescaped backslash
                if not self._ends_with_unescaped_backslash(text[:candidate]):
                    last_safe_cut = candidate

        return last_safe_cut

    @staticmethod
    def _ends_with_unescaped_backslash(s: str) -> bool:
        """
        Check if the string ends with an odd number of consecutive backslashes.
        If so, the last backslash is escaping the next character (which isn't in s),
        so cutting here would break an escape sequence.
        """
        count = 0
        for char in reversed(s):
            if char == '\\':
                count += 1
            else:
                break
        return count % 2 == 1
