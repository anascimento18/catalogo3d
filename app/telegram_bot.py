import re
import json
import uuid
import shutil
import zipfile
import logging
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
    ADMIN_PASSWORD
)
from app.database import SessionLocal, Model3D, Category

logger = logging.getLogger("telegram_bot")

# Diretório temporário para uploads do Telegram
TEMP_TG_DIR = DATA_DIR / "temp_telegram"
TEMP_TG_DIR.mkdir(parents=True, exist_ok=True)

# Estado das conversas dos usuários (FSM)
# { chat_id: { "step": "...", "files_3d": [], "cover_img": ..., "gallery_imgs": [], ... } }
USER_WIZARDS: Dict[int, Dict[str, Any]] = {}

# Sessões autorizadas dinamicamente
AUTHORIZED_CHATS = set()


def is_authorized(user_id: str, chat_id: str, admin_chat_id: Optional[str]) -> bool:
    """Verifica se o usuário ou chat tem permissão para usar o bot."""
    if str(user_id) in AUTHORIZED_CHATS or str(chat_id) in AUTHORIZED_CHATS:
        return True
    if admin_chat_id:
        allowed = [s.strip().strip('"\'') for s in str(admin_chat_id).split(",") if s.strip()]
        if str(user_id) in allowed or str(chat_id) in allowed:
            return True
    return False


async def setup_telegram_webhook(bot_token: str, base_domain: str):
    """Configura o webhook do Telegram com suporte a mensagens e botões inline."""
    if not bot_token or not base_domain:
        return
    webhook_url = f"{base_domain.rstrip('/')}/api/telegram/webhook"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                f"https://api.telegram.org/bot{bot_token}/setWebhook",
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


async def send_telegram_reply(bot_token: str, chat_id: int, text: str, reply_markup: Optional[dict] = None):
    """Envia mensagem de texto formatada com suporte a botões inline."""
    if not bot_token or not chat_id:
        return
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
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json=payload
            )
    except Exception as e:
        logger.error(f"Erro ao responder no Telegram (chat {chat_id}): {e}")


async def answer_callback_query(bot_token: str, callback_query_id: str, text: Optional[str] = None):
    """Responde ao clique de botão inline no Telegram para remover o loading."""
    if not bot_token or not callback_query_id:
        return
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery", json=payload)
    except Exception as e:
        logger.error(f"Erro ao responder callback query no Telegram: {e}")


async def download_telegram_file(bot_token: str, file_id: str, dest_path: Path) -> bool:
    """Baixa um arquivo dos servidores do Telegram para o disco local."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.get(f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}")
            file_path_on_tg = res.json().get("result", {}).get("file_path")
            if not file_path_on_tg:
                return False
            download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path_on_tg}"
            file_res = await client.get(download_url)
            dest_path.write_bytes(file_res.content)
            return True
    except Exception as e:
        logger.error(f"Erro ao baixar arquivo {file_id} do Telegram: {e}")
        return False


async def process_telegram_update(update: dict, bot_token: str, admin_chat_id: Optional[str] = None) -> dict:
    """
    Processa mensagens e callbacks recebidos pelo Bot do Telegram.
    Implementa um assistente conversacional passo a passo (/newmodelo).
    """
    # 1. Extrai mensagem ou callback_query
    callback_query = update.get("callback_query")
    message = update.get("message") or update.get("channel_post")

    chat_id = None
    user_id = None
    text = ""
    document = None
    photos = None

    if callback_query:
        from_user = callback_query.get("from", {})
        user_id = str(from_user.get("id", ""))
        message = callback_query.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        callback_data = callback_query.get("data", "")
        await answer_callback_query(bot_token, callback_query.get("id"))
    elif message:
        from_user = message.get("from", {})
        user_id = str(from_user.get("id", ""))
        chat_id = message.get("chat", {}).get("id")
        text = str(message.get("text") or message.get("caption") or "").strip()
        document = message.get("document")
        photos = message.get("photo")
        callback_data = None
    else:
        return {"ok": True, "ignored": "No valid message or callback"}

    if not chat_id:
        return {"ok": False, "error": "No chat_id"}

    # 2. Comando especial de autorização por senha
    if text.startswith("/auth"):
        parts = text.split()
        if len(parts) >= 2 and parts[1].strip() == ADMIN_PASSWORD:
            AUTHORIZED_CHATS.add(str(user_id))
            AUTHORIZED_CHATS.add(str(chat_id))
            await send_telegram_reply(
                bot_token, chat_id,
                f"🔓 *Autorizado com Sucesso!*\n\n"
                f"Olá André! Seu Telegram ID `{user_id}` foi autenticado com sucesso.\n"
                f"Agora você pode usar todos os recursos do assistente!\n\n"
                f"👉 Digite /newmodelo para cadastrar seu primeiro modelo."
            )
            return {"ok": True}
        else:
            await send_telegram_reply(
                bot_token, chat_id,
                "❌ *Senha incorreta.*\nDigite: `/auth <sua_senha_admin>`"
            )
            return {"ok": False}

    # 3. Validação de Segurança
    if not is_authorized(user_id, str(chat_id), admin_chat_id):
        logger.warning(f"Tentativa de acesso não autorizada: user_id={user_id}, chat_id={chat_id}")
        await send_telegram_reply(
            bot_token, chat_id,
            f"🔒 *Acesso Restrito ao Administrador*\n\n"
            f"Seu ID no Telegram é: `{user_id}`\n\n"
            f"Para autorizar este aparelho, digite:\n"
            f"`/auth <sua_senha_admin>`\n"
            f"_(Ex: `/auth 3aField@2026`)_"
        )
        return {"ok": False, "error": "Não autorizado"}

    # 4. Comandos Globais
    if text == "/cancelar" or text == "/cancel":
        if chat_id in USER_WIZARDS:
            del USER_WIZARDS[chat_id]
        await send_telegram_reply(
            bot_token, chat_id,
            "❌ *Cadastro cancelado.* Os arquivos temporários foram descartados.\n\n"
            "Quando quiser começar de novo, basta digitar /newmodelo!"
        )
        return {"ok": True}

    if text == "/start" or text == "/ajuda" or text == "/help":
        await send_telegram_reply(
            bot_token, chat_id,
            "👋 *Olá André! Bem-vindo ao Assistente Studio 3D.* 🤖\n\n"
            "Aqui você cadastra modelos completos diretamente pelo celular, com fotos e arquivos 3D!\n\n"
            "🚀 *Comandos Disponíveis:*\n"
            "👉 /newmodelo - Iniciar cadastro guiado de modelo 3D\n"
            "👉 /status - Ver total de modelos no catálogo\n"
            "👉 /cancelar - Cancelar cadastro em andamento\n"
            "👉 /ajuda - Exibir esta mensagem"
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

    # 5. Início do Assistente: /newmodelo
    if text == "/newmodelo" or text == "/novo":
        session_id = uuid.uuid4().hex[:6]
        user_temp_dir = TEMP_TG_DIR / f"{chat_id}_{session_id}"
        user_temp_dir.mkdir(parents=True, exist_ok=True)

        USER_WIZARDS[chat_id] = {
            "session_id": session_id,
            "temp_dir": user_temp_dir,
            "step": "WAIT_3D",
            "files_3d": [],
            "cover_img": None,
            "gallery_imgs": [],
            "title": "",
            "category_id": 1,
            "category_name": "Decoração & Casa",
            "price": 0.0,
            "show_price": True,
            "is_featured": False,
            "order_count": 18,
            "description": ""
        }

        await send_telegram_reply(
            bot_token, chat_id,
            "🚀 *Cadastro de Novo Modelo 3D (Passo 1 de 6)*\n\n"
            "📁 *Envie o(s) Arquivo(s) 3D:*\n"
            "Envie agora o arquivo `.STL`, `.3MF`, `.STEP`, `.OBJ` ou `.ZIP`.\n\n"
            "💡 _Dica: Se o modelo tiver várias peças, você pode enviar um arquivo `.ZIP` contendo todas elas ou enviar múltiplos arquivos .STL!_"
        )
        return {"ok": True}

    # Se não há wizard ativo para este usuário
    wizard = USER_WIZARDS.get(chat_id)
    if not wizard:
        await send_telegram_reply(
            bot_token, chat_id,
            "💡 Digite /newmodelo para iniciar o cadastro passo a passo de uma nova peça 3D!"
        )
        return {"ok": True}

    step = wizard.get("step")

    # =========================================================================
    # PASSO 1: Aguardando Arquivo 3D
    # =========================================================================
    if step == "WAIT_3D":
        if not document:
            await send_telegram_reply(
                bot_token, chat_id,
                "⚠️ *Por favor, envie o arquivo 3D como Documento/Arquivo no Telegram* (`.STL`, `.3MF`, `.OBJ`, `.ZIP`)."
            )
            return {"ok": True}

        file_name = document.get("file_name", "modelo.stl")
        ext = Path(file_name).suffix.lower()

        if ext not in ALLOWED_3D_EXTENSIONS:
            await send_telegram_reply(
                bot_token, chat_id,
                f"⚠️ A extensão `{ext}` não é permitida. Envie arquivos `.STL`, `.3MF`, `.STEP`, `.OBJ` ou `.ZIP`."
            )
            return {"ok": True}

        await send_telegram_reply(bot_token, chat_id, f"⏳ Baixando `{file_name}`...")

        target_file = wizard["temp_dir"] / file_name
        success = await download_telegram_file(bot_token, document.get("file_id"), target_file)
        if not success:
            await send_telegram_reply(bot_token, chat_id, "❌ Falha ao baixar arquivo do Telegram. Tente enviar novamente.")
            return {"ok": False}

        file_size = target_file.stat().st_size
        parts_count = 1

        # Inspeciona se for .ZIP
        if ext == ".zip":
            try:
                with zipfile.ZipFile(target_file, "r") as zf:
                    pieces = [n for n in zf.namelist() if any(n.lower().endswith(e) for e in ALLOWED_3D_EXTENSIONS)]
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

        wizard["step"] = "WAIT_COVER"

        await send_telegram_reply(
            bot_token, chat_id,
            f"✅ *Arquivo 3D recebido!*\n"
            f"📁 `{file_name}` ({file_size/1024/1024:.2f} MB) — *{parts_count} peça(s) detectada(s)*.\n\n"
            f"---\n"
            f"🖼️ *Passo 2 de 6: Foto de Capa Principal*\n"
            f"Envie agora a **Foto de Capa Principal** da peça (esta foto será a vitrine principal no catálogo)."
        )
        return {"ok": True}

    # =========================================================================
    # PASSO 2: Aguardando Foto de Capa Principal
    # =========================================================================
    if step == "WAIT_COVER":
        file_id = None
        orig_name = "capa.jpg"

        if photos:
            file_id = photos[-1].get("file_id")
            orig_name = f"capa_{uuid.uuid4().hex[:4]}.jpg"
        elif document:
            doc_ext = Path(document.get("file_name", "")).suffix.lower()
            if doc_ext in ALLOWED_IMG_EXTENSIONS:
                file_id = document.get("file_id")
                orig_name = document.get("file_name")

        if not file_id:
            await send_telegram_reply(
                bot_token, chat_id,
                "⚠️ Por favor, envie uma imagem válida (`.JPG`, `.PNG`, `.WEBP`) para ser a foto de capa."
            )
            return {"ok": True}

        await send_telegram_reply(bot_token, chat_id, "⏳ Baixando foto de capa...")

        target_cover = wizard["temp_dir"] / orig_name
        success = await download_telegram_file(bot_token, file_id, target_cover)
        if not success:
            await send_telegram_reply(bot_token, chat_id, "❌ Falha ao baixar imagem. Tente enviar novamente.")
            return {"ok": False}

        wizard["cover_img"] = {
            "name": orig_name,
            "path": target_cover
        }

        wizard["step"] = "WAIT_GALLERY"

        keyboard = {
            "inline_keyboard": [
                [{"text": "➡️ Concluir Fotos (Sem Fotos Extras)", "callback_data": "gallery_done"}]
            ]
        }

        await send_telegram_reply(
            bot_token, chat_id,
            f"✅ *Foto de Capa recebida com sucesso!*\n\n"
            f"---\n"
            f"📸 *Passo 3 de 6: Fotos Adicionais da Galeria (Opcional)*\n"
            f"Deseja adicionar mais fotos deste modelo para o carrossel na vitrine?\n\n"
            f"• Se tiver mais fotos, **envie outra foto agora**.\n"
            f"• Se NÃO tiver mais fotos, clique no botão abaixo ou digite /concluir_fotos:",
            reply_markup=keyboard
        )
        return {"ok": True}

    # =========================================================================
    # PASSO 3: Aguardando Fotos Adicionais ou Conclusão da Galeria
    # =========================================================================
    if step == "WAIT_GALLERY":
        # Se clicou no botão "Concluir Fotos" ou digitou /concluir_fotos ou "não"
        if callback_data == "gallery_done" or text in ("/concluir_fotos", "não", "nao", "concluir", "pular"):
            wizard["step"] = "WAIT_TITLE"
            total_g = len(wizard["gallery_imgs"])
            await send_telegram_reply(
                bot_token, chat_id,
                f"✅ *Galeria definida com sucesso!* ({total_g} fotos adicionais cadastradas).\n\n"
                f"---\n"
                f"📝 *Passo 4 de 6: Título do Modelo*\n"
                f"Digite o nome/título da peça:\n"
                f"_Exemplo: BABY REAPER, Vaso Geométrico Poligonal, Suporte Articulado..._"
            )
            return {"ok": True}

        # Recebeu mais uma foto para a galeria
        file_id = None
        orig_name = f"gal_{len(wizard['gallery_imgs'])+1}.jpg"

        if photos:
            file_id = photos[-1].get("file_id")
        elif document:
            doc_ext = Path(document.get("file_name", "")).suffix.lower()
            if doc_ext in ALLOWED_IMG_EXTENSIONS:
                file_id = document.get("file_id")
                orig_name = document.get("file_name")

        if file_id:
            target_gal = wizard["temp_dir"] / orig_name
            success = await download_telegram_file(bot_token, file_id, target_gal)
            if success:
                wizard["gallery_imgs"].append({
                    "name": orig_name,
                    "path": target_gal
                })
                count = len(wizard["gallery_imgs"])
                keyboard = {
                    "inline_keyboard": [
                        [{"text": f"➡️ Concluir Galeria ({count} extras)", "callback_data": "gallery_done"}]
                    ]
                }
                await send_telegram_reply(
                    bot_token, chat_id,
                    f"📸 *Foto extra #{count} adicionada à galeria!*\n\n"
                    f"Envie outra foto se desejar, ou clique no botão abaixo para prosseguir:",
                    reply_markup=keyboard
                )
                return {"ok": True}

        await send_telegram_reply(
            bot_token, chat_id,
            "💡 Envie mais uma foto para o carrossel, ou clique em **Concluir Fotos** no botão abaixo:",
            reply_markup={"inline_keyboard": [[{"text": "➡️ Concluir Fotos", "callback_data": "gallery_done"}]]}
        )
        return {"ok": True}

    # =========================================================================
    # PASSO 4: Aguardando Título
    # =========================================================================
    if step == "WAIT_TITLE":
        if not text:
            await send_telegram_reply(bot_token, chat_id, "⚠️ Digite o título do modelo:")
            return {"ok": True}

        wizard["title"] = text
        wizard["step"] = "WAIT_CATEGORY"

        # Carrega categorias do banco para montar os botões inline
        db = SessionLocal()
        categories = []
        try:
            categories = db.query(Category).all()
        finally:
            db.close()

        keyboard_buttons = []
        # Cria botões em colunas de 2
        row = []
        for cat in categories:
            row.append({"text": cat.name, "callback_data": f"cat_{cat.id}"})
            if len(row) == 2:
                keyboard_buttons.append(row)
                row = []
        if row:
            keyboard_buttons.append(row)

        await send_telegram_reply(
            bot_token, chat_id,
            f"✅ *Título salvo:* {text}\n\n"
            f"---\n"
            f"🏷️ *Passo 5 de 6: Categoria*\n"
            f"Selecione a categoria deste modelo clicando em um dos botões abaixo:",
            reply_markup={"inline_keyboard": keyboard_buttons}
        )
        return {"ok": True}

    # =========================================================================
    # PASSO 5: Aguardando Categoria
    # =========================================================================
    if step == "WAIT_CATEGORY":
        cat_id = None
        if callback_data and callback_data.startswith("cat_"):
            try:
                cat_id = int(callback_data.split("_")[1])
            except:
                pass

        db = SessionLocal()
        try:
            if cat_id:
                cat = db.query(Category).filter(Category.id == cat_id).first()
            else:
                # Tenta buscar por texto
                cat = db.query(Category).filter(Category.name.ilike(f"%{text}%")).first()

            if not cat:
                cat = db.query(Category).first()

            wizard["category_id"] = cat.id
            wizard["category_name"] = cat.name
        finally:
            db.close()

        wizard["step"] = "WAIT_PRICE"

        await send_telegram_reply(
            bot_token, chat_id,
            f"✅ *Categoria selecionada:* {wizard['category_name']}\n\n"
            f"---\n"
            f"💰 *Passo 6 de 6: Preço do Modelo*\n"
            f"Digite o preço da peça em Reais (ex: `50` ou `50,00`).\n"
            f"_Se for sob consulta / orçamento personalizado, digite `0`._"
        )
        return {"ok": True}

    # =========================================================================
    # PASSO 6: Aguardando Preço
    # =========================================================================
    if step == "WAIT_PRICE":
        clean_price_str = re.sub(r'[^\d,.]', '', text).replace(',', '.')
        try:
            price = float(clean_price_str)
        except:
            price = 0.0

        wizard["price"] = price

        if price > 0:
            wizard["step"] = "WAIT_SHOW_PRICE"
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": f"✅ Sim, exibir R$ {price:.2f}", "callback_data": "showprice_yes"},
                        {"text": "💬 Não, exibir 'Sob Consulta'", "callback_data": "showprice_no"}
                    ]
                ]
            }
            await send_telegram_reply(
                bot_token, chat_id,
                f"💰 *Preço registrado:* R$ {price:.2f}\n\n"
                f"Deseja exibir este valor publicamente na vitrine para os clientes?",
                reply_markup=keyboard
            )
            return {"ok": True}
        else:
            wizard["show_price"] = False
            wizard["step"] = "WAIT_FEATURED"
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "⭐ Sim, destacar", "callback_data": "feat_yes"},
                        {"text": "⚪ Não destacar", "callback_data": "feat_no"}
                    ]
                ]
            }
            await send_telegram_reply(
                bot_token, chat_id,
                f"💰 *Preço definido como:* Sob Consulta\n\n"
                f"Deseja destacar este modelo na seção **'Mais Pedidos'** da página principal?",
                reply_markup=keyboard
            )
            return {"ok": True}

    # =========================================================================
    # PASSO 6.1: Exibir Preço na Vitrine?
    # =========================================================================
    if step == "WAIT_SHOW_PRICE":
        if callback_data == "showprice_no" or text.lower() in ("não", "nao"):
            wizard["show_price"] = False
        else:
            wizard["show_price"] = True

        wizard["step"] = "WAIT_FEATURED"
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "⭐ Sim, destacar", "callback_data": "feat_yes"},
                    {"text": "⚪ Não destacar", "callback_data": "feat_no"}
                ]
            ]
        }
        await send_telegram_reply(
            bot_token, chat_id,
            f"⭐ Deseja destacar este modelo na seção **'Mais Pedidos'** da vitrine?",
            reply_markup=keyboard
        )
        return {"ok": True}

    # =========================================================================
    # PASSO 6.2: Destacar em "Mais Pedidos"?
    # =========================================================================
    if step == "WAIT_FEATURED":
        if callback_data == "feat_yes" or text.lower() in ("sim", "destacar"):
            wizard["is_featured"] = True
        else:
            wizard["is_featured"] = False

        wizard["step"] = "WAIT_DESC"

        await send_telegram_reply(
            bot_token, chat_id,
            "📝 *Descrição da Peça:*\n"
            "Digite os detalhes do modelo (material recomendado, dimensões, opções de cores, etc.):\n\n"
            "_💡 Se preferir não escrever agora, digite /pular._"
        )
        return {"ok": True}

    # =========================================================================
    # PASSO 6.3: Descrição e Confirmação Final
    # =========================================================================
    if step == "WAIT_DESC":
        if text and text != "/pular":
            wizard["description"] = text
        else:
            wizard["description"] = "Modelo de alta precisão impresso sob demanda com acabamento profissional."

        wizard["step"] = "CONFIRM"

        price_display = f"R$ {wizard['price']:.2f}" if wizard["show_price"] and wizard["price"] > 0 else "Sob Consulta"
        feat_display = "Sim (★ Mais Pedido)" if wizard["is_featured"] else "Não"
        file_info = wizard["files_3d"][0]
        total_photos = 1 + len(wizard["gallery_imgs"])

        summary_msg = (
            f"📋 *Resumo do Modelo para Publicação:*\n\n"
            f"🔹 *Título:* {wizard['title']}\n"
            f"🏷️ *Categoria:* {wizard['category_name']}\n"
            f"💰 *Preço:* {price_display}\n"
            f"⭐ *Destaque:* {feat_display}\n"
            f"🔥 *Prova Social:* {wizard['order_count']} pedidos realizados\n"
            f"📁 *Arquivo 3D:* `{file_info['name']}` ({file_info['parts_count']} peças)\n"
            f"🖼️ *Galeria:* {total_photos} foto(s) cadastradas\n"
            f"📝 *Descrição:* _{wizard['description']}_\n\n"
            f"Tudo pronto! Deseja publicar o modelo no catálogo agora?"
        )

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🚀 Publicar Modelo Agora", "callback_data": "publish_confirm"},
                    {"text": "❌ Cancelar", "callback_data": "cancel_wizard"}
                ]
            ]
        }

        await send_telegram_reply(bot_token, chat_id, summary_msg, reply_markup=keyboard)
        return {"ok": True}

    # =========================================================================
    # PASSO 7: Publicação Definitiva
    # =========================================================================
    if step == "CONFIRM":
        if callback_data == "cancel_wizard" or text.lower() in ("cancelar", "cancel"):
            del USER_WIZARDS[chat_id]
            await send_telegram_reply(bot_token, chat_id, "❌ Publicação cancelada. Digite /newmodelo quando quiser recomeçar.")
            return {"ok": True}

        if callback_data == "publish_confirm" or text.lower() in ("sim", "publicar", "/publicar", "ok"):
            await send_telegram_reply(bot_token, chat_id, "⏳ Publicando modelo e gravando arquivos no catálogo...")

            unique_id = uuid.uuid4().hex[:8]
            clean_title = "".join(c for c in wizard["title"] if c.isalnum() or c in ("-", "_", " ")).strip().replace(" ", "_")

            # 1. Move Foto de Capa
            cover_info = wizard["cover_img"]
            c_ext = Path(cover_info["name"]).suffix.lower()
            saved_cover_name = f"{clean_title}_{unique_id}_cover{c_ext}"
            shutil.move(str(cover_info["path"]), str(IMAGE_DIR / saved_cover_name))

            # 2. Move Fotos da Galeria
            saved_gallery_names = []
            for idx, g_info in enumerate(wizard["gallery_imgs"]):
                g_ext = Path(g_info["name"]).suffix.lower()
                g_name = f"{clean_title}_{unique_id}_gal_{idx+1}{g_ext}"
                shutil.move(str(g_info["path"]), str(IMAGE_DIR / g_name))
                saved_gallery_names.append(g_name)

            # 3. Move Arquivo 3D
            f_3d = wizard["files_3d"][0]
            f_ext = f_3d["ext"]
            saved_3d_name = f"{clean_title}_{unique_id}{f_ext}"
            target_3d = MODEL_DIR / saved_3d_name
            shutil.move(str(f_3d["path"]), str(target_3d))

            parts_count = f_3d["parts_count"]
            format_str = f_ext.lstrip(".").upper()

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
                    files_3d_list=json.dumps([{"name": f_3d["name"], "size": f_3d["size"]}]),
                    parts_count=parts_count,
                    file_format=format_str,
                    file_size_bytes=f_3d["size"],
                    price=wizard["price"],
                    show_price=wizard["show_price"],
                    order_count=wizard["order_count"],
                    is_featured=wizard["is_featured"],
                    is_public=True
                )
                db.add(new_model)
                db.commit()
                db.refresh(new_model)
                model_id = new_model.id
            finally:
                db.close()

            # Limpa temporários
            shutil.rmtree(wizard["temp_dir"], ignore_errors=True)
            del USER_WIZARDS[chat_id]

            total_photos = 1 + len(saved_gallery_names)
            await send_telegram_reply(
                bot_token, chat_id,
                f"🎉 *Modelo Publicado com Sucesso!*\n\n"
                f"📦 *{wizard['title']}* já está no ar para seus clientes!\n\n"
                f"• ID: `#{model_id}`\n"
                f"• Categoria: {wizard['category_name']}\n"
                f"• Fotos na galeria: {total_photos}\n"
                f"• Peças 3D: {parts_count}\n\n"
                f"👉 [Visualizar na Vitrine Online]({CATALOG_DOMAIN})"
            )
            return {"ok": True}

    return {"ok": True}
