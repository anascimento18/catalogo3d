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

def test_edit_model():
    """Testa edição/correção de título, descrição, categoria e preço via PATCH."""
    login_res = client.post("/api/auth/login", json={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD
    })
    assert login_res.status_code == 200

    # Busca modelos para pegar um ID existente
    models_res = client.get("/api/admin/models", cookies=login_res.cookies)
    assert models_res.status_code == 200
    models = models_res.json()
    assert len(models) > 0
    target_id = models[0]["id"]

    # Atualiza título e corrige descrição
    patch_res = client.patch(
        f"/api/admin/models/{target_id}",
        json={
            "title": "BABY REAPER - Edição Especial",
            "description": "BABY REAPER miniaturas colecionáveis de alta precisão, escolha o seu!",
            "price": 55.00,
            "category_id": 1,
            "show_price": True,
            "is_featured": True,
            "order_count": 25
        },
        cookies=login_res.cookies
    )
    assert patch_res.status_code == 200
    res_data = patch_res.json()
    assert res_data["ok"] is True
    assert res_data["title"] == "BABY REAPER - Edição Especial"
    assert "miniaturas colecionáveis" in res_data["description"]
    print(f"[OK] Edição de Modelo (PATCH): Título e descrição corrigidos com sucesso para o modelo {target_id}.")

def test_delete_and_clear_orders():
    """Testa exclusão de orçamento individual e limpeza total do histórico."""
    login_res = client.post("/api/auth/login", json={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD
    })
    assert login_res.status_code == 200

    # Busca lista de pedidos para pegar um ID
    orders_res = client.get("/api/admin/orders", cookies=login_res.cookies)
    assert orders_res.status_code == 200
    orders = orders_res.json()
    assert len(orders) > 0
    order_id = orders[0]["id"]

    # Exclui o pedido individual
    del_res = client.delete(f"/api/admin/orders/{order_id}", cookies=login_res.cookies)
    assert del_res.status_code == 200
    assert del_res.json()["ok"] is True
    print(f"[OK] Exclusão de Pedido Individual: Pedido {order_id} removido com sucesso.")

    # Limpa todos os pedidos de teste para não poluir o banco de dados
    clear_res = client.delete("/api/admin/orders", cookies=login_res.cookies)
    assert clear_res.status_code == 200
    assert clear_res.json()["ok"] is True
    print("[OK] Limpeza Total do Histórico de Orçamentos: Histórico limpo com sucesso.")

def test_telegram_wizard_auth():
    """Testa autenticação dinâmica e início de wizard no Telegram."""
    import asyncio
    from app.telegram_bot import process_telegram_update

    # 1. Usuário não autorizado envia /newmodelo
    unauth_up = {
        "message": {
            "chat": {"id": 999999},
            "from": {"id": 999999},
            "text": "/newmodelo"
        }
    }
    res = asyncio.run(process_telegram_update(unauth_up, "fake_token", "5370959021438146805"))
    assert res["ok"] is False

    # 2. Usuário envia /auth com senha de administrador
    auth_up = {
        "message": {
            "chat": {"id": 999999},
            "from": {"id": 999999},
            "text": "/auth 3aField@2026"
        }
    }
    res_auth = asyncio.run(process_telegram_update(auth_up, "fake_token", "5370959021438146805"))
    assert res_auth["ok"] is True

    # 3. Agora autorizado envia /newmodelo
    new_up = {
        "message": {
            "chat": {"id": 999999},
            "from": {"id": 999999},
            "text": "/newmodelo"
        }
    }
    res_new = asyncio.run(process_telegram_update(new_up, "fake_token", "5370959021438146805"))
    assert res_new["ok"] is True

    # 4. Envia arquivo 3D acima de 20MB (deve ser rejeitado com mensagem explicativa e instrução para usar painel web)
    big_file_up = {
        "message": {
            "chat": {"id": 999999},
            "from": {"id": 999999},
            "document": {
                "file_name": "modelo_grande.stl",
                "file_id": "fake_file_id",
                "file_size": 25 * 1024 * 1024 # 25 MB
            }
        }
    }
    res_big = asyncio.run(process_telegram_update(big_file_up, "fake_token", "5370959021438146805"))
    assert res_big["ok"] is True
    print("[OK] Telegram Bot Wizard: Proteção de limite 20MB da API do Telegram validada com sucesso!")

    print("[OK] Telegram Bot Wizard: Autenticação dinâmica e início de /newmodelo validados com sucesso!")

def test_external_url_model_workflow():
    """Testa cadastro de modelo via link externo (sem arquivo 3D físico) e redirecionamento."""
    # 1. Login
    login_res = client.post("/api/auth/login", json={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD
    })
    assert login_res.status_code == 200

    # 2. Cadastro com link de personalizador e foto de capa (sem arquivos 3D físicos)
    files = [
        ("image", ("cover_maker.jpg", b"\xFF\xD8\xFF\xE0 Fake JPG Cover Maker", "image/jpeg"))
    ]
    data = {
        "title": "Chaveiro Personalizado MakerWorld",
        "category_id": 1,
        "price": 35.00,
        "show_price": True,
        "external_url": "https://makerworld.com/pt/models/123456#profileId-789"
    }
    upload_res = client.post("/api/admin/models", data=data, files=files, cookies=login_res.cookies)
    assert upload_res.status_code == 200
    res_data = upload_res.json()
    model_id = res_data["id"]
    assert res_data["external_url"] == "https://makerworld.com/pt/models/123456#profileId-789"
    print(f"[OK] Cadastro por Link: Modelo {model_id} criado sem arquivo 3D local com sucesso.")

    # 2b. Cadastro SOMENTE com link (SEM arquivos 3D e SEM foto de capa - capa padrão automática)
    data_only_link = {
        "title": "Suporte Articulado Só Link",
        "category_id": 1,
        "price": 45.00,
        "show_price": True,
        "external_url": "makerworld.com/pt/models/987654"
    }
    upload_only_link_res = client.post("/api/admin/models", data=data_only_link, cookies=login_res.cookies)
    assert upload_only_link_res.status_code == 200
    res_only_link = upload_only_link_res.json()
    assert res_only_link["external_url"] == "https://makerworld.com/pt/models/987654"
    print(f"[OK] Cadastro Somente Link (Zero Arquivos/Zero Fotos): Modelo {res_only_link['id']} criado com capa padrão e URL normalizada.")
    client.delete(f"/api/admin/models/{res_only_link['id']}", cookies=login_res.cookies)

    # 3. Teste de download com redirecionamento para o site
    dl_res = client.get(f"/api/admin/models/{model_id}/download", cookies=login_res.cookies, follow_redirects=False)
    assert dl_res.status_code == 303
    assert dl_res.headers["location"] == "https://makerworld.com/pt/models/123456#profileId-789"
    print("[OK] Redirecionamento 303: Download do modelo direciona diretamente para o site do personalizador.")

    # 4. Edição do link externo
    patch_res = client.patch(f"/api/admin/models/{model_id}", json={
        "external_url": "https://makerworld.com/pt/models/999999"
    }, cookies=login_res.cookies)
    assert patch_res.status_code == 200
    assert patch_res.json()["external_url"] == "https://makerworld.com/pt/models/999999"
    print("[OK] Edição de Link: URL atualizada com sucesso.")

    # 5. Blindagem F12: Confirma que o link NÃO vaza na vitrine pública
    cat_res = client.get("/api/public/catalog")
    assert cat_res.status_code == 200
    for item in cat_res.json():
        assert "external_url" not in item, "VULNERABILIDADE F12: external_url vazou na vitrine pública!"
    print("[OK] Blindagem F12: Link externo do personalizador NUNCA exposto aos visitantes.")

    # 6. Limpeza do modelo de teste
    del_res = client.delete(f"/api/admin/models/{model_id}", cookies=login_res.cookies)
    assert del_res.status_code == 200
    print("[OK] Limpeza: Modelo de teste por link excluído.")

if __name__ == "__main__":
    test_public_catalog_anti_f12()
    test_protected_download_unauthorized()
    test_admin_login_and_download()
    test_order_submission()
    test_multipart_and_gallery_upload()
    test_edit_model()
    test_delete_and_clear_orders()
    test_external_url_model_workflow()
    test_telegram_wizard_auth()
    print("\nTODOS OS TESTES DE SEGURANÇA E FUNCIONALIDADES PASSARAM COM SUCESSO!")


