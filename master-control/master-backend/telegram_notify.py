import os
import json
import uuid
import httpx
from typing import Optional, Tuple, Dict, Any

# Simple Telegram bot notifier with optional runtime configuration file.
# You can configure via one of the following methods:
# 1) Runtime config file (preferred for UI management): master-backend/config/telegram.json
# 2) Environment variables:
#    - TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
#    - or MASTER_TG_BOT_TOKEN and MASTER_TG_CHAT_ID (aliases)
# Optional thread/topic id: TELEGRAM_THREAD_ID or MASTER_TG_THREAD_ID

CONFIG_DIR = os.path.join(os.path.dirname(__file__), 'config')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'telegram.json')

# Schema stored in CONFIG_FILE:
# {
#   "active_id": "<uuid>",
#   "bots": [
#     {"id": "<uuid>", "label": "Main", "token": "...", "chat_id": "...", "thread_id": 12345}
#   ]
# }

def _ensure_config_dir() -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
    except Exception:
        pass

def _load_cfg() -> Dict[str, Any]:
    _ensure_config_dir()
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
                if isinstance(data, dict):
                    data.setdefault('bots', [])
                    data.setdefault('active_id', None)
                    data.setdefault('webhook_secret', None)
                    data.setdefault('webhook_url', None)
                    return data
    except Exception:
        pass
    return {"bots": [], "active_id": None, "webhook_secret": None, "webhook_url": None}

def _save_cfg(cfg: Dict[str, Any]) -> bool:
    _ensure_config_dir()
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception:
        return False

def list_bots() -> Dict[str, Any]:
    cfg = _load_cfg()
    # mask token for UI safety
    bots = []
    for b in cfg.get('bots', []):
        t = b.get('token') or ''
        bots.append({
            'id': b.get('id'),
            'label': b.get('label'),
            'chat_id': b.get('chat_id'),
            'thread_id': b.get('thread_id'),
            'token_last4': t[-4:] if len(t) >= 4 else (t if t else None),
            'has_token': bool(t),
        })
    return {'active_id': cfg.get('active_id'), 'bots': bots}

def add_bot(label: Optional[str], token: str, chat_id: str, thread_id: Optional[int] = None) -> Dict[str, Any]:
    cfg = _load_cfg()
    bot = {
        'id': str(uuid.uuid4()),
        'label': label or 'Bot',
        'token': str(token),
        'chat_id': str(chat_id),
        'thread_id': int(thread_id) if (isinstance(thread_id, int) or (isinstance(thread_id, str) and thread_id.isdigit())) else None,
    }
    cfg.setdefault('bots', []).append(bot)
    if not cfg.get('active_id'):
        cfg['active_id'] = bot['id']
    _save_cfg(cfg)
    return {'id': bot['id']}

def update_bot(bot_id: str, label: Optional[str] = None, token: Optional[str] = None, chat_id: Optional[str] = None, thread_id: Optional[int] = None) -> bool:
    cfg = _load_cfg()
    for b in cfg.get('bots', []):
        if str(b.get('id')) == str(bot_id):
            if label is not None:
                b['label'] = label
            if token is not None:
                b['token'] = token
            if chat_id is not None:
                b['chat_id'] = chat_id
            if thread_id is not None:
                try:
                    b['thread_id'] = int(thread_id)
                except Exception:
                    b['thread_id'] = None
            _save_cfg(cfg)
            return True
    return False

def delete_bot(bot_id: str) -> bool:
    cfg = _load_cfg()
    bots = cfg.get('bots', [])
    new_bots = [b for b in bots if str(b.get('id')) != str(bot_id)]
    changed = len(new_bots) != len(bots)
    if not changed:
        return False
    cfg['bots'] = new_bots
    if cfg.get('active_id') == bot_id:
        cfg['active_id'] = new_bots[0]['id'] if new_bots else None
    _save_cfg(cfg)
    return True

# --- Webhook management ---

def ensure_webhook_secret() -> str:
    cfg = _load_cfg()
    if not cfg.get('webhook_secret'):
        cfg['webhook_secret'] = uuid.uuid4().hex
        _save_cfg(cfg)
    return str(cfg['webhook_secret'])

def get_webhook_secret() -> str | None:
    cfg = _load_cfg()
    return cfg.get('webhook_secret')

def set_webhook_base(base_url: str) -> Dict[str, Any]:
    token, _, _ = _active_settings()
    if not token:
        return {"ok": False, "error": "no_token"}
    base = (base_url or '').strip().rstrip('/')
    if not base.startswith('http://') and not base.startswith('https://'):
        return {"ok": False, "error": "invalid_base_url"}
    secret = ensure_webhook_secret()
    url = f"{base}/telegram/webhook/{secret}"
    try:
        with httpx.Client(timeout=6.0) as client:
            r = client.post(f"https://api.telegram.org/bot{token}/setWebhook", data={"url": url})
            if r.status_code == 200 and (r.json() or {}).get('ok'):
                cfg = _load_cfg()
                cfg['webhook_url'] = url
                _save_cfg(cfg)
                return {"ok": True, "url": url}
            else:
                return {"ok": False, "error": (r.json() if 'application/json' in (r.headers.get('content-type') or '') else r.text)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def delete_webhook() -> Dict[str, Any]:
    token, _, _ = _active_settings()
    if not token:
        return {"ok": False, "error": "no_token"}
    try:
        with httpx.Client(timeout=6.0) as client:
            r = client.post(f"https://api.telegram.org/bot{token}/setWebhook", data={"url": ''})
            ok = (r.status_code == 200 and (r.json() or {}).get('ok'))
            if ok:
                cfg = _load_cfg()
                cfg['webhook_url'] = None
                _save_cfg(cfg)
            return {"ok": ok}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def webhook_info() -> Dict[str, Any]:
    token, _, _ = _active_settings()
    if not token:
        return {"ok": False, "error": "no_token"}
    try:
        with httpx.Client(timeout=6.0) as client:
            r = client.get(f"https://api.telegram.org/bot{token}/getWebhookInfo")
            if r.status_code == 200:
                cfg = _load_cfg()
                data = r.json()
                return {"ok": True, "info": data, "url": cfg.get('webhook_url')}
            return {"ok": False, "error": r.text}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def is_allowed_chat(chat_id: int | str) -> bool:
    try:
        cid = str(chat_id)
    except Exception:
        return False
    _, chat_id_cfg, _ = _active_settings()
    return bool(chat_id_cfg) and (str(chat_id_cfg) == cid)

async def send_to_chat_id(text: str, chat_id: str | int, disable_notification: bool = False) -> bool:
    token, _, thread_id = _active_settings()
    return await _send(token, str(chat_id), text, thread_id, disable_notification)

def activate_bot(bot_id: str) -> bool:
    cfg = _load_cfg()
    if any(str(b.get('id')) == str(bot_id) for b in cfg.get('bots', [])):
        cfg['active_id'] = bot_id
        _save_cfg(cfg)
        return True
    return False

def _active_settings() -> Tuple[str, str, Optional[int]]:
    cfg = _load_cfg()
    active_id = cfg.get('active_id')
    if active_id:
        for b in cfg.get('bots', []):
            if str(b.get('id')) == str(active_id):
                token = str(b.get('token') or '')
                chat_id = str(b.get('chat_id') or '')
                thread_id = b.get('thread_id')
                return token, chat_id, thread_id
    # Fallback to environment variables
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("MASTER_TG_BOT_TOKEN") or ""
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("MASTER_TG_CHAT_ID") or ""
    thread_id_env = os.getenv("TELEGRAM_THREAD_ID") or os.getenv("MASTER_TG_THREAD_ID")
    thread_id = None
    try:
        if thread_id_env is not None:
            thread_id = int(thread_id_env)
    except Exception:
        thread_id = None
    return token, chat_id, thread_id

async def _send(token: str, chat_id: str, text: str, thread_id: Optional[int] = None, disable_notification: bool = False) -> bool:
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: Dict[str, Any] = {"chat_id": chat_id, "text": text}
    # Only set parse_mode if the message contains obvious HTML tags to avoid accidental formatting
    if '<' in text and '>' in text:
        payload["parse_mode"] = "HTML"
    if thread_id:
        try:
            payload["message_thread_id"] = int(thread_id)
        except Exception:
            pass
    if disable_notification:
        payload["disable_notification"] = True
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.post(url, data=payload)
            return r.status_code == 200
    except Exception:
        return False

async def send_telegram(text: str) -> bool:
    token, chat_id, thread_id = _active_settings()
    return await _send(token, chat_id, text, thread_id, disable_notification=False)

async def send_telegram_text(text: str, bot_id: Optional[str] = None, disable_notification: bool = False) -> bool:
    token: str = ""; chat_id: str = ""; thread_id: Optional[int] = None
    if bot_id:
        cfg = _load_cfg()
        for b in cfg.get('bots', []):
            if str(b.get('id')) == str(bot_id):
                token = str(b.get('token') or '')
                chat_id = str(b.get('chat_id') or '')
                thread_id = b.get('thread_id')
                break
    if not token or not chat_id:
        token2, chat2, thread2 = _active_settings()
        token = token or token2
        chat_id = chat_id or chat2
        thread_id = thread_id or thread2
    return await _send(token, chat_id, text, thread_id, disable_notification)

async def test_bot(bot_id: Optional[str] = None) -> Dict[str, Any]:
    """Send a lightweight chat action to verify bot can reach chat. Falls back to sendMessage."""
    token, chat_id, thread_id = _active_settings() if not bot_id else (None, None, None)
    if bot_id:
        cfg = _load_cfg()
        for b in cfg.get('bots', []):
            if str(b.get('id')) == str(bot_id):
                token = str(b.get('token') or '')
                chat_id = str(b.get('chat_id') or '')
                thread_id = b.get('thread_id')
                break
    if not token or not chat_id:
        return {"ok": False, "error": "no_bot"}
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            # Try chat action (typing), which doesn't clutter chat
            url = f"https://api.telegram.org/bot{token}/sendChatAction"
            payload = {"chat_id": chat_id, "action": "typing"}
            if thread_id:
                try:
                    payload["message_thread_id"] = int(thread_id)
                except Exception:
                    pass
            r = await client.post(url, data=payload)
            if r.status_code == 200 and (r.json() or {}).get('ok'):
                return {"ok": True}
            # fallback to a minimal message
            url2 = f"https://api.telegram.org/bot{token}/sendMessage"
            payload2 = {"chat_id": chat_id, "text": "ping", "disable_notification": True}
            if thread_id:
                try:
                    payload2["message_thread_id"] = int(thread_id)
                except Exception:
                    pass
            r2 = await client.post(url2, data=payload2)
            return {"ok": r2.status_code == 200}
    except Exception as e:
        return {"ok": False, "error": str(e)}
