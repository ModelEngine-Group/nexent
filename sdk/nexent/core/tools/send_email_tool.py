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

    inputs = {
        "to": {"type": "string", "description": "Recipient email address, multiple recipients separated by commas"},
        "subject": {"type": "string", "description": "Email subject"},
        "content": {"type": "string", "description": "Email content, supports HTML format"},
        "cc": {"type": "string", "description": "CC email address, multiple CCs separated by commas, optional",
               "nullable": True},
        "bcc": {"type": "string", "description": "BCC email address, multiple BCCs separated by commas, optional",
                "nullable": True}}
    output_type = "string"
    category = ToolCategory.EMAIL.value

    def __init__(self, smtp_server: str=Field(description="SMTP Server Address"),
                 smtp_port: int=Field(description="SMTP server port"), 
                 username: str=Field(description="SMTP server username"), 
                 password: str=Field(description="SMTP server password"), 
                 use_ssl: bool=Field(description="Use SSL", default=True),
                 sender_name: Optional[str] = Field(description="Sender name", default=None),
                 timeout: int = Field(description="Timeout", default=30)):
        super().__init__()
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.sender_name = sender_name
        self.timeout = timeout

    def forward(self, to: str, subject: str, content: str, cc: str = "", bcc: str = "") -> str:
        try:
            logger.info("Creating email message...")
            # Create email object
            msg = MIMEMultipart()
            msg['From'] = f"{self.sender_name} <{self.username}>" if self.sender_name else self.username
            msg['To'] = to
            msg['Subject'] = subject

            if cc:
                msg['Cc'] = cc
            if bcc:
                msg['Bcc'] = bcc

            # Add email content
            msg.attach(MIMEText(content, 'html'))

            logger.info(f"Connecting to SMTP server {self.smtp_server}:{self.smtp_port}...")

            # Create SSL context
            context = ssl.create_default_context()
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED

            # Connect to SMTP server using SSL
            logger.info("Using SSL connection...")
            server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context, timeout=self.timeout)

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
