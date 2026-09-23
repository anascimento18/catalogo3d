import httpx
import logging
from datetime import datetime
from urllib.parse import quote
from app.config import (
    N8N_WEBHOOK_URL,
    EVOLUTION_URL,
    EVOLUTION_KEY,
    EVOLUTION_INSTANCE,
    DEST_WHATSAPP,
    CATALOG_DOMAIN
)

logger = logging.getLogger("catalogo_notifier")

async def send_order_notification(order_data: dict, model_data: dict) -> dict:
    """
    Envia a notificação do pedido para o n8n e Evolution API.
    Retorna o status do envio e o link direto do WhatsApp (fallback).
    """
    model_title = model_data.get("title", "Modelo 3D")
    category = model_data.get("category_name", "Geral")
    price = model_data.get("price", 0.0)
    show_price = model_data.get("show_price", True)
    image_filename = model_data.get("image_filename", "")
    external_url = model_data.get("external_url", "")
    
    cust_name = order_data.get("customer_name", "Cliente")
    cust_phone = order_data.get("customer_phone", "")
    cust_notes = order_data.get("customer_notes", "Nenhuma observação informada.")
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Monta texto de preço
    if show_price and price > 0:
        price_text = f"R$ {price:.2f}"
    elif price > 0:
        price_text = f"Sob Consulta (Seu preço cadastrado no painel: R$ {price:.2f})"
    else:
        price_text = "Sob Consulta"

    # URL pública da foto do modelo
    image_url = f"{CATALOG_DOMAIN}/api/public/images/{image_filename}"

    link_line = f"\n🔗 *Link do Site/Personalizador:*\n{external_url}\n" if external_url else ""

    # Mensagem formatada para o WhatsApp do André
    message_text = (
        f"📦 *NOVO PEDIDO DE IMPRESSÃO 3D!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔹 *Modelo:* {model_title}\n"
        f"🔹 *Categoria:* {category}\n"
        f"💰 *Valor de Referência:* {price_text}\n"
        f"🆔 *Código do Item:* #{model_data.get('id')}\n"
        f"{link_line}\n"
        f"👤 *DADOS DO CLIENTE:*\n"
        f"• *Nome:* {cust_name}\n"
        f"• *WhatsApp:* {cust_phone}\n"
        f"• *Observações:* {cust_notes}\n\n"
        f"⏰ *Recebido em:* {now_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    # Link direto para o cliente chamar no WhatsApp se desejar
    client_msg = f"Olá André! Gostaria de encomendar a impressão 3D do modelo: *{model_title}*."
    wa_direct_link = f"https://wa.me/{DEST_WHATSAPP}?text={quote(client_msg)}"

    payload = {
        "event": "new_order",
        "timestamp": now_str,
        "whatsapp_dest": DEST_WHATSAPP,
        "image_url": image_url,
        "message": message_text,
        "model": {
            "id": model_data.get("id"),
            "title": model_title,
            "category": category,
            "price": price,
            "show_price": show_price,
            "image_filename": image_filename
        },
        "customer": {
            "name": cust_name,
            "phone": cust_phone,
            "notes": cust_notes
        }
    }

    n8n_ok = False
    evolution_ok = False

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Envio para o Webhook do n8n
        if N8N_WEBHOOK_URL:
            try:
                res = await client.post(N8N_WEBHOOK_URL, json=payload)
                if res.status_code in (200, 201, 204):
                    n8n_ok = True
            except Exception as e:
                logger.warning(f"Falha ao acionar webhook n8n: {e}")

        # 2. Envio direto para a Evolution API se o n8n não responder ou como redundância
        if EVOLUTION_URL and EVOLUTION_KEY and not n8n_ok:
            try:
                evo_endpoint = f"{EVOLUTION_URL.rstrip('/')}/message/sendMedia/{EVOLUTION_INSTANCE}"
                evo_headers = {
                    "apikey": EVOLUTION_KEY,
                    "Content-Type": "application/json"
                }
                evo_body = {
                    "number": DEST_WHATSAPP,
                    "mediatype": "image",
                    "mimetype": "image/jpeg",
                    "caption": message_text,
                    "media": image_url,
                    "fileName": f"{model_title}.jpg"
                }
                res_evo = await client.post(evo_endpoint, headers=evo_headers, json=evo_body)
                if res_evo.status_code in (200, 201):
                    evolution_ok = True
            except Exception as e:
                logger.warning(f"Falha ao enviar via Evolution API: {e}")

    return {
        "ok": True,
        "n8n_notified": n8n_ok,
        "evolution_notified": evolution_ok,
        "wa_direct_link": wa_direct_link
    }
