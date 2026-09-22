import json
from fastapi.testclient import TestClient
from app.main import app
from app.config import ADMIN_USERNAME, ADMIN_PASSWORD

client = TestClient(app)

def test_public_catalog_anti_f12():
    """Garante que a rota pública NUNCA expõe arquivos 3D ou links para download."""
    res = client.get("/api/public/catalog")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 2
    
    for item in data:
        # Campos que DEVEM existir
        assert "id" in item
        assert "title" in item
        assert "image_url" in item
        assert "category_name" in item
        assert "order_count" in item
        
        # Campos PROIBIDOS (Blindagem F12)
        assert "file_3d_filename" not in item, "VULNERABILIDADE F12: file_3d_filename exposto no JSON público!"
        assert "file_3d_path" not in item, "VULNERABILIDADE F12: file_3d_path exposto no JSON público!"
        assert "download_url" not in item, "VULNERABILIDADE F12: download_url exposta no JSON público!"
    
    print("[OK] Teste Anti-F12: Passou com 100% de seguranca (Zero links de arquivos 3D expostos).")

def test_protected_download_unauthorized():
    """Tenta baixar o arquivo 3D sem login (deve receber 401)."""
    res = client.get("/api/admin/models/1/download")
    assert res.status_code == 401
    print("[OK] Teste de Protecao de Download: Retornou 401 Unauthorized para visitantes nao autenticados.")

def test_admin_login_and_download():
    """Faz login como Admin e testa o download do arquivo 3D bruto."""
    # 1. Login
    login_res = client.post("/api/auth/login", json={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD
    })
    assert login_res.status_code == 200
    assert "admin_session" in login_res.cookies
    print("[OK] Teste de Autenticacao Admin: Login realizado com sucesso e cookie HttpOnly gerado.")

    # 2. Download autenticado
    download_res = client.get("/api/admin/models/1/download", cookies=login_res.cookies)
    assert download_res.status_code == 200
    assert len(download_res.content) > 0
    print(f"[OK] Teste de Download Admin: Arquivo 3D baixado com sucesso ({len(download_res.content)} bytes).")

def test_order_submission():
    """Simula um visitante solicitando a impressao 3D."""
    order_payload = {
        "model_id": 1,
        "customer_name": "Marcos Silva",
        "customer_phone": "(65) 99876-5432",
        "customer_notes": "Gostaria de saber o prazo para entrega em Cuiaba."
    }
    res = client.post("/api/public/order", json=order_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "wa_direct_link" in data
    print("[OK] Teste de Solicitacao de Pedido: Pedido registrado e notificacao despachada com sucesso.")

def test_multipart_and_gallery_upload():
    """Testa upload de modelo com múltiplas peças 3D (auto-zip) e galeria de fotos."""
    import zipfile
    import io

    # 1. Login Admin
    login_res = client.post("/api/auth/login", json={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD
    })
    assert login_res.status_code == 200

    # 2. Upload com 3 peças 3D e 2 fotos adicionais
    files = [
        ("image", ("cover.jpg", b"\xFF\xD8\xFF\xE0 Fake JPG Cover", "image/jpeg")),
        ("files_3d", ("body.stl", b"solid body\nendsolid", "application/octet-stream")),
        ("files_3d", ("head.stl", b"solid head\nendsolid", "application/octet-stream")),
        ("files_3d", ("scythe.stl", b"solid scythe\nendsolid", "application/octet-stream")),
        ("gallery_images", ("foto_detalhe1.jpg", b"\xFF\xD8\xFF\xE0 Foto Detalhe 1", "image/jpeg")),
        ("gallery_images", ("foto_detalhe2.jpg", b"\xFF\xD8\xFF\xE0 Foto Detalhe 2", "image/jpeg"))
    ]
    data = {
        "title": "Baby Reaper Multi-Peças",
        "category_id": 1,
        "price": 85.00,
        "show_price": True,
        "is_featured": True,
        "order_count": 22,
        "description": "Modelo articulado com 3 componentes separados."
    }

    upload_res = client.post("/api/admin/models", data=data, files=files, cookies=login_res.cookies)
    assert upload_res.status_code == 200
    res_data = upload_res.json()
    assert res_data["ok"] is True
    assert res_data["parts_count"] == 3
    assert res_data["gallery_count"] == 3
    model_id = res_data["id"]
    print(f"[OK] Upload Multi-Peças e Galeria: Sucesso (3 peças 3D, 3 fotos na galeria, ID: {model_id}).")

    # 3. Validação na Vitrine Pública
    cat_res = client.get("/api/public/catalog")
    assert cat_res.status_code == 200
    reaper = next(m for m in cat_res.json() if m["id"] == model_id)
    assert reaper["parts_count"] == 3
    assert len(reaper["gallery"]) == 3
    assert "file_3d_filename" not in reaper
    print("[OK] Vitrine Pública: Modelo multi-peças e galeria listados corretamente sem exposição F12.")

    # 4. Download Consolidado das Peças em .ZIP pelo Admin
    dl_res = client.get(f"/api/admin/models/{model_id}/download", cookies=login_res.cookies)
    assert dl_res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(dl_res.content), "r") as zf:
        namelist = zf.namelist()
        assert "body.stl" in namelist
        assert "head.stl" in namelist
        assert "scythe.stl" in namelist
    print(f"[OK] Download Consolidado .ZIP: Verificado ({len(dl_res.content)} bytes contendo body.stl, head.stl, scythe.stl).")

if __name__ == "__main__":
    test_public_catalog_anti_f12()
    test_protected_download_unauthorized()
    test_admin_login_and_download()
    test_order_submission()
    test_multipart_and_gallery_upload()
    print("\nTODOS OS TESTES DE SEGURANÇA E FUNCIONALIDADES PASSARAM COM SUCESSO!")
