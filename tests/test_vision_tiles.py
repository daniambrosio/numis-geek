"""Fatiamento de screenshots/PDFs altos (bug Avenue Out/26, 2026-11-02)."""
from io import BytesIO

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from numis_geek.services import vision_tiles as vt  # noqa: E402


def _table_image(width=3200, rows=120, row_h=110, line_gap=8):
    """Imagem tipo app: cada "linha de tabela" tem 2 linhas de texto com
    respiro curto entre elas (nome / subtítulo) e respiro longo entre rows.
    Retorna (img, lista de (y0, y1) de cada row em coordenadas originais)."""
    h = rows * row_h
    img = Image.new("RGB", (width, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    spans = []
    for r in range(rows):
        y0 = r * row_h + 30
        d.rectangle((200, y0, 2000, y0 + 22), fill=(20, 20, 20))           # nome
        y1 = y0 + 22 + line_gap
        d.rectangle((200, y1, 900, y1 + 16), fill=(150, 150, 150))         # subtítulo cinza
        spans.append((y0, y1 + 16))
        # bordas verticais de card (não podem impedir o corte)
        d.line((100, r * row_h, 100, (r + 1) * row_h), fill=(200, 200, 200))
        d.line((3100, r * row_h, 3100, (r + 1) * row_h), fill=(200, 200, 200))
    return img, spans


def _png(img):
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_normal_screenshot_passes_through_untouched():
    blob = _png(Image.new("RGB", (1600, 1000), "white"))
    assert vt.split_image(blob, "image/png") == [(blob, "image/png")]


def test_tall_screenshot_is_tiled_without_cutting_table_rows():
    img, spans = _table_image()
    tiles = vt.split_image(_png(img), "image/png")
    assert len(tiles) > 1
    scale = vt.TILE_MAX_W / img.width
    cuts, y = [], 0
    for blob, mime in tiles:
        t = Image.open(BytesIO(blob))
        assert mime == "image/jpeg"
        assert t.width == vt.TILE_MAX_W and t.height <= vt.TILE_MAX_H
        y += t.height
        cuts.append(y)
    assert cuts[-1] == round(img.height * scale)
    # Nenhum corte cai dentro de uma row (incluindo o respiro nome/subtítulo).
    for c in cuts[:-1]:
        orig = c / scale
        for y0, y1 in spans:
            assert not (y0 - 2 <= orig <= y1 + 2), f"corte em {orig:.0f} parte a row {y0}-{y1}"


def test_tile_count_is_capped(monkeypatch):
    monkeypatch.setattr(vt, "MAX_TILES", 3)
    img = Image.new("RGB", (1400, 1400 * 6), "white")
    with pytest.raises(vt.TooManyTilesError):
        vt.split_image(_png(img), "image/png")


def _pdf(*pages):
    buf = BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=list(pages[1:]))
    return buf.getvalue()


def test_pdf_with_normal_pages_stays_a_document():
    pytest.importorskip("pypdfium2")
    a4 = Image.new("RGB", (595, 842), "white")
    assert vt.pdf_screenshot_tiles(_pdf(a4, a4)) is None


def test_screenshot_pdf_is_stitched_and_tiled():
    """Página 1 alta + página 2 curta (formato do export do app Avenue): as
    páginas são costuradas antes de fatiar, então a soma das alturas das
    fatias cobre as duas páginas."""
    pytest.importorskip("pypdfium2")
    p1, _ = _table_image(width=3200, rows=60)
    p2, _ = _table_image(width=3200, rows=10)
    tiles = vt.pdf_screenshot_tiles(_pdf(p1, p2))
    assert tiles is not None and len(tiles) > 1
    total = sum(Image.open(BytesIO(b)).height for b, _ in tiles)
    expected = (p1.height + p2.height) * vt.TILE_MAX_W / 3200
    assert abs(total - expected) <= 3
    assert all(Image.open(BytesIO(b)).height <= vt.TILE_MAX_H for b, _ in tiles)


def test_invalid_pdf_falls_back_to_document():
    pytest.importorskip("pypdfium2")
    assert vt.pdf_screenshot_tiles(b"%PDF-1.4 fake") is None
