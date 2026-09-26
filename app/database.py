import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from app.config import DATABASE_URL, ADMIN_USERNAME, ADMIN_PASSWORD

# Configuração do Engine com Normalização de Dialeto PostgreSQL
db_url = DATABASE_URL
connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}

if "sqlite" not in db_url:
    # Corrige prefixo legado postgres://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    
    # Se o driver não foi explicitado (ex: postgresql://user:pass@host:5432/db)
    if db_url.startswith("postgresql://") and not db_url.startswith("postgresql+"):
        try:
            import psycopg2
            db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        except ImportError:
            try:
                import psycopg
                db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
            except ImportError:
                pass

engine = create_engine(db_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    slug = Column(String(100), nullable=False, unique=True)
    icon = Column(String(50), default="box")
    sort_order = Column(Integer, default=0)

class Model3D(Base):
    __tablename__ = "models"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    category_name = Column(String(100), default="Geral")
    
    # Arquivos (Salvos no volume em disco ou link de site/personalizador)
    image_filename = Column(String(255), nullable=False)   # Foto de Capa (Primária)
    gallery_images = Column(Text, default="[]")             # Array JSON de fotos adicionais da galeria
    file_3d_filename = Column(String(255), nullable=True, default="") # Arquivo 3D ou pacote .ZIP com todas as peças
    external_url = Column(String(500), nullable=True)       # Link direto do site/personalizador original (opcional)
    files_3d_list = Column(Text, default="[]")              # Array JSON com cada arquivo 3D do projeto
    parts_count = Column(Integer, default=1)                # Quantidade de peças componentes
    file_format = Column(String(20), default="STL")
    file_size_bytes = Column(Integer, default=0)
    
    # Lógica de Vendas e Marketing
    price = Column(Float, default=0.0)
    show_price = Column(Boolean, default=True)  # True = mostra preço; False = 'Sob Consulta'
    order_count = Column(Integer, default=15)    # Prova social para marketing
    is_featured = Column(Boolean, default=False) # Para a seção 'Mais Pedidos'
    is_public = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, nullable=False)
    model_title = Column(String(200), nullable=False)
    price_registered = Column(Float, default=0.0)
    show_price = Column(Boolean, default=True)
    
    customer_name = Column(String(150), nullable=False)
    customer_phone = Column(String(50), nullable=False)
    customer_notes = Column(Text, default="")
    
    status = Column(String(50), default="Pendente")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class AdminUser(Base):
    __tablename__ = "admin_users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
    
    # Migrações automáticas de colunas se faltarem
    with engine.connect() as conn:
        for col, col_type, default in [
            ("gallery_images", "TEXT", "'[]'"),
            ("files_3d_list", "TEXT", "'[]'"),
            ("parts_count", "INTEGER", "1"),
            ("external_url", "VARCHAR(500)", "NULL"),
        ]:
            try:
                # Sintaxe PostgreSQL
                conn.execute(text(f"ALTER TABLE models ADD COLUMN IF NOT EXISTS {col} {col_type} DEFAULT {default};"))
                conn.commit()
            except Exception:
                try:
                    # Sintaxe SQLite
                    conn.execute(text(f"ALTER TABLE models ADD COLUMN {col} {col_type} DEFAULT {default};"))
                    conn.commit()
                except Exception:
                    pass
                
    db = SessionLocal()
    try:
        # Seed de categorias padrão se não existirem
        if db.query(Category).count() == 0:
            default_categories = [
                Category(name="Decoração & Casa", slug="decoracao", icon="home", sort_order=1),
                Category(name="Religioso", slug="religioso", icon="cross", sort_order=2),
                Category(name="Peças Técnicas & Reposição", slug="tecnicas", icon="settings", sort_order=3),
                Category(name="Geek & Colecionáveis", slug="geek", icon="gamepad-2", sort_order=4),
                Category(name="Cosplay & Adereços", slug="cosplay", icon="shield", sort_order=5),
                Category(name="Brinquedos & Articulados", slug="brinquedos", icon="smile", sort_order=6),
                Category(name="Litofanias & Personalizados", slug="litofanias", icon="sparkles", sort_order=7),
                Category(name="Suportes & Utilidades", slug="utilidades", icon="wrench", sort_order=8),
            ]
            db.add_all(default_categories)
            db.commit()

        # Seed do usuário administrador inicial
        from app.security import hash_password, verify_password
        admin = db.query(AdminUser).filter_by(username=ADMIN_USERNAME).first()
        if not admin:
            new_admin = AdminUser(
                username=ADMIN_USERNAME,
                password_hash=hash_password(ADMIN_PASSWORD)
            )
            db.add(new_admin)
            db.commit()
        else:
            if "$" not in admin.password_hash or not verify_password(ADMIN_PASSWORD, admin.password_hash):
                admin.password_hash = hash_password(ADMIN_PASSWORD)
                db.commit()
    finally:
        db.close()
