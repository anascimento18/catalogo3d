import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"
IMAGE_DIR = UPLOAD_DIR / "images"
MODEL_DIR = UPLOAD_DIR / "models_3d"

# Garante criação das pastas
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Banco de Dados (PostgreSQL no Swarm ou SQLite localmente para desenvolvimento/testes)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'catalogo.db'}")

# Segurança do Administrador
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "andre")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "3aField@2026")
SECRET_KEY = os.getenv("SECRET_KEY", "b98f2c31e405a6d7c8e9fa0123456789abcdef0123456789abcdef0123456789")
ADMIN_ROUTE = os.getenv("ADMIN_ROUTE", "/loginAdmin")

# Integrações WhatsApp (n8n e Evolution API v2)
DEST_WHATSAPP = os.getenv("DEST_WHATSAPP", "5565992217557")
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "https://hookncst.3afieldservice.com.br/webhook/catalogo-pedido")
EVOLUTION_URL = os.getenv("EVOLUTION_URL", "https://evowsapi.3afieldservice.com.br")
EVOLUTION_KEY = os.getenv("EVOLUTION_KEY", "4eddc4b3-5499-47a1-9b8b-d4afa9ad00e8")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "default")
CATALOG_DOMAIN = os.getenv("CATALOG_DOMAIN", "https://catalogo3d.3afieldservice.com.br")

# Ingestão Automática via Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8856055764:AAF5PxZzZ6y9GHgCGr-t6apEtQkPKFDfGsM")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "613898449,5370959021438146805")
TELEGRAM_API_SERVER = os.getenv("TELEGRAM_API_SERVER", "https://api.telegram.org").rstrip("/")
TELEGRAM_LOCAL_DIR = Path(os.getenv("TELEGRAM_LOCAL_DIR", "/var/lib/telegram-bot-api"))


# Formatos suportados
ALLOWED_3D_EXTENSIONS = {".stl", ".3mf", ".obj", ".step", ".stp", ".iges", ".igs", ".fbx", ".gltf", ".glb", ".blend", ".scad", ".zip", ".rar", ".7z"}
ALLOWED_IMG_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

