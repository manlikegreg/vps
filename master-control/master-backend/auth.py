import os
import time
import hmac
import hashlib
import base64
import json

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "dev-secret")
TOKEN_TTL = int(os.getenv("ADMIN_TOKEN_TTL", "7200"))  # 2 hours


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


def create_token(sub: str) -> str:
    payload = {"sub": sub, "exp": int(time.time()) + TOKEN_TTL}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(ADMIN_SECRET.encode(), raw, hashlib.sha256).digest()
    return "v1." + _b64(raw) + "." + _b64(sig)


def verify_token(tok: str) -> bool:
    try:
        v, p, s = tok.split(".")
        if v != "v1":
            return False
        raw = _b64d(p)
        sig = _b64d(s)
        sig2 = hmac.new(ADMIN_SECRET.encode(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, sig2):
            return False
        payload = json.loads(raw.decode())
        if payload.get("exp", 0) < int(time.time()):
            return False
        return True
    except Exception:
        return False


def check_credentials(username: str, password: str) -> bool:
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD
