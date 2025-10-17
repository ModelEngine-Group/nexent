import email
import logging
import imaplib
import json
from datetime import datetime, timedelta
from email.header import decode_header
from typing import List

from smolagents.tools import Tool
from pydantic import Field

from ..utils.tools_common_message import ToolCategory

logger = logging.getLogger("get_email_tool")

class GetEmailTool(Tool):
    name = "get_email"
    description = (
        "Get emails from email server. Supports filtering emails by time range and sender (sender must be an email address, not a name or non-ASCII string; subject filtering is not supported due to IMAP limitations)."
    )

    inputs = {
        "days": {"type": "integer", "description": "Get emails from the past few days, default is 7 days", "default": 7,
                 "nullable": True},
        "sender": {"type": "string", "description": "Filter by sender (must be an email address, not a name or non-ASCII string)", "nullable": True},
        "max_emails": {"type": "integer", "description": "Maximum number of emails to retrieve, default is 10",
                       "default": 10, "nullable": True}}
    output_type = "string"
    category = ToolCategory.EMAIL.value

    def __init__(self, imap_server: str=Field(description="IMAP Server Address"),
                 imap_port: int=Field(description="IMAP Server Port"), 
                 username: str=Field(description="IMAP Server Username"), 
                 password: str=Field(description="IMAP Server Password"), 
                 use_ssl: bool=Field(description="Use SSL", default=True),
                 timeout: int = Field(description="Timeout", default=30)):
        super().__init__()
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.timeout = timeout

    def _decode_subject(self, subject):
        """Decode email subject, fallback to utf-8 or latin1 for unknown encodings"""
        if subject is None:
            return ""
        decoded_chunks = []
        for chunk, encoding in decode_header(subject):
            if isinstance(chunk, bytes):
                try:
                    if encoding:
                        decoded_chunks.append(chunk.decode(encoding, errors='replace'))
                    else:
                        decoded_chunks.append(chunk.decode('utf-8', errors='replace'))
                except Exception:
                    try:
                        decoded_chunks.append(chunk.decode('utf-8', errors='replace'))
                    except Exception:
                        decoded_chunks.append(chunk.decode('latin1', errors='replace'))
            else:
                decoded_chunks.append(str(chunk))
        return ''.join(decoded_chunks)

    def _parse_email(self, msg):
        """Parse email content, decode body with fallback to utf-8 or latin1"""
        email_data = {"subject": self._decode_subject(msg["subject"]), "from": msg["from"], "date": msg["date"],
            "body": "", "attachments": []}

        def safe_decode(payload, encoding=None):
            if payload is None:
                return ""
            if encoding is None:
                encoding = 'utf-8'
            try:
                return payload.decode(encoding, errors='replace')
            except Exception:
                try:
                    return payload.decode('utf-8', errors='replace')
                except Exception:
                    return payload.decode('latin1', errors='replace')

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        encoding = part.get_content_charset()
                        email_data["body"] = safe_decode(payload, encoding)
                    except Exception:
                        email_data["body"] = part.get_payload()
                elif part.get_filename():
                    email_data["attachments"].append(part.get_filename())
        else:
            try:
                payload = msg.get_payload(decode=True)
                encoding = msg.get_content_charset()
                email_data["body"] = safe_decode(payload, encoding)
            except Exception:
                email_data["body"] = msg.get_payload()

        return email_data

    def forward(self, days: int = 7, sender: str = None, max_emails: int = 10) -> List[str]:
        try:
            # Connect to IMAP server
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port) if self.use_ssl else imaplib.IMAP4(
                self.imap_server, self.imap_port)
            mail.login(self.username, self.password)
            mail.select('INBOX')

            # Build search criteria
            search_criteria = []

            # Add time condition
            if days:
                date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
                search_criteria.append(f'(SINCE "{date}")')

            # Add sender condition
            if sender:
                search_criteria.append(f'(FROM "{sender}")')

            # Execute search
            search_query = ' '.join(search_criteria)
            logger.info(f"Searching emails with criteria: {search_query}")
            _, message_numbers = mail.search(None, search_query)

            # Fetch emails
            formatted_emails = []
            for num in message_numbers[0].split()[:max_emails]:
                _, msg_data = mail.fetch(num, '(RFC822)')
                email_body = msg_data[0][1]
                msg = email.message_from_bytes(email_body)
                parsed_email = self._parse_email(msg)

                # Create JSON formatted email content
                email_json = {"subject": parsed_email['subject'], "date": parsed_email['date'],
                    "from": parsed_email['from'], "body": parsed_email['body']}

                formatted_emails.append(json.dumps(email_json, ensure_ascii=False))

            # Close connection
            mail.close()
            mail.logout()

            return formatted_emails

        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP Error: {str(e)}")
            return [json.dumps({"error": f"Failed to retrieve emails: {str(e)}"}, ensure_ascii=False)]
        except Exception as e:
            logger.error(f"Unexpected Error: {str(e)}")
            return [json.dumps({"error": f"An unexpected error occurred: {str(e)}"}, ensure_ascii=False)]
        