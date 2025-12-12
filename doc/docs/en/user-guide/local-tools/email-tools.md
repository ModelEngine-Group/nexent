---
title: Email Tools
---

# Email Tools

Email tools help agents receive notifications and send results via common mail providers.

## 🧭 Tool List

- `get_email`: Fetch emails by time window and sender, with max count limits
- `send_email`: Send HTML emails with multiple recipients, CC, and BCC

## 🧰 Example Use Cases

- Periodically pull the past 7 days of notifications for summarization
- Send execution results to recipients and CC teammates
- Filter alerts from specific monitoring senders

## 🧾 Parameters & Behavior

### get_email
- `days`: Look back in days, default 7.
- `sender`: Filter by email address, optional.
- `max_emails`: Max messages to return, default 10.
- Requires IMAP host, port, username, password; SSL supported.
- Returns JSON with subject, time, sender, and body summary.

### send_email
- `to`: Comma-separated recipients.
- `subject`: Email subject.
- `content`: HTML body.
- `cc`, `bcc`: Comma-separated CC/BCC, optional.
- Requires SMTP host, port, username, password; optional sender display name and SSL.
- Returns delivery status, subject, and recipient info.

## 🛠️ How to Use

1. **Collect provider settings**: IMAP/SMTP host, port, account/app password, SSL.
2. **Receive**: Call `get_email` with `days`/`sender`/`max_emails`; start with small ranges to test.
3. **Send**: Call `send_email` with recipients, subject, and HTML content; add `cc`/`bcc` if needed.
4. **Post-process**: Summarize or extract key info from fetched bodies if desired.

## 🛡️ Safety & Best Practices

- Use provider-issued app passwords or restricted accounts; avoid exposing primary credentials.
- Keep `max_emails` reasonable to avoid heavy pulls.
- Verify recipient lists before sending; restrict allowed domains in production.

## 📮 Common Provider Settings

Use app passwords where available and enable IMAP/SMTP in account settings. Ports reflect common defaults—always confirm with the provider’s latest docs.

- QQ Mail: IMAP `imap.qq.com:993` (SSL); SMTP `smtp.qq.com:465` (SSL); enable IMAP/SMTP and generate an authorization code.
- Gmail: IMAP `imap.gmail.com:993`; SMTP `smtp.gmail.com:465` (SSL) or `587` (STARTTLS); enable IMAP and use an app password.
- Outlook (Microsoft 365/Hotmail): IMAP `outlook.office365.com:993`; SMTP `smtp.office365.com:587` (STARTTLS); tenants may require modern auth or app passwords.
- 163 Mail: IMAP `imap.163.com:993` (SSL); SMTP `smtp.163.com:465` (SSL); enable client authorization password in mailbox settings.

