import re
import uuid
import httpx
import logging
from pathlib import Path
from sqlalchemy.orm import Session
from app.config import (
    IMAGE_DIR,
    MODEL_DIR,
    ALLOWED_3D_EXTENSIONS,
    ALLOWED_IMG_EXTENSIONS,
    CATALOG_DOMAIN
)
from app.database import SessionLocal, Model3D, Category

logger = logging.getLogger("telegram_bot")

# Armazena temporariamente último arquivo 3D enviado sem foto (ou última foto sem arquivo 3D) por chat
PENDING_UPLOADS = {}

async def setup_telegram_webhook(bot_token: str, base_domain: str):
    """Configura o webhook do Telegram automaticamente na inicialização."""
    if not bot_token or not base_domain:
        return
    webhook_url = f"{base_domain.rstrip('/')}/api/telegram/webhook"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                f"https://api.telegram.org/bot{bot_token}/setWebhook",
                json={"url": webhook_url}
            )
            data = res.json()
            if data.get("ok"):
                logger.info(f"Webhook do Telegram registrado com sucesso: {webhook_url}")
            else:
                logger.warning(f"Aviso ao registrar webhook do Telegram: {data}")
    except Exception as e:
        logger.error(f"Erro ao configurar webhook do Telegram: {e}")

async def process_telegram_update(update: dict, bot_token: str, admin_chat_id: str = None) -> dict:
    """
    Processa mensagens recebidas pelo Bot do Telegram para cadastrar modelos automaticamente.
    """
    message = update.get("message") or update.get("channel_post")
    if not message:
        return {"ok": True, "ignored": "Sem mensagem"}

    from_user = message.get("from", {})
    user_id = str(from_user.get("id", ""))
    chat_id = message.get("chat", {}).get("id")

    # Validação de segurança: apenas o André pode enviar
    if admin_chat_id:
        allowed_ids = [s.strip().strip('"\'') for s in str(admin_chat_id).split(",") if s.strip()]
        if allowed_ids and str(user_id) not in allowed_ids and str(chat_id) not in allowed_ids:
            logger.warning(f"Tentativa de envio não autorizada no Telegram pelo usuário {user_id} (chat_id: {chat_id})")
            return {"ok": False, "error": "Não autorizado"}

    document = message.get("document")
    photos = message.get("photo")
    caption = str(message.get("caption") or message.get("text") or "").strip()

    # Se for comando /start ou ajuda
    if not document and not photos:
        await send_telegram_reply(
            bot_token, chat_id,
            "👋 *Olá André!* Sou o seu assistente de publicação do Catálogo 3D.\n\n"
            "Para cadastrar um modelo, basta me enviar:\n"
            "📦 **Arquivo 3D** (`.STL`, `.3MF`, `.STEP`, `.OBJ`, `.ZIP`)\n"
            "🖼️ **Foto de Capa**\n\n"
            "💡 *Dica:* Na legenda da mensagem, você pode escrever o nome e preço:\n"
            "`Vaso Facetado R$ 85 #decoracao`\n"
            "Ou simplesmente o nome: `Suporte Articulado`."
        )
        return {"ok": True}

    title = caption or "Modelo 3D Telegram"
    price = 0.0
    show_price = True

    # Extração de preço na legenda (ex: R$ 85, 85.00 ou 85,00)
    price_match = re.search(r'(?:R\$\s*|preco\s*|valor\s*)?(\d+(?:[.,]\d{1,2})?)', caption, re.IGNORECASE)
    if price_match:
        try:
            price = float(price_match.group(1).replace(',', '.'))
        except:
            price = 0.0

    async with httpx.AsyncClient(timeout=40.0) as client:

        # CASO 1: Envio de Documento 3D
        if document:
            file_name = document.get("file_name", "modelo.stl")
            ext = Path(file_name).suffix.lower()

            if ext not in ALLOWED_3D_EXTENSIONS:
                await send_telegram_reply(bot_token, chat_id, f"⚠️ A extensão `{ext}` não é suportada. Envie arquivos `.STL`, `.3MF`, `.STEP`, etc.")
                return {"ok": False}

            file_id = document.get("file_id")
            file_info_res = await client.get(f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}")
            file_path_on_tg = file_info_res.json().get("result", {}).get("file_path")

            if not file_path_on_tg:
                await send_telegram_reply(bot_token, chat_id, "❌ Não foi possível baixar o arquivo do Telegram.")
                return {"ok": False}

            download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path_on_tg}"
            raw_data = await client.get(download_url)

            unique_id = uuid.uuid4().hex[:8]
            clean_title = re.sub(r'[^\w\s-]', '', title).strip().replace(" ", "_")
            saved_3d_name = f"{clean_title}_{unique_id}{ext}"
            (MODEL_DIR / saved_3d_name).write_bytes(raw_data.content)

            # Verifica se já temos uma foto pendente neste chat
            pending_photo = PENDING_UPLOADS.pop(chat_id, None)
            saved_img_name = pending_photo or "vaso_facetado.jpg"

            # Salva no Banco de Dados
            db = SessionLocal()
            try:
                model = Model3D(
                    title=title,
                    description=f"Cadastrado via Telegram por @{from_user.get('username', 'andre')}",
                    category_id=1,
                    category_name="Decoração & Casa",
                    image_filename=saved_img_name,
                    file_3d_filename=saved_3d_name,
                    file_format=ext.lstrip(".").upper(),
                    file_size_bytes=len(raw_data.content),
                    price=price,
                    show_price=price > 0,
                    order_count=15,
                    is_public=True
                )
                db.add(model)
                db.commit()
                db.refresh(model)

                reply_msg = (
                    f"✅ *Modelo 3D Publicado no Catálogo!*\n\n"
                    f"🔹 *Título:* {title}\n"
                    f"🔹 *Arquivo:* `{file_name}` ({len(raw_data.content)/1024/1024:.2f} MB)\n"
                    f"💰 *Preço:* {'R$ ' + f'{price:.2f}' if price > 0 else 'Sob Consulta'}\n\n"
                    f"🌐 [Acessar Vitrine Online]({CATALOG_DOMAIN})"
                )
                if not pending_photo:
                    reply_msg += "\n\n💡 *Dica:* Envie a foto de capa agora para atualizar a miniatura deste modelo."

                await send_telegram_reply(bot_token, chat_id, reply_msg)
            finally:
                db.close()

            return {"ok": True}

        # CASO 2: Envio de Foto
        if photos:
            # Pega a foto de maior resolução (última da lista)
            largest_photo = photos[-1]
            file_id = largest_photo.get("file_id")

            file_info_res = await client.get(f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}")
            file_path_on_tg = file_info_res.json().get("result", {}).get("file_path")

            if file_path_on_tg:
                download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path_on_tg}"
                raw_data = await client.get(download_url)

                unique_id = uuid.uuid4().hex[:8]
                saved_img_name = f"photo_{unique_id}.jpg"
                (IMAGE_DIR / saved_img_name).write_bytes(raw_data.content)

                # Verifica se há modelo recente sem foto para atualizar
                db = SessionLocal()
                try:
                    last_model = db.query(Model3D).order_by(Model3D.id.desc()).first()
                    if last_model and last_model.image_filename in ("vaso_facetado.jpg", "engrenagem.jpg"):
                        last_model.image_filename = saved_img_name
                        db.commit()
                        await send_telegram_reply(
                            bot_token, chat_id,
                            f"📸 Foto vinculada com sucesso ao modelo *{last_model.title}*!"
                        )
                    else:
                        PENDING_UPLOADS[chat_id] = saved_img_name
                        await send_telegram_reply(
                            bot_token, chat_id,
                            "📸 Foto recebida! Agora envie o arquivo 3D (`.STL`, `.3MF`) correspondente."
                        )
                finally:
                    db.close()

            return {"ok": True}

    return {"ok": True}

async def send_telegram_reply(bot_token: str, chat_id: int, text: str):
    """Envia mensagem de resposta no Telegram."""
    if not bot_token or not chat_id:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False
                }
            )
    except Exception as e:
        logger.error(f"Erro ao responder no Telegram: {e}")
