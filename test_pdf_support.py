import io
import zipfile
import asyncio
from unittest.mock import patch, AsyncMock
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app, MODEL_DIR, IMAGE_DIR
from app.database import SessionLocal, Model3D, Category
from app.config import ADMIN_USERNAME, ADMIN_PASSWORD
from app.telegram_bot import (
    process_telegram_update,
    _get_or_create_wizard,
    finalize_and_publish,
    USER_WIZARDS
)

client = TestClient(app)

def test_web_admin_pdf_bundle_upload_and_download():
    """Testa upload via painel web de arquivo 3D + Manual em PDF e verifica o .ZIP gerado."""
    # 1. Login Admin
    login_res = client.post("/api/auth/login", json={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD
    })
    assert login_res.status_code == 200
    cookies = login_res.cookies

    # 2. Upload com 1 peça STL + 1 Manual PDF
    files = [
        ("image", ("cover.jpg", b"\xFF\xD8\xFF\xE0 Fake JPG Cover", "image/jpeg")),
        ("files_3d", ("miniatura.stl", b"solid miniatura\nendsolid", "application/octet-stream")),
        ("files_3d", ("manual_instrucoes.pdf", b"%PDF-1.4 Fake PDF Content for Assembly", "application/pdf")),
    ]
    data = {
        "title": "Miniatura com Manual PDF",
        "category_id": 1,
        "price": 120.00,
        "show_price": True,
        "is_featured": False,
        "order_count": 10,
        "description": "Peça de colecionador acompanhada de manual de montagem em PDF."
    }

    upload_res = client.post("/api/admin/models", data=data, files=files, cookies=cookies)
    assert upload_res.status_code == 200, upload_res.text
    res_data = upload_res.json()
    assert res_data["ok"] is True
    # parts_count deve ser 1 (peça física), pois o PDF é documento informativo
    assert res_data["parts_count"] == 1
    model_id = res_data["id"]

    # 3. Baixar arquivo empacotado e conferir se contém o STL E o PDF
    dl_res = client.get(f"/api/admin/models/{model_id}/download", cookies=cookies)
    assert dl_res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(dl_res.content), "r") as zf:
        names = zf.namelist()
        assert "miniatura.stl" in names, "miniatura.stl ausente no pacote!"
        assert "manual_instrucoes.pdf" in names, "manual_instrucoes.pdf ausente no pacote!"

    # 4. Limpeza
    del_res = client.delete(f"/api/admin/models/{model_id}", cookies=cookies)
    assert del_res.status_code == 200
    print("[OK] Upload Web: Arquivo 3D + Manual PDF empacotados com sucesso no .ZIP de impressão!")

async def test_telegram_bot_pdf_and_3d_workflow():
    """Testa envio de arquivo 3D e manual em PDF no Telegram Bot."""
    chat_id = 99887766
    auth_up = {
        "message": {
            "chat": {"id": chat_id},
            "from": {"id": chat_id},
            "text": "/auth 3aField@2026"
        }
    }
    await process_telegram_update(auth_up, "fake_token", None)

    wizard = _get_or_create_wizard(chat_id)

    # 1. Envia arquivo 3D STL
    async def fake_download_stl(token, fid, dest):
        dest.write_bytes(b"solid peca\nendsolid")
        return True, "Sucesso"

    stl_up = {
        "message": {
            "chat": {"id": chat_id},
            "from": {"id": chat_id},
            "document": {
                "file_name": "guerreira.stl",
                "file_id": "stl_fid",
                "file_size": 1500
            }
        }
    }
    with patch("app.telegram_bot.download_telegram_file", side_effect=fake_download_stl), \
         patch("app.telegram_bot.send_telegram_reply", new_callable=AsyncMock):
        await process_telegram_update(stl_up, "fake_token", None)

    # 2. Envia manual de montagem em PDF
    async def fake_download_pdf(token, fid, dest):
        dest.write_bytes(b"%PDF-1.4 Manual de Montagem da Guerreira")
        return True, "Sucesso"

    pdf_up = {
        "message": {
            "chat": {"id": chat_id},
            "from": {"id": chat_id},
            "document": {
                "file_name": "guia_montagem.pdf",
                "file_id": "pdf_fid",
                "file_size": 2500
            }
        }
    }
    with patch("app.telegram_bot.download_telegram_file", side_effect=fake_download_pdf), \
         patch("app.telegram_bot.send_telegram_reply", new_callable=AsyncMock):
        await process_telegram_update(pdf_up, "fake_token", None)

    assert len(wizard["files_3d"]) == 2
    assert any(f["name"] == "guerreira.stl" for f in wizard["files_3d"])
    assert any(f["name"] == "guia_montagem.pdf" for f in wizard["files_3d"])

    # 3. Envia foto de capa
    fake_img = wizard["temp_dir"] / "capa.jpg"
    fake_img.write_bytes(b"\xFF\xD8\xFF\xE0 Cover")
    wizard["cover_img"] = {
        "name": "capa.jpg",
        "path": fake_img,
        "file_id": "img_fid",
        "file_unique_id": "img_unique",
        "hash": "hash123"
    }
    wizard["title"] = "Guerreira Valquíria 3D"
    wizard["description"] = "Miniatura épica acompanhada de guia completo de montagem."
    wizard["category_id"] = 1
    wizard["category_name"] = "Geek & Colecionáveis"
    wizard["price"] = 99.0
    wizard["show_price"] = True

    # 4. Finaliza e publica
    with patch("app.telegram_bot.send_telegram_reply", new_callable=AsyncMock):
        await finalize_and_publish("fake_token", chat_id, wizard, with_price=True)

    # 5. Verifica no banco e no disco
    db = SessionLocal()
    saved = db.query(Model3D).filter(Model3D.title == "Guerreira Valquíria 3D").first()
    assert saved is not None
    assert saved.parts_count == 1 # Exclui o PDF da contagem de peças físicas
    assert saved.file_3d_filename.endswith(".zip")

    # Verifica se o zip contém guerreira.stl e guia_montagem.pdf
    zip_path = MODEL_DIR / saved.file_3d_filename
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        assert "guerreira.stl" in namelist
        assert "guia_montagem.pdf" in namelist

    # Limpeza
    db.delete(saved)
    db.commit()
    db.close()
    if zip_path.exists(): zip_path.unlink()

    print("[OK] Telegram Bot: Envio e empacotamento conjunto de arquivo 3D + Manual PDF 100% validado!")

if __name__ == "__main__":
    test_web_admin_pdf_bundle_upload_and_download()
    asyncio.run(test_telegram_bot_pdf_and_3d_workflow())
    print("\nTODOS OS TESTES DE SUPORTE A MANUAL PDF PASSARAM COM SUCESSO!")
