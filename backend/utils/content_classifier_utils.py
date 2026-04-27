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
        self._known_tags = {
            "<SKILL>",
            "</SKILL>",
            "<SUMMARY>",
            "</SUMMARY>",
            "</FILE>",
        }
        self._pending_file_path: Optional[str] = None

    def classify(self, chunk: str) -> List[Dict[str, Any]]:
        """Process streaming chunk and return list of classified events."""
        results = []
        self.buffer += chunk

        while self.buffer:
            if self.buffer.startswith("<"):
                if ">" not in self.buffer:
                    break
                results.extend(self._process_tag_start())
            else:
                results.extend(self._process_non_tag_content())

        return results

    def _process_tag_start(self) -> List[Dict[str, Any]]:
        """Process buffer when it starts with '<' - extracts and handles tags."""
        results = []
        gt_pos = self.buffer.index(">")
        potential_tag = self.buffer[:gt_pos + 1]
        matched = self._match_known_tag_with_buffer(potential_tag)

        if matched:
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
            self.buffer = self.buffer[gt_pos + 1:]
            return results

        self.tag_count += 1
        content_after_tag = self.buffer[gt_pos + 1:]
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
            if match:
                self._pending_file_path = match.group(1)
                return "<FILE>"

        return None

    def _create_event(self, content: str) -> Dict[str, Any]:
        """Create event based on current state."""
        if not content:
            return {}

        if self.state == "skill_body":
            return {"type": "skill_body", "content": content}
        elif self.state == "file":
            return {"type": "file_content", "content": content, "path": self.current_file_path}
        elif self.state == "summary":
            return {"type": "summary", "content": content}
        else:
            return {"type": "others", "content": content}

    def _handle_tag(self, tag: str) -> Optional[Dict[str, Any]]:
        """Handle matched tag and update state."""
        if tag == "<SKILL>":
            self.state = "skill_body"
            return None

        elif tag == "<SUMMARY>":
            self.state = "summary"
            return None

        elif tag == "</SUMMARY>" or tag == "</SKILL>":
            if tag == "</SKILL>":
                self.state = "summary"
            else:
                self.state = "others"
            return None

        elif tag == "<FILE>":
            self.state = "file"
            self.current_file_path = self._pending_file_path
            self._pending_file_path = None
            return {"type": "file_content", "content": "", "path": self.current_file_path, "is_new_file": True}

        elif tag == "</FILE>":
            self.state = "skill_body"
            self.current_file_path = None
            return None

        return None
