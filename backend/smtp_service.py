"""Free Google Gmail SMTP service for AraaBot.

Sends instant email notifications, welcome messages, and account security notices
using standard Google SMTP (smtp.gmail.com:587).
Configure via environment variables:
  SMTP_USER = your_email@gmail.com
  SMTP_PASS = your_16_character_google_app_password
"""
import os, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

def send_email(to_email, subject, body_html, smtp_user=None, smtp_pass=None):
    """Sends an email via Google Gmail SMTP server. Returns (success: bool, message: str)."""
    user = smtp_user or SMTP_USER
    pwd = smtp_pass or SMTP_PASS
    if not user or not pwd:
        # Fallback / graceful notice if credentials are not configured yet
        return False, "SMTP_USER or SMTP_PASS (Google App Password) not configured"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"AraaBot <{user}>"
        msg["To"] = to_email
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=12) as server:
            server.starttls()
            server.login(user, pwd)
            server.send_message(msg)
        return True, "Email delivered successfully"
    except Exception as exc:
        print("[SMTP] Delivery failed to", to_email, ":", exc)
        return False, str(exc)

def send_welcome_email(to_email, name="Trader"):
    """Send a welcome confirmation to new registered users."""
    subject = "Welcome to AraaBot AI Quantum Trading Terminal"
    body_html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background:#0b0f17; color:#f8fafc; padding:30px; border-radius:12px; max-width:600px; margin:auto;">
      <h2 style="color:#10b981; margin-top:0;">⚡ Welcome to AraaBot.in, {name}!</h2>
      <p style="color:#94a3b8; font-size:14px; line-height:1.6;">
        Your trading workspace is active. You have access to 995+ global markets with <b>Araa AI 3.8 Neural Decision Engine</b>, real-time TradingView charts, and automated bot controls.
      </p>
      <div style="background:#151d2a; border:1px solid #1e293b; border-radius:8px; padding:16px; margin:20px 0;">
        <p style="margin:0; font-size:13px; color:#cbd5e1;"><b>Account:</b> {to_email}</p>
        <p style="margin:6px 0 0; font-size:13px; color:#10b981;"><b>Paper Wallet Balance:</b> $1,00,000.00 Ready</p>
      </div>
      <a href="https://araabot.in" style="display:inline-block; background:#10b981; color:#0f172a; font-weight:700; text-decoration:none; padding:12px 24px; border-radius:8px; font-size:14px;">Launch Terminal</a>
      <p style="margin-top:24px; font-size:11px; color:#64748b;">AraaBot Institutional Quant Engine · Automated Market Signals</p>
    </div>
    """
    return send_email(to_email, subject, body_html)
