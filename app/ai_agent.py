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
    Pesquisa referências de preços e mercado no Brasil para peças de estúdios profissionais de impressão 3D.
    Filtra arquivos digitais STL ou sucatas chinesas de baixo custo.
    """
    if not query:
        return []
    try:
        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        clean_q = re.sub(r'[^\w\s]', ' ', query).strip()
        data = {"q": f"{clean_q} estatua colecionavel impressao 3d pronta estudio preco brasil mercado livre elo7"}
        with httpx.Client(timeout=3.5) as client:
            res = client.post(url, data=data, headers=headers)
            if res.status_code == 200:
                snippets = re.findall(r'<a class="result__snippet[^"]*"[^>]*>(.*?)</a>', res.text, re.DOTALL)
                cleaned = []
                for s in snippets:
                    c = re.sub(r'<[^>]+>', '', s).strip()
                    c = re.sub(r'\s+', ' ', c)
                    lower_c = c.lower()
                    # Ignora resultados que sejam apenas arquivos digitais ou downloads STL baratos
                    if any(term in lower_c for term in ["arquivo stl", "download digital", "arquivo digital", "link stl", "pack stl"]):
                        continue
                    if c:
                        cleaned.append(c)
                    if len(cleaned) >= 3:
                        break
                return cleaned
    except Exception as e:
        logger.info(f"Busca de mercado não retornou dados rápidos (prosseguindo sem busca): {e}")
    return []


def _generate_fallback(filename: str, categories: List[str]) -> Dict[str, Any]:
    """Gera dados inteligentes de fallback alinhados com precificação de alto padrão (10-15% abaixo do teto)."""
    stem = Path(filename).stem
    clean_title = re.sub(r'[_\-\.]+', ' ', stem).strip().title()
    if not clean_title:
        clean_title = "Modelo Decorativo 3D"
        
    cat = categories[0] if categories else "Decoração & Casa"
    lower_title = clean_title.lower()

    if any(w in lower_title for w in ["diorama", "estatua", "estátua", "spawn", "seiya", "batman", "marvel", "dc", "fallout", "skeletor", "resina"]):
        cat = "Geek & Colecionáveis"
        max_p = 580.0
        sug_p = 490.0 # ~15% abaixo do topo
        p_range = "R$ 490,00 - R$ 580,00"
        reason = "Peça de colecionador premium com alto nível de detalhe. Preço fixado em 15% abaixo do topo de mercado de R$ 580,00."
    elif any(w in lower_title for w in ["presépio", "presepio", "kit", "multi", "natal", "conjunto"]):
        cat = "Decoração & Casa"
        max_p = 260.0
        sug_p = 220.0 # ~15% abaixo do topo
        p_range = "R$ 220,00 - R$ 260,00"
        reason = "Kit composto com acabamento refinado. Preço fixado em 15% abaixo do teto de mercado de R$ 260,00."
    elif any(w in lower_title for w in ["luminaria", "luminária", "abajur", "shoji", "led"]):
        cat = "Decoração & Casa"
        max_p = 210.0
        sug_p = 180.0 # ~14% abaixo do topo
        p_range = "R$ 180,00 - R$ 210,00"
        reason = "Luminária de alto apelo estético. Preço fixado em 14% abaixo do teto de mercado de R$ 210,00."
    elif any(w in lower_title for w in ["sonic", "articulado", "flexi", "boneco", "figura", "toy", "brinquedo"]):
        cat = "Brinquedos & Articulados"
        max_p = 120.0
        sug_p = 100.0 # ~16% abaixo do topo
        p_range = "R$ 100,00 - R$ 120,00"
        reason = "Modelo articulado de alta precisão. Preço posicionado 16% abaixo do topo de mercado."
    else:
        max_p = 90.0
        sug_p = 78.0 # ~13% abaixo do topo
        p_range = "R$ 78,00 - R$ 90,00"
        reason = "Peça exclusiva impressa sob demanda. Preço posicionado estrategicamente 13% abaixo do topo de mercado."

    return {
        "title": clean_title,
        "category": cat,
        "description": "Modelo exclusivo impresso em 3D de alta precisão com acabamento impecável, pronto para impressionar.",
        "suggested_price": sug_p,
        "max_market_price": max_p,
        "price_range": p_range,
        "reasoning": reason
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
    ESTRATÉGIA DE PRECIFICAÇÃO:
    - É TERMINANTEMENTE PROIBIDO calcular média de preços ou usar valores de sucatas da Shopee.
    - Identifica o VALOR MÁXIMO DE MERCADO para estúdios profissionais no Brasil.
    - Fixa o PREÇO SUGERIDO ESTRITAMENTE ENTRE 10% A 15% ABAIXO DO VALOR MÁXIMO.
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

    # 1. Pesquisa rápida de referências de estúdios e mercado premium
    stem_for_search = Path(filename).stem
    search_query = re.sub(r'[_\-\.]+', ' ', stem_for_search)
    try:
        snippets = await asyncio.to_thread(search_market_pricing, search_query)
    except Exception:
        snippets = []

    market_context = ""
    if snippets:
        market_context = "\nReferências de mercado especializado no Brasil:\n" + "\n".join(f"- {s}" for s in snippets)

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

    # 3. Monta prompt com a REGRA DE OURO de precificação (10% a 15% abaixo do TOPO)
    prompt = f"""Você é o diretor comercial e precificador de um estúdio profissional de impressão 3D de ALTO PADRÃO no Brasil.

ATENÇÃO CRÍTICA SOBRE PREÇO - SIGA ESTRITAMENTE ESTAS REGRAS:
1. É TERMINANTEMENTE PROIBIDO CALCULAR MÉDIA DE MERCADO OU USAR PREÇOS BAIXOS DE ARQUIVOS DIGITAIS STL OU SUCATAS DA SHOPEE!
2. O cliente exige uma ESTRATÉGIA DE PRECIFICAÇÃO PREMIUM / TOPO DE MERCADO:
   - Você DEVE determinar o VALOR MÁXIMO REALISTA DE MERCADO ("max_market_price") praticado por estúdios de primeira linha no Brasil para esta peça pronta, impressa em alta resolução e acabada.
   - O preço sugerido ("suggested_price") DEVE ser calculado EXATAMENTE ENTRE 10% A 15% ABAIXO DO VALOR MÁXIMO (ou seja, de 85% a 90% do valor máximo).
   - "price_range" deve ser formatado como: "R$ [suggested_price] - R$ [max_market_price]" mostrando o topo de mercado.

PARÂMETROS DE MERCADO BRASILEIRO PARA PEÇAS IMPRESSAS EM 3D:
- Dioramas / Estátuas Colecionáveis / Anime / Heróis / Vilões (ex: Spawn, Seiya, Batman, Fallout, Skeletor, estátuas em resina):
  * Valor Máximo de Mercado: R$ 480,00 a R$ 900,00+
  * Preço Sugerido (10% a 15% abaixo do topo): R$ 410,00 a R$ 780,00
- Presépios Completos / Kits Multi-Peças / Conjuntos Decorativos (ex: 10 a 20 peças, kits de Natal):
  * Valor Máximo de Mercado: R$ 240,00 a R$ 380,00+
  * Preço Sugerido (10% a 15% abaixo do topo): R$ 200,00 a R$ 320,00
- Luminárias Decorativas / Peças de Design Sofisticadas (ex: Shoji, abajures geek, LED):
  * Valor Máximo de Mercado: R$ 180,00 a R$ 280,00
  * Preço Sugerido (10% a 15% abaixo do topo): R$ 150,00 a R$ 240,00
- Action Figures Articuladas / Flexis / Personagens Populares (ex: Sonic, Amy Rose, articulados médios):
  * Valor Máximo de Mercado: R$ 90,00 a R$ 150,00
  * Preço Sugerido (10% a 15% abaixo do topo): R$ 78,00 a R$ 128,00
- Fidgets / Chaveiros Premium / Miniaturas compactas:
  * Valor Máximo de Mercado: R$ 50,00 a R$ 85,00
  * Preço Sugerido (10% a 15% abaixo do topo): R$ 42,00 a R$ 72,00

Analise os dados desta peça:
- Nome do arquivo/modelo: "{filename}"
{f'- Legenda/Observação informada: "{caption}"' if caption else ''}
{f'- Link da fonte: {external_url}' if external_url else ''}
{market_context}
- Categorias disponíveis no catálogo: {json.dumps(cat_list, ensure_ascii=False)}

Suas metas obrigatórias:
1. Criar um título comercial MARQUETEIRO e chamativo em Português do Brasil (PT-BR). NUNCA deixe nomes crus como "Mood_Ghost.rar" ou em inglês se houver termo mais atraente em português.
2. Selecionar a melhor categoria existente na lista acima.
3. Redigir uma descrição persuasiva de venda com 2 a 3 frases, destacando charme visual, exclusividade e acabamento premium.
4. Definir "max_market_price" (valor teto de mercado no Brasil) e calcular "suggested_price" (número decimal com 10% a 15% de desconto sobre o teto).
5. Incluir 1 frase curta justificando o preço posicionado estrategicamente 10% a 15% abaixo do topo de mercado.

Retorne EXCLUSIVAMENTE um JSON válido com esta estrutura exata:
{{
  "title": "Nome Comercial Chamativo em Português",
  "category": "Nome exato de uma das categorias listadas",
  "description": "Descrição persuasiva curta de 2 a 3 frases.",
  "suggested_price": 490.0,
  "max_market_price": 580.0,
  "price_range": "R$ 490,00 - R$ 580,00",
  "reasoning": "Preço posicionado estrategicamente 15% abaixo do topo de mercado (R$ 580,00) para garantir alta conversão com margem máxima de estúdio premium."
}}"""

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
        "max_tokens": 2048
    }

    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=35.0) as client:
            res = await client.post(MINIMAX_API_URL, headers=headers, json=payload)
            if res.status_code == 200:
                data = res.json()
                raw_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                clean = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()
                clean = re.sub(r'```json\s*', '', clean)
                clean = re.sub(r'```\s*', '', clean).strip()

                parsed = json.loads(clean)
                
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
                    price = float(parsed.get("suggested_price") or 75.0)
                except:
                    price = 75.0

                desc = str(parsed.get("description") or "").strip()
                if not desc:
                    desc = "Modelo de alto padrão impresso em 3D sob demanda com acabamento refinado."

                max_m = parsed.get("max_market_price")
                if max_m:
                    p_range = f"R$ {price:.2f} - R$ {float(max_m):.2f}"
                else:
                    p_range = str(parsed.get("price_range") or f"R$ {price:.2f} - R$ {price*1.15:.2f}")

                reasoning = str(parsed.get("reasoning") or "Preço calculado entre 10% a 15% abaixo do teto de mercado para máxima margem e alta conversão.")

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

    return _generate_fallback(filename, cat_list)
