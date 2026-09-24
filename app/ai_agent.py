import os
import re
import json
import base64
import logging
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
import httpx

from app.config import (
    MINIMAX_API_KEY,
    MINIMAX_API_URL,
    MINIMAX_MODEL
)

logger = logging.getLogger("ai_agent")

def search_market_pricing(query: str) -> List[str]:
    """
    Pesquisa rápida de preços e mercado no Brasil para peças similares impressas em 3D.
    Utiliza DuckDuckGo de forma ultraleve sem sobrecarregar ou atrasar a resposta.
    """
    if not query:
        return []
    try:
        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        clean_q = re.sub(r'[^\w\s]', ' ', query).strip()
        data = {"q": f"{clean_q} impressao 3d preco shopee mercado livre brasil"}
        with httpx.Client(timeout=3.5) as client:
            res = client.post(url, data=data, headers=headers)
            if res.status_code == 200:
                snippets = re.findall(r'<a class="result__snippet[^"]*"[^>]*>(.*?)</a>', res.text, re.DOTALL)
                cleaned = []
                for s in snippets[:3]:
                    c = re.sub(r'<[^>]+>', '', s).strip()
                    c = re.sub(r'\s+', ' ', c)
                    if c:
                        cleaned.append(c)
                return cleaned
    except Exception as e:
        logger.info(f"Busca de mercado não retornou dados rápidos (prosseguindo sem busca): {e}")
    return []


def _generate_fallback(filename: str, categories: List[str]) -> Dict[str, Any]:
    """Gera dados inteligentes de fallback caso a IA esteja temporariamente indisponível."""
    stem = Path(filename).stem
    clean_title = re.sub(r'[_\-\.]+', ' ', stem).strip().title()
    if not clean_title:
        clean_title = "Modelo Decorativo 3D"
        
    cat = categories[0] if categories else "Decoração & Casa"
    for c in categories:
        if any(w.lower() in clean_title.lower() for w in ["geek", "game", "pokemon", "mario", "anime", "action", "ghost", "fantasma", "heroi", "star"]):
            if "geek" in c.lower():
                cat = c
                break
        elif any(w.lower() in clean_title.lower() for w in ["suporte", "organizador", "base", "case", "adaptador"]):
            if "suporte" in c.lower() or "utilidade" in c.lower():
                cat = c
                break
        elif any(w.lower() in clean_title.lower() for w in ["vaso", "abajur", "luminaria", "quadro", "casa"]):
            if "decoração" in c.lower() or "casa" in c.lower():
                cat = c
                break

    return {
        "title": clean_title,
        "category": cat,
        "description": "Modelo 3D de alta qualidade com acabamento primoroso e encaixes precisos. Ideal para decoração ou uso diário.",
        "suggested_price": 45.0,
        "price_range": "R$ 35,00 - R$ 60,00",
        "reasoning": "Estimativa padrão com base na média de mercado para itens impressos em 3D sob demanda."
    }


async def analyze_model_proposal(
    image_path: Optional[Path],
    filename: str,
    caption: str = "",
    external_url: Optional[str] = None,
    categories: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Analisa a imagem e dados do modelo 3D usando o MiniMax (MiniMax-M3 com visão e raciocínio).
    Retorna:
    - title: Título comercial atrativo em português (PT-BR)
    - category: Nome da categoria que melhor se encaixa
    - description: Descrição curta de venda (2-3 frases)
    - suggested_price: Preço sugerido em Reais (float)
    - price_range: Faixa de preço de mercado (str)
    - reasoning: Justificativa comercial resumida
    """
    cat_list = categories or [
        "Decoração & Casa",
        "Peças Técnicas & Reposição",
        "Geek & Colecionáveis",
        "Cosplay & Adereços",
        "Brinquedos & Articulados",
        "Litofanias & Personalizados",
        "Suportes & Utilidades"
    ]

    if not MINIMAX_API_KEY:
        logger.warning("MINIMAX_API_KEY não configurada. Usando fallback estruturado.")
        return _generate_fallback(filename, cat_list)

    # 1. Pesquisa rápida de mercado em thread pool para não travar o loop assíncrono
    stem_for_search = Path(filename).stem
    search_query = re.sub(r'[_\-\.]+', ' ', stem_for_search)
    try:
        snippets = await asyncio.to_thread(search_market_pricing, search_query)
    except Exception:
        snippets = []

    market_context = ""
    if snippets:
        market_context = "\nResultados encontrados no mercado brasileiro (Shopee/Mercado Livre):\n" + "\n".join(f"- {s}" for s in snippets)

    # 2. Prepara imagem em base64 se disponível
    image_b64 = None
    media_type = "image/jpeg"
    if image_path and image_path.is_file():
        try:
            ext = image_path.suffix.lower()
            if ext == ".png":
                media_type = "image/png"
            elif ext == ".webp":
                media_type = "image/webp"
            with open(image_path, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.error(f"Erro ao codificar imagem em base64: {e}")

    # 3. Monta prompt de engenharia para marketing de impressão 3D
    prompt = f"""Você é o especialista de marketing e precificação de um estúdio profissional de impressão 3D no Brasil.
Analise os dados desta peça:
- Nome do arquivo: "{filename}"
{f'- Legenda/Observação informada: "{caption}"' if caption else ''}
{f'- Link da fonte: {external_url}' if external_url else ''}
{market_context}
- Categorias disponíveis no catálogo: {json.dumps(cat_list, ensure_ascii=False)}

Suas metas obrigatórias:
1. Criar um título comercial MARQUETEIRO e chamativo em Português do Brasil (PT-BR). NUNCA deixe nomes crus como "Mood_Ghost.rar" ou em inglês se houver termo mais atraente em português.
2. Selecionar a melhor categoria existente na lista acima.
3. Redigir uma descrição persuasiva de venda com 2 a 3 frases, destacando charme visual, utilidade ou acabamento premium.
4. Sugerir um preço justo de venda em Reais (BRL) para o produto pronto impresso (número decimal), mais a faixa estimada de mercado (ex: "R$ 35,00 - R$ 55,00").
5. Incluir 1 frase curta justificando o preço e apelo comercial.

Retorne EXCLUSIVAMENTE um JSON válido com esta estrutura exata:
{{
  "title": "Nome Comercial Chamativo em Português",
  "category": "Nome exato de uma das categorias listadas",
  "description": "Descrição persuasiva curta de 2 a 3 frases.",
  "suggested_price": 45.0,
  "price_range": "R$ 35,00 - R$ 55,00",
  "reasoning": "Justificativa comercial curta."
}}"""

    # 4. Constrói conteúdo da mensagem
    content_list = [{"type": "text", "text": prompt}]
    if image_b64:
        content_list.append({
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{image_b64}"}
        })

    payload = {
        "model": MINIMAX_MODEL,
        "messages": [
            {
                "role": "user",
                "content": content_list
            }
        ],
        "max_tokens": 1000
    }

    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json"
    }

    # 5. Executa requisição com timeout resiliente
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            res = await client.post(MINIMAX_API_URL, headers=headers, json=payload)
            if res.status_code == 200:
                data = res.json()
                raw_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                # Remove bloco <think>...</think> gerado pelo MiniMax-M3
                clean = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()
                # Remove marcações markdown
                clean = re.sub(r'```json\s*', '', clean)
                clean = re.sub(r'```\s*', '', clean).strip()

                parsed = json.loads(clean)
                
                # Valida e normaliza campos
                title = str(parsed.get("title") or "").strip()
                if not title:
                    title = _generate_fallback(filename, cat_list)["title"]
                    
                cat = str(parsed.get("category") or "").strip()
                matched_cat = cat_list[0]
                for c in cat_list:
                    if c.lower() in cat.lower() or cat.lower() in c.lower():
                        matched_cat = c
                        break

                try:
                    price = float(parsed.get("suggested_price") or 45.0)
                except:
                    price = 45.0

                desc = str(parsed.get("description") or "").strip()
                if not desc:
                    desc = "Modelo de alto padrão impresso em 3D com acabamento refinado."

                p_range = str(parsed.get("price_range") or f"R$ {price*0.8:.2f} - R$ {price*1.3:.2f}")
                reasoning = str(parsed.get("reasoning") or "Preço calculado com base no tamanho, acabamento e demanda de mercado.")

                return {
                    "title": title,
                    "category": matched_cat,
                    "description": desc,
                    "suggested_price": round(price, 2),
                    "price_range": p_range,
                    "reasoning": reasoning
                }
            else:
                logger.error(f"Erro na API MiniMax: HTTP {res.status_code} - {res.text}")
    except Exception as e:
        logger.error(f"Exceção ao chamar IA MiniMax: {e}")

    # Fallback transparente em caso de erro na rede ou resposta inválida
    return _generate_fallback(filename, cat_list)
