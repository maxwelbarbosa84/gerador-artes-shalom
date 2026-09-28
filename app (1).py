from __future__ import annotations

import io
import json
import os
import re
import unicodedata
from urllib.parse import urljoin, urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

LANCZOS = Image.Resampling.LANCZOS  # requer Pillow >= 9.1

# ============================================================
# CONFIGURAÇÕES FIXAS (identidade visual da Shalom Imóveis)
# ============================================================
BASE_URL = "https://shalomimoveispb.com.br"
LOGO_PATH = "logo_shalom.png"
ICONE_TELEFONE_PATH = "icone_telefone.png"   # opcional (PNG com fundo transparente)
ICONE_WHATSAPP_PATH = "icone_whatsapp.png"   # opcional (PNG com fundo transparente)

ASSINATURA_NOME = "Maxwel Barbosa | Corretor de Imóveis | CRECI PB 8615"
TELEFONE = "(83)98863-8049"

AZUL_MARINHO = (11, 31, 58)
DOURADO = (201, 162, 75)
BRANCO = (255, 255, 255)
VERDE_WHATSAPP = (37, 211, 102)

# A arte é desenhada em resolução dupla (2160x2700) para máxima nitidez.
# Todas as medidas abaixo são em "pixels de referência" (1080x1350).
ESCALA = 2


def px(n: float) -> int:
    return int(round(n * ESCALA))


LARGURA, ALTURA = px(1080), px(1350)
MARGEM = px(60)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

FONT_CANDIDATES = [
    "Montserrat-Bold.ttf",
    "/usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "arialbd.ttf",
]
SYMBOL_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "DejaVuSans.ttf",
    "seguisym.ttf",
]

TIPOS_IMOVEL = {
    "galpao": "Galpão",
    "casa": "Casa",
    "apartamento": "Apartamento",
    "terreno": "Terreno",
    "sala comercial": "Sala Comercial",
    "sala": "Sala",
    "loja": "Loja",
    "predio": "Prédio",
    "sitio": "Sítio",
    "fazenda": "Fazenda",
    "chacara": "Chácara",
    "cobertura": "Cobertura",
    "kitnet": "Kitnet",
    "flat": "Flat",
    "studio": "Studio",
    "lote": "Lote",
    "armazem": "Armazém",
    "barracao": "Barracão",
    "sobrado": "Sobrado",
    "escritorio": "Escritório",
    "edificio": "Edifício",
    "ponto comercial": "Ponto Comercial",
}


# ============================================================
# UTILITÁRIOS GERAIS
# ============================================================
def get_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def get_symbol_font(size: int):
    for path in SYMBOL_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return None


def sem_acento(texto: str) -> str:
    return (
        unicodedata.normalize("NFD", texto)
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )


def formatar_valor(texto: str) -> str:
    """Converte 'R$ 450.000,00', '450000' ou '450000.5' em 'R$ 450.000,00'."""
    if not texto:
        return ""
    t = re.sub(r"[^\d.,]", "", texto.strip())
    if not t:
        return ""
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") == 1 and len(t.split(".")[1]) <= 2:
        pass
    else:
        t = t.replace(".", "")
    try:
        numero = float(t)
    except ValueError:
        return texto
    s = f"{numero:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


# ============================================================
# WEB SCRAPING
# ============================================================
def baixar_pagina(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def extrair_url_imagem(img_tag) -> str | None:
    for attr in ("src", "data-src", "data-lazy-src", "data-original", "data-lazy"):
        valor = img_tag.get(attr)
        if valor and not valor.startswith("data:"):
            return valor
    srcset = img_tag.get("srcset") or img_tag.get("data-srcset")
    if srcset:
        return srcset.split(",")[0].strip().split(" ")[0]
    return None


def encontrar_primeira_imagem(soup: BeautifulSoup) -> str | None:
    seletores = [
        "div.carousel-inner img",
        "div.owl-stage img",
        "div.owl-carousel img",
        "div.swiper-wrapper img",
        "div.slick-track img",
        "div[class*=carousel] img",
        "div[class*=slider] img",
        "div[class*=gallery] img",
    ]
    for seletor in seletores:
        for img in soup.select(seletor):
            src = extrair_url_imagem(img)
            if src:
                return urljoin(BASE_URL + "/", src)
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return urljoin(BASE_URL + "/", og["content"])
    return None


def baixar_imagem(url_imagem: str) -> Image.Image:
    r = requests.get(url_imagem, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def linhas_da_pagina(soup: BeautifulSoup) -> list[str]:
    return [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]


def valor_por_rotulo(linhas: list[str], rotulo: str) -> str:
    """Acha 'Rótulo: valor' ou 'Rótulo' seguido do valor na linha seguinte."""
    for i, l in enumerate(linhas):
        if re.fullmatch(rf"{rotulo}\s*:?", l, re.I) and i + 1 < len(linhas):
            return linhas[i + 1]
        m = re.match(rf"{rotulo}\s*:\s*(.+)", l, re.I)
        if m:
            return m.group(1)
    return ""


# ---------- Status ----------
def detectar_status(soup: BeautifulSoup, url: str, texto: str) -> str:
    h1 = soup.find("h1")
    titulo_tag = soup.title.get_text(" ", strip=True) if soup.title else ""
    prioridades = [
        url + " " + (h1.get_text(" ", strip=True) if h1 else "") + " " + titulo_tag,
        " ".join(
            el.get_text(" ", strip=True)
            for el in soup.select("[class*=status], [class*=badge], [class*=finalidade], [class*=tag]")
        ),
        texto[:1500],
    ]
    for fonte in prioridades:
        f = sem_acento(fonte)
        if re.search(r"alug|locacao|para locar", f):
            return "ALUGUEL"
        if re.search(r"venda|vender|comprar", f):
            return "VENDA"
    return ""


# ---------- Tipo de imóvel ----------
def detectar_tipo(soup: BeautifulSoup, url: str, texto: str) -> str:
    h1 = soup.find("h1")
    titulo_tag = soup.title.get_text(" ", strip=True) if soup.title else ""
    slug = re.sub(r"[-_/]", " ", urlparse(url).path)
    fontes = [
        h1.get_text(" ", strip=True) if h1 else "",
        titulo_tag,
        slug,
        texto[:2000],
    ]
    chaves = sorted(TIPOS_IMOVEL.keys(), key=len, reverse=True)
    padrao = re.compile(r"\b(" + "|".join(re.escape(c) for c in chaves) + r")\b")
    for fonte in fontes:
        m = padrao.search(sem_acento(fonte))
        if m:
            return TIPOS_IMOVEL[m.group(1)]
    return ""


# ---------- Código do imóvel ----------
def detectar_codigo(soup: BeautifulSoup, url: str, texto: str, linhas: list[str]) -> str:
    rotulo = r"(?:c[óo]digo(?:\s+do\s+im[óo]vel)?|c[óo]d\.?|refer[êe]ncia|ref\.?)"
    padrao_valido = r"[A-Za-z]{0,3}-?\d{1,8}"

    val = valor_por_rotulo(linhas, rotulo).strip()
    if val and re.fullmatch(padrao_valido, val):
        return val.upper()

    m = re.search(rotulo + r"\s*[:\-–#nº°]*\s*(" + padrao_valido + r")\b", texto, re.I)
    if m:
        return m.group(1).upper()

    numeros = re.findall(r"\d{2,8}", urlparse(url).path)
    return numeros[-1] if numeros else ""


# ---------- Localização ----------
def limpar_local(t: str) -> str:
    t = re.sub(r"\s+", " ", t).strip(" -–|,")
    t = re.sub(r"^(localiza[cç][aã]o|endere[cç]o|bairro|cidade)\s*:?\s*", "", t, flags=re.I)
    t = re.sub(r"\s*[-/]\s*[A-Z]{2}$", "", t)  # remove UF final (" - PB")
    partes = [p.strip() for p in t.split(",") if p.strip()]
    if len(partes) > 2:
        partes = partes[-2:]
    return ", ".join(partes)


def cidade_do_json_ld(soup: BeautifulSoup) -> str:
    def procurar(no):
        if isinstance(no, dict):
            addr = no.get("address")
            if isinstance(addr, dict) and addr.get("addressLocality"):
                return addr["addressLocality"]
            for v in no.values():
                r = procurar(v)
                if r:
                    return r
        elif isinstance(no, list):
            for v in no:
                r = procurar(v)
                if r:
                    return r
        return ""

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            r = procurar(json.loads(script.string or ""))
            if r:
                return r
        except Exception:
            continue
    return ""


def detectar_localizacao(soup: BeautifulSoup, linhas: list[str]) -> str:
    bairro = limpar_local(valor_por_rotulo(linhas, r"bairro"))
    cidade = limpar_local(valor_por_rotulo(linhas, r"cidade")) or limpar_local(cidade_do_json_ld(soup))
    if bairro and cidade:
        return f"{bairro}, {cidade}"

    for el in soup.select("[class*=local], [class*=bairro], [class*=endereco], [class*=address]"):
        t = limpar_local(el.get_text(" ", strip=True))
        if 3 < len(t) < 80:
            return t

    h1 = soup.find("h1")
    titulo = h1.get_text(" ", strip=True) if h1 else ""
    m = re.search(r"\bem\s+([^,\-|]+),\s*([^,\-|]+)", titulo, re.I)
    if m:
        return f"{m.group(1).strip()}, {m.group(2).strip()}"

    return bairro or cidade


# ---------- Valor ----------
def detectar_valor(soup: BeautifulSoup, texto: str) -> str:
    for el in soup.select("[class*=preco], [class*=price], [class*=valor]"):
        m = re.search(r"R\$\s*[\d\.]+(?:,\d{2})?", el.get_text(" ", strip=True))
        if m:
            return formatar_valor(m.group(0))
    m = re.search(r"R\$\s*[\d\.]+(?:,\d{2})?", texto)
    return formatar_valor(m.group(0)) if m else ""


def extrair_dados(soup: BeautifulSoup, url: str) -> dict:
    texto = soup.get_text(" ", strip=True)
    linhas = linhas_da_pagina(soup)
    return {
        "status": detectar_status(soup, url, texto),
        "valor": detectar_valor(soup, texto),
        "localizacao": detectar_localizacao(soup, linhas),
        "descricao": detectar_tipo(soup, url, texto),   # tipo do imóvel
        "codigo": detectar_codigo(soup, url, texto, linhas),
    }


# ============================================================
# ÍCONES (telefone e WhatsApp)
# ============================================================
def icone_fallback(tipo: str, tam: int) -> Image.Image:
    """Ícone desenhado por código, usado se o PNG local não existir."""
    s = tam * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cor = VERDE_WHATSAPP if tipo == "whatsapp" else DOURADO
    d.ellipse([0, 0, s - 1, s - 1], fill=cor)
    if tipo == "whatsapp":
        d.polygon([(s * 0.10, s * 0.93), (s * 0.15, s * 0.62), (s * 0.40, s * 0.85)], fill=cor)
    fonte = get_symbol_font(int(s * 0.62))
    if fonte:
        d.text(
            (s / 2, s / 2), "\u2706", font=fonte,
            fill=BRANCO if tipo == "whatsapp" else AZUL_MARINHO, anchor="mm",
        )
    return img.resize((tam, tam), LANCZOS)


def carregar_icone(caminho: str, tipo: str, altura: int) -> Image.Image:
    if os.path.exists(caminho):
        ic = Image.open(caminho).convert("RGBA")
        largura = int(ic.width * altura / ic.height)
        return ic.resize((largura, altura), LANCZOS)
    return icone_fallback(tipo, altura)


# ============================================================
# GERAÇÃO DA ARTE
# ============================================================
def cortar_para_preencher(img: Image.Image, w: int, h: int) -> Image.Image:
    escala = max(w / img.width, h / img.height)
    novo = img.resize((int(img.width * escala) + 1, int(img.height * escala) + 1), LANCZOS)
    esq = (novo.width - w) // 2
    topo = (novo.height - h) // 2
    return novo.crop((esq, topo, esq + w, topo + h))


def gradiente_vertical(w, h, cor, alpha_topo, alpha_base) -> Image.Image:
    grad = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(grad)
    for y in range(h):
        a = int(alpha_topo + (alpha_base - alpha_topo) * y / max(h - 1, 1))
        d.line([(0, y), (w, y)], fill=cor + (a,))
    return grad


def texto_com_sombra(draw, xy, texto, fonte, cor):
    x, y = xy
    d = px(2)
    draw.text((x + d, y + d), texto, font=fonte, fill=(0, 0, 0, 160))
    draw.text((x, y), texto, font=fonte, fill=cor)


def fonte_ajustada(draw, texto, tamanho_px, largura_max):
    fonte = get_font(tamanho_px)
    while draw.textlength(texto, font=fonte) > largura_max and tamanho_px > px(14):
        tamanho_px -= 1
        fonte = get_font(tamanho_px)
    return fonte, tamanho_px


def gerar_arte(foto, status, valor, localizacao, tipo_imovel, codigo) -> Image.Image:
    base = cortar_para_preencher(foto, LARGURA, ALTURA).convert("RGBA")

    # --- Overlays fixos (superior e inferior) ---
    base.alpha_composite(gradiente_vertical(LARGURA, px(320), AZUL_MARINHO, 230, 0), (0, 0))
    base.alpha_composite(gradiente_vertical(LARGURA, px(820), AZUL_MARINHO, 0, 248), (0, ALTURA - px(820)))

    draw = ImageDraw.Draw(base)

    # --- Logomarca: topo, centralizada no eixo horizontal ---
    if os.path.exists(LOGO_PATH):
        logo = Image.open(LOGO_PATH).convert("RGBA")
        lw = px(300)
        lh = int(logo.height * lw / logo.width)
        logo = logo.resize((lw, lh), LANCZOS)
        base.alpha_composite(logo, ((LARGURA - lw) // 2, MARGEM))
    else:
        f = get_font(px(38))
        t = "SHALOM IMÓVEIS"
        w = draw.textlength(t, font=f)
        texto_com_sombra(draw, ((LARGURA - w) / 2, MARGEM), t, f, DOURADO)

    # --- Tag de status (sem colchetes): VENDA / ALUGUEL ---
    if status:
        f_tag = get_font(px(34))
        w_tag = draw.textlength(status, font=f_tag)
        pad_x, pad_y = px(26), px(16)
        draw.rounded_rectangle(
            [MARGEM, MARGEM, MARGEM + w_tag + 2 * pad_x, MARGEM + px(34) + 2 * pad_y + px(6)],
            radius=px(10),
            fill=DOURADO,
        )
        draw.text((MARGEM + pad_x, MARGEM + pad_y), status, font=f_tag, fill=AZUL_MARINHO)

    # ========== Bloco inferior (montado de baixo para cima) ==========
    y = ALTURA - px(50)

    # Linha 2 do rodapé: [ícone telefone][ícone WhatsApp] (83)98863-8049 (fonte grande)
    f_tel, tam_tel = fonte_ajustada(draw, TELEFONE, px(70), LARGURA - 2 * MARGEM - px(180))
    y -= tam_tel
    larg_tel = draw.textlength(TELEFONE, font=f_tel)
    ic_h = int(tam_tel * 0.95)
    ic_tel = carregar_icone(ICONE_TELEFONE_PATH, "telefone", ic_h)
    ic_wa = carregar_icone(ICONE_WHATSAPP_PATH, "whatsapp", ic_h)
    gap = px(14)
    larg_total = ic_tel.width + gap + ic_wa.width + gap * 2 + larg_tel
    x = (LARGURA - larg_total) / 2

    bbox = draw.textbbox((0, y), TELEFONE, font=f_tel)
    centro_y = (bbox[1] + bbox[3]) / 2
    icon_y = int(centro_y - ic_h / 2)

    base.alpha_composite(ic_tel, (int(x), icon_y))
    x += ic_tel.width + gap
    base.alpha_composite(ic_wa, (int(x), icon_y))
    x += ic_wa.width + gap * 2
    draw = ImageDraw.Draw(base)  # recria após alpha_composite
    texto_com_sombra(draw, (x, y), TELEFONE, f_tel, BRANCO)

    # Linha 1 do rodapé: nome / função / CRECI (fonte padrão)
    y -= px(18)
    f_nome, tam_nome = fonte_ajustada(draw, ASSINATURA_NOME, px(30), LARGURA - 2 * MARGEM)
    y -= tam_nome
    larg_nome = draw.textlength(ASSINATURA_NOME, font=f_nome)
    draw.text(((LARGURA - larg_nome) / 2, y), ASSINATURA_NOME, font=f_nome, fill=BRANCO)

    # Linha dourada separadora
    y -= px(26)
    draw.line([(MARGEM, y), (LARGURA - MARGEM, y)], fill=DOURADO, width=px(3))

    # Valor
    if valor:
        y -= px(84) + px(28)
        texto_com_sombra(draw, (MARGEM, y), valor, get_font(px(84)), DOURADO)

    # Código do imóvel (no lugar dos antigos atributos)
    if codigo:
        y -= px(38) + px(22)
        texto_com_sombra(draw, (MARGEM, y), f"Cód. {codigo}", get_font(px(38)), BRANCO)

    # Localização
    if localizacao:
        y -= px(38) + px(18)
        f_loc, _ = fonte_ajustada(draw, localizacao, px(38), LARGURA - 2 * MARGEM)
        texto_com_sombra(draw, (MARGEM, y), localizacao, f_loc, DOURADO)

    # Tipo de imóvel (no lugar do título)
    if tipo_imovel:
        f_tipo, tam_tipo = fonte_ajustada(draw, tipo_imovel, px(80), LARGURA - 2 * MARGEM)
        y -= tam_tipo + px(16)
        texto_com_sombra(draw, (MARGEM, y), tipo_imovel, f_tipo, BRANCO)

    return base.convert("RGB")


# ============================================================
# INTERFACE STREAMLIT
# ============================================================
st.set_page_config(page_title="Gerador de Artes | Shalom Imóveis", page_icon="🏠")
st.title("🏠 Gerador de Artes – Shalom Imóveis")
st.caption("Cole o link do anúncio, revise os dados e gere a arte para redes sociais.")

for chave in ("status", "valor", "localizacao", "descricao", "codigo", "url_imagem"):
    st.session_state.setdefault(chave, "")

url = st.text_input("URL do anúncio", placeholder=f"{BASE_URL}/imovel/...")

if st.button("🔎 Buscar dados do anúncio"):
    if not url.strip():
        st.warning("Cole a URL do anúncio primeiro.")
    else:
        try:
            with st.spinner("Lendo o anúncio..."):
                soup = baixar_pagina(url.strip())
                dados = extrair_dados(soup, url.strip())
                st.session_state.url_imagem = encontrar_primeira_imagem(soup) or ""
                for k, v in dados.items():
                    st.session_state[k] = v
            if not st.session_state.url_imagem:
                st.warning("Não encontrei a imagem do carrossel. O site pode carregar as fotos via JavaScript.")
            else:
                st.success("Dados carregados! Revise os campos abaixo.")
        except Exception as e:
            st.error(f"Não consegui acessar o anúncio: {e}")

st.subheader("Dados da arte (edite se necessário)")
opcoes_status = ["", "VENDA", "ALUGUEL"]
atual = st.session_state.status if st.session_state.status in opcoes_status else ""
status = st.selectbox("Status", opcoes_status, index=opcoes_status.index(atual))
valor = st.text_input("Valor", key="valor", placeholder="R$ 450.000,00")
localizacao = st.text_input("Localização", key="localizacao", placeholder="Bairro, Cidade")
descricao = st.text_input("Título / descrição (tipo do imóvel)", key="descricao", placeholder="Galpão")
codigo = st.text_input("Código do imóvel", key="codigo", placeholder="1234")

if st.button("🎨 Gerar Imagem", type="primary"):
    try:
        if not st.session_state.url_imagem:
            if not url.strip():
                st.warning("Cole a URL do anúncio.")
                st.stop()
            with st.spinner("Buscando a foto principal..."):
                st.session_state.url_imagem = encontrar_primeira_imagem(baixar_pagina(url.strip())) or ""
        if not st.session_state.url_imagem:
            st.error("Imagem principal não encontrada.")
            st.stop()

        with st.spinner("Gerando arte em alta resolução..."):
            foto = baixar_imagem(st.session_state.url_imagem)
            arte = gerar_arte(foto, status, formatar_valor(valor), localizacao, descricao, codigo)
        st.image(arte, use_container_width=True)

        buffer = io.BytesIO()
        arte.save(buffer, format="JPEG", quality=100, subsampling=0, optimize=True)
        st.download_button(
            "⬇️ Baixar imagem (máxima qualidade)",
            data=buffer.getvalue(),
            file_name="arte_shalom.jpg",
            mime="image/jpeg",
        )
    except Exception as e:
        st.error(f"Erro ao gerar a arte: {e}")
