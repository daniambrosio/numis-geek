"""Prepara imagens/PDFs "tipo screenshot" pra visão do Claude.

Bug 2026-11-02 (fechamento Out/26 Avenue): o PDF exportado do app da Avenue
tinha uma página de 3200×14400 px. A API reduz cada imagem/página pra
~1.15 MP antes de ler — essa página virou ~350 px de largura, ilegível. O
modelo só enxergou os totais em fonte grande e INVENTOU o resto (AAPL 50 ×
$180,50, MSFT, VOO...). O tiling antigo só cortava acima de 8000 px, e
mesmo uma fatia de 1290×8000 sofre o mesmo downscale.

Estratégia:
- Imagem "alta" (altura > 2× largura) ou maior que 8000 px: reduz a
  largura pra no máximo TILE_MAX_W e fatia em blocos de até TILE_MAX_H,
  cortando numa faixa uniforme (espaço entre linhas) pra nunca partir
  uma linha de tabela ao meio — e sem sobreposição, então nenhuma linha
  aparece duplicada em duas fatias.
- PDF: se alguma página for "alta" (screenshot exportado como PDF), as
  páginas são rasterizadas, costuradas verticalmente (a Avenue partia a
  linha do T 4.625 15/11/44 entre a página 1 e 2) e fatiadas como acima.
  PDF normal (A4 de banco/fatura) segue como document block — a API usa a
  camada de texto, que é melhor que OCR.
"""
from __future__ import annotations

from io import BytesIO

# A API reduz qualquer imagem com lado > 1568 px ou > ~1.15 MP. Fatias
# largas e baixas (1568×730 ≈ 1.14 MP) chegam SEM redução: a largura útil
# sobe de ~1070 px (fatia quadrada de 1400, reduzida pela API) pra 1568 —
# na 1ª versão o modelo ainda lia "T 4.31" onde estava "T 4".
TILE_MAX_W = 1568
TILE_MAX_H = 730
# Quanto subir a partir do corte ideal procurando uma faixa em branco.
_CUT_SEARCH = 300
# Pixel "fora do fundo": difere da mediana da linha por > _ROW_TOL_LEVEL
# níveis de cinza. Linha "vazia": no máximo _ROW_MAX_OFF desses pixels,
# DESCONTADAS as colunas estruturais (bordas verticais de card, que após o
# resize viram 3-4 px de anti-aliasing cada). Contagem absoluta, não
# fração: subtítulo cinza pequeno ocupa < 1% da linha.
_ROW_TOL_LEVEL = 10
_ROW_MAX_OFF = 2
# Coluna estrutural: fora do fundo em ≥ 75% das linhas da janela de busca.
_STRUCTURAL_COL_FREQ = 0.75
# Altura mínima (px, na largura final) da faixa vazia onde se pode cortar.
_MIN_GAP = 14
# Sobreposição quando não há faixa vazia pra cortar (conteúdo denso).
_OVERLAP = 60
# Proporção a partir da qual a imagem é considerada "alta".
TALL_RATIO = 2.0
_HARD_LIMIT = 8000
# Teto de fatias por documento (a API aceita até 100 imagens; acima de 20
# o limite de dimensão cai pra 2000 px, que já respeitamos).
MAX_TILES = 60


class TooManyTilesError(ValueError):
    pass


def _needs_tiling(w: int, h: int) -> bool:
    return max(w, h) > _HARD_LIMIT or h > TALL_RATIO * w


def _off_background(gray):
    """Matriz bool (h×w): pixel destoa da mediana da sua linha."""
    import numpy as np

    med = np.median(gray, axis=1, keepdims=True)
    return np.abs(gray.astype(np.int16) - med) > _ROW_TOL_LEVEL


def _find_cut(off, start: int, target: int) -> int:
    """Corte no meio da faixa vazia (≥ _MIN_GAP linhas) mais perto de target.

    Exigir uma faixa — e não uma linha vazia qualquer — evita cortar no
    respiro de poucos px entre o nome e o subtítulo de uma MESMA linha de
    tabela (ex.: "Banco do Brasil" / "CD BANCO DO BRASIL 4.22").
    """
    lo = max(start + 1, target - _CUT_SEARCH)
    window = off[lo:target + 1]
    structural = window.mean(axis=0) >= _STRUCTURAL_COL_FREQ
    uniform = window[:, ~structural].sum(axis=1) <= _ROW_MAX_OFF
    i = len(uniform) - 1
    while i >= 0:
        if not uniform[i]:
            i -= 1
            continue
        end = i
        while i >= 0 and uniform[i]:
            i -= 1
        begin = i + 1
        if end - begin + 1 >= _MIN_GAP:
            return lo + (begin + end + 1) // 2
    return -1  # sem faixa vazia: caller corta no target COM sobreposição


def _trim_side_margins(img):
    """Corta colunas vazias nas laterais (margem de página) antes de reduzir
    — cada pixel de largura economizado vira resolução no texto."""
    import numpy as np

    gray = np.asarray(img.convert("L"))
    med = np.median(gray, axis=0, keepdims=True)
    off = (np.abs(gray.astype(np.int16) - med) > _ROW_TOL_LEVEL).sum(axis=0)
    content = np.nonzero(off > max(2, gray.shape[0] * 0.002))[0]
    if content.size == 0:
        return img
    pad = 16
    left = max(0, int(content[0]) - pad)
    right = min(img.width, int(content[-1]) + 1 + pad)
    if right - left < img.width * 0.5:  # algo estranho — não arrisca
        return img
    return img.crop((left, 0, right, img.height))


def _to_rgb_on_white(img):
    """RGB sem perder conteúdo transparente: `convert("RGB")` direto pinta o
    fundo transparente de preto (texto preto some — audit 2026-11-02)."""
    from PIL import Image

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return img if img.mode == "RGB" else img.convert("RGB")


def _tile(img) -> list[tuple[bytes, str]]:
    """Reduz largura e fatia verticalmente em cortes limpos. Retorna JPEGs."""
    import numpy as np
    from PIL import Image

    img = _to_rgb_on_white(img)
    img = _trim_side_margins(img)
    w, h = img.size
    if w > TILE_MAX_W:
        new_h = max(1, round(h * TILE_MAX_W / w))
        img = img.resize((TILE_MAX_W, new_h), Image.LANCZOS)
        w, h = img.size
    off = _off_background(np.asarray(img.convert("L")))
    tiles: list[tuple[bytes, str]] = []
    top = 0
    while top < h:
        next_top = None
        if h - top <= TILE_MAX_H:
            bottom = h
        else:
            bottom = _find_cut(off, top, top + TILE_MAX_H)
            if bottom < 0:
                # Conteúdo denso sem respiro: corta no limite e repete
                # _OVERLAP px na fatia seguinte pra a linha partida aparecer
                # inteira em uma delas (a nota no prompt avisa da repetição).
                bottom = top + TILE_MAX_H
                next_top = bottom - _OVERLAP
        buf = BytesIO()
        img.crop((0, top, w, bottom)).save(buf, format="JPEG", quality=90)
        tiles.append((buf.getvalue(), "image/jpeg"))
        if len(tiles) > MAX_TILES:
            raise TooManyTilesError(
                f"documento grande demais: mais de {MAX_TILES} fatias — "
                "divida o arquivo em partes menores"
            )
        top = next_top if next_top is not None else bottom
    return tiles


def split_image(blob: bytes, mime_type: str | None) -> list[tuple[bytes, str | None]]:
    """Imagem dentro do normal → `[(blob, mime)]` intacto. Alta/enorme → fatias."""
    try:
        from PIL import Image
    except ImportError:
        return [(blob, mime_type)]
    try:
        img = Image.open(BytesIO(blob))
        w, h = img.size
    except Exception:
        return [(blob, mime_type)]
    if not _needs_tiling(w, h):
        return [(blob, mime_type)]
    try:
        return _tile(img)
    except TooManyTilesError:
        raise
    except Exception:
        # Decode/resize falhou: manda o original (comportamento anterior).
        return [(blob, mime_type)]


def pdf_screenshot_tiles(blob: bytes) -> list[tuple[bytes, str]] | None:
    """Fatias pra PDF tipo screenshot; None quando o PDF deve ir como document.

    None também quando pypdfium2 não está instalado ou o PDF não abre — o
    caller cai no document block (comportamento anterior).
    """
    try:
        import pypdfium2 as pdfium
        from PIL import Image
    except ImportError:
        return None
    try:
        doc = pdfium.PdfDocument(blob)
    except Exception:
        return None
    try:
        sizes = [doc[i].get_size() for i in range(len(doc))]
        if not sizes or not any(_needs_tiling(int(w), int(h)) for w, h in sizes):
            return None
        # PDF com camada de texto segue como document block: a API lê o
        # texto, que é melhor que OCR de bitmap (audit 2026-11-02). Só o
        # PDF-imagem (export do app Avenue: 0 caracteres) é rasterizado.
        if any(_page_has_text(doc[i]) for i in range(len(doc))):
            return None
        widest = max(w for w, _ in sizes)
        # Escala que leva a página mais larga a ~1.4× a largura da fatia (o
        # corte de margem ainda vai estreitar). Página estreita sobe (até
        # 4×) em vez de ficar nos 72 dpi nativos do PDF.
        scale = max(0.05, min(4.0, TILE_MAX_W * 1.4 / widest))
        # Teto de fatias ANTES de renderizar: evita alocar bitmap gigante só
        # pra descobrir que o documento passa do limite.
        final_h = sum(h for _, h in sizes) * scale * min(1.0, TILE_MAX_W / (widest * scale))
        if final_h / TILE_MAX_H > MAX_TILES * 1.2:
            raise TooManyTilesError(
                f"documento grande demais: ~{int(final_h / TILE_MAX_H)} fatias "
                f"(máx. {MAX_TILES}) — divida o arquivo em partes menores"
            )
        pages = [_to_rgb_on_white(doc[i].render(scale=scale).to_pil()) for i in range(len(doc))]
    except TooManyTilesError:
        raise
    except Exception:
        return None
    finally:
        doc.close()
    total_h = sum(p.height for p in pages)
    width = max(p.width for p in pages)
    canvas = Image.new("RGB", (width, total_h), "white")
    y = 0
    for p in pages:
        canvas.paste(p, (0, y))
        y += p.height
    return _tile(canvas)


def _page_has_text(page) -> bool:
    try:
        return page.get_textpage().count_chars() >= 20
    except Exception:
        return False
