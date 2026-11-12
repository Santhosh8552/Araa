# =====================================================================
# ARAABOT TELEGRAM NOTIFICATION DISPATCHER
# Live mobile trade execution, target hit & daily P&L broadcasts
# =====================================================================
import os
import time
import requests
import logging
from database import query, query_one, write, get_state, set_state

logger = logging.getLogger("telegram_notifier")

def get_telegram_config(user_id=None):
    """Fetches user-specific or global platform telegram bot credentials."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    
    # Check database state if not in env
    db_token = get_state("telegram_bot_token", "")
    db_chat = get_state("telegram_chat_id", "")
    
    token = bot_token or db_token
    target_chat = chat_id or db_chat
    
    # User-level override if stored
    if user_id:
        u_token = get_state(f"user_{user_id}_telegram_token", "")
        u_chat = get_state(f"user_{user_id}_telegram_chat", "")
        if u_token:
            token = u_token
        if u_chat:
            target_chat = u_chat
            
    return token, target_chat

def save_telegram_config(bot_token, chat_id, user_id=None):
    """Saves Telegram configuration either globally or for a specific user."""
    bot_token = (bot_token or "").strip()
    chat_id = (chat_id or "").strip()
    
    if user_id:
        set_state(f"user_{user_id}_telegram_token", bot_token)
        set_state(f"user_{user_id}_telegram_chat", chat_id)
    else:
        set_state("telegram_bot_token", bot_token)
        set_state("telegram_chat_id", chat_id)
        
    return True

def send_telegram_message(text, user_id=None, parse_mode="HTML"):
    """Sends formatted notification directly to Telegram channel or user chat."""
    token, chat_id = get_telegram_config(user_id)
    if not token or not chat_id:
        return False, "Telegram bot token or chat ID not configured"
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(url, json=payload, timeout=6)
        data = res.json()
        if data.get("ok"):
            return True, "Sent"
        else:
            return False, data.get("description", "Telegram API returned error")
    except Exception as e:
        logger.warning(f"[TELEGRAM] Delivery failed: {e}")
        return False, str(e)

def test_telegram_connection(bot_token, chat_id):
    """Tests provided Telegram bot token and chat_id with an instant greeting."""
    if not bot_token or not chat_id:
        return False, "Both Bot Token and Chat ID are required"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    text = (
        "⚡ <b>ARAA AI QUANTUM BOT · TELEGRAM CONNECTED</b>\n\n"
        "✅ Live Trade Signals &amp; Closed Profit Alerts are now linked to this chat!\n"
        f"🕒 Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n"
        "🤖 <i>3-Agent Committee Active (Alpha · Beta · Gamma)</i>"
    )
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=6)
        d = res.json()
        if d.get("ok"):
            return True, "Connected successfully! Test message sent to your Telegram."
        return False, d.get("description", "Invalid token or chat ID")
    except Exception as e:
        return False, str(e)

def notify_order_opened(symbol, side, price, qty, leverage, win_prob, source="COINDCX LIVE", user_id=None):
    """Broadcasts new live bot entry."""
    side_icon = "🟢 LONG / BUY" if side.upper() in ("BUY", "LONG") else "🔴 SHORT / SELL"
    msg = (
        f"⚡ <b>ARAA AI TRADE OPENED</b>\n\n"
        f"📊 <b>Pair:</b> #{symbol}\n"
        f"🎯 <b>Direction:</b> {side_icon}\n"
        f"💵 <b>Entry Price:</b> ${price:,.4f}\n"
        f"⚙️ <b>Leverage:</b> {int(leverage)}x\n"
        f"🧠 <b>AI Win Probability:</b> {win_prob:.1f}%\n"
        f"🌐 <b>Execution:</b> {source}\n"
        f"🕒 {time.strftime('%H:%M:%S UTC', time.gmtime())}"
    )
    return send_telegram_message(msg, user_id=user_id)

def notify_order_closed(symbol, side, pnl, roi_pct, reason="TARGET_REACHED", user_id=None):
    """Broadcasts completed trade outcome and booked profits."""
    is_win = pnl >= 0
    status_icon = "💰 <b>TARGET HIT (PROFIT BOOKED)</b>" if is_win else "🛑 <b>STOP LOSS TRIGGERED</b>"
    pnl_sign = "+" if is_win else ""
    msg = (
        f"{status_icon}\n\n"
        f"📊 <b>Pair:</b> #{symbol} ({side})\n"
        f"💵 <b>Realized P&amp;L:</b> {pnl_sign}${pnl:,.2f} ({pnl_sign}{roi_pct:.2f}% ROI)\n"
        f"📝 <b>Exit Reason:</b> {reason}\n"
        f"🕒 {time.strftime('%H:%M:%S UTC', time.gmtime())}"
    )
    return send_telegram_message(msg, user_id=user_id)
