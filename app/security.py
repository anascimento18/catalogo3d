import hashlib
import hmac
import time
import secrets
from typing import Optional
from fastapi import Request, HTTPException, status
from app.config import SECRET_KEY

# Armazenamento simples de rate-limiting em memória (IP -> lista de timestamps)
FAILED_ATTEMPTS = {}
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_TIME_SECONDS = 300  # 5 minutos

def hash_password(password: str) -> str:
    """Gera hash PBKDF2-HMAC-SHA256 com salt seguro."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}${key.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    """Verifica senha contra o hash armazenado."""
    try:
        salt, key_hex = stored_hash.split("$")
        key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
        return hmac.compare_digest(key.hex(), key_hex)
    except Exception:
        return False

def create_session_token(username: str, expires_in_seconds: int = 86400 * 7) -> str:
    """Cria token de sessão assinado com timestamp de expiração."""
    expire_at = int(time.time()) + expires_in_seconds
    data = f"{username}:{expire_at}"
    signature = hmac.new(SECRET_KEY.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{data}:{signature}"

def verify_session_token(token: str) -> Optional[str]:
    """Valida token de sessão assinado e retorna username se válido."""
    if not token:
        return None
    parts = token.split(":")
    if len(parts) != 3:
        return None
    username, expire_at_str, signature = parts
    try:
        expire_at = int(expire_at_str)
        if time.time() > expire_at:
            return None
        data = f"{username}:{expire_at_str}"
        expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()
        if hmac.compare_digest(signature, expected_sig):
            return username
    except Exception:
        pass
    return None

def check_rate_limit(client_ip: str) -> bool:
    """Verifica se o IP está bloqueado por excesso de tentativas de login."""
    now = time.time()
    attempts = FAILED_ATTEMPTS.get(client_ip, [])
    # Mantém apenas tentativas recentes dentro da janela
    attempts = [t for t in attempts if now - t < LOCKOUT_TIME_SECONDS]
    FAILED_ATTEMPTS[client_ip] = attempts
    return len(attempts) < MAX_FAILED_ATTEMPTS

def record_failed_attempt(client_ip: str):
    now = time.time()
    attempts = FAILED_ATTEMPTS.get(client_ip, [])
    attempts.append(now)
    FAILED_ATTEMPTS[client_ip] = attempts

def reset_failed_attempts(client_ip: str):
    if client_ip in FAILED_ATTEMPTS:
        del FAILED_ATTEMPTS[client_ip]

def get_current_admin(request: Request) -> str:
    """Dependência FastAPI que garante que a requisição é do Administrador autenticado."""
    token = request.cookies.get("admin_session")
    username = verify_session_token(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Acesso não autorizado. Faça login como administrador."
        )
    return username
