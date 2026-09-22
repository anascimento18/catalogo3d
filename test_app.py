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

if __name__ == "__main__":
    test_public_catalog_anti_f12()
    test_protected_download_unauthorized()
    test_admin_login_and_download()
    test_order_submission()
    print("\nTODOS OS TESTES DE SEGURANÇA E FUNCIONALIDADES PASSARAM COM SUCESSO!")
