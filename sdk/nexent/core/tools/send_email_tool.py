import json
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from pydantic import Field
from smolagents.tools import Tool

from ..utils.tools_common_message import ToolCategory

logger = logging.getLogger("send_email_tool")
class SendEmailTool(Tool):
    name = "send_email"
    description = "Send email to specified recipients. Supports only HTML formatted email content, and can add multiple recipients, CC, and BCC."

    description_zh = "向指定收件人发送 HTML 格式邮件，支持添加多个收件人、抄送和密送。"

    inputs = {
        "to": {
            "type": "string",
            "description": "Recipient email address, multiple recipients separated by commas",
            "description_zh": "收件人邮箱地址，多个收件人用逗号分隔"
        },
        "subject": {
            "type": "string",
            "description": "Email subject",
            "description_zh": "邮件主题"
        },
        "content": {
            "type": "string",
            "description": "Email content, supports HTML format",
            "description_zh": "邮件内容，支持 HTML 格式"
        },
        "cc": {
            "type": "string",
            "description": "CC email address, multiple CCs separated by commas, optional",
            "description_zh": "抄送邮箱地址，多个抄送用逗号分隔，可选",
            "nullable": True
        },
        "bcc": {
            "type": "string",
            "description": "BCC email address, multiple BCCs separated by commas, optional",
            "description_zh": "密送邮箱地址，多个密送用逗号分隔，可选",
            "nullable": True
        },
        "sender_email": {
            "type": "string",
            "description": "Actual sender email address (From address), optional - defaults to username",
            "description_zh": "实际发件人邮箱地址（From字段），可选，默认为username",
            "nullable": True
        }
    }

    init_param_descriptions = {
        "smtp_server": {
            "description": "SMTP Server Address",
            "description_zh": "SMTP 服务器地址"
        },
        "smtp_port": {
            "description": "SMTP server port",
            "description_zh": "SMTP 服务器端口"
        },
        "username": {
            "description": "SMTP server username",
            "description_zh": "SMTP 服务器用户名"
        },
        "password": {
            "description": "SMTP server password",
            "description_zh": "SMTP 服务器密码"
        },
        "use_ssl": {
            "description": "Use SSL/TLS encryption (set to False for plain text)",
            "description_zh": "使用 SSL/TLS 加密（设为 False 使用明文）"
        },
        "sender_email": {
            "description": "Actual sender email address (From address), defaults to username",
            "description_zh": "实际发件人邮箱地址，默认为 username"
        },
        "sender_name": {
            "description": "Sender name",
            "description_zh": "发件人名称"
        },
        "timeout": {
            "description": "Timeout",
            "description_zh": "连接超时时间（秒）"
        }
    }
    output_type = "string"
    category = ToolCategory.EMAIL.value

    def __init__(self, smtp_server: str = "",
                 smtp_port: int = 587,
                 username: str = "",
                 password: str = "",
                 use_ssl: bool = True,
                 sender_email: Optional[str] = None,
                 sender_name: Optional[str] = None,
                 timeout: int = 30):
        super().__init__()
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.sender_email = sender_email or username
        self.sender_name = sender_name
        self.timeout = timeout

    def _create_ssl_context(self, skip_verify: bool = False) -> ssl.SSLContext:
        """Create SSL context with optional verification disabled for self-signed certs."""
        context = ssl.create_default_context()
        if skip_verify:
            logger.warning("SSL verification disabled - use only for internal/local SMTP servers")
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        else:
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
        return context

    def forward(self, to: str, subject: str, content: str, cc: str = "", bcc: str = "",
                sender_email: Optional[str] = None) -> str:
        try:
            logger.info("Creating email message...")
            msg = MIMEMultipart()

            sender = sender_email or self.sender_email
            if self.sender_name:
                msg['From'] = f"{self.sender_name} <{sender}>"
            else:
                msg['From'] = sender

            msg['To'] = to
            msg['Subject'] = subject

            if cc:
                msg['Cc'] = cc
            if bcc:
                msg['Bcc'] = bcc

            # Add email content
            msg.attach(MIMEText(content, 'html'))

            logger.info(f"Connecting to SMTP server {self.smtp_server}:{self.smtp_port}...")

            # Connect to SMTP server
            if self.smtp_port == 465:
                # Port 465 uses implicit SSL
                logger.info("Using implicit SSL connection (port 465)...")
                context = self._create_ssl_context(skip_verify=True)
                server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context, timeout=self.timeout)
            elif self.use_ssl:
                # Port 587 (and others) use STARTTLS
                logger.info("Using STARTTLS connection...")
                server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=self.timeout)
                server.starttls(context=self._create_ssl_context(skip_verify=True))
            else:
                # Port 25 - plain connection (may have self-signed certs)
                logger.info("Using plain text connection (port 25)...")
                server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=self.timeout)
                # Some servers force TLS handshake even on plain connections
                # Skip cert verification for port 25 to handle self-signed certs
                try:
                    server.starttls(context=self._create_ssl_context(skip_verify=True))
                    logger.info("Server upgraded to TLS connection")
                except smtplib.SMTPNotSupportedError:
                    logger.info("Server does not support STARTTLS, using plain connection")
                except Exception as tls_err:
                    logger.warning(f"TLS upgrade failed: {tls_err}, continuing with plain connection")

            logger.info("Logging in...")
            # Login
            server.login(self.username, self.password)

            # Send email
            recipients = [to]
            if cc:
                recipients.extend(cc.split(','))
            if bcc:
                recipients.extend(bcc.split(','))

            logger.info("Sending email...")
            server.send_message(msg)
            logger.info("Email sent successfully!")
            server.quit()

            return json.dumps({"status": "success", "message": "Email sent successfully", "to": to, "subject": subject},
                ensure_ascii=False)

        except smtplib.SMTPException as e:
            logger.error(f"SMTP Error: {str(e)}")
            return json.dumps({"status": "error", "message": f"Failed to send email: {str(e)}"}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Unexpected Error: {str(e)}")
            return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"},
                ensure_ascii=False)
