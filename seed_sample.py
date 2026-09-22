import shutil
from pathlib import Path
from app.database import init_db, SessionLocal, Model3D, Category
from app.config import IMAGE_DIR, MODEL_DIR

def seed_demo_data():
    init_db()
    db = SessionLocal()
    try:
        if db.query(Model3D).count() == 0:
            # Cria arquivos dummy para demonstração imediata
            sample_stl_path = MODEL_DIR / "vaso_facetado_sample.stl"
            sample_stl_path.write_bytes(b"solid sample\nfacet normal 0 0 0\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 1 1 0\nendloop\nendfacet\nendsolid sample")

            sample_3mf_path = MODEL_DIR / "engrenagem_helicoidal_sample.3mf"
            sample_3mf_path.write_bytes(b"PK\x03\x04\x14\x00\x00\x003D_MANUFACTURING_FORMAT_SAMPLE")

            # Cria SVGs convertidos em imagem ou placeholder visual de alta qualidade
            img_vaso = IMAGE_DIR / "vaso_facetado.jpg"
            img_engrenagem = IMAGE_DIR / "engrenagem.jpg"

            # Copia uma foto existente se houver ou cria dummy
            photo_src = Path("C:/Users/AndreNascimento/Downloads/cnh.jpg")
            if photo_src.exists():
                shutil.copy(photo_src, img_vaso)
                shutil.copy(photo_src, img_engrenagem)
            else:
                img_vaso.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\xff\xd9")
                img_engrenagem.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\xff\xd9")

            m1 = Model3D(
                title="Vaso Geométrico Facetado",
                description="Design minimalista contemporâneo com faces poligonais. Ideal para decoração de interiores, fabricado em filamento PLA premium com acabamento acetinado.",
                category_id=1,
                category_name="Decoração & Casa",
                image_filename="vaso_facetado.jpg",
                file_3d_filename="vaso_facetado_sample.stl",
                file_format="STL",
                file_size_bytes=1024 * 450,
                price=65.0,
                show_price=True,
                order_count=42,
                is_featured=True,
                is_public=True
            )

            m2 = Model3D(
                title="Engrenagem Helicoidal de Precisão",
                description="Componente mecânico para substituição e prototipagem industrial. Projetado com ângulo de dente otimizado para alta transferência de torque e baixo atrito.",
                category_id=2,
                category_name="Peças Técnicas & Reposição",
                image_filename="engrenagem.jpg",
                file_3d_filename="engrenagem_helicoidal_sample.3mf",
                file_format="3MF",
                file_size_bytes=1024 * 820,
                price=110.0,
                show_price=False,  # Sob consulta!
                order_count=19,
                is_featured=True,
                is_public=True
            )

            db.add_all([m1, m2])
            db.commit()
            print("Demonstração inicial cadastrada com sucesso!")
    finally:
        db.close()

if __name__ == "__main__":
    seed_demo_data()
