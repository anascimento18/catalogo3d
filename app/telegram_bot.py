import re
import json
import uuid
import shutil
import zipfile
import logging
import asyncio
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any
import httpx
from sqlalchemy.orm import Session

from app.config import (
    DATA_DIR,
    IMAGE_DIR,
    MODEL_DIR,
    ALLOWED_3D_EXTENSIONS,
    ALLOWED_IMG_EXTENSIONS,
    CATALOG_DOMAIN,
    ADMIN_PASSWORD,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_ADMIN_CHAT_ID,
    TELEGRAM_API_SERVER,
    TELEGRAM_LOCAL_DIR
)
from app.database import SessionLocal, Model3D, Category
from app.ai_agent import analyze_model_proposal

logger = logging.getLogger("telegram_bot")

# Diretório temporário para uploads do Telegram
TEMP_TG_DIR = DATA_DIR / "temp_telegram"
TEMP_TG_DIR.mkdir(parents=True, exist_ok=True)

# Estado das conversas dos usuários
# { chat_id: { "step": "...", "files_3d": [], "cover_img": ..., "gallery_imgs": [], ... } }
USER_WIZARDS: Dict[int, Dict[str, Any]] = {}

# Sessões autorizadas persistentes em disco
AUTH_FILE = DATA_DIR / "authorized_telegram_users.json"

def _load_authorized_chats() -> set:
    s = {"613898449"}
    if AUTH_FILE.exists():
        try:
            with open(AUTH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    s.update(str(x) for x in data)
        except Exception as e:
            logger.warning(f"Erro ao carregar {AUTH_FILE}: {e}")
    return s

def _save_authorized_chat(chat_id: str):
    AUTHORIZED_CHATS.add(str(chat_id))
    try:
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(list(AUTHORIZED_CHATS), f, indent=2)
    except Exception as e:
        logger.error(f"Erro ao salvar {AUTH_FILE}: {e}")

AUTHORIZED_CHATS = _load_authorized_chats()


def is_authorized(user_id: str, chat_id: str, admin_chat_id: Optional[str]) -> bool:
    """Verifica se o usuário ou chat tem permissão para usar o bot."""
    global AUTHORIZED_CHATS
    if not AUTHORIZED_CHATS:
        AUTHORIZED_CHATS = _load_authorized_chats()

    if str(user_id) in AUTHORIZED_CHATS or str(chat_id) in AUTHORIZED_CHATS:
        return True
    if admin_chat_id:
        allowed = [s.strip().strip('"\'') for s in str(admin_chat_id).split(",") if s.strip()]
        if str(user_id) in allowed or str(chat_id) in allowed:
            return True
    return False


async def telegram_webhook_watchdog(bot_token: str, base_domain: str, interval_seconds: int = 180):
    """
    Guardião resiliente (Watchdog) que garante que o webhook do Telegram NUNCA caia.
    Verifica a cada X segundos se o webhook continua ativo no Telegram.
    Se detectar queda, reinício ou remoção externa, reconecta automaticamente!
    """
    if not bot_token or not base_domain:
        return
    webhook_url = f"{base_domain.rstrip('/')}/api/telegram/webhook"

    # 1. Configuração inicial imediata
    await setup_telegram_webhook(bot_token, base_domain)

    # 2. Loop de vigilância contínua
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"{TELEGRAM_API_SERVER}/bot{bot_token}/getWebhookInfo")
                if res.status_code == 200:
                    info = res.json().get("result", {})
                    curr_url = info.get("url", "")
                    if curr_url != webhook_url:
                        logger.warning(
                            f"[TELEGRAM WATCHDOG] Webhook estava desconectado (url={curr_url!r}). "
                            f"Restaurando para {webhook_url}..."
                        )
                        await setup_telegram_webhook(bot_token, base_domain)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[TELEGRAM WATCHDOG] Erro temporário ao checar webhook: {e}")


async def setup_telegram_webhook(bot_token: str, base_domain: str):
    """Configura o webhook do Telegram com suporte a mensagens e botões inline."""
    if not bot_token or not base_domain:
        return
    webhook_url = f"{base_domain.rstrip('/')}/api/telegram/webhook"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                f"{TELEGRAM_API_SERVER}/bot{bot_token}/setWebhook",
                json={
                    "url": webhook_url,
                    "allowed_updates": ["message", "callback_query"]
                }
            )
            data = res.json()
            if data.get("ok"):
                logger.info(f"Webhook do Telegram registrado com sucesso: {webhook_url}")
            else:
                logger.warning(f"Aviso ao registrar webhook do Telegram: {data}")
    except Exception as e:
        logger.error(f"Erro ao configurar webhook do Telegram: {e}")


async def send_telegram_reply(bot_token: str, chat_id: int, text: str, reply_markup: Optional[dict] = None) -> Optional[int]:
    """
    Envia mensagem de texto formatada com suporte a botões inline e fallback automático para texto plano.
    Retorna o message_id gerado no Telegram se bem-sucedido.
    """
    if not bot_token or not chat_id:
        return None
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                f"{TELEGRAM_API_SERVER}/bot{bot_token}/sendMessage",
                json=payload
            )
            if res.status_code == 200 and res.json().get("ok"):
                return res.json().get("result", {}).get("message_id")
            
            # Se o Telegram rejeitar devido a caracteres especiais do Markdown
            logger.warning(f"Aviso ao enviar markdown ({res.text}). Reenviando em texto plano...")
            plain_payload = {
                "chat_id": chat_id,
                "text": text.replace("*", "").replace("_", "").replace("`", ""),
                "disable_web_page_preview": False
            }
            if reply_markup:
                plain_payload["reply_markup"] = reply_markup
            plain_res = await client.post(
                f"{TELEGRAM_API_SERVER}/bot{bot_token}/sendMessage",
                json=plain_payload
            )
            if plain_res.status_code == 200 and plain_res.json().get("ok"):
                return plain_res.json().get("result", {}).get("message_id")
    except Exception as e:
        logger.error(f"Erro ao responder no Telegram (chat {chat_id}): {e}")
    return None


async def remove_inline_keyboard(bot_token: str, chat_id: int, message_id: int):
    """Desativa os botões inline de uma mensagem para evitar duplos cliques e propostas fantasmas."""
    if not bot_token or not chat_id or not message_id:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{TELEGRAM_API_SERVER}/bot{bot_token}/editMessageReplyMarkup",
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "reply_markup": {"inline_keyboard": []}
                }
            )
    except Exception as e:
        logger.debug(f"Aviso ao desativar botões inline (mensagem {message_id}): {e}")


async def answer_callback_query(bot_token: str, callback_query_id: str, text: Optional[str] = None):
    """Responde ao clique de botão inline no Telegram para remover o loading."""
    if not bot_token or not callback_query_id:
        return
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{TELEGRAM_API_SERVER}/bot{bot_token}/answerCallbackQuery", json=payload)
    except Exception as e:
        logger.error(f"Erro ao responder callback query no Telegram: {e}")


async def download_telegram_file(bot_token: str, file_id: str, dest_path: Path) -> tuple[bool, str]:
    """
    Baixa um arquivo do Telegram para o disco local com suporte a API local (cópia direta instantânea)
    ou streaming em chunks (suporte a arquivos gigantes até 2 GB).
    """
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        timeout_config = httpx.Timeout(connect=30.0, read=600.0, write=120.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout_config) as client:
            res = await client.get(f"{TELEGRAM_API_SERVER}/bot{bot_token}/getFile?file_id={file_id}")
            res_data = res.json()
            if not res_data.get("ok"):
                err_desc = res_data.get("description", "Erro ao obter informações do arquivo no Telegram")
                logger.error(f"Telegram getFile error para file_id {file_id}: {err_desc}")
                return False, err_desc

            file_path_on_tg = res_data.get("result", {}).get("file_path")
            if not file_path_on_tg:
                return False, "Caminho do arquivo não fornecido pelo Telegram"

            # 1. Se o servidor local do Telegram estiver em volume compartilhado, copia diretamente
            local_direct_path = Path(file_path_on_tg)
            if local_direct_path.is_file():
                shutil.copyfile(local_direct_path, dest_path)
                return True, "Sucesso"
            
            shared_vol_path = TELEGRAM_LOCAL_DIR / file_path_on_tg
            if shared_vol_path.is_file():
                shutil.copyfile(shared_vol_path, dest_path)
                return True, "Sucesso"

            # 2. Caso contrário, faz stream via HTTP
            download_url = f"{TELEGRAM_API_SERVER}/file/bot{bot_token}/{file_path_on_tg}"
            async with client.stream("GET", download_url) as file_res:
                if file_res.status_code != 200:
                    return False, f"Servidor do Telegram retornou HTTP {file_res.status_code}"
                with open(dest_path, "wb") as f:
                    async for chunk in file_res.aiter_bytes(chunk_size=131072):
                        f.write(chunk)
            return True, "Sucesso"
    except httpx.ReadTimeout:
        logger.error(f"Timeout ao baixar arquivo {file_id} do Telegram (>600s)")
        return False, "Tempo limite esgotado ao baixar o arquivo dos servidores do Telegram (>600s)"
    except Exception as e:
        logger.error(f"Erro ao baixar arquivo {file_id} do Telegram: {e}")
        return False, str(e)


# Cache de updates processados para deduplicação instantânea
PROCESSED_UPDATES = set()
PROCESSED_QUEUE = []

# Locks por chat para garantir processamento estritamente sequencial
CHAT_LOCKS: Dict[int, asyncio.Lock] = {}


def _get_or_create_wizard(chat_id: int) -> dict:
    """Retorna o rascunho ativo ou inicializa um novo."""
    if chat_id not in USER_WIZARDS:
        session_id = uuid.uuid4().hex[:6]
        user_temp_dir = TEMP_TG_DIR / f"{chat_id}_{session_id}"
        user_temp_dir.mkdir(parents=True, exist_ok=True)
        USER_WIZARDS[chat_id] = {
            "session_id": session_id,
            "temp_dir": user_temp_dir,
            "step": "WAIT_INPUT",
            "files_3d": [],
            "external_url": None,
            "cover_img": None,
            "gallery_imgs": [],
            "title": "",
            "category_id": 1,
            "category_name": "Decoração & Casa",
            "price": 0.0,
            "show_price": True,
            "price_range": "",
            "reasoning": "",
            "is_featured": False,
            "order_count": 18,
            "description": "",
            "proposal_message_id": None
        }
    return USER_WIZARDS[chat_id]


async def send_proposal_card(bot_token: str, chat_id: int, wizard: dict):
    """Envia o Card Interativo de Proposta Inteligente gerado pela IA."""
    price_val = wizard.get("price", 0.0)
    show_price = wizard.get("show_price", True)
    price_display = f"R$ {price_val:.2f}" if (show_price and price_val > 0) else "Sob Consulta"
    price_range = wizard.get("price_range", "")

    files_3d = wizard.get("files_3d", [])
    has_pdf = any(f["name"].lower().endswith(".pdf") for f in files_3d)
    pdf_count = len([f for f in files_3d if f["name"].lower().endswith(".pdf")])
    pieces_3d_count = len([f for f in files_3d if not f["name"].lower().endswith(".pdf")])

    if not files_3d and wizard.get("external_url"):
        origin_str = f"🔗 Link: `{wizard['external_url']}`"
    elif len(files_3d) == 1:
        f = files_3d[0]
        size_mb = f.get("size", 0) / (1024 * 1024)
        if f["name"].lower().endswith(".pdf"):
            origin_str = f"📄 `{f['name']}` ({size_mb:.1f} MB)"
        else:
            origin_str = f"`{f['name']}` ({size_mb:.1f} MB)"
    else:
        parts_text = f"{pieces_3d_count} peça(s) 3D" if pieces_3d_count else ""
        pdf_text = f"+ {pdf_count} manual PDF" if pdf_count else ""
        origin_str = f"📦 {parts_text} {pdf_text} (compactados em .ZIP)".strip()

    photos_count = 1 + len(wizard.get("gallery_imgs", []))

    teto_info = f"\n📊 *Faixa / Teto de Mercado:* {price_range}" if price_range else ""

    card_text = (
        f"✨ *Proposta Inteligente de Publicação* 🤖\n\n"
        f"🏷️ *Título Comercial:* {wizard['title']}\n"
        f"📂 *Categoria:* {wizard['category_name']}\n"
        f"💰 *Preço Sugerido (15% abaixo do teto):* *{price_display}*{teto_info}\n"
        f"📁 *Arquivo 3D:* {origin_str}\n"
        f"🖼️ *Fotos da Vitrine:* {photos_count} foto(s)\n\n"
        f"📝 *Descrição de Venda:*\n"
        f"_{wizard['description']}_\n\n"
        f"💡 *Estratégia de Precificação:*\n"
        f"_{wizard.get('reasoning', 'Preço calculado estrategicamente 10% a 15% abaixo do teto de mercado para máxima margem de estúdio premium.')}_\n\n"
        f"👇 _Aprove em 1 clique ou personalize o que desejar:_"
    )

    approve_label = f"✅ Aprovar e Publicar ({price_display})" if show_price and price_val > 0 else "✅ Aprovar e Publicar"

    keyboard = {
        "inline_keyboard": [
            [
                {"text": approve_label, "callback_data": "ai_approve_price"},
                {"text": "💬 Publicar Sob Consulta", "callback_data": "ai_approve_quote"}
            ],
            [
                {"text": "🏷️ Alterar Categoria", "callback_data": "ai_change_cat"},
                {"text": "💰 Alterar Valor", "callback_data": "ai_change_price"}
            ],
            [
                {"text": "📝 Alterar Título", "callback_data": "ai_change_title"},
                {"text": "📸 + Adicionar Fotos", "callback_data": "ai_add_photos"}
            ],
            [
                {"text": "❌ Cancelar", "callback_data": "ai_cancel"}
            ]
        ]
    }

    msg_id = await send_telegram_reply(bot_token, chat_id, card_text, reply_markup=keyboard)
    if msg_id:
        wizard["proposal_message_id"] = msg_id


async def trigger_ai_proposal(bot_token: str, chat_id: int, wizard: dict, caption: str = ""):
    """Executa a análise de IA via MiniMax e exibe o card interativo de proposta."""
    has_3d = bool(wizard.get("files_3d") or wizard.get("external_url"))
    has_cover = bool(wizard.get("cover_img"))

    if not has_3d or not has_cover:
        return

    await send_telegram_reply(
        bot_token, chat_id,
        "🤖 *Analisando peça com IA e pesquisando referências de topo de mercado no Brasil...* 🔍"
    )

    db = SessionLocal()
    categories_names = []
    try:
        categories_db = db.query(Category).all()
        categories_names = [c.name for c in categories_db]
    finally:
        db.close()

    # Identifica nome principal (prioriza arquivo 3D em vez do manual PDF para nomear a peça)
    if wizard.get("files_3d"):
        non_pdf = [f["name"] for f in wizard["files_3d"] if not f["name"].lower().endswith(".pdf")]
        main_filename = non_pdf[0] if non_pdf else wizard["files_3d"][0]["name"]
    else:
        main_filename = wizard.get("external_url") or "modelo.stl"

    cover_path = wizard["cover_img"]["path"] if wizard.get("cover_img") else None

    # Chama IA MiniMax com regra de teto -15%
    ai_result = await analyze_model_proposal(
        image_path=cover_path,
        filename=main_filename,
        caption=caption,
        external_url=wizard.get("external_url"),
        categories=categories_names
    )

    wizard["title"] = ai_result.get("title", "Modelo Decorativo 3D")
    wizard["category_name"] = ai_result.get("category", "Decoração & Casa")
    wizard["description"] = ai_result.get("description", "")
    wizard["price"] = float(ai_result.get("suggested_price", 75.0))
    wizard["show_price"] = True
    wizard["price_range"] = ai_result.get("price_range", "")
    wizard["reasoning"] = ai_result.get("reasoning", "")
    wizard["step"] = "PROPOSAL"

    # Mapeia ID da categoria
    db = SessionLocal()
    try:
        matched_cat = db.query(Category).filter(Category.name.ilike(wizard["category_name"])).first()
        if not matched_cat:
            matched_cat = db.query(Category).first()
        wizard["category_id"] = matched_cat.id if matched_cat else 1
        wizard["category_name"] = matched_cat.name if matched_cat else "Decoração & Casa"
    finally:
        db.close()

    await send_proposal_card(bot_token, chat_id, wizard)


async def finalize_and_publish(bot_token: str, chat_id: int, wizard: dict, with_price: bool = True):
    """Grava arquivos permanentemente e publica o modelo no banco de dados com blindagem total contra fantasmas."""
    
    # 0. Blindagem estrita contra modelos vazios / fantasmas
    has_3d = bool(wizard.get("files_3d") or wizard.get("external_url"))
    has_cover = bool(wizard.get("cover_img"))
    has_title = bool(wizard.get("title") and str(wizard.get("title")).strip())

    if not has_title or not has_3d or not has_cover:
        logger.warning(f"Tentativa de publicação descartada para chat {chat_id}: rascunho inválido ou já processado.")
        await send_telegram_reply(
            bot_token, chat_id,
            "⚠️ *Esta proposta já foi concluída ou expirou!*\n\nEnvie o arquivo 3D e uma foto da peça para iniciar um novo cadastro."
        )
        return

    await send_telegram_reply(bot_token, chat_id, "⏳ Publicando modelo e gravando arquivos no catálogo...")

    unique_id = uuid.uuid4().hex[:8]
    clean_title = "".join(c for c in wizard["title"] if c.isalnum() or c in ("-", "_", " ")).strip().replace(" ", "_")
    if not clean_title:
        clean_title = f"modelo_{unique_id}"

    # 1. Foto de Capa
    cover_info = wizard.get("cover_img")
    saved_cover_name = ""
    if cover_info and Path(cover_info["path"]).is_file():
        c_ext = Path(cover_info["name"]).suffix.lower() or ".jpg"
        saved_cover_name = f"{clean_title}_{unique_id}_cover{c_ext}"
        shutil.move(str(cover_info["path"]), str(IMAGE_DIR / saved_cover_name))
    else:
        saved_cover_name = "default_3d_cover.png"

    # 2. Galeria de fotos adicionais (apenas fotos reais que não sejam idênticas à capa)
    saved_gallery_names = []
    for idx, g_info in enumerate(wizard.get("gallery_imgs", [])):
        if Path(g_info["path"]).is_file():
            g_ext = Path(g_info["name"]).suffix.lower() or ".jpg"
            g_name = f"{clean_title}_{unique_id}_gal_{idx+1}{g_ext}"
            shutil.move(str(g_info["path"]), str(IMAGE_DIR / g_name))
            saved_gallery_names.append(g_name)

    # 3. Arquivo(s) 3D ou Link
    if not wizard.get("files_3d") and wizard.get("external_url"):
        saved_3d_name = ""
        parts_count = 1
        format_str = "LINK"
        total_size = 0
        files_3d_list_json = json.dumps([{"name": f"Link: {wizard['external_url']}", "size": 0}])
    elif len(wizard.get("files_3d", [])) == 1:
        f_3d = wizard["files_3d"][0]
        f_ext = f_3d["ext"]
        saved_3d_name = f"{clean_title}_{unique_id}{f_ext}"
        target_3d = MODEL_DIR / saved_3d_name
        shutil.move(str(f_3d["path"]), str(target_3d))
        parts_count = f_3d.get("parts_count", 1)
        format_str = f_ext.lstrip(".").upper()
        total_size = f_3d.get("size", 0)
        files_3d_list_json = json.dumps([{"name": f_3d["name"], "size": f_3d["size"]}])
    else:
        # Múltiplas peças e/ou Peças + Manual PDF -> Compacta em .ZIP
        saved_3d_name = f"{clean_title}_{unique_id}.zip"
        target_3d = MODEL_DIR / saved_3d_name
        with zipfile.ZipFile(target_3d, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
            for item in wizard.get("files_3d", []):
                if Path(item["path"]).is_file():
                    zf.write(item["path"], arcname=item["name"])
        # Contagem de peças físicas (exclui PDFs da contagem de peças de impressão)
        real_parts = [f for f in wizard.get("files_3d", []) if not f["name"].lower().endswith(".pdf")]
        parts_count = len(real_parts) if real_parts else 1
        format_str = "ZIP"
        total_size = target_3d.stat().st_size if target_3d.exists() else 0
        files_3d_list_json = json.dumps([{"name": f["name"], "size": f["size"]} for f in wizard.get("files_3d", [])])

    final_price = wizard["price"] if with_price else 0.0
    show_price_flag = with_price and (wizard["price"] > 0)

    # 4. Grava no Banco de Dados
    db = SessionLocal()
    try:
        new_model = Model3D(
            title=wizard["title"],
            description=wizard["description"],
            category_id=wizard["category_id"],
            category_name=wizard["category_name"],
            image_filename=saved_cover_name,
            gallery_images=json.dumps(saved_gallery_names),
            file_3d_filename=saved_3d_name,
            external_url=wizard.get("external_url"),
            files_3d_list=files_3d_list_json,
            parts_count=parts_count,
            file_format=format_str,
            file_size_bytes=total_size,
            price=final_price,
            show_price=show_price_flag,
            is_featured=wizard.get("is_featured", False),
            order_count=wizard.get("order_count", 18),
            is_public=True
        )
        db.add(new_model)
        db.commit()
        db.refresh(new_model)
        model_id = new_model.id
    finally:
        db.close()

    # Limpa temporários e remove rascunho da memória
    shutil.rmtree(wizard["temp_dir"], ignore_errors=True)
    del USER_WIZARDS[chat_id]

    total_photos = 1 + len(saved_gallery_names)
    price_label = f"R$ {final_price:.2f}" if show_price_flag else "Sob Consulta"
    has_pdf_info = " (com Manual em PDF)" if any(f.get("name", "").lower().endswith(".pdf") for f in wizard.get("files_3d", [])) else ""

    await send_telegram_reply(
        bot_token, chat_id,
        f"🎉 *Modelo Publicado com Sucesso!* 🚀\n\n"
        f"📦 *{wizard['title']}* já está disponível na vitrine online!\n\n"
        f"• ID: `#{model_id}`\n"
        f"• Valor: *{price_label}*\n"
        f"• Categoria: {wizard['category_name']}\n"
        f"• Fotos cadastradas: {total_photos}\n"
        f"• Peças 3D: {parts_count}{has_pdf_info}\n\n"
        f"👉 [Visualizar na Vitrine Online]({CATALOG_DOMAIN})"
    )


async def process_telegram_update(update: dict, bot_token: str, admin_chat_id: Optional[str] = None) -> dict:
    """
    Ponto de entrada de atualizações do Telegram com proteção estrita de duplicatas
    e serialização por chat.
    """
    update_id = update.get("update_id")
    if update_id:
        if update_id in PROCESSED_UPDATES:
            logger.info(f"Update duplicado ignorado: {update_id}")
            return {"ok": True, "duplicate": True}
        PROCESSED_UPDATES.add(update_id)
        PROCESSED_QUEUE.append(update_id)
        if len(PROCESSED_QUEUE) > 2000:
            old = PROCESSED_QUEUE.pop(0)
            PROCESSED_UPDATES.discard(old)

    callback_query = update.get("callback_query")
    message = update.get("message") or update.get("channel_post")
    chat_id = None
    if callback_query:
        chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
    elif message:
        chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return await _dispatch_telegram_update(update, bot_token, admin_chat_id)

    lock = CHAT_LOCKS.setdefault(chat_id, asyncio.Lock())
    async with lock:
        return await _dispatch_telegram_update(update, bot_token, admin_chat_id)


async def _dispatch_telegram_update(update: dict, bot_token: str, admin_chat_id: Optional[str] = None) -> dict:
    """
    Processador inteligente de mensagens, arquivos e botões interativos com IA.
    """
    callback_query = update.get("callback_query")
    message = update.get("message") or update.get("channel_post")

    chat_id = None
    user_id = None
    text = ""
    document = None
    photos = None
    callback_data = None
    msg_id = None

    if callback_query:
        from_user = callback_query.get("from", {})
        user_id = str(from_user.get("id", ""))
        message = callback_query.get("message", {})
        msg_id = message.get("message_id")
        chat_id = message.get("chat", {}).get("id")
        callback_data = callback_query.get("data", "")
        await answer_callback_query(bot_token, callback_query.get("id"))
    elif message:
        from_user = message.get("from", {})
        user_id = str(from_user.get("id", ""))
        chat_id = message.get("chat", {}).get("id")
        msg_id = message.get("message_id")
        text = str(message.get("text") or message.get("caption") or "").strip()
        document = message.get("document")
        photos = message.get("photo")
    else:
        return {"ok": True, "ignored": "No valid message or callback"}

    if not chat_id:
        return {"ok": False, "error": "No chat_id"}

    # 1. Comando de autorização por senha
    if text.startswith("/auth"):
        parts = text.split(maxsplit=1)
        if len(parts) >= 2 and parts[1].strip() == ADMIN_PASSWORD:
            _save_authorized_chat(str(user_id))
            _save_authorized_chat(str(chat_id))
            await send_telegram_reply(
                bot_token, chat_id,
                f"🔓 *Autorizado com Sucesso!*\n\n"
                f"Olá André! Seu Telegram ID `{user_id}` foi autenticado com sucesso.\n"
                f"Agora você pode cadastrar modelos enviando arquivos e fotos diretamente pelo chat!\n\n"
                f"👉 Experimente encaminhar ou enviar um arquivo 3D e uma foto da peça."
            )
            return {"ok": True}
        else:
            await send_telegram_reply(
                bot_token, chat_id,
                "❌ *Acesso negado.*\nDigite: `/auth <senha>`"
            )
            return {"ok": False}

    # 2. Validação de Segurança
    if not is_authorized(user_id, str(chat_id), admin_chat_id):
        logger.warning(f"Tentativa de acesso não autorizada: user_id={user_id}, chat_id={chat_id}")
        await send_telegram_reply(
            bot_token, chat_id,
            f"🔒 *Acesso Restrito ao Administrador*\n\n"
            f"Seu ID no Telegram é: `{user_id}`\n\n"
            f"Para autorizar este aparelho, digite:\n"
            f"`/auth <senha>`"
        )
        return {"ok": False, "error": "Não autorizado"}

    # 3. Comandos Globais
    if text in ("/cancelar", "/cancel"):
        if chat_id in USER_WIZARDS:
            shutil.rmtree(USER_WIZARDS[chat_id]["temp_dir"], ignore_errors=True)
            del USER_WIZARDS[chat_id]
        await send_telegram_reply(
            bot_token, chat_id,
            "❌ *Cadastro cancelado.* Os arquivos temporários foram descartados.\n\n"
            "Quando quiser cadastrar novamente, basta enviar o arquivo 3D e a foto da peça!"
        )
        return {"ok": True}

    if text in ("/start", "/ajuda", "/help"):
        await send_telegram_reply(
            bot_token, chat_id,
            "🤖 *Assistente Studio 3D com IA MiniMax* ✨\n\n"
            "Cadastrar novas peças agora é super prático e inteligente:\n\n"
            "1️⃣ *Envie ou encaminhe o arquivo 3D* (`.STL`, `.3MF`, `.ZIP`, `.RAR`), manual de montagem (`.PDF`) ou link do modelo;\n"
            "2️⃣ *Envie a foto da peça* impressa;\n\n"
            "✨ *O que a IA faz por você:*\n"
            "• Cria um título comercial chamativo em português;\n"
            "• Pesquisa referências de topo de mercado no Brasil;\n"
            "• Sugere o preço com 10% a 15% de desconto sobre o teto de mercado (estúdio premium);\n"
            "• Apresenta uma proposta para você **aprovar em 1 clique** ou personalizar!\n\n"
            "🚀 *Comandos:*\n"
            "👉 /newmodelo - Iniciar novo rascunho\n"
            "👉 /status - Ver catálogo\n"
            "👉 /cancelar - Cancelar rascunho atual"
        )
        return {"ok": True}

    if text == "/status":
        db = SessionLocal()
        try:
            total = db.query(Model3D).count()
            cats = db.query(Category).all()
            cat_list = "\n".join([f"• {c.name}" for c in cats])
            await send_telegram_reply(
                bot_token, chat_id,
                f"📊 *Status do Catálogo 3D:*\n\n"
                f"📦 *Modelos publicados:* {total}\n"
                f"🏷️ *Categorias ativas ({len(cats)}):*\n{cat_list}\n\n"
                f"🌐 Vitrine: {CATALOG_DOMAIN}"
            )
        finally:
            db.close()
        return {"ok": True}

    # 4. Início explícito de novo modelo
    if text in ("/newmodelo", "/novo"):
        if chat_id in USER_WIZARDS:
            shutil.rmtree(USER_WIZARDS[chat_id]["temp_dir"], ignore_errors=True)
            del USER_WIZARDS[chat_id]
        wizard = _get_or_create_wizard(chat_id)
        is_local_api = "api.telegram.org" not in TELEGRAM_API_SERVER
        limit_desc = "2.000 MB (2 GB)" if is_local_api else "20 MB"

        await send_telegram_reply(
            bot_token, chat_id,
            "🚀 *Novo Cadastro com IA Iniciado!*\n\n"
            "📁 *Envie o Arquivo 3D* (`.STL`, `.3MF`, `.ZIP`, `.RAR`), manual de montagem (`.PDF`) **OU cole o link** do modelo;\n"
            "🖼️ E envie a **foto da peça** (pode mandar juntos ou um depois do outro).\n\n"
            f"💡 _Suporte a arquivos de até {limit_desc}!_"
        )
        return {"ok": True}

    # =========================================================================
    # 5. Tratamento de Botões Inline (Callbacks)
    # =========================================================================
    if callback_data:
        # Se não há wizard ativo para o chat, o botão clicado é antigo/expirado
        if chat_id not in USER_WIZARDS:
            if msg_id:
                await remove_inline_keyboard(bot_token, chat_id, msg_id)
            await send_telegram_reply(
                bot_token, chat_id,
                "⚠️ *Esta proposta já foi concluída ou expirou!*\n\nEnvie um novo arquivo 3D e uma foto da peça para cadastrar outro modelo."
            )
            return {"ok": True}

        wizard = USER_WIZARDS[chat_id]

        # APROVAÇÃO E PUBLICAÇÃO
        if callback_data in ("ai_approve_price", "ai_approve_quote"):
            # Desativa os botões da mensagem do Telegram imediatamente
            if msg_id:
                await remove_inline_keyboard(bot_token, chat_id, msg_id)
            elif wizard.get("proposal_message_id"):
                await remove_inline_keyboard(bot_token, chat_id, wizard["proposal_message_id"])

            with_price = (callback_data == "ai_approve_price")
            await finalize_and_publish(bot_token, chat_id, wizard, with_price=with_price)
            return {"ok": True}

        # CANCELAR
        if callback_data == "ai_cancel":
            if msg_id:
                await remove_inline_keyboard(bot_token, chat_id, msg_id)
            shutil.rmtree(wizard["temp_dir"], ignore_errors=True)
            del USER_WIZARDS[chat_id]
            await send_telegram_reply(bot_token, chat_id, "❌ Cadastro cancelado com sucesso. Arquivos descartados.")
            return {"ok": True}

        # ALTERAR CATEGORIA
        if callback_data == "ai_change_cat":
            db = SessionLocal()
            categories = []
            try:
                categories = db.query(Category).all()
            finally:
                db.close()

            cat_buttons = []
            row = []
            for cat in categories:
                row.append({"text": cat.name, "callback_data": f"ai_setcat_{cat.id}"})
                if len(row) == 2:
                    cat_buttons.append(row)
                    row = []
            if row:
                cat_buttons.append(row)
            cat_buttons.append([{"text": "⬅️ Voltar à Proposta", "callback_data": "ai_back_to_card"}])

            await send_telegram_reply(
                bot_token, chat_id,
                "🏷️ *Escolha a categoria desejada:*",
                reply_markup={"inline_keyboard": cat_buttons}
            )
            return {"ok": True}

        if callback_data.startswith("ai_setcat_"):
            try:
                cat_id = int(callback_data.split("_")[-1])
                db = SessionLocal()
                try:
                    cat = db.query(Category).filter(Category.id == cat_id).first()
                    if cat:
                        wizard["category_id"] = cat.id
                        wizard["category_name"] = cat.name
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"Erro ao selecionar categoria: {e}")

            await send_telegram_reply(bot_token, chat_id, f"✅ Categoria alterada para: *{wizard['category_name']}*")
            await send_proposal_card(bot_token, chat_id, wizard)
            return {"ok": True}

        # ALTERAR VALOR
        if callback_data == "ai_change_price":
            wizard["step"] = "WAIT_CUSTOM_PRICE"
            await send_telegram_reply(
                bot_token, chat_id,
                "💰 *Digite o novo valor em Reais* (ex: `45` ou `49,90`):\n"
                "_Se quiser sob consulta, digite 0._"
            )
            return {"ok": True}

        # ALTERAR TÍTULO
        if callback_data == "ai_change_title":
            wizard["step"] = "WAIT_CUSTOM_TITLE"
            await send_telegram_reply(
                bot_token, chat_id,
                "📝 *Digite o novo título comercial para este modelo:*"
            )
            return {"ok": True}

        # ADICIONAR MAIS FOTOS
        if callback_data == "ai_add_photos":
            await send_telegram_reply(
                bot_token, chat_id,
                "📸 *Envie agora a(s) próxima(s) foto(s) da peça!*\n"
                "Elas serão adicionadas automaticamente à galeria da vitrine."
            )
            return {"ok": True}

        # VOLTAR AO CARD
        if callback_data == "ai_back_to_card":
            await send_proposal_card(bot_token, chat_id, wizard)
            return {"ok": True}

    wizard = _get_or_create_wizard(chat_id)

    # =========================================================================
    # 6. Estados de Edição Manual de Campos
    # =========================================================================
    if wizard.get("step") == "WAIT_CUSTOM_PRICE" and text:
        clean_price_str = re.sub(r'[^\d,.]', '', text).replace(',', '.')
        try:
            new_p = float(clean_price_str)
            wizard["price"] = new_p
            wizard["show_price"] = new_p > 0
            wizard["step"] = "PROPOSAL"
            lbl = f"R$ {new_p:.2f}" if new_p > 0 else "Sob Consulta"
            await send_telegram_reply(bot_token, chat_id, f"✅ Preço atualizado para: *{lbl}*")
            await send_proposal_card(bot_token, chat_id, wizard)
            return {"ok": True}
        except Exception:
            await send_telegram_reply(bot_token, chat_id, "⚠️ Valor inválido. Digite apenas o valor numérico (ex: 45 ou 49,90):")
            return {"ok": True}

    if wizard.get("step") == "WAIT_CUSTOM_TITLE" and text:
        wizard["title"] = text.strip()
        wizard["step"] = "PROPOSAL"
        await send_telegram_reply(bot_token, chat_id, f"✅ Título atualizado para: *{wizard['title']}*")
        await send_proposal_card(bot_token, chat_id, wizard)
        return {"ok": True}

    # =========================================================================
    # 7. Recebimento de Links Externos (MakerWorld, Thingiverse, etc.)
    # =========================================================================
    if text:
        url_match = re.search(r"(https?://[^\s]+|www\.[^\s]+)", text)
        if url_match:
            detected_url = url_match.group(0)
            if not detected_url.startswith("http"):
                detected_url = "https://" + detected_url
            wizard["external_url"] = detected_url
            await send_telegram_reply(bot_token, chat_id, f"🔗 *Link do modelo registrado!*\n`{detected_url}`")
            if wizard.get("cover_img"):
                await trigger_ai_proposal(bot_token, chat_id, wizard, caption=text)
            else:
                await send_telegram_reply(
                    bot_token, chat_id,
                    "🖼️ *Agora envie a foto da peça impressa* para a IA analisar o visual e gerar a proposta completa!"
                )
            return {"ok": True}

    # =========================================================================
    # 8. Recebimento de Imagens (Blindagem Total contra Duplicação)
    # =========================================================================
    is_img_doc = bool(document) and Path(document.get("file_name", "")).suffix.lower() in ALLOWED_IMG_EXTENSIONS
    if photos or is_img_doc:
        file_unique_id = ""
        if photos:
            img_file_id = photos[-1].get("file_id")
            file_unique_id = photos[-1].get("file_unique_id", "")
            img_name = f"foto_{uuid.uuid4().hex[:6]}.jpg"
        else:
            img_file_id = document.get("file_id")
            file_unique_id = document.get("file_unique_id", "")
            img_name = document.get("file_name") or f"foto_{uuid.uuid4().hex[:6]}.jpg"

        target_img = wizard["temp_dir"] / img_name
        success, err = await download_telegram_file(bot_token, img_file_id, target_img)
        if not success:
            await send_telegram_reply(bot_token, chat_id, f"❌ Falha ao baixar imagem: {err}")
            return {"ok": False}

        # Calcula hash MD5 do arquivo baixado para garantir unicidade absoluta
        img_bytes = target_img.read_bytes()
        img_hash = hashlib.md5(img_bytes).hexdigest()

        # 1. Primeira foto se torna a capa principal
        if not wizard.get("cover_img"):
            wizard["cover_img"] = {
                "name": img_name,
                "path": target_img,
                "file_id": img_file_id,
                "file_unique_id": file_unique_id,
                "hash": img_hash
            }
            # Se já possuímos arquivo 3D ou link, ativa a IA!
            if wizard.get("files_3d") or wizard.get("external_url"):
                await trigger_ai_proposal(bot_token, chat_id, wizard, caption=text)
            else:
                await send_telegram_reply(
                    bot_token, chat_id,
                    "🖼️ *Foto da peça recebida com sucesso!*\n\n"
                    "📁 Agora envie o **arquivo 3D** (`.STL`, `.3MF`, `.ZIP`, `.RAR`) ou o **link do site** para a IA gerar o anúncio!"
                )
            return {"ok": True}
        else:
            # 2. Já existe capa -> Verifica se esta foto é DUPLICADA da capa!
            cover = wizard["cover_img"]
            is_dup_cover = (
                (file_unique_id and file_unique_id == cover.get("file_unique_id")) or
                (img_file_id and img_file_id == cover.get("file_id")) or
                (img_hash and img_hash == cover.get("hash"))
            )
            if is_dup_cover:
                logger.info(f"Foto duplicada da capa ignorada para chat {chat_id} (hash {img_hash}).")
                target_img.unlink(missing_ok=True)
                return {"ok": True}

            # 3. Verifica se esta foto já existe na galeria
            for g in wizard.get("gallery_imgs", []):
                if (file_unique_id and file_unique_id == g.get("file_unique_id")) or (img_hash and img_hash == g.get("hash")):
                    logger.info(f"Foto idêntica já existente na galeria ignorada para chat {chat_id} (hash {img_hash}).")
                    target_img.unlink(missing_ok=True)
                    return {"ok": True}

            # 4. Foto extra legítima adicionada à galeria
            wizard["gallery_imgs"].append({
                "name": img_name,
                "path": target_img,
                "file_id": img_file_id,
                "file_unique_id": file_unique_id,
                "hash": img_hash
            })
            total_gal = 1 + len(wizard["gallery_imgs"])
            if wizard.get("step") == "PROPOSAL":
                await send_telegram_reply(bot_token, chat_id, f"📸 *Foto extra adicionada!* (Total de {total_gal} fotos para a vitrine).")
                await send_proposal_card(bot_token, chat_id, wizard)
            else:
                await send_telegram_reply(bot_token, chat_id, f"📸 *Foto extra salva!* (Total: {total_gal} fotos).")
            return {"ok": True}

    # =========================================================================
    # 9. Recebimento de Arquivos 3D (.STL, .3MF, .ZIP, .RAR, etc.)
    # =========================================================================
    if document:
        raw_file_name = document.get("file_name") or "modelo.stl"
        file_name = Path(raw_file_name).name
        file_name = re.sub(r'[^\w\-_\. ()]', '_', file_name)
        ext = Path(file_name).suffix.lower()

        if ext not in ALLOWED_3D_EXTENSIONS:
            await send_telegram_reply(
                bot_token, chat_id,
                f"⚠️ O formato `{ext}` não é reconhecido. Envie arquivos 3D (`.STL`, `.3MF`, `.OBJ`, `.ZIP`, `.RAR`), manual (`.PDF`) ou fotos (`.JPG`, `.PNG`)."
            )
            return {"ok": True}

        # Limite de tamanho
        file_size_bytes = document.get("file_size", 0)
        is_local_api = "api.telegram.org" not in TELEGRAM_API_SERVER
        max_tg_size = 2000 * 1024 * 1024 if is_local_api else 20 * 1024 * 1024
        if file_size_bytes and file_size_bytes > max_tg_size:
            size_mb = file_size_bytes / (1024 * 1024)
            await send_telegram_reply(
                bot_token, chat_id,
                f"⚠️ *Arquivo muito grande ({size_mb:.1f} MB)*\n\n"
                f"O limite máximo aceito pela Bot API é de **{'2.000 MB (2 GB)' if is_local_api else '20 MB'}**.\n\n"
                f"💡 Acesse `{CATALOG_DOMAIN}/admin` para fazer o upload diretamente pelo navegador!"
            )
            return {"ok": True}

        # Evita duplicatas do mesmo arquivo no mesmo modelo
        if any(f["name"] == file_name for f in wizard.get("files_3d", [])):
            logger.info(f"Arquivo já adicionado ao modelo atual: {file_name}")
            return {"ok": True}

        await send_telegram_reply(bot_token, chat_id, f"⏳ Baixando `{file_name}`...")

        target_file = wizard["temp_dir"] / file_name
        success, err_msg = await download_telegram_file(bot_token, document.get("file_id"), target_file)
        if not success:
            await send_telegram_reply(bot_token, chat_id, f"❌ Falha no download: {err_msg}")
            return {"ok": False}

        file_size = target_file.stat().st_size
        parts_count = 1

        # Se for ZIP, inspeciona peças
        if ext == ".zip":
            try:
                with zipfile.ZipFile(target_file, "r") as zf:
                    pieces = [n for n in zf.namelist() if any(n.lower().endswith(e) for e in ALLOWED_3D_EXTENSIONS if e != ".pdf")]
                    if pieces:
                        parts_count = len(pieces)
            except Exception:
                pass

        wizard["files_3d"].append({
            "name": file_name,
            "path": target_file,
            "size": file_size,
            "ext": ext,
            "parts_count": parts_count
        })

        size_mb = file_size / (1024 * 1024)
        pkg_info = f" ({parts_count} peças detectadas)" if parts_count > 1 else ""

        # Se já tiver foto de capa, ativa a IA!
        if wizard.get("cover_img"):
            await trigger_ai_proposal(bot_token, chat_id, wizard, caption=text)
        else:
            if ext == ".pdf":
                await send_telegram_reply(
                    bot_token, chat_id,
                    f"📄 *Manual de Montagem em PDF recebido:* `{file_name}` ({size_mb:.1f} MB)!\nEle será empacotado junto aos arquivos de impressão 3D.\n\n"
                    f"👉 Agora envie os **arquivos 3D** (`.STL`, `.3MF`, `.ZIP`) e a **foto da peça**!"
                )
            else:
                await send_telegram_reply(
                    bot_token, chat_id,
                    f"✅ *Arquivo 3D recebido:* `{file_name}` ({size_mb:.1f} MB){pkg_info}!\n\n"
                    f"🖼️ *Agora envie a foto da peça impressa* para a IA analisar o visual e gerar a proposta completa!"
                )
        return {"ok": True}

    # Se recebeu algum texto solto e o modelo já está com a proposta montada
    if wizard.get("step") == "PROPOSAL":
        await send_proposal_card(bot_token, chat_id, wizard)
        return {"ok": True}

    # Se recebeu mensagem genérica sem arquivos
    await send_telegram_reply(
        bot_token, chat_id,
        "💡 *Como cadastrar com IA:*\n"
        "Envie ou encaminhe o **arquivo 3D** (`.STL`, `.3MF`, `.ZIP`, `.RAR`) e a **foto da peça** impressa!"
    )
    return {"ok": True}
