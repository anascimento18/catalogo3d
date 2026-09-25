import asyncio
import shutil
import hashlib
from pathlib import Path
from unittest.mock import patch, AsyncMock

from app.telegram_bot import (
    process_telegram_update,
    _get_or_create_wizard,
    finalize_and_publish,
    USER_WIZARDS
)
from app.database import SessionLocal, Model3D

async def test_photo_deduplication_and_ghost_rejection():
    chat_id = 88887777
    auth_update = {
        "message": {
            "chat": {"id": chat_id},
            "from": {"id": chat_id},
            "text": "/auth 3aField@2026"
        }
    }
    await process_telegram_update(auth_update, "test_token", None)

    wizard = _get_or_create_wizard(chat_id)
    fake_img = wizard["temp_dir"] / "test_photo.jpg"
    shutil.copyfile("app/static/img/default_3d_cover.png", fake_img)
    img_bytes = fake_img.read_bytes()
    img_hash = hashlib.md5(img_bytes).hexdigest()

    # 1. Simula envio da 1ª foto
    photo_update_1 = {
        "message": {
            "chat": {"id": chat_id},
            "from": {"id": chat_id},
            "photo": [
                {"file_id": "file_123", "file_unique_id": "unique_abc", "file_size": 100}
            ]
        }
    }
    async def fake_download(token, fid, dest):
        dest.write_bytes(img_bytes)
        return True, "Sucesso"

    with patch("app.telegram_bot.download_telegram_file", side_effect=fake_download), \
         patch("app.telegram_bot.send_telegram_reply", new_callable=AsyncMock):
        await process_telegram_update(photo_update_1, "test_token", None)

    assert wizard["cover_img"] is not None
    assert len(wizard["gallery_imgs"]) == 0
    print("[OK] 1ª foto recebida e atribuída como capa principal (Galeria = 0).")

    # 2. Simula envio da MESMA foto novamente (duplicata de rede/webhook)
    photo_update_dup = {
        "message": {
            "chat": {"id": chat_id},
            "from": {"id": chat_id},
            "photo": [
                {"file_id": "file_123_different_size", "file_unique_id": "unique_abc", "file_size": 200}
            ]
        }
    }
    with patch("app.telegram_bot.download_telegram_file", side_effect=fake_download), \
         patch("app.telegram_bot.send_telegram_reply", new_callable=AsyncMock):
        await process_telegram_update(photo_update_dup, "test_token", None)

    assert len(wizard["gallery_imgs"]) == 0, "FALHA: Foto duplicada entrou na galeria!"
    print("[OK] Foto duplicada rejeitada com sucesso (Galeria continua 0)!")

    # 3. Simula tentativa de publicar wizard fantasma/vazio
    empty_chat_id = 99990000
    empty_wizard = _get_or_create_wizard(empty_chat_id) # sem título, sem arquivos
    db_before = SessionLocal().query(Model3D).count()
    with patch("app.telegram_bot.send_telegram_reply", new_callable=AsyncMock):
        await finalize_and_publish("test_token", empty_chat_id, empty_wizard, with_price=True)
    db_after = SessionLocal().query(Model3D).count()
    assert db_before == db_after, "FALHA: Rascunho vazio/fantasma foi publicado no banco!"
    print("[OK] Blindagem anti-fantasma: Tentativa de publicar rascunho sem arquivos bloqueada!")

    # Limpeza
    shutil.rmtree(wizard["temp_dir"], ignore_errors=True)
    shutil.rmtree(empty_wizard["temp_dir"], ignore_errors=True)
    if chat_id in USER_WIZARDS: del USER_WIZARDS[chat_id]
    if empty_chat_id in USER_WIZARDS: del USER_WIZARDS[empty_chat_id]

    print("\nTESTE DE DEDUPLICAÇÃO E ANTI-FANTASMA PASSOU 100%!")

if __name__ == "__main__":
    asyncio.run(test_photo_deduplication_and_ghost_rejection())
