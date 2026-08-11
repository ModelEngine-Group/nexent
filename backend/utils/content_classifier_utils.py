"""Content classification utilities for streaming LLM output parsing."""

import re
from typing import Any, Dict, List, Optional


class ContentClassifier:
    """Parse XML tags from LLM output and classify streaming content in real-time.

    Uses tag pool matching with state machine for elegant streaming XML parsing.
    Classifies content into:
    - skill_body: SKILL.md content (including frontmatter - detected by frontend)
    - file_content: Additional file content with path information
    - summary: Summary text after </SKILL>
    - others: Content outside all tags (LLM reasoning process)

    Includes DoS protection to prevent resource exhaustion from malicious input.
    """

    MAX_BUFFER_SIZE = 1024 * 1024  # 1MB
    MAX_TAG_LENGTH = 256           # Single tag max length
    MAX_PATH_LENGTH = 512          # File path max length
    MAX_TAG_COUNT = 100            # Max tags before stopping

    def __init__(self):
        self.state = "others"  # others | skill_body | file | summary
        self.current_file_path: Optional[str] = None
        self.buffer = ""
        self.tag_count = 0
        self.saw_control_tag = False
        self._origin_type: Optional[str] = None
        self._state_before_file = "others"
        self._known_tags = {
            "<SKILL>",
            "</SKILL>",
            "<SUMMARY>",
            "</SUMMARY>",
            "</FILE>",
        }
        self._pending_file_path: Optional[str] = None

    def classify(
        self,
        chunk: str,
        origin_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Process one streaming chunk and return classified delta events.

        ``origin_type`` preserves the upstream observer type for content outside
        the XML control blocks. Content inside a control block is emitted with
        a semantic NL2Skill type and carries the upstream type as metadata.
        """
        results = []
        self._origin_type = origin_type
        self.buffer += chunk

        if len(self.buffer) > self.MAX_BUFFER_SIZE:
            overflow = self.buffer[:-self.MAX_BUFFER_SIZE]
            self.buffer = self.buffer[-self.MAX_BUFFER_SIZE:]
            event = self._create_event(overflow)
            if event:
                results.append(event)

        while self.buffer:
            if self.buffer.startswith("<"):
                if ">" not in self.buffer:
                    break
                events = self._process_tag_start()
                if events is None:
                    break
                results.extend(events)
            else:
                results.extend(self._process_non_tag_content())

        return results

    def flush(self, origin_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Emit any non-tag tail left in the incremental buffer."""
        if origin_type is not None:
            self._origin_type = origin_type
        results = []
        while self.buffer:
            if self.buffer.startswith("<") and ">" in self.buffer:
                events = self._process_tag_start(final=True)
                if events is not None:
                    results.extend(events)
                    continue
            content = self.buffer
            self.buffer = ""
            event = self._create_event(content)
            if event:
                results.append(event)
        return results

    def _process_tag_start(self, final: bool = False) -> Optional[List[Dict[str, Any]]]:
        """Process buffer when it starts with '<' - extracts and handles tags."""
        results = []
        gt_pos = self.buffer.index(">")
        potential_tag = self.buffer[:gt_pos + 1]
        matched = self._match_known_tag_with_buffer(potential_tag)

        if matched:
            content_after_tag = self.buffer[gt_pos + 1:]
            if not content_after_tag and not final:
                return None
            if content_after_tag and not content_after_tag.startswith(("\n", "\r\n")):
                return self._emit_potential_tag_start()
            results.extend(self._handle_matched_tag(gt_pos, potential_tag, matched))
        elif len(potential_tag) > self.MAX_TAG_LENGTH:
            results.extend(self._emit_dos_protected_content())
        else:
            results.extend(self._emit_potential_tag_start())

        return results

    def _handle_matched_tag(self, gt_pos: int, potential_tag: str, matched_tag: str) -> List[Dict[str, Any]]:
        """Handle a successfully matched tag and process following content."""
        results = []
        if self.tag_count >= self.MAX_TAG_COUNT:
            remaining = self.buffer[gt_pos + 1:]
            if remaining.startswith("\r\n"):
                remaining = remaining[2:]
            elif remaining.startswith("\n"):
                remaining = remaining[1:]
            self.buffer = remaining
            return results

        self.tag_count += 1
        content_after_tag = self.buffer[gt_pos + 1:]
        if content_after_tag.startswith("\r\n"):
            content_after_tag = content_after_tag[2:]
        elif content_after_tag.startswith("\n"):
            content_after_tag = content_after_tag[1:]
        self.buffer = ""

        event = self._handle_tag(matched_tag)
        if event:
            results.append(event)

        if content_after_tag:
            results.extend(self._process_content_after_tag(content_after_tag))

        return results

    def _process_content_after_tag(self, content: str) -> List[Dict[str, Any]]:
        """Process content following a tag, handling embedded tag starts."""
        results = []
        if "<" not in content:
            event = self._create_event(content)
            if event:
                results.append(event)
            return results

        next_tag_pos = content.index("<")
        immediate_content = content[:next_tag_pos]
        if immediate_content:
            event = self._create_event(immediate_content)
            if event:
                results.append(event)

        self.buffer = content[next_tag_pos:]
        return results

    def _emit_dos_protected_content(self) -> List[Dict[str, Any]]:
        """Handle content that exceeds max tag length (DoS protection)."""
        results = []
        event = self._create_event("<")
        if event:
            results.append(event)
        self.buffer = self.buffer[1:]
        return results

    def _emit_potential_tag_start(self) -> List[Dict[str, Any]]:
        """Handle buffer starting with '<' that doesn't match any known tag."""
        results = []
        event = self._create_event("<")
        if event:
            results.append(event)
        self.buffer = self.buffer[1:]
        return results

    def _process_non_tag_content(self) -> List[Dict[str, Any]]:
        """Process buffered content that doesn't start with '<'."""
        results = []
        next_tag_pos = self.buffer.find("<")
        if next_tag_pos != -1:
            if next_tag_pos == 0:
                return results
            emit_len = next_tag_pos
        else:
            emit_len = min(len(self.buffer), 64)
        event = self._create_event(self.buffer[:emit_len])
        if event:
            results.append(event)
        self.buffer = self.buffer[emit_len:]
        return results

    def _match_known_tag_with_buffer(self, buffer_content: str) -> Optional[str]:
        """Check if buffer content matches a known complete tag."""
        # Check exact match for simple tags
        if buffer_content in self._known_tags:
            return buffer_content

        # Check <FILE path="..."> pattern
        if buffer_content.startswith("<FILE ") and buffer_content.endswith(">"):
            match = re.match(
                r'<FILE\s+path="([^"]{1,' + str(self.MAX_PATH_LENGTH) + r'})">$',
                buffer_content
            )
            if match and self._is_valid_file_path(match.group(1)):
                self._pending_file_path = match.group(1)
                return "<FILE>"

        return None

    def _is_valid_file_path(self, path: str) -> bool:
        """Return whether a streamed FILE path is a real relative skill file path."""
        normalized = str(path or "").strip()
        if not normalized:
            return False
        if normalized in {"...", "…", "path", "file path", "相对于技能根目录的路径"}:
            return False
        if normalized.startswith("/") or "\\" in normalized or "\x00" in normalized:
            return False

        parts = normalized.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            return False
        return True

    def _create_event(self, content: str) -> Dict[str, Any]:
        """Create event based on current state."""
        if not content:
            return {}

        metadata = (
            {"origin_type": self._origin_type}
            if self._origin_type
            else {}
        )
        if self.state == "skill_body":
            return {"type": "skill_body", "content": content, "path": "SKILL.md", **metadata}
        elif self.state == "file":
            return {
                "type": "file_content",
                "content": content,
                "path": self.current_file_path,
                **metadata,
            }
        elif self.state == "summary":
            return {"type": "summary", "content": content, **metadata}
        else:
            return {
                "type": self._origin_type or "others",
                "content": content,
                **metadata,
            }

    def _handle_tag(self, tag: str) -> Optional[Dict[str, Any]]:
        """Handle matched tag and update state."""
        if tag == "<SKILL>":
            self.saw_control_tag = True
            self.state = "skill_body"
            return None

        elif tag == "<SUMMARY>":
            self.saw_control_tag = True
            self.state = "summary"
            return None

        elif tag == "</SUMMARY>" or tag == "</SKILL>":
            if tag == "</SKILL>":
                self.state = "summary"
            else:
                self.state = "others"
            return None

        elif tag == "<FILE>":
            self.saw_control_tag = True
            self._state_before_file = self.state
            self.state = "file"
            self.current_file_path = self._pending_file_path
            self._pending_file_path = None
            event = {
                "type": "file_content",
                "content": "",
                "path": self.current_file_path,
                "is_new_file": True,
            }
            if self._origin_type:
                event["origin_type"] = self._origin_type
            return event

        elif tag == "</FILE>":
            if self.state == "file":
                self.state = self._state_before_file
            self.current_file_path = None
            self._state_before_file = "others"
            return None

        return None
