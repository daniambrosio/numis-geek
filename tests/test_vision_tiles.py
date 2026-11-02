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
    # Margens laterais vazias são cortadas antes do resize.
    scale = vt.TILE_MAX_W / vt._trim_side_margins(img).width
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
    assert total > (p1.height + p2.height) * vt.TILE_MAX_W / 3200  # margem cortada → escala maior
    assert all(Image.open(BytesIO(b)).height <= vt.TILE_MAX_H for b, _ in tiles)


def test_invalid_pdf_falls_back_to_document():
    pytest.importorskip("pypdfium2")
    assert vt.pdf_screenshot_tiles(b"%PDF-1.4 fake") is None


# ── audit adversarial 2026-11-02 ─────────────────────────────────────────────


def _text_pdf(width=300, height=2000, text="Saldo em conta 1.234,56 " * 3):
    """PDF mínimo com camada de texto real (Helvetica), página alta."""
    content = f"BT /F1 10 Tf 20 {height - 40} Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
        f"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>".encode(),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + o + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return out.getvalue()


def test_tall_pdf_with_text_layer_stays_a_document():
    """PDF alto COM texto (ex.: extrato gerado por sistema) vai como document
    block — a API lê a camada de texto, melhor que OCR de bitmap."""
    pytest.importorskip("pypdfium2")
    assert vt.pdf_screenshot_tiles(_text_pdf()) is None


def test_narrow_screenshot_pdf_is_upscaled_not_72dpi():
    """Página-imagem estreita (390pt, export de celular) renderiza acima de
    72 dpi: a fatia sai na largura cheia, não com 390 px."""
    pytest.importorskip("pypdfium2")
    img, _ = _table_image(width=390, rows=40, row_h=40)
    tiles = vt.pdf_screenshot_tiles(_pdf(img))
    assert tiles
    # Bem acima dos 390 px nativos (margens laterais vazias são cortadas).
    assert Image.open(BytesIO(tiles[0][0])).width >= 1400


def test_transparent_png_is_composited_on_white():
    img = Image.new("RGBA", (400, 1200), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((50, 50, 300, 80), fill=(0, 0, 0, 255))
    tiles = vt.split_image(_png(img), "image/png")
    first = Image.open(BytesIO(tiles[0][0])).convert("L")
    lo, hi = first.getextrema()
    assert hi > 240 and lo < 30  # fundo branco + texto preto, não tudo preto


def test_dense_content_without_gap_overlaps_tiles():
    """Sem faixa vazia (conteúdo denso), corta no limite mas repete
    _OVERLAP px na fatia seguinte — nenhuma linha some na emenda."""
    img = Image.new("RGB", (vt.TILE_MAX_W, 4000), "white")
    d = ImageDraw.Draw(img)
    for y in range(0, 4000, 6):  # "linhas de texto" com respiro de 3 px
        d.rectangle((40, y, vt.TILE_MAX_W - 40, y + 2), fill=(0, 0, 0))
    tiles = vt.split_image(_png(img), "image/png")
    total = sum(Image.open(BytesIO(b)).height for b, _ in tiles)
    assert total == 4000 + vt._OVERLAP * (len(tiles) - 1)


def test_pdf_too_many_tiles_fails_before_rendering(monkeypatch):
    pytest.importorskip("pypdfium2")
    monkeypatch.setattr(vt, "MAX_TILES", 2)
    img, _ = _table_image(width=3200, rows=200)
    with pytest.raises(vt.TooManyTilesError):
        vt.pdf_screenshot_tiles(_pdf(img))


def test_corrupt_tall_image_falls_back_to_original(monkeypatch):
    blob = _png(Image.new("RGB", (400, 1200), "white"))
    monkeypatch.setattr(vt, "_tile", lambda img: (_ for _ in ()).throw(OSError("truncated")))
    assert vt.split_image(blob, "image/png") == [(blob, "image/png")]
