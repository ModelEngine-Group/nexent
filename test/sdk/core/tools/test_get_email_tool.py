import pytest
from unittest.mock import MagicMock, patch
import json
import email
from datetime import datetime, timedelta

# Import target module
from sdk.nexent.core.tools.get_email_tool import GetEmailTool


@pytest.fixture
def get_email_tool():
    """Create GetEmailTool instance for testing"""
    tool = GetEmailTool(
        imap_server="imap.test.com",
        imap_port=993,
        username="test@test.com",
        password="test_password",
        use_ssl=True,
        timeout=30
    )
    return tool


class TestGetEmailTool:
    """Test GetEmailTool functionality"""

    def test_init_with_custom_values(self):
        """Test initialization with custom values"""
        tool = GetEmailTool(
            imap_server="imap.example.com",
            imap_port=143,
            username="user@example.com",
            password="password123",
            use_ssl=False,
            timeout=60
        )

        assert tool.imap_server == "imap.example.com"
        assert tool.imap_port == 143
        assert tool.username == "user@example.com"
        assert tool.password == "password123"
        assert tool.use_ssl is False
        assert tool.timeout == 60

    def test_decode_subject_none(self, get_email_tool):
        """Test _decode_subject with None input"""
        result = get_email_tool._decode_subject(None)
        assert result == ""

    def test_decode_subject_string(self, get_email_tool):
        """Test _decode_subject with string input"""
        result = get_email_tool._decode_subject("Test Subject")
        assert result == "Test Subject"

    def test_parse_email_simple(self, get_email_tool):
        """Test _parse_email with simple email message"""
        # Create a simple email message
        msg = email.message.EmailMessage()
        msg["Subject"] = "Test Subject"
        msg["From"] = "sender@test.com"

        result = get_email_tool._parse_email(msg)

        assert result["subject"] == "Test Subject"
        assert result["from"] == "sender@test.com"
        assert result["attachments"] == []

    def test_parse_email_multipart(self, get_email_tool):
        """Test _parse_email with multipart email message"""
        # Create a multipart email message
        msg = email.message.EmailMessage()
        msg["Subject"] = "Multipart Test"
        msg["From"] = "sender@test.com"
        msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"

        # Add text part
        text_part = email.message.EmailMessage()
        text_part.set_content("Text content")
        msg.attach(text_part)

        # Add attachment
        attachment = email.message.EmailMessage()
        attachment.set_content("Attachment content")
        attachment.add_header("Content-Disposition",
                              "attachment", filename="test.txt")
        msg.attach(attachment)

        result = get_email_tool._parse_email(msg)

        assert result["subject"] == "Multipart Test"
        assert result["body"] == "Attachment content\n"

    def test_forward_success_with_results(self, get_email_tool):
        """Test forward method with successful email retrieval"""
        # Mock IMAP connection and email data
        mock_mail = MagicMock()
        mock_mail.search.return_value = (None, [b"1 2 3"])
        mock_mail.fetch.return_value = (None, [(None, b"email data")])

        # Mock email message
        mock_msg = email.message.EmailMessage()
        mock_msg["Subject"] = "Test Subject"
        mock_msg["From"] = "sender@test.com"
        mock_msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
        mock_msg.set_content("Test body")

        with patch('imaplib.IMAP4_SSL', return_value=mock_mail), \
                patch('email.message_from_bytes', return_value=mock_msg):

            result = get_email_tool.forward(days=7, max_emails=3)

        # Verify result
        assert len(result) == 3
        for email_json in result:
            email_data = json.loads(email_json)
            assert "subject" in email_data
            assert "from" in email_data
            assert "date" in email_data
            assert "body" in email_data

        # Verify IMAP calls
        mock_mail.login.assert_called_once_with(
            "test@test.com", "test_password")
        mock_mail.select.assert_called_once_with('INBOX')
        mock_mail.close.assert_called_once()
        mock_mail.logout.assert_called_once()

    def test_forward_success_with_sender_filter(self, get_email_tool):
        """Test forward method with sender filter"""
        # Mock IMAP connection
        mock_mail = MagicMock()
        mock_mail.search.return_value = (None, [b"1 2"])
        mock_mail.fetch.return_value = (None, [(None, b"email data")])

        # Mock email message
        mock_msg = email.message.EmailMessage()
        mock_msg["Subject"] = "Test Subject"
        mock_msg["From"] = "specific@test.com"
        mock_msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
        mock_msg.set_content("Test body")

        with patch('imaplib.IMAP4_SSL', return_value=mock_mail), \
                patch('email.message_from_bytes', return_value=mock_msg):

            result = get_email_tool.forward(
                days=7, sender="specific@test.com", max_emails=2)

        # Verify search was called with sender filter
        mock_mail.search.assert_called_once()
        search_args = mock_mail.search.call_args[0]
        assert 'FROM "specific@test.com"' in search_args[1]

    def test_forward_success_with_time_filter(self, get_email_tool):
        """Test forward method with time filter"""
        # Mock IMAP connection
        mock_mail = MagicMock()
        mock_mail.search.return_value = (None, [b"1"])
        mock_mail.fetch.return_value = (None, [(None, b"email data")])

        # Mock email message
        mock_msg = email.message.EmailMessage()
        mock_msg["Subject"] = "Test Subject"
        mock_msg["From"] = "sender@test.com"
        mock_msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
        mock_msg.set_content("Test body")

        with patch('imaplib.IMAP4_SSL', return_value=mock_mail), \
                patch('email.message_from_bytes', return_value=mock_msg):

            result = get_email_tool.forward(days=3, max_emails=1)

        # Verify search was called with time filter
        mock_mail.search.assert_called_once()
        search_args = mock_mail.search.call_args[0]
        assert 'SINCE' in search_args[1]

    def test_forward_success_no_ssl(self):
        """Test forward method without SSL"""
        tool = GetEmailTool(
            imap_server="imap.test.com",
            imap_port=143,
            username="test@test.com",
            password="test_password",
            use_ssl=False
        )

        # Mock IMAP connection
        mock_mail = MagicMock()
        mock_mail.search.return_value = (None, [b"1"])
        mock_mail.fetch.return_value = (None, [(None, b"email data")])

        # Mock email message
        mock_msg = email.message.EmailMessage()
        mock_msg["Subject"] = "Test Subject"
        mock_msg["From"] = "sender@test.com"
        mock_msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
        mock_msg.set_content("Test body")

        with patch('imaplib.IMAP4', return_value=mock_mail), \
                patch('email.message_from_bytes', return_value=mock_msg):

            result = tool.forward(days=7, max_emails=1)

        # Verify IMAP4 (not SSL) was used
        assert len(result) == 1

    def test_forward_imap_error(self, get_email_tool):
        """Test forward method with IMAP error"""
        # Mock IMAP connection with error
        mock_mail = MagicMock()
        mock_mail.login.side_effect = Exception("IMAP connection failed")

        with patch('imaplib.IMAP4_SSL', return_value=mock_mail):
            result = get_email_tool.forward(days=7, max_emails=1)

        # Verify error handling
        assert len(result) == 1
        error_data = json.loads(result[0])
        assert "error" in error_data

    def test_forward_unexpected_error(self, get_email_tool):
        """Test forward method with unexpected error"""
        # Mock IMAP connection with unexpected error
        mock_mail = MagicMock()
        mock_mail.login.side_effect = RuntimeError("Unexpected error")

        with patch('imaplib.IMAP4_SSL', return_value=mock_mail):
            result = get_email_tool.forward(days=7, max_emails=1)

        # Verify error handling
        assert len(result) == 1
        error_data = json.loads(result[0])
        assert "error" in error_data
        assert "An unexpected error occurred" in error_data["error"]

    def test_forward_empty_search_results(self, get_email_tool):
        """Test forward method with empty search results"""
        # Mock IMAP connection with empty results
        mock_mail = MagicMock()
        mock_mail.search.return_value = (None, [b""])

        with patch('imaplib.IMAP4_SSL', return_value=mock_mail):
            result = get_email_tool.forward(days=7, max_emails=1)

        # Verify empty result
        assert len(result) == 0

    def test_forward_default_parameters(self, get_email_tool):
        """Test forward method with default parameters"""
        # Mock IMAP connection
        mock_mail = MagicMock()
        mock_mail.search.return_value = (None, [b"1"])
        mock_mail.fetch.return_value = (None, [(None, b"email data")])

        # Mock email message
        mock_msg = email.message.EmailMessage()
        mock_msg["Subject"] = "Test Subject"
        mock_msg["From"] = "sender@test.com"
        mock_msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
        mock_msg.set_content("Test body")

        with patch('imaplib.IMAP4_SSL', return_value=mock_mail), \
                patch('email.message_from_bytes', return_value=mock_msg):

            result = get_email_tool.forward()

        # Verify default parameters were used
        assert len(result) == 1
        mock_mail.search.assert_called_once()
        search_args = mock_mail.search.call_args[0]
        assert 'SINCE' in search_args[1]  # Should have time filter for 7 days
        assert 'FROM' not in search_args[1]  # Should not have sender filter
