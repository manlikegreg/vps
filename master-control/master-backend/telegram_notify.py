import os
import httpx
from typing import Optional

# Simple Telegram bot notifier (no-op if not configured)
# Configure at least one of the following pairs in the master-backend environment:
# - TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
# - MASTER_TG_BOT_TOKEN and MASTER_TG_CHAT_ID (aliases)
# Optional: TELEGRAM_THREAD_ID (aka message thread/topic id for forums)

async def send_telegram(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("MASTER_TG_BOT_TOKEN") or ""
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("MASTER_TG_CHAT_ID") or ""
    thread_id = os.getenv("TELEGRAM_THREAD_ID") or os.getenv("MASTER_TG_THREAD_ID")
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if thread_id:
        try:
            payload["message_thread_id"] = int(thread_id)
        except Exception:
            pass
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.post(url, data=payload)
            return r.status_code == 200
    except Exception:
        return False
