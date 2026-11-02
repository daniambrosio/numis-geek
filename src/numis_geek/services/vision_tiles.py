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

# Fatias de até 1400×1400 ≈ 1.96 MP: a API reduz pra ~1.15 MP (~1070 px de
# lado), o que mantém legível texto de UI renderizado a 2-3× (retina).
TILE_MAX_W = 1400
TILE_MAX_H = 1400
# Quanto subir a partir do corte ideal procurando uma faixa em branco.
_CUT_SEARCH = 400
# Linha "vazia": no máximo _ROW_MAX_OFF pixels fogem da mediana da linha
# por > _ROW_TOL_LEVEL níveis de cinza. Contagem absoluta (não fração):
# subtítulo cinza pequeno ocupa < 1% da linha e passava como vazia; as
# bordas verticais de card somam só ~2-6 px.
_ROW_TOL_LEVEL = 10
_ROW_MAX_OFF = 6
# Altura mínima (px, na largura final) da faixa vazia onde se pode cortar.
_MIN_GAP = 14
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


def _uniform_rows(gray):
    """Máscara bool por linha: True quando a linha é "vazia" (fundo)."""
    import numpy as np

    med = np.median(gray, axis=1, keepdims=True)
    off = np.abs(gray.astype(np.int16) - med) > _ROW_TOL_LEVEL
    return off.sum(axis=1) <= _ROW_MAX_OFF


def _find_cut(uniform, start: int, target: int) -> int:
    """Corte no meio da faixa vazia (≥ _MIN_GAP linhas) mais perto de target.

    Exigir uma faixa — e não uma linha vazia qualquer — evita cortar no
    respiro de 4-6 px entre o nome e o subtítulo de uma MESMA linha de
    tabela (ex.: "Banco do Brasil" / "CD BANCO DO BRASIL 4.22").
    """
    lo = max(start + 1, target - _CUT_SEARCH)
    y = target
    while y >= lo:
        if not uniform[y]:
            y -= 1
            continue
        end = y
        while y >= lo and uniform[y]:
            y -= 1
        begin = y + 1
        # Faixa pode continuar abaixo do target (ainda é espaço vazio).
        run = end - begin + 1
        if run >= _MIN_GAP:
            return (begin + end + 1) // 2
    return target


def _tile(img) -> list[tuple[bytes, str]]:
    """Reduz largura e fatia verticalmente em cortes limpos. Retorna JPEGs."""
    import numpy as np
    from PIL import Image

    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if w > TILE_MAX_W:
        new_h = max(1, round(h * TILE_MAX_W / w))
        img = img.resize((TILE_MAX_W, new_h), Image.LANCZOS)
        w, h = img.size
    uniform = _uniform_rows(np.asarray(img.convert("L")))
    tiles: list[tuple[bytes, str]] = []
    top = 0
    while top < h:
        if h - top <= TILE_MAX_H:
            bottom = h
        else:
            bottom = _find_cut(uniform, top, top + TILE_MAX_H)
        buf = BytesIO()
        img.crop((0, top, w, bottom)).save(buf, format="JPEG", quality=90)
        tiles.append((buf.getvalue(), "image/jpeg"))
        if len(tiles) > MAX_TILES:
            raise TooManyTilesError(
                f"documento grande demais: mais de {MAX_TILES} fatias — "
                "divida o arquivo em partes menores"
            )
        top = bottom
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
    return _tile(img)


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
        widest = max(w for w, _ in sizes)
        # Renderiza já na largura final (evita bitmap gigante em memória).
        scale = min(1.0, TILE_MAX_W / widest) if widest > TILE_MAX_W else TILE_MAX_W / widest
        pages = [doc[i].render(scale=scale).to_pil().convert("RGB") for i in range(len(doc))]
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
