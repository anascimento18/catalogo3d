-- ============================================================
-- SCRIPT DE INICIALIZAÇÃO DO BANCO POSTGRESQL (postgreslink)
-- Banco de Dados: catalogo3d
-- ============================================================

-- 1. Criação do Banco de Dados (execute conectado como postgres)
-- CREATE DATABASE catalogo3d;

-- Conecte-se ao banco catalogo3d antes de executar as tabelas abaixo:
-- \c catalogo3d;

-- 2. Tabela de Categorias
CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    slug VARCHAR(100) NOT NULL UNIQUE,
    icon VARCHAR(50) DEFAULT 'box',
    sort_order INTEGER DEFAULT 0
);

-- 3. Tabela de Modelos 3D
CREATE TABLE IF NOT EXISTS models (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description TEXT DEFAULT '',
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    category_name VARCHAR(100) DEFAULT 'Geral',
    image_filename VARCHAR(255) NOT NULL,
    file_3d_filename VARCHAR(255) NOT NULL,
    file_format VARCHAR(20) DEFAULT 'STL',
    file_size_bytes BIGINT DEFAULT 0,
    price DOUBLE PRECISION DEFAULT 0.0,
    show_price BOOLEAN DEFAULT TRUE,
    order_count INTEGER DEFAULT 15,
    is_featured BOOLEAN DEFAULT FALSE,
    is_public BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc')
);

-- 4. Tabela de Pedidos / Leads
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    model_id INTEGER NOT NULL,
    model_title VARCHAR(200) NOT NULL,
    price_registered DOUBLE PRECISION DEFAULT 0.0,
    show_price BOOLEAN DEFAULT TRUE,
    customer_name VARCHAR(150) NOT NULL,
    customer_phone VARCHAR(50) NOT NULL,
    customer_notes TEXT DEFAULT '',
    status VARCHAR(50) DEFAULT 'Pendente',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc')
);

-- 5. Tabela de Administradores
CREATE TABLE IF NOT EXISTS admin_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc')
);

-- 6. Carga Inicial de Categorias
INSERT INTO categories (name, slug, icon, sort_order) VALUES
('Decoração & Casa', 'decoracao', 'home', 1),
('Peças Técnicas & Reposição', 'tecnicas', 'settings', 2),
('Geek & Colecionáveis', 'geek', 'gamepad-2', 3),
('Cosplay & Adereços', 'cosplay', 'shield', 4),
('Brinquedos & Articulados', 'brinquedos', 'smile', 5),
('Litofanias & Personalizados', 'litofanias', 'sparkles', 6),
('Suportes & Utilidades', 'utilidades', 'wrench', 7)
ON CONFLICT (slug) DO NOTHING;

-- 7. Carga do Usuário Administrador Inicial (andre / 3aField@2026)
-- Hash PBKDF2 correspondente a '3aField@2026'
INSERT INTO admin_users (username, password_hash) VALUES
('andre', 'e03fae83f2a893cb997a488f78bdfba4$6087754d924168019e31d3f5e55e8876fe602958fbc8d6268846c92d52eb93e0')
ON CONFLICT (username) DO NOTHING;
