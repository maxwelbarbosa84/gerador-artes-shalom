from __future__ import annotations

import io
import os
import re
from urllib.parse import urljoin

import requests
import streamlit as st
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

# ============================================================
# CONFIGURAÇÕES FIXAS (identidade visual da Shalom Imóveis)
# ============================================================
BASE_URL = "https://shalomimoveispb.com.br"
LOGO_PATH = "logo_shalom.png"
ASSINATURA = "Maxwel Barbosa | Corretor de imóveis CRECI PB 8615 | (83)98863-8049"

# Ajuste os tons abaixo se quiser bater exatamente com o manual de marca
AZUL_MARINHO = (11, 31, 58)
DOURADO = (201, 162, 75)
BRANCO = (255, 255, 255)

LARGURA, ALTURA = 1080, 1350  # formato retrato 4:5 (feed do Instagram)
MARGEM = 60

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

FONT_CANDIDATES = [
    "Montserrat-Bold.ttf",  # coloque este arquivo no repositório, se quiser
    "/usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf",  # via packages.txt
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "arialbd.ttf",
]


# ============================================================
# UTILITÁRIOS
# ============================================================
def get_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def formatar_valor(texto: str) -> str:
    """Converte 'R$ 450.000,00', '450000' ou '450000.5' em 'R$ 450.000,00'."""
    if not texto:
        return ""
    t = texto.strip()
    t = re.sub(r"[^\d.,]", "", t)
    if not t:
        return ""
    if "," in t:  # padrão brasileiro: 1.234,56
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") == 1 and len(t.split(".")[1]) <= 2:  # 450000.50
        pass
    else:  # 450.000
        t = t.replace(".", "")
    try:
        numero = float(t)
    except ValueError:
        return texto
    inteiro = f"{numero:,.2f}"  # 450,000.00
    return "R$ " + inteiro.replace(",", "X").replace(".", ",").replace("X", ".")


def baixar_pagina(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def extrair_url_imagem(img_tag) -> str | None:
    """Trata lazy-load (data-src etc.) e srcset."""
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
    # Plano B: imagem de compartilhamento da página
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return urljoin(BASE_URL + "/", og["content"])
    return None


def baixar_imagem(url_imagem: str) -> Image.Image:
    r = requests.get(url_imagem, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def extrair_dados(soup: BeautifulSoup, url: str) -> dict:
    texto = soup.get_text(" ", strip=True)
    dados = {"status": "", "valor": "", "localizacao": "", "descricao": ""}

    # Título
    h1 = soup.find("h1")
    titulo = h1.get_text(" ", strip=True) if h1 else ""

    # Status
    base = (url + " " + titulo + " " + texto[:1500]).lower()
    if re.search(r"alug|loca[cç][aã]o", base):
        dados["status"] = "[ LOCAÇÃO ]"
    elif "venda" in base or "vender" in base:
        dados["status"] = "[ VENDA ]"

    # Valor
    m = re.search(r"R\$\s*[\d\.]+(?:,\d{2})?", texto)
    if m:
        dados["valor"] = formatar_valor(m.group(0))

    # Localização
    for el in soup.select("[class*=local], [class*=bairro], [class*=endereco], [class*=address]"):
        t = el.get_text(" ", strip=True)
        if 3 < len(t) < 80:
            dados["localizacao"] = t
            break

    # Atributos (até 3)
    atributos = []
    for padrao in (
        r"(\d+)\s*(quartos?|su[ií]tes?|banheiros?|vagas?)",
        r"(\d+[\.,]?\d*)\s*(m²|m2)",
    ):
        for num, unidade in re.findall(padrao, texto, flags=re.I):
            item = f"{num} {unidade.replace('m2', 'm²')}"
            if item.lower() not in [a.lower() for a in atributos]:
                atributos.append(item)
            if len(atributos) == 3:
                break
        if len(atributos) == 3:
            break

    dados["descricao"] = titulo
    dados["atributos"] = " | ".join(atributos[:3])
    return dados


# ============================================================
# GERAÇÃO DA ARTE
# ============================================================
def cortar_para_preencher(img: Image.Image, w: int, h: int) -> Image.Image:
    escala = max(w / img.width, h / img.height)
    novo = img.resize((int(img.width * escala) + 1, int(img.height * escala) + 1), Image.LANCZOS)
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


def quebrar_texto(draw, texto, fonte, largura_max, max_linhas):
    palavras = texto.split()
    linhas, atual = [], ""
    for p in palavras:
        teste = (atual + " " + p).strip()
        if draw.textlength(teste, font=fonte) <= largura_max:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    if len(linhas) > max_linhas:
        linhas = linhas[:max_linhas]
        linhas[-1] = linhas[-1].rstrip(" .,") + "…"
    return linhas


def texto_com_sombra(draw, xy, texto, fonte, cor):
    x, y = xy
    draw.text((x + 2, y + 2), texto, font=fonte, fill=(0, 0, 0, 160))
    draw.text((x, y), texto, font=fonte, fill=cor)


def gerar_arte(foto, status, valor, localizacao, descricao, atributos) -> Image.Image:
    base = cortar_para_preencher(foto, LARGURA, ALTURA).convert("RGBA")

    # --- Overlays fixos (superior e inferior) ---
    base.alpha_composite(gradiente_vertical(LARGURA, 320, AZUL_MARINHO, 230, 0), (0, 0))
    base.alpha_composite(gradiente_vertical(LARGURA, 760, AZUL_MARINHO, 0, 245), (0, ALTURA - 760))

    draw = ImageDraw.Draw(base)

    # --- Logomarca (canto superior direito) ---
    if os.path.exists(LOGO_PATH):
        logo = Image.open(LOGO_PATH).convert("RGBA")
        lw = 280
        lh = int(logo.height * lw / logo.width)
        logo = logo.resize((lw, lh), Image.LANCZOS)
        base.alpha_composite(logo, (LARGURA - MARGEM - lw, MARGEM))
    else:
        f = get_font(34)
        t = "SHALOM IMÓVEIS"
        w = draw.textlength(t, font=f)
        texto_com_sombra(draw, (LARGURA - MARGEM - w, MARGEM), t, f, DOURADO)

    # --- Tag de status (canto superior esquerdo) ---
    if status:
        f_tag = get_font(34)
        w_tag = draw.textlength(status, font=f_tag)
        pad_x, pad_y = 26, 16
        draw.rounded_rectangle(
            [MARGEM, MARGEM, MARGEM + w_tag + 2 * pad_x, MARGEM + 34 + 2 * pad_y + 6],
            radius=10,
            fill=DOURADO,
        )
        draw.text((MARGEM + pad_x, MARGEM + pad_y), status, font=f_tag, fill=AZUL_MARINHO)

    # --- Bloco inferior: do rodapé para cima ---
    y = ALTURA - MARGEM

    # Assinatura (fixa) com ajuste automático de tamanho
    tamanho = 28
    fonte_ass = get_font(tamanho)
    while draw.textlength(ASSINATURA, font=fonte_ass) > LARGURA - 2 * MARGEM and tamanho > 14:
        tamanho -= 1
        fonte_ass = get_font(tamanho)
    y -= tamanho
    larg_ass = draw.textlength(ASSINATURA, font=fonte_ass)
    draw.text(((LARGURA - larg_ass) / 2, y), ASSINATURA, font=fonte_ass, fill=BRANCO)

    # Linha dourada separadora
    y -= 28
    draw.line([(MARGEM, y), (LARGURA - MARGEM, y)], fill=DOURADO, width=3)

    # Valor
    if valor:
        f_valor = get_font(84)
        y -= 84 + 30
        texto_com_sombra(draw, (MARGEM, y), valor, f_valor, DOURADO)

    # Atributos
    if atributos:
        f_attr = get_font(34)
        y -= 34 + 24
        texto_com_sombra(draw, (MARGEM, y), atributos, f_attr, BRANCO)

    # Localização
    if localizacao:
        f_loc = get_font(36)
        y -= 36 + 20
        texto_com_sombra(draw, (MARGEM, y), localizacao, f_loc, DOURADO)

    # Título (até 2 linhas)
    if descricao:
        f_tit = get_font(52)
        linhas = quebrar_texto(draw, descricao, f_tit, LARGURA - 2 * MARGEM, 2)
        y -= len(linhas) * 64 + 18
        for i, linha in enumerate(linhas):
            texto_com_sombra(draw, (MARGEM, y + i * 64), linha, f_tit, BRANCO)

    return base.convert("RGB")


# ============================================================
# INTERFACE STREAMLIT
# ============================================================
st.set_page_config(page_title="Gerador de Artes | Shalom Imóveis", page_icon="🏠")
st.title("🏠 Gerador de Artes – Shalom Imóveis")
st.caption("Cole o link do anúncio, revise os dados e gere a arte para redes sociais.")

for chave in ("status", "valor", "localizacao", "descricao", "atributos", "url_imagem"):
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
opcoes_status = ["", "[ VENDA ]", "[ LOCAÇÃO ]"]
atual = st.session_state.status if st.session_state.status in opcoes_status else ""
status = st.selectbox("Status", opcoes_status, index=opcoes_status.index(atual))
valor = st.text_input("Valor", key="valor", placeholder="R$ 450.000,00")
localizacao = st.text_input("Localização", key="localizacao", placeholder="Bairro, Cidade")
descricao = st.text_input("Título / descrição", key="descricao")
atributos = st.text_input("Atributos (até 3, separados por |)", key="atributos",
                          placeholder="3 quartos | 2 vagas | 120 m²")

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

        with st.spinner("Gerando arte..."):
            foto = baixar_imagem(st.session_state.url_imagem)
            arte = gerar_arte(
                foto,
                status,
                formatar_valor(valor),
                localizacao,
                descricao,
                atributos,
            )
        st.image(arte, use_container_width=True)

        buffer = io.BytesIO()
        arte.save(buffer, format="PNG")
        st.download_button(
            "⬇️ Baixar imagem",
            data=buffer.getvalue(),
            file_name="arte_shalom.png",
            mime="image/png",
        )
    except Exception as e:
        st.error(f"Erro ao gerar a arte: {e}")
