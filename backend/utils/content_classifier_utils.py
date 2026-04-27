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

        # Append chunk to current buffer
        self.buffer += chunk

        # Process buffer until we can't complete more operations
        while self.buffer:
            # Check if buffer starts with a potential tag
            if self.buffer.startswith("<"):
                # Look for closing > in buffer
                if ">" not in self.buffer:
                    # Incomplete tag, wait for more content
                    break

                gt_pos = self.buffer.index(">")
                potential_tag = self.buffer[:gt_pos + 1]

                # Try to match known tags
                matched = self._match_known_tag_with_buffer(potential_tag)
                if matched:
                    # Check DoS limit BEFORE incrementing
                    if self.tag_count >= self.MAX_TAG_COUNT:
                        break
                    self.tag_count += 1

                    # Content immediately after tag (before next < or end of buffer)
                    content_after_tag = self.buffer[gt_pos + 1:]
                    self.buffer = ""

                    # Handle the matched tag
                    event = self._handle_tag(matched)
                    if event:
                        results.append(event)

                    # Process content after tag
                    if content_after_tag:
                        # If content contains another tag start, only process until that point
                        if "<" in content_after_tag:
                            next_tag_pos = content_after_tag.index("<")
                            immediate_content = content_after_tag[:next_tag_pos]
                            if immediate_content:
                                event = self._create_event(immediate_content)
                                if event:
                                    results.append(event)
                            # Keep the rest (including the <) for next iteration
                            self.buffer = content_after_tag[next_tag_pos:]
                        else:
                            # No more tags in content, emit all
                            event = self._create_event(content_after_tag)
                            if event:
                                results.append(event)
                    continue

                # Tag doesn't match any known pattern
                # Check if it's too long (potential DoS)
                if len(potential_tag) > self.MAX_TAG_LENGTH:
                    # Emit < as content and retry
                    event = self._create_event("<")
                    if event:
                        results.append(event)
                    self.buffer = self.buffer[1:]
                    continue

                # Not a recognized tag, emit < and continue processing
                event = self._create_event("<")
                if event:
                    results.append(event)
                self.buffer = self.buffer[1:]
                continue

            # No tag start, emit buffered content
            # Emit in chunks for efficiency, not character-by-character
            if len(self.buffer) > 1:
                emit_len = min(len(self.buffer), 64)  # Emit up to 64 chars at a time
                event = self._create_event(self.buffer[:emit_len])
                if event:
                    results.append(event)
                self.buffer = self.buffer[emit_len:]
            else:
                # Single character
                event = self._create_event(self.buffer)
                if event:
                    results.append(event)
                self.buffer = ""

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

        elif tag == "</SKILL>":
            self.state = "summary"
            return None

        elif tag == "<SUMMARY>":
            self.state = "summary"
            return None

        elif tag == "</SUMMARY>":
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
