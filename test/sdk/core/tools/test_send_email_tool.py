import pytest
from unittest.mock import MagicMock, patch, Mock
import json
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Import target module
from sdk.nexent.core.tools.send_email_tool import SendEmailTool


@pytest.fixture
def send_email_tool():
    """Create SendEmailTool instance for testing"""
    tool = SendEmailTool(
        smtp_server="smtp.test.com",
        smtp_port=587,
        username="test@test.com",
        password="test_password",
        use_ssl=True,
        sender_name="Test Sender",
        timeout=30
    )
    return tool


@pytest.fixture
def send_email_tool_minimal():
    """Create SendEmailTool instance with minimal parameters"""
    tool = SendEmailTool(
        smtp_server="smtp.example.com",
        smtp_port=465,
        username="user@example.com",
        password="password123"
    )
    return tool


class TestSendEmailTool:
    """Test SendEmailTool functionality"""

    def test_init_with_custom_values(self):
        """Test initialization with custom values"""
        tool = SendEmailTool(
            smtp_server="smtp.example.com",
            smtp_port=587,
            username="user@example.com",
            password="password123",
            use_ssl=False,
            sender_name="Custom Sender",
            timeout=60
        )

        assert tool.smtp_server == "smtp.example.com"
        assert tool.smtp_port == 587
        assert tool.username == "user@example.com"
        assert tool.password == "password123"
        assert tool.use_ssl is False
        assert tool.sender_name == "Custom Sender"
        assert tool.timeout == 60

    def test_tool_attributes(self, send_email_tool):
        """Test tool class attributes"""
        assert send_email_tool.name == "send_email"
        assert "Send email to specified recipients" in send_email_tool.description
        assert send_email_tool.output_type == "string"
        assert send_email_tool.category == "email"

    def test_tool_inputs_schema(self, send_email_tool):
        """Test tool inputs schema"""
        inputs = send_email_tool.inputs

        assert "to" in inputs
        assert inputs["to"]["type"] == "string"
        assert "Recipient email address" in inputs["to"]["description"]

        assert "subject" in inputs
        assert inputs["subject"]["type"] == "string"
        assert "Email subject" in inputs["subject"]["description"]

        assert "content" in inputs
        assert inputs["content"]["type"] == "string"
        assert "Email content" in inputs["content"]["description"]

        assert "cc" in inputs
        assert inputs["cc"]["type"] == "string"
        assert inputs["cc"]["nullable"] is True

        assert "bcc" in inputs
        assert inputs["bcc"]["type"] == "string"
        assert inputs["bcc"]["nullable"] is True

    @patch('smtplib.SMTP_SSL')
    @patch('ssl.create_default_context')
    def test_forward_success_basic_email(self, mock_ssl_context, mock_smtp_ssl, send_email_tool):
        """Test successful basic email sending"""
        # Mock SSL context
        mock_context = Mock()
        mock_ssl_context.return_value = mock_context

        # Mock SMTP server
        mock_server = Mock()
        mock_smtp_ssl.return_value = mock_server

        result = send_email_tool.forward(
            to="recipient@example.com",
            subject="Test Subject",
            content="<p>Test HTML content</p>"
        )

        # Parse result
        result_data = json.loads(result)

        # Verify success response
        assert result_data["status"] == "success"
        assert result_data["message"] == "Email sent successfully"
        assert result_data["to"] == "recipient@example.com"
        assert result_data["subject"] == "Test Subject"

        # Verify SMTP operations
        mock_smtp_ssl.assert_called_once_with(
            "smtp.test.com", 587, context=mock_context, timeout=30
        )
        mock_server.login.assert_called_once_with(
            "test@test.com", "test_password")
        mock_server.send_message.assert_called_once()
        mock_server.quit.assert_called_once()

    @patch('smtplib.SMTP_SSL')
    @patch('ssl.create_default_context')
    def test_forward_success_with_cc_and_bcc(self, mock_ssl_context, mock_smtp_ssl, send_email_tool):
        """Test successful email sending with CC and BCC"""
        # Mock SSL context
        mock_context = Mock()
        mock_ssl_context.return_value = mock_context

        # Mock SMTP server
        mock_server = Mock()
        mock_smtp_ssl.return_value = mock_server

        result = send_email_tool.forward(
            to="recipient@example.com",
            subject="Test Subject",
            content="<p>Test content</p>",
            cc="cc1@example.com,cc2@example.com",
            bcc="bcc@example.com"
        )

        # Parse result
        result_data = json.loads(result)

        # Verify success response
        assert result_data["status"] == "success"

        # Verify send_message was called with proper recipients
        mock_server.send_message.assert_called_once()
        call_args = mock_server.send_message.call_args[0][0]

        # Verify email headers
        assert call_args['From'] == "Test Sender <test@test.com>"
        assert call_args['To'] == "recipient@example.com"
        assert call_args['Subject'] == "Test Subject"
        assert call_args['Cc'] == "cc1@example.com,cc2@example.com"
        assert call_args['Bcc'] == "bcc@example.com"

    @patch('smtplib.SMTP_SSL')
    @patch('ssl.create_default_context')
    def test_forward_success_multiple_recipients(self, mock_ssl_context, mock_smtp_ssl, send_email_tool):
        """Test successful email sending with multiple recipients"""
        # Mock SSL context
        mock_context = Mock()
        mock_ssl_context.return_value = mock_context

        # Mock SMTP server
        mock_server = Mock()
        mock_smtp_ssl.return_value = mock_server

        result = send_email_tool.forward(
            to="recipient1@example.com,recipient2@example.com",
            subject="Test Subject",
            content="<p>Test content</p>",
            cc="cc@example.com",
            bcc="bcc@example.com"
        )

        # Parse result
        result_data = json.loads(result)

        # Verify success response
        assert result_data["status"] == "success"
        assert result_data["to"] == "recipient1@example.com,recipient2@example.com"

    @patch('smtplib.SMTP_SSL')
    @patch('ssl.create_default_context')
    def test_forward_smtp_send_error(self, mock_ssl_context, mock_smtp_ssl, send_email_tool):
        """Test email sending with SMTP send error"""
        # Mock SSL context
        mock_context = Mock()
        mock_ssl_context.return_value = mock_context

        # Mock SMTP server with send failure
        mock_server = Mock()
        mock_server.send_message.side_effect = smtplib.SMTPRecipientsRefused(
            "Recipients refused"
        )
        mock_smtp_ssl.return_value = mock_server

        result = send_email_tool.forward(
            to="recipient@example.com",
            subject="Test Subject",
            content="<p>Test content</p>"
        )

        # Parse result
        result_data = json.loads(result)

        # Verify error response
        assert result_data["status"] == "error"
        assert "Failed to send email" in result_data["message"]

    @patch('smtplib.SMTP_SSL')
    @patch('ssl.create_default_context')
    def test_forward_unexpected_exception(self, mock_ssl_context, mock_smtp_ssl, send_email_tool):
        """Test email sending with unexpected exception"""
        # Mock SSL context
        mock_context = Mock()
        mock_ssl_context.return_value = mock_context

        # Mock SMTP server with unexpected error
        mock_server = Mock()
        mock_server.login.side_effect = RuntimeError("Unexpected error")
        mock_smtp_ssl.return_value = mock_server

        result = send_email_tool.forward(
            to="recipient@example.com",
            subject="Test Subject",
            content="<p>Test content</p>"
        )

        # Parse result
        result_data = json.loads(result)

        # Verify error response
        assert result_data["status"] == "error"
        assert "An unexpected error occurred" in result_data["message"]
        assert "Unexpected error" in result_data["message"]

    @patch('smtplib.SMTP_SSL')
    @patch('ssl.create_default_context')
    def test_forward_empty_cc_and_bcc(self, mock_ssl_context, mock_smtp_ssl, send_email_tool):
        """Test email sending with empty CC and BCC"""
        # Mock SSL context
        mock_context = Mock()
        mock_ssl_context.return_value = mock_context

        # Mock SMTP server
        mock_server = Mock()
        mock_smtp_ssl.return_value = mock_server

        result = send_email_tool.forward(
            to="recipient@example.com",
            subject="Test Subject",
            content="<p>Test content</p>",
            cc="",
            bcc=""
        )

        # Parse result
        result_data = json.loads(result)

        # Verify success response
        assert result_data["status"] == "success"

        # Verify email headers don't include empty CC/BCC
        call_args = mock_server.send_message.call_args[0][0]
        assert 'Cc' not in call_args
        assert 'Bcc' not in call_args

    @patch('smtplib.SMTP_SSL')
    @patch('ssl.create_default_context')
    def test_forward_html_content_attachment(self, mock_ssl_context, mock_smtp_ssl, send_email_tool):
        """Test that HTML content is properly attached to email"""
        # Mock SSL context
        mock_context = Mock()
        mock_ssl_context.return_value = mock_context

        # Mock SMTP server
        mock_server = Mock()
        mock_smtp_ssl.return_value = mock_server

        html_content = "<h1>Test Header</h1><p>This is <strong>bold</strong> text.</p>"

        result = send_email_tool.forward(
            to="recipient@example.com",
            subject="Test Subject",
            content=html_content
        )

        # Parse result
        result_data = json.loads(result)

        # Verify success response
        assert result_data["status"] == "success"

        # Verify email message structure
        call_args = mock_server.send_message.call_args[0][0]
        assert isinstance(call_args, MIMEMultipart)

        # Verify HTML content is attached
        attachments = call_args.get_payload()
        assert len(attachments) == 1
        assert isinstance(attachments[0], MIMEText)
        assert attachments[0].get_content_type() == "text/html"
        assert attachments[0].get_payload() == html_content

    @patch('smtplib.SMTP_SSL')
    @patch('ssl.create_default_context')
    def test_forward_ssl_context_configuration(self, mock_ssl_context, mock_smtp_ssl, send_email_tool):
        """Test SSL context is properly configured"""
        # Mock SSL context
        mock_context = Mock()
        mock_ssl_context.return_value = mock_context

        # Mock SMTP server
        mock_server = Mock()
        mock_smtp_ssl.return_value = mock_server

        send_email_tool.forward(
            to="recipient@example.com",
            subject="Test Subject",
            content="<p>Test content</p>"
        )

        # Verify SSL context configuration
        mock_ssl_context.assert_called_once()
        assert mock_context.check_hostname is True
        assert mock_context.verify_mode == ssl.CERT_REQUIRED

        # Verify SMTP_SSL is called with context
        mock_smtp_ssl.assert_called_once_with(
            "smtp.test.com", 587, context=mock_context, timeout=30
        )

    @patch('smtplib.SMTP_SSL')
    @patch('ssl.create_default_context')
    def test_forward_timeout_configuration(self, mock_ssl_context, mock_smtp_ssl):
        """Test timeout configuration is properly passed"""
        # Create tool with custom timeout
        tool = SendEmailTool(
            smtp_server="smtp.example.com",
            smtp_port=465,
            username="user@example.com",
            password="password123",
            timeout=60
        )

        # Mock SSL context
        mock_context = Mock()
        mock_ssl_context.return_value = mock_context

        # Mock SMTP server
        mock_server = Mock()
        mock_smtp_ssl.return_value = mock_server

        tool.forward(
            to="recipient@example.com",
            subject="Test Subject",
            content="<p>Test content</p>"
        )

        # Verify timeout is passed to SMTP_SSL
        mock_smtp_ssl.assert_called_once_with(
            "smtp.example.com", 465, context=mock_context, timeout=60
        )

    @patch('smtplib.SMTP_SSL')
    @patch('ssl.create_default_context')
    def test_forward_server_quit_called_on_success(self, mock_ssl_context, mock_smtp_ssl, send_email_tool):
        """Test that server.quit() is called on successful send"""
        # Mock SSL context
        mock_context = Mock()
        mock_ssl_context.return_value = mock_context

        # Mock SMTP server
        mock_server = Mock()
        mock_smtp_ssl.return_value = mock_server

        send_email_tool.forward(
            to="recipient@example.com",
            subject="Test Subject",
            content="<p>Test content</p>"
        )

        # Verify server.quit() is called
        mock_server.quit.assert_called_once()

    def test_forward_empty_parameters(self, send_email_tool):
        """Test forward method with empty parameters"""
        with patch('smtplib.SMTP_SSL') as mock_smtp_ssl, \
                patch('ssl.create_default_context') as mock_ssl_context:

            # Mock SSL context
            mock_context = Mock()
            mock_ssl_context.return_value = mock_context

            # Mock SMTP server
            mock_server = Mock()
            mock_smtp_ssl.return_value = mock_server

            result = send_email_tool.forward(
                to="",
                subject="",
                content=""
            )

            # Parse result
            result_data = json.loads(result)

            # Should still succeed (empty strings are valid)
            assert result_data["status"] == "success"
            assert result_data["to"] == ""
            assert result_data["subject"] == ""


if __name__ == '__main__':
    pytest.main([__file__])
