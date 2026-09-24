import asyncio
import os
import shutil
from pathlib import Path
from unittest.mock import patch, AsyncMock

from app.config import TELEGRAM_BOT_TOKEN
from app.telegram_bot import (
    process_telegram_update,
    USER_WIZARDS,
    _get_or_create_wizard,
    trigger_ai_proposal,
    finalize_and_publish,
    send_proposal_card
)
from app.database import SessionLocal, Model3D, Category

async def test_full_ai_bot_workflow():
    test_chat_id = 99912345
    auth_update = {
        "message": {
            "chat": {"id": test_chat_id},
            "from": {"id": test_chat_id},
            "text": "/auth 3aField@2026"
        }
    }
    # 1. Autenticação
    res = await process_telegram_update(auth_update, "test_token", None)
    assert res["ok"] is True

    # 2. Inicializa wizard
    wizard = _get_or_create_wizard(test_chat_id)
    
    # Cria arquivo fake .rar e foto fake
    fake_rar = wizard["temp_dir"] / "Mood Ghost.rar"
    fake_rar.write_bytes(b"Rar! fake rar archive content for testing")
    wizard["files_3d"].append({
        "name": "Mood Ghost.rar",
        "path": fake_rar,
        "size": 1024,
        "ext": ".rar",
        "parts_count": 1
    })

    fake_img = wizard["temp_dir"] / "cover.jpg"
    shutil.copyfile("app/static/img/default_3d_cover.png", fake_img)
    wizard["cover_img"] = {
        "name": "cover.jpg",
        "path": fake_img
    }

    print("[1] Testando trigger_ai_proposal com MiniMax...")
    # Mock do envio no telegram para não tentar enviar para a internet durante teste
    with patch("app.telegram_bot.send_telegram_reply", new_callable=AsyncMock) as mock_reply:
        await trigger_ai_proposal("test_token", test_chat_id, wizard)
        assert wizard["step"] == "PROPOSAL"
        assert len(wizard["title"]) > 3
        assert wizard["price"] > 0
        assert wizard["category_name"] != ""
        print(f"   -> Título gerado pela IA: {wizard['title']}")
        print(f"   -> Categoria gerada pela IA: {wizard['category_name']}")
        print(f"   -> Preço sugerido: R$ {wizard['price']:.2f}")
        print(f"   -> Faixa: {wizard['price_range']}")
        print(f"   -> Descrição: {wizard['description'][:80]}...")

    # 3. Teste de alteração de preço
    print("[2] Testando alteração de preço...")
    price_change_cb = {
        "callback_query": {
            "id": "cb_1",
            "from": {"id": test_chat_id},
            "message": {"chat": {"id": test_chat_id}},
            "data": "ai_change_price"
        }
    }
    with patch("app.telegram_bot.send_telegram_reply", new_callable=AsyncMock):
        await process_telegram_update(price_change_cb, "test_token", None)
        assert wizard["step"] == "WAIT_CUSTOM_PRICE"

    new_price_msg = {
        "message": {
            "chat": {"id": test_chat_id},
            "from": {"id": test_chat_id},
            "text": "59.90"
        }
    }
    with patch("app.telegram_bot.send_telegram_reply", new_callable=AsyncMock):
        await process_telegram_update(new_price_msg, "test_token", None)
        assert wizard["step"] == "PROPOSAL"
        assert wizard["price"] == 59.90
        print("   -> Preço atualizado com sucesso para R$ 59.90")

    # 4. Teste de aprovação e publicação
    print("[3] Testando aprovação e publicação com 1 clique...")
    approve_cb = {
        "callback_query": {
            "id": "cb_2",
            "from": {"id": test_chat_id},
            "message": {"chat": {"id": test_chat_id}},
            "data": "ai_approve_price"
        }
    }
    with patch("app.telegram_bot.send_telegram_reply", new_callable=AsyncMock):
        await process_telegram_update(approve_cb, "test_token", None)
        assert test_chat_id not in USER_WIZARDS

    # Verifica se foi gravado no banco de dados
    db = SessionLocal()
    try:
        created = db.query(Model3D).filter(Model3D.price == 59.90).order_by(Model3D.id.desc()).first()
        assert created is not None
        assert created.price == 59.90
        assert created.show_price is True
        print(f"   -> Modelo gravado no banco! ID: #{created.id}, Título: '{created.title}', Preço: R$ {created.price:.2f}")
        # Limpa o modelo de teste
        db.delete(created)
        db.commit()
    finally:
        db.close()

    print("\nTODOS OS FLUXOS DO AGENTE IA TELEGRAM BOT TESTADOS COM SUCESSO ABSOLUTO!")

if __name__ == "__main__":
    asyncio.run(test_full_ai_bot_workflow())
