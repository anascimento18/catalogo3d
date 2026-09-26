from fastapi.testclient import TestClient
from pathlib import Path
import json

from app.main import app, IMAGE_DIR, MODEL_DIR
from app.database import SessionLocal, Model3D, Category

client = TestClient(app)

def test_bulk_delete_endpoint():
    db = SessionLocal()
    cat = db.query(Category).first()
    if not cat:
        cat = Category(name="Teste", icon="box")
        db.add(cat)
        db.commit()
        db.refresh(cat)

    # 1. Cria 2 arquivos de teste
    test_img1 = IMAGE_DIR / "bulk_test_img1.png"
    test_img1.write_text("dummy img 1")
    test_3d1 = MODEL_DIR / "bulk_test_3d1.stl"
    test_3d1.write_text("dummy 3d 1")

    test_img2 = IMAGE_DIR / "bulk_test_img2.png"
    test_img2.write_text("dummy img 2")
    test_3d2 = MODEL_DIR / "bulk_test_3d2.stl"
    test_3d2.write_text("dummy 3d 2")

    # 2. Cria 2 modelos no banco
    m1 = Model3D(
        title="Modelo Teste Bulk 1",
        description="Desc 1",
        category_id=cat.id,
        price=50.0,
        show_price=True,
        image_filename=test_img1.name,
        file_3d_filename=test_3d1.name,
        file_format="STL"
    )
    m2 = Model3D(
        title="Modelo Teste Bulk 2",
        description="Desc 2",
        category_id=cat.id,
        price=75.0,
        show_price=True,
        image_filename=test_img2.name,
        file_3d_filename=test_3d2.name,
        file_format="STL"
    )
    db.add(m1)
    db.add(m2)
    db.commit()
    db.refresh(m1)
    db.refresh(m2)

    id1, id2 = m1.id, m2.id

    # 3. Autentica no admin
    from app.config import ADMIN_USERNAME, ADMIN_PASSWORD
    login_res = client.post("/api/auth/login", json={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD
    })
    assert login_res.status_code == 200
    cookies = login_res.cookies

    # 4. Executa chamada de bulk-delete
    res = client.post("/api/admin/models/bulk-delete", json={"model_ids": [id1, id2]}, cookies=cookies)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ok"] is True
    assert data["deleted_count"] == 2

    # 5. Verifica se saíram do banco
    db.expire_all()
    check1 = db.query(Model3D).filter(Model3D.id == id1).first()
    check2 = db.query(Model3D).filter(Model3D.id == id2).first()
    assert check1 is None
    assert check2 is None

    # 6. Verifica se arquivos foram limpos do disco
    assert not test_img1.exists()
    assert not test_3d1.exists()
    assert not test_img2.exists()
    assert not test_3d2.exists()

    db.close()
    print("\n[OK] Teste de Exclusão em Massa (Bulk Delete) passou com 100% de sucesso!")

if __name__ == "__main__":
    test_bulk_delete_endpoint()
