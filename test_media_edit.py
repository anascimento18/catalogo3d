import io
import json
import zipfile
from fastapi.testclient import TestClient
from pathlib import Path

from app.main import app, MODEL_DIR, IMAGE_DIR
from app.config import ADMIN_USERNAME, ADMIN_PASSWORD

client = TestClient(app)

def test_full_media_edit_lifecycle():
    # 1. Login
    login_res = client.post("/api/auth/login", json={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD
    })
    assert login_res.status_code == 200
    cookies = login_res.cookies

    # 2. Criar modelo base com 1 peça STL e sem fotos de galeria
    files = [
        ("image", ("cover1.jpg", b"\xFF\xD8\xFF\xE0 Test Cover 1", "image/jpeg")),
        ("files_3d", ("peca_teste.stl", b"solid peca\nendsolid", "application/octet-stream")),
    ]
    data = {
        "title": "Modelo Teste Edicao Midia",
        "category_id": 1,
        "price": 89.90,
        "show_price": True,
        "is_featured": False,
        "order_count": 5,
        "description": "Descricao inicial"
    }

    create_res = client.post("/api/admin/models", data=data, files=files, cookies=cookies)
    assert create_res.status_code == 200
    model_id = create_res.json()["id"]

    try:
        # 3. Testar troca de foto de capa (POST /cover)
        new_cover_file = ("image", ("nova_capa.png", b"\x89PNG\r\n\x1a\n Test New PNG Cover", "image/png"))
        cover_res = client.post(f"/api/admin/models/{model_id}/cover", files=[new_cover_file], cookies=cookies)
        assert cover_res.status_code == 200
        cover_data = cover_res.json()
        assert cover_data["ok"] is True
        assert "nova_capa" in cover_data["image_filename"] or "Modelo_Teste" in cover_data["image_filename"]
        new_cover_path = IMAGE_DIR / cover_data["image_filename"]
        assert new_cover_path.exists()

        # 4. Testar adição de fotos à galeria (POST /gallery)
        gal_files = [
            ("images", ("foto_gal_1.jpg", b"\xFF\xD8\xFF\xE0 Gal 1", "image/jpeg")),
            ("images", ("foto_gal_2.jpg", b"\xFF\xD8\xFF\xE0 Gal 2", "image/jpeg"))
        ]
        gal_res = client.post(f"/api/admin/models/{model_id}/gallery", files=gal_files, cookies=cookies)
        assert gal_res.status_code == 200
        gal_data = gal_res.json()
        assert gal_data["ok"] is True
        assert len(gal_data["gallery_images"]) == 2
        first_gal_img = gal_data["gallery_images"][0]
        assert (IMAGE_DIR / first_gal_img).exists()

        # 5. Testar exclusão de uma foto da galeria (DELETE /gallery/{filename})
        del_gal_res = client.delete(f"/api/admin/models/{model_id}/gallery/{first_gal_img}", cookies=cookies)
        assert del_gal_res.status_code == 200
        del_gal_data = del_gal_res.json()
        assert del_gal_data["ok"] is True
        assert len(del_gal_data["gallery_images"]) == 1
        assert not (IMAGE_DIR / first_gal_img).exists()

        # 6. Testar anexação de manual em PDF a um modelo que tinha STL único (POST /pdf)
        # Deve empacotar STL existente + novo PDF em um .ZIP (bundle)
        pdf_file = ("pdf_file", ("manual_montagem.pdf", b"%PDF-1.4 Fake PDF Assembly Manual", "application/pdf"))
        pdf_res = client.post(f"/api/admin/models/{model_id}/pdf", files=[pdf_file], cookies=cookies)
        assert pdf_res.status_code == 200
        pdf_data = pdf_res.json()
        assert pdf_data["ok"] is True
        assert pdf_data["pdf_name"] == "manual_montagem.pdf"
        assert pdf_data["parts_count"] == 1  # 1 peça impressa, PDF não conta como peça 3D

        # 7. Baixar modelo e inspecionar zip: deve conter STL E PDF
        dl_res = client.get(f"/api/admin/models/{model_id}/download", cookies=cookies)
        assert dl_res.status_code == 200
        with zipfile.ZipFile(io.BytesIO(dl_res.content), "r") as zf:
            names = zf.namelist()
            assert any(n.endswith(".stl") for n in names)
            assert "manual_montagem.pdf" in names

        # 8. Testar substituição do PDF (POST /pdf com novo arquivo)
        new_pdf_file = ("pdf_file", ("manual_v2.pdf", b"%PDF-1.4 Manual v2 Content", "application/pdf"))
        rep_res = client.post(f"/api/admin/models/{model_id}/pdf", files=[new_pdf_file], cookies=cookies)
        assert rep_res.status_code == 200
        rep_data = rep_res.json()
        assert rep_data["pdf_name"] == "manual_v2.pdf"

        # Conferir no download se o antigo foi substituído pelo novo
        dl_res2 = client.get(f"/api/admin/models/{model_id}/download", cookies=cookies)
        assert dl_res2.status_code == 200
        with zipfile.ZipFile(io.BytesIO(dl_res2.content), "r") as zf:
            names = zf.namelist()
            assert "manual_v2.pdf" in names
            assert "manual_montagem.pdf" not in names

        # 9. Testar remoção do PDF (DELETE /pdf)
        del_pdf_res = client.delete(f"/api/admin/models/{model_id}/pdf", cookies=cookies)
        assert del_pdf_res.status_code == 200
        del_pdf_data = del_pdf_res.json()
        assert del_pdf_data["ok"] is True
        assert not any(p.get("name", "").endswith(".pdf") for p in del_pdf_data["files_3d_list"])

        # Conferir no download se não há mais PDF no pacote
        dl_res3 = client.get(f"/api/admin/models/{model_id}/download", cookies=cookies)
        assert dl_res3.status_code == 200
        with zipfile.ZipFile(io.BytesIO(dl_res3.content), "r") as zf:
            names = zf.namelist()
            assert not any(n.endswith(".pdf") for n in names)
            assert any(n.endswith(".stl") for n in names)

        # 10. Testar restauração da capa para default (POST /cover/reset)
        reset_res = client.post(f"/api/admin/models/{model_id}/cover/reset", cookies=cookies)
        assert reset_res.status_code == 200
        assert reset_res.json()["image_filename"] == "default_3d_cover.png"

        print("[OK] Todos os testes de edição de mídias (Capa, Galeria e PDF) passaram com 100% de sucesso!")

    finally:
        # Limpeza do modelo criado
        client.delete(f"/api/admin/models/{model_id}", cookies=cookies)

if __name__ == "__main__":
    test_full_media_edit_lifecycle()
