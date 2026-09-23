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
    """Envia mensagem de texto formatada com suporte a botões inline e fallback automático para texto plano."""
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
            res = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json=payload
            )
            # Se o Telegram rejeitar devido a caracteres especiais de Markdown (ex: underscore em comandos ou nomes de arquivos)
            if res.status_code != 200 or not res.json().get("ok"):
                logger.warning(f"Aviso ao enviar markdown ({res.text}). Reenviando em texto plano...")
                plain_payload = {
                    "chat_id": chat_id,
                    "text": text.replace("*", "").replace("_", "").replace("`", ""),
                    "disable_web_page_preview": False
                }
                if reply_markup:
                    plain_payload["reply_markup"] = reply_markup
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json=plain_payload
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


async def download_telegram_file(bot_token: str, file_id: str, dest_path: Path) -> tuple[bool, str]:
    """
    Baixa um arquivo dos servidores do Telegram para o disco local com streaming em chunks.
    Retorna (sucesso, mensagem_ou_erro).
    """
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        timeout_config = httpx.Timeout(connect=20.0, read=180.0, write=60.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout_config) as client:
            res = await client.get(f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}")
            res_data = res.json()
            if not res_data.get("ok"):
                err_desc = res_data.get("description", "Erro ao obter informações do arquivo no Telegram")
                logger.error(f"Telegram getFile error para file_id {file_id}: {err_desc}")
                return False, err_desc

            file_path_on_tg = res_data.get("result", {}).get("file_path")
            if not file_path_on_tg:
                return False, "Caminho do arquivo não fornecido pelo Telegram"

            download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path_on_tg}"
            async with client.stream("GET", download_url) as file_res:
                if file_res.status_code != 200:
                    return False, f"Servidor do Telegram retornou HTTP {file_res.status_code}"
                with open(dest_path, "wb") as f:
                    async for chunk in file_res.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
            return True, "Sucesso"
    except httpx.ReadTimeout:
        logger.error(f"Timeout ao baixar arquivo {file_id} do Telegram (>180s)")
        return False, "Tempo limite esgotado ao baixar o arquivo dos servidores do Telegram (>180s)"
    except Exception as e:
        logger.error(f"Erro ao baixar arquivo {file_id} do Telegram: {e}")
        return False, str(e)


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
            "🚀 *Cadastro de Novo Modelo 3D (Passo 1 de 5)*\n\n"
            "📁 *Envie o(s) Arquivo(s) 3D:*\n"
            "Envie o arquivo `.STL`, `.3MF`, `.STEP`, `.OBJ` ou `.ZIP`.\n\n"
            "💡 *Dicas importantes:*\n"
            "• **Limite do Telegram:** A API do Telegram permite download de arquivos de até **20 MB**. Se o seu arquivo for maior que 20MB, você pode cadastrar pelo painel web: `catalogo3d.3afieldservice.com.br/admin` (onde aceita até 500 MB).\n"
            "• **Múltiplas Peças:** Se seu modelo tem várias peças, pode enviar os arquivos `.STL` individuais um a um aqui no chat!"
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
    # PASSO 1: Aguardando Arquivo(s) 3D
    # =========================================================================
    if step == "WAIT_3D":
        # Se clicou no botão "Concluir Arquivos 3D" ou digitou comando de conclusão
        if callback_data == "files_3d_done" or text.lower() in ("/concluir", "/concluir_arquivos", "concluir", "pronto", "ok", "avancar", "avançar"):
            if not wizard["files_3d"]:
                await send_telegram_reply(
                    bot_token, chat_id,
                    "⚠️ Nenhum arquivo 3D foi enviado ainda. Envie o arquivo `.STL`, `.3MF`, `.STEP`, `.OBJ` ou `.ZIP` primeiro."
                )
                return {"ok": True}

            wizard["step"] = "WAIT_COVER"
            total_parts = sum(f.get("parts_count", 1) for f in wizard["files_3d"])
            await send_telegram_reply(
                bot_token, chat_id,
                f"✅ *Arquivos 3D concluídos com sucesso!* ({len(wizard['files_3d'])} arquivo(s), {total_parts} peça(s)).\n\n"
                f"---\n"
                f"🖼️ *Passo 2 de 5: Foto da Peça (Capa)*\n"
                f"Envie agora a foto principal da peça (esta foto será a vitrine no catálogo)."
            )
            return {"ok": True}

        # Se já enviou arquivo 3D e mandou uma foto, transiciona automaticamente para o Passo 2 (Capa)
        is_photo = bool(photos) or (bool(document) and Path(document.get("file_name", "")).suffix.lower() in ALLOWED_IMG_EXTENSIONS)
        if is_photo and wizard["files_3d"]:
            wizard["step"] = "WAIT_COVER"
            step = "WAIT_COVER"
        else:
            if not document:
                await send_telegram_reply(
                    bot_token, chat_id,
                    "⚠️ *Por favor, envie o arquivo 3D como Documento/Arquivo no Telegram* (`.STL`, `.3MF`, `.OBJ`, `.ZIP`).\n\n"
                    f"_💡 Se o arquivo for maior que 20 MB, envie diretamente pelo painel web: {CATALOG_DOMAIN}/admin_"
                )
                return {"ok": True}

            file_size_bytes = document.get("file_size", 0)
            if file_size_bytes and file_size_bytes > 20 * 1024 * 1024:
                size_mb = file_size_bytes / (1024 * 1024)
                await send_telegram_reply(
                    bot_token, chat_id,
                    f"⚠️ *Arquivo muito grande para o Telegram ({size_mb:.1f} MB)*\n\n"
                    f"A API oficial de Bots do Telegram impõe um limite de **20 MB** para download de arquivos pelo chat.\n\n"
                    f"💡 *Como publicar este modelo:*\n"
                    f"1️⃣ **Pelo Painel Web (Recomendado):**\n"
                    f"Acesse diretamente pelo navegador:\n"
                    f"🌐 `{CATALOG_DOMAIN}/admin`\n"
                    f"_(O painel web aceita arquivos .ZIP ou .STL de até 500 MB sem limite do Telegram!)_\n\n"
                    f"2️⃣ **Ou envie as peças .STL separadamente aqui:**\n"
                    f"Se o seu arquivo for um `.ZIP` com várias peças, envie os arquivos `.STL` individuais um a um aqui no chat (cada um abaixo de 20 MB). O assistente junta todos automaticamente em um único pacote!"
                )
                return {"ok": True}

            raw_file_name = document.get("file_name") or "modelo.stl"
            file_name = Path(raw_file_name).name
            file_name = re.sub(r'[^\w\-_\. ()]', '_', file_name)
            ext = Path(file_name).suffix.lower()

            if ext not in ALLOWED_3D_EXTENSIONS:
                await send_telegram_reply(
                    bot_token, chat_id,
                    f"⚠️ A extensão `{ext}` não é permitida. Envie arquivos `.STL`, `.3MF`, `.STEP`, `.OBJ` ou `.ZIP`."
                )
                return {"ok": True}

            await send_telegram_reply(bot_token, chat_id, f"⏳ Baixando `{file_name}`...")

            target_file = wizard["temp_dir"] / file_name
            success, err_msg = await download_telegram_file(bot_token, document.get("file_id"), target_file)
            if not success:
                if "file is too big" in err_msg.lower():
                    await send_telegram_reply(
                        bot_token, chat_id,
                        f"⚠️ *Arquivo maior que 20 MB (Limite da API do Telegram)*\n\n"
                        f"O Telegram não permite que robôs baixem arquivos com mais de 20 MB.\n\n"
                        f"💡 *Soluções:*\n"
                        f"1️⃣ Acesse o painel web `{CATALOG_DOMAIN}/admin` para subir arquivos de até 500 MB;\n"
                        f"2️⃣ Ou envie os arquivos `.STL` das peças individualmente aqui no chat."
                    )
                else:
                    await send_telegram_reply(
                        bot_token, chat_id,
                        f"❌ *Falha no download:* {err_msg}.\n\n"
                        f"Tente enviar novamente ou faça o upload diretamente pelo painel web:\n"
                        f"🌐 `{CATALOG_DOMAIN}/admin`"
                    )
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

            # Se for .ZIP, já é um pacote consolidado: avança para a foto de capa
            if ext == ".zip":
                wizard["step"] = "WAIT_COVER"
                await send_telegram_reply(
                    bot_token, chat_id,
                    f"✅ *Pacote ZIP recebido!*\n"
                    f"📁 `{file_name}` ({file_size/1024/1024:.2f} MB) — *{parts_count} peça(s) detectada(s)*.\n\n"
                    f"---\n"
                    f"🖼️ *Passo 2 de 5: Foto da Peça (Capa)*\n"
                    f"Envie agora a foto principal da peça (esta foto será a vitrine no catálogo)."
                )
                return {"ok": True}
            else:
                # Se for arquivo avulso (.STL, .3MF, etc.), permite enviar mais peças ou concluir
                count = len(wizard["files_3d"])
                keyboard = {
                    "inline_keyboard": [
                        [{"text": f"➡️ Concluir Arquivos 3D ({count} peça{'s' if count > 1 else ''})", "callback_data": "files_3d_done"}]
                    ]
                }
                await send_telegram_reply(
                    bot_token, chat_id,
                    f"✅ *Peça 3D #{count} recebida com sucesso!*\n"
                    f"📁 `{file_name}` ({file_size/1024/1024:.2f} MB)\n\n"
                    f"💡 *O modelo possui mais peças?*\n"
                    f"• Se tiver mais peças `.STL`, envie o próximo arquivo agora;\n"
                    f"• Se já enviou todas as peças deste modelo, clique no botão abaixo ou envie a foto de capa:",
                    reply_markup=keyboard
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
        success, err_msg = await download_telegram_file(bot_token, file_id, target_cover)
        if not success:
            await send_telegram_reply(bot_token, chat_id, f"❌ Falha ao baixar imagem de capa: {err_msg}. Tente enviar novamente.")
            return {"ok": False}

        wizard["cover_img"] = {
            "name": orig_name,
            "path": target_cover
        }

        # Avança direto para o título! Se tiver só 1 foto, basta digitar o nome. Se tiver mais, pode enviar mais fotos!
        wizard["step"] = "WAIT_TITLE"

        await send_telegram_reply(
            bot_token, chat_id,
            f"✅ *Foto de Capa recebida com sucesso!*\n\n"
            f"---\n"
            f"📝 *Passo 3 de 5: Título do Modelo*\n"
            f"Digite o nome da peça (ex: _Casinhas Pinha Natal_):\n\n"
            f"💡 _Se tiver mais fotos para a vitrine, pode enviar outra foto agora mesmo!_"
        )
        return {"ok": True}

    # =========================================================================
    # Compatibilidade com sessões anteriores em WAIT_GALLERY
    # =========================================================================
    if step == "WAIT_GALLERY":
        wizard["step"] = "WAIT_TITLE"
        step = "WAIT_TITLE"

    # =========================================================================
    # PASSO 3: Aguardando Título (ou Fotos Extras da Galeria)
    # =========================================================================
    if step == "WAIT_TITLE":
        # Se o usuário enviou outra foto em vez de texto, adiciona à galeria!
        extra_file_id = None
        extra_orig_name = f"gal_{len(wizard['gallery_imgs'])+1}.jpg"

        if photos:
            extra_file_id = photos[-1].get("file_id")
        elif document:
            doc_ext = Path(document.get("file_name", "")).suffix.lower()
            if doc_ext in ALLOWED_IMG_EXTENSIONS:
                extra_file_id = document.get("file_id")
                extra_orig_name = document.get("file_name")

        if extra_file_id:
            await send_telegram_reply(bot_token, chat_id, "⏳ Baixando foto adicional...")
            target_gal = wizard["temp_dir"] / extra_orig_name
            success, err_msg = await download_telegram_file(bot_token, extra_file_id, target_gal)
            if success:
                wizard["gallery_imgs"].append({
                    "name": extra_orig_name,
                    "path": target_gal
                })
                count = len(wizard["gallery_imgs"])
                total_all = 1 + count
                await send_telegram_reply(
                    bot_token, chat_id,
                    f"📸 *Foto extra #{count} adicionada!* (Total: {total_all} fotos cadastradas).\n\n"
                    f"📝 Digite agora o **Título do modelo** (ou envie mais uma foto se desejar):"
                )
                return {"ok": True}
            else:
                await send_telegram_reply(
                    bot_token, chat_id,
                    f"⚠️ Falha ao baixar foto adicional: {err_msg}. Digite o título do modelo para continuar:"
                )
                return {"ok": True}

        # Se clicou em algum callback antigo de galeria
        if callback_data == "gallery_done":
            await send_telegram_reply(bot_token, chat_id, "📝 Digite o título do modelo:")
            return {"ok": True}

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
            f"🏷️ *Passo 4 de 5: Categoria*\n"
            f"Selecione a categoria deste modelo clicando em um dos botões abaixo:",
            reply_markup={"inline_keyboard": keyboard_buttons}
        )
        return {"ok": True}

    # =========================================================================
    # PASSO 4: Aguardando Categoria
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
            f"💰 *Passo 5 de 5: Preço do Modelo*\n"
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
        total_3d_files = len(wizard["files_3d"])
        if total_3d_files == 1:
            file_info = wizard["files_3d"][0]
            parts_summary = f"`{file_info['name']}` ({file_info['parts_count']} peça(s))"
        else:
            parts_summary = f"{total_3d_files} peças (.STL agrupadas em .ZIP)"
        total_photos = 1 + len(wizard["gallery_imgs"])

        summary_msg = (
            f"📋 *Resumo do Modelo para Publicação:*\n\n"
            f"🔹 *Título:* {wizard['title']}\n"
            f"🏷️ *Categoria:* {wizard['category_name']}\n"
            f"💰 *Preço:* {price_display}\n"
            f"⭐ *Destaque:* {feat_display}\n"
            f"🔥 *Prova Social:* {wizard['order_count']} pedidos realizados\n"
            f"📁 *Arquivo 3D:* {parts_summary}\n"
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

            # 3. Processa e Move Arquivo(s) 3D
            if len(wizard["files_3d"]) == 1:
                f_3d = wizard["files_3d"][0]
                f_ext = f_3d["ext"]
                saved_3d_name = f"{clean_title}_{unique_id}{f_ext}"
                target_3d = MODEL_DIR / saved_3d_name
                shutil.move(str(f_3d["path"]), str(target_3d))
                parts_count = f_3d["parts_count"]
                format_str = f_ext.lstrip(".").upper()
                total_size = f_3d["size"]
            else:
                # Múltiplas peças (.STL) recebidas individualmente: empacota em .ZIP com compressão rápida
                saved_3d_name = f"{clean_title}_{unique_id}.zip"
                target_3d = MODEL_DIR / saved_3d_name
                with zipfile.ZipFile(target_3d, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
                    for item in wizard["files_3d"]:
                        zf.write(item["path"], arcname=item["name"])
                parts_count = len(wizard["files_3d"])
                format_str = "ZIP"
                total_size = target_3d.stat().st_size

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
                    files_3d_list=json.dumps([{"name": f["name"], "size": f["size"]} for f in wizard["files_3d"]]),
                    parts_count=parts_count,
                    file_format=format_str,
                    file_size_bytes=total_size,
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
