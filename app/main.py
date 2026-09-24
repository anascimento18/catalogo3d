import os
import json
import zipfile
import shutil
import uuid
from pathlib import Path
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, status, Request, Response, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

import asyncio
from app.config import (
    IMAGE_DIR,
    MODEL_DIR,
    ADMIN_ROUTE,
    ADMIN_USERNAME,
    ALLOWED_3D_EXTENSIONS,
    ALLOWED_IMG_EXTENSIONS,
    BASE_DIR,
    CATALOG_DOMAIN,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_ADMIN_CHAT_ID
)
from app.database import init_db, get_db, Model3D, Category, Order, AdminUser
from app.security import (
    get_current_admin,
    verify_session_token,
    create_session_token,
    verify_password,
    check_rate_limit,
    record_failed_attempt,
    reset_failed_attempts
)
from app.notifier import send_order_notification
from app.telegram_bot import process_telegram_update, setup_telegram_webhook, telegram_webhook_watchdog

STATIC_DIR = BASE_DIR / "app" / "static"

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializa banco de dados e seeds
    init_db()

    # Garante que a capa padrão esteja disponível no IMAGE_DIR
    default_cover_target = IMAGE_DIR / "default_3d_cover.png"
    default_cover_static = STATIC_DIR / "img" / "default_3d_cover.png"
    if not default_cover_target.exists() and default_cover_static.exists():
        try:
            shutil.copy(default_cover_static, default_cover_target)
        except Exception:
            pass

    # Inicia o Watchdog do Webhook do Telegram em background (auto-recuperação permanente)
    watchdog_task = None
    if TELEGRAM_BOT_TOKEN:
        watchdog_task = asyncio.create_task(
            telegram_webhook_watchdog(TELEGRAM_BOT_TOKEN, CATALOG_DOMAIN, interval_seconds=180)
        )
    yield
    if watchdog_task:
        watchdog_task.cancel()


app = FastAPI(
    title="Catálogo & Portfólio 3D",
    description="Plataforma de portfólio 3D com pedidos via WhatsApp e controle de acesso exclusivo",
    version="2.0.0",
    lifespan=lifespan
)

# Headers de segurança
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# Monta arquivos estáticos
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ==========================================
# ROTAS DE PÁGINAS HTML
# ==========================================

@app.get("/")
def serve_index():
    """Página principal da vitrine pública."""
    return FileResponse(STATIC_DIR / "index.html")

@app.get(ADMIN_ROUTE)
def serve_login(request: Request):
    """Página de login do administrador."""
    token = request.cookies.get("admin_session")
    if token and verify_session_token(token):
        return RedirectResponse(url="/admin", status_code=303)
    return FileResponse(STATIC_DIR / "login.html")

@app.get("/admin")
def serve_admin(request: Request):
    """Painel de gerenciamento exclusivo do administrador."""
    token = request.cookies.get("admin_session")
    if not token or not verify_session_token(token):
        return RedirectResponse(url=ADMIN_ROUTE, status_code=303)
    return FileResponse(STATIC_DIR / "admin.html")


# ==========================================
# ROTAS PÚBLICAS (ZERO-TRUST - BLINDAGEM F12)
# ==========================================

@app.get("/api/public/categories")
def get_categories(db: Session = Depends(get_db)):
    """Lista as categorias para filtros da vitrine."""
    categories = db.query(Category).order_by(Category.sort_order).all()
    return [
        {"id": c.id, "name": c.name, "slug": c.slug, "icon": c.icon}
        for c in categories
    ]

@app.get("/api/public/catalog")
def get_public_catalog(
    category_id: Optional[int] = None,
    search: Optional[str] = None,
    featured_only: bool = False,
    db: Session = Depends(get_db)
):
    """
    Retorna os modelos para a vitrine pública.
    ATENÇÃO DE SEGURANÇA: Esta rota NUNCA expõe caminhos de arquivo 3D ou links para download.
    """
    query = db.query(Model3D).filter(Model3D.is_public == True)

    if category_id:
        query = query.filter(Model3D.category_id == category_id)
    if featured_only:
        query = query.filter(Model3D.is_featured == True)
    if search:
        s = f"%{search.strip().lower()}%"
        query = query.filter(Model3D.title.ilike(s) | Model3D.description.ilike(s))

    models = query.order_by(Model3D.is_featured.desc(), Model3D.id.desc()).all()

    # Monta resposta estritamente filtrada
    results = []
    for m in models:
        # Processa galeria de fotos
        gallery_list = []
        try:
            raw_gallery = json.loads(m.gallery_images or "[]")
            gallery_list = [f"/api/public/images/{img}" for img in raw_gallery if img]
        except Exception:
            gallery_list = []
            
        primary_url = f"/api/public/images/{m.image_filename}"
        full_gallery = [primary_url] + [g for g in gallery_list if g != primary_url]

        item = {
            "id": m.id,
            "title": m.title,
            "description": m.description,
            "category_id": m.category_id,
            "category_name": m.category_name,
            "image_url": primary_url,
            "gallery": full_gallery,
            "parts_count": m.parts_count or 1,
            "file_format": m.file_format,
            "show_price": m.show_price,
            "price": m.price if m.show_price else None,
            "order_count": m.order_count,
            "is_featured": m.is_featured
        }
        results.append(item)
    return results

@app.get("/api/public/images/{filename}")
def get_image(filename: str):
    """Serve as fotos dos modelos."""
    safe_name = Path(filename).name
    file_path = IMAGE_DIR / safe_name
    if not file_path.is_file():
        fallback_path = STATIC_DIR / "img" / safe_name
        if fallback_path.is_file():
            return FileResponse(fallback_path)
        raise HTTPException(status_code=404, detail="Imagem não encontrada.")
    return FileResponse(file_path)

@app.post("/api/public/order")
async def create_order(
    request: Request,
    db: Session = Depends(get_db)
):
    """Recebe a solicitação de orçamento do visitante e notifica via WhatsApp."""
    data = await request.json()
    model_id = data.get("model_id")
    cust_name = str(data.get("customer_name", "")).strip()
    cust_phone = str(data.get("customer_phone", "")).strip()
    cust_notes = str(data.get("customer_notes", "")).strip()

    if not model_id or not cust_name or not cust_phone:
        raise HTTPException(status_code=400, detail="Nome e WhatsApp são obrigatórios.")

    model = db.query(Model3D).filter(Model3D.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Modelo não encontrado.")

    # Registra o pedido no banco
    order = Order(
        model_id=model.id,
        model_title=model.title,
        price_registered=model.price,
        show_price=model.show_price,
        customer_name=cust_name,
        customer_phone=cust_phone,
        customer_notes=cust_notes
    )
    db.add(order)
    
    # Incrementa contador de pedidos (efeito manada / marketing)
    model.order_count = (model.order_count or 0) + 1
    db.commit()

    # Despacha notificação para o WhatsApp do André (via n8n / Evolution API)
    notify_res = await send_order_notification(
        order_data={
            "customer_name": cust_name,
            "customer_phone": cust_phone,
            "customer_notes": cust_notes
        },
        model_data={
            "id": model.id,
            "title": model.title,
            "category_name": model.category_name,
            "price": model.price,
            "show_price": model.show_price,
            "image_filename": model.image_filename,
            "external_url": model.external_url or ""
        }
    )

    return {
        "ok": True,
        "message": "Solicitação enviada com sucesso! André entrará em contato via WhatsApp.",
        "wa_direct_link": notify_res.get("wa_direct_link")
    }

@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request):
    """
    Recebe atualizações do Bot do Telegram.
    Responde HTTP 200 OK imediatamente (< 2ms) e processa em background
    para evitar que o Telegram sofra timeout e envie mensagens duplicadas.
    """
    update = await request.json()
    asyncio.create_task(process_telegram_update(update, TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID))
    return {"ok": True}


# ==========================================
# ROTAS DE AUTENTICAÇÃO DO ADMINISTRADOR
# ==========================================

@app.post("/api/auth/login")
async def login(request: Request, response: Response, db: Session = Depends(get_db)):
    """Valida credenciais com proteção contra força bruta (Rate Limiting)."""
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas tentativas falhas. Aguarde 5 minutos antes de tentar novamente."
        )

    data = await request.json()
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()

    admin = db.query(AdminUser).filter(AdminUser.username == username).first()
    if not admin or not verify_password(password, admin.password_hash):
        record_failed_attempt(client_ip)
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")

    reset_failed_attempts(client_ip)
    token = create_session_token(username)

    # Define cookie HttpOnly criptografado
    response.set_cookie(
        key="admin_session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False, # Traefik gerencia SSL externamente
        max_age=86400 * 7
    )
    return {"ok": True, "message": "Login realizado com sucesso."}

@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie("admin_session")
    return {"ok": True}

@app.get("/api/auth/me")
def check_auth(current_admin: str = Depends(get_current_admin)):
    return {"authenticated": True, "username": current_admin}


# ==========================================
# ROTAS PROTEGIDAS DO ADMINISTRADOR
# ==========================================

@app.get("/api/admin/models")
def get_admin_models(
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin)
):
    """Lista completa de modelos com metadados confidenciais para o Admin."""
    models = db.query(Model3D).order_by(Model3D.id.desc()).all()
    results = []
    for m in models:
        gallery_list = []
        files_list = []
        try:
            gallery_list = json.loads(m.gallery_images or "[]")
        except Exception:
            gallery_list = []
        try:
            files_list = json.loads(m.files_3d_list or "[]")
        except Exception:
            files_list = []

        results.append({
            "id": m.id,
            "title": m.title,
            "description": m.description,
            "category_id": m.category_id,
            "category_name": m.category_name,
            "image_filename": m.image_filename,
            "gallery_images": gallery_list,
            "file_3d_filename": m.file_3d_filename,
            "external_url": m.external_url or "",
            "files_3d_list": files_list,
            "parts_count": m.parts_count or 1,
            "file_format": m.file_format,
            "file_size_bytes": m.file_size_bytes,
            "price": m.price,
            "show_price": m.show_price,
            "order_count": m.order_count,
            "is_featured": m.is_featured,
            "is_public": m.is_public,
            "created_at": m.created_at.strftime("%d/%m/%Y %H:%M") if m.created_at else ""
        })
    return results

@app.post("/api/admin/models")
async def upload_model(
    title: str = Form(...),
    category_id: int = Form(...),
    description: str = Form(""),
    price: float = Form(0.0),
    show_price: bool = Form(True),
    order_count: int = Form(15),
    is_featured: bool = Form(False),
    external_url: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    files_3d: List[UploadFile] = File(default=[]),
    file_3d: Optional[UploadFile] = File(None),
    gallery_images: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin)
):
    """Cadastro de novo modelo 3D com suporte a arquivo físico (.STL/.3MF/.ZIP) ou link de personalizador."""
    clean_url = external_url.strip() if external_url else ""
    if clean_url and not clean_url.startswith("http://") and not clean_url.startswith("https://"):
        clean_url = "https://" + clean_url

    # Consolida arquivos 3D (suporta tanto files_3d múltiplos quanto file_3d único)
    all_3d_files = [f for f in files_3d if f and f.filename]
    if file_3d and file_3d.filename and file_3d not in all_3d_files:
        all_3d_files.append(file_3d)

    if not all_3d_files and not clean_url:
        raise HTTPException(status_code=400, detail="Envie pelo menos um arquivo 3D ou informe o link do site/personalizador.")

    category = db.query(Category).filter(Category.id == category_id).first()
    category_name = category.name if category else "Geral"

    unique_id = uuid.uuid4().hex[:8]
    clean_title = "".join(c for c in title if c.isalnum() or c in ("-", "_", " ")).strip().replace(" ", "_")

    # 1. Salva Foto de Capa (Primária)
    if image and image.filename:
        ext_img = Path(image.filename).suffix.lower()
        if ext_img not in ALLOWED_IMG_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Extensão de imagem principal não suportada ({ext_img}).")
        saved_img_name = f"{clean_title}_{unique_id}_cover{ext_img}"
        target_img = IMAGE_DIR / saved_img_name
        with open(target_img, "wb") as f:
            shutil.copyfileobj(image.file, f)
    else:
        # Se não enviou imagem de capa, utiliza a imagem padrão Studio 3D
        saved_img_name = "default_3d_cover.png"

    # 2. Salva Fotos Secundárias da Galeria
    saved_gallery_filenames = []
    for idx, gal_file in enumerate(gallery_images):
        if not gal_file or not gal_file.filename:
            continue
        g_ext = Path(gal_file.filename).suffix.lower()
        if g_ext in ALLOWED_IMG_EXTENSIONS:
            g_name = f"{clean_title}_{unique_id}_gal_{idx+1}{g_ext}"
            g_target = IMAGE_DIR / g_name
            with open(g_target, "wb") as f:
                shutil.copyfileobj(gal_file.file, f)
            saved_gallery_filenames.append(g_name)

    # 3. Salva Arquivo(s) 3D ou Registra Link Externo
    parts_metadata = []
    if not all_3d_files:
        # Modelo baseado em Link Externo de Personalizador / Site
        saved_3d_name = ""
        file_size = 0
        parts_count = 1
        format_str = "LINK"
        parts_metadata = [{"name": f"Link Externo: {clean_url}", "size": 0}]
    elif len(all_3d_files) == 1:
        f_single = all_3d_files[0]
        ext_3d = Path(f_single.filename).suffix.lower()
        if ext_3d not in ALLOWED_3D_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Extensão 3D não suportada ({ext_3d}).")

        saved_3d_name = f"{clean_title}_{unique_id}{ext_3d}"
        target_3d = MODEL_DIR / saved_3d_name
        with open(target_3d, "wb") as f:
            shutil.copyfileobj(f_single.file, f)

        file_size = target_3d.stat().st_size
        parts_count = 1

        # Se for um .ZIP único, inspeciona quantas peças tem dentro
        if ext_3d == ".zip":
            try:
                with zipfile.ZipFile(target_3d, "r") as zf:
                    pieces = [n for n in zf.namelist() if any(n.lower().endswith(e) for e in ALLOWED_3D_EXTENSIONS)]
                    if pieces:
                        parts_count = len(pieces)
                        parts_metadata = [{"name": Path(p).name, "size": 0} for p in pieces]
            except Exception:
                pass
        else:
            parts_metadata = [{"name": f_single.filename, "size": file_size}]

        format_str = ext_3d.lstrip(".").upper()
    else:
        # Múltiplos arquivos 3D: salva cada um e gera um .ZIP consolidado
        saved_part_files = []
        for idx, f_part in enumerate(all_3d_files):
            p_ext = Path(f_part.filename).suffix.lower()
            if p_ext not in ALLOWED_3D_EXTENSIONS:
                continue
            safe_orig_name = Path(f_part.filename).name
            p_name = f"{clean_title}_{unique_id}_part_{idx+1}_{safe_orig_name}"
            p_target = MODEL_DIR / p_name
            with open(p_target, "wb") as f:
                shutil.copyfileobj(f_part.file, f)
            p_size = p_target.stat().st_size
            saved_part_files.append((p_target, safe_orig_name))
            parts_metadata.append({"name": safe_orig_name, "size": p_size})

        saved_3d_name = f"{clean_title}_{unique_id}_bundle.zip"
        target_zip = MODEL_DIR / saved_3d_name
        with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
            for p_path, p_orig_name in saved_part_files:
                zf.write(p_path, arcname=p_orig_name)

        file_size = target_zip.stat().st_size
        parts_count = len(parts_metadata)
        format_str = "BUNDLE ZIP"

    new_model = Model3D(
        title=title,
        description=description,
        category_id=category_id,
        category_name=category_name,
        image_filename=saved_img_name,
        gallery_images=json.dumps(saved_gallery_filenames),
        file_3d_filename=saved_3d_name,
        external_url=clean_url if clean_url else None,
        files_3d_list=json.dumps(parts_metadata),
        parts_count=parts_count,
        file_format=format_str,
        file_size_bytes=file_size,
        price=price,
        show_price=show_price,
        order_count=order_count,
        is_featured=is_featured,
        is_public=True
    )
    db.add(new_model)
    db.commit()
    db.refresh(new_model)

    return {
        "ok": True,
        "id": new_model.id,
        "title": new_model.title,
        "parts_count": parts_count,
        "gallery_count": len(saved_gallery_filenames) + 1,
        "external_url": new_model.external_url or ""
    }

@app.delete("/api/admin/models/{model_id}")
def delete_model(
    model_id: int,
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin)
):
    """Exclui o modelo e remove os arquivos do disco."""
    model = db.query(Model3D).filter(Model3D.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Modelo não encontrado.")

    # Remove arquivos físicos
    img_path = IMAGE_DIR / model.image_filename
    if img_path.exists():
        try: img_path.unlink()
        except: pass
    if model.file_3d_filename:
        file_path = MODEL_DIR / model.file_3d_filename
        if file_path.exists():
            try: file_path.unlink()
            except: pass

    db.delete(model)
    db.commit()
    return {"ok": True}

@app.patch("/api/admin/models/{model_id}")
async def update_model(
    model_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin)
):
    """Atualiza configurações de título, descrição, categoria, preço, prova social, link externo ou destaque do modelo."""
    model = db.query(Model3D).filter(Model3D.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Modelo não encontrado.")

    data = await request.json()
    if "title" in data and data["title"] is not None:
        model.title = str(data["title"]).strip()
    if "description" in data and data["description"] is not None:
        model.description = str(data["description"]).strip()
    if "external_url" in data:
        raw_url = str(data["external_url"]).strip() if data["external_url"] is not None else ""
        model.external_url = raw_url if raw_url else None
    if "category_id" in data and data["category_id"] is not None:
        cat = db.query(Category).filter(Category.id == int(data["category_id"])).first()
        if cat:
            model.category_id = cat.id
            model.category_name = cat.name
    if "price" in data and data["price"] is not None:
        model.price = float(data["price"])
    if "show_price" in data and data["show_price"] is not None:
        model.show_price = bool(data["show_price"])
    if "order_count" in data and data["order_count"] is not None:
        model.order_count = int(data["order_count"])
    if "is_featured" in data and data["is_featured"] is not None:
        model.is_featured = bool(data["is_featured"])
    if "is_public" in data and data["is_public"] is not None:
        model.is_public = bool(data["is_public"])

    db.commit()
    db.refresh(model)
    return {
        "ok": True,
        "id": model.id,
        "title": model.title,
        "description": model.description,
        "category_id": model.category_id,
        "category_name": model.category_name,
        "price": model.price,
        "external_url": model.external_url or "",
        "message": "Modelo atualizado com sucesso."
    }

@app.get("/api/admin/models/{model_id}/download")
def download_model_3d(
    model_id: int,
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin)
):
    """
    DOWNLOAD SEGURO DO ARQUIVO 3D BRUTO (.STL / .3MF) OU REDIRECIONAMENTO AO SITE ORIGINAL.
    Proteção estrita: Exige sessão ativa de Administrador.
    """
    model = db.query(Model3D).filter(Model3D.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Modelo não encontrado.")

    if model.file_3d_filename:
        target = MODEL_DIR / model.file_3d_filename
        if target.is_file():
            return FileResponse(
                target,
                media_type="application/octet-stream",
                filename=model.file_3d_filename
            )

    # Se não há arquivo físico em disco, mas há link externo cadastrado, redireciona ao site
    if model.external_url:
        return RedirectResponse(url=model.external_url, status_code=303)

    raise HTTPException(status_code=404, detail="Arquivo 3D físico não encontrado no servidor.")

@app.get("/api/admin/orders")
def get_orders(
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin)
):
    """Lista histórico de orçamentos e pedidos de clientes com links de acesso."""
    orders = db.query(Order).order_by(Order.id.desc()).limit(100).all()
    model_ids = {o.model_id for o in orders if o.model_id}
    model_map = {}
    if model_ids:
        models_data = db.query(Model3D.id, Model3D.external_url, Model3D.file_3d_filename).filter(Model3D.id.in_(model_ids)).all()
        model_map = {m[0]: {"external_url": m[1] or "", "file_3d_filename": m[2] or ""} for m in models_data}

    return [
        {
            "id": o.id,
            "model_id": o.model_id,
            "model_title": o.model_title,
            "external_url": model_map.get(o.model_id, {}).get("external_url", ""),
            "file_3d_filename": model_map.get(o.model_id, {}).get("file_3d_filename", ""),
            "price_registered": o.price_registered,
            "show_price": o.show_price,
            "customer_name": o.customer_name,
            "customer_phone": o.customer_phone,
            "customer_notes": o.customer_notes,
            "status": o.status,
            "created_at": o.created_at.strftime("%d/%m/%Y %H:%M") if o.created_at else ""
        }
        for o in orders
    ]

@app.delete("/api/admin/orders/{order_id}")
def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin)
):
    """Exclui um pedido/orçamento específico do histórico."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")
    db.delete(order)
    db.commit()
    return {"ok": True, "message": "Pedido removido do histórico com sucesso."}

@app.delete("/api/admin/orders")
def clear_all_orders(
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin)
):
    """Limpa todo o histórico de orçamentos e pedidos de teste."""
    count = db.query(Order).delete()
    db.commit()
    return {"ok": True, "deleted_count": count, "message": "Todo o histórico de orçamentos foi limpo."}

