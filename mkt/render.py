"""Grafica di feed (1080x1350) e storie (1080x1920), sempre con la STESSA mascotte (assets/mascot.png).
La mascotte non viene mai ridisegnata né sostituita: si usano i pixel dell'immagine originale (ritaglio o intera)."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from mkt.content import DISCLAIMER, Post

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
MASCOT = ROOT / "assets" / "mascot.png"
FEED, STORY = (1080, 1350), (1080, 1920)
BG_TOP, BG_BOTTOM = (6, 10, 30), (14, 12, 44)
GREEN, PURPLE, WHITE, MUTED = (20, 241, 149), (153, 69, 255), (244, 246, 252), (160, 168, 194)
MARGIN = 84
ROBOT_BOX = (90, 250, 930, 1010)  # robot, scanner e token nel poster originale (1086x1448)
UI = {"it": {"swipe": "Scorri  →", "cta_tag": "LINK IN BIO", "story_tag": "OGGI NEL FEED"},
      "en": {"swipe": "Swipe  →", "cta_tag": "LINK IN BIO", "story_tag": "TODAY IN THE FEED"}}


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"Inter-{weight}.otf"), size)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=fnt) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def fit(draw: ImageDraw.ImageDraw, text: str, weight: str, start: int, minimum: int, width: int, max_h: int,
        spacing: float = 1.22) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Il corpo più grande per cui il testo sta nel riquadro."""
    size = start
    while True:
        fnt = font(weight, size)
        lines = wrap(draw, text, fnt, width)
        if int(len(lines) * size * spacing) <= max_h or size <= minimum:
            return fnt, lines
        size -= 2


def background(size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, BG_TOP)
    px = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        px.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM, strict=True)))
    glow = Image.new("RGB", size, (0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse([w - 520, -260, w + 260, 520], fill=(40, 20, 100))
    g.ellipse([-300, h - 420, 420, h + 300], fill=(0, 50, 56))
    return ImageChops.add(img, glow.filter(ImageFilter.GaussianBlur(160)))


@lru_cache(maxsize=1)
def poster() -> Image.Image:
    return Image.open(MASCOT).convert("RGB")


def _edge_fade(size: tuple[int, int], fade: int) -> Image.Image:
    """Maschera che sfuma i bordi del ritaglio: la mascotte si fonde con lo sfondo senza tagli netti."""
    w, h = size
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rectangle([fade, fade, w - fade, h - fade], fill=255)
    return m.filter(ImageFilter.GaussianBlur(fade / 2.2))


@lru_cache(maxsize=1)
def robot() -> tuple[Image.Image, Image.Image]:
    """Ritaglio del robot dal poster originale e maschera (esclude il menu a destra, tagliato nel ritaglio)."""
    crop = poster().crop(ROBOT_BOX)
    mask = _edge_fade(crop.size, 70)
    cut = Image.new("L", crop.size, 255)
    ImageDraw.Draw(cut).rectangle([640, 0, crop.size[0], 480], fill=0)
    return crop, ImageChops.multiply(mask, cut.filter(ImageFilter.GaussianBlur(28)))


def paste_robot(img: Image.Image, width: int, x: int, y: int) -> None:
    crop, mask = robot()
    h = round(crop.size[1] * width / crop.size[0])
    img.paste(crop.resize((width, h), Image.LANCZOS), (x, y), mask.resize((width, h), Image.LANCZOS))


def paste_poster(img: Image.Image, y: int, height: int | None = None) -> None:
    """Il poster intero (titolo compreso), centrato in larghezza e ritagliato in alto/basso se serve."""
    w = img.size[0]
    p = poster().resize((w, round(poster().size[1] * w / poster().size[0])), Image.LANCZOS)
    height = height or p.size[1]
    top = (p.size[1] - height) // 2
    piece = p.crop((0, top, w, top + height))
    img.paste(piece, (0, y), _edge_fade(piece.size, 36))


def _fade_bottom(img: Image.Image, start: int, strength: float = 0.94) -> None:
    h = img.size[1]
    shade = Image.new("L", (1, h), 0)
    for y in range(start, h):
        shade.putpixel((0, y), int(255 * strength * min(1.0, (y - start) / max(1, (h - start) * 0.55)) ** 1.2))
    img.paste(Image.new("RGB", img.size, BG_TOP), (0, 0), shade.resize(img.size))


def _dots(draw: ImageDraw.ImageDraw, size: tuple[int, int], index: int, total: int) -> None:
    for i in range(total):
        x = MARGIN + i * 34
        draw.rounded_rectangle([x, size[1] - 70, x + 22, size[1] - 64], radius=3,
                               fill=GREEN if i == index else (70, 76, 104))


def _brand(draw: ImageDraw.ImageDraw, brand: str, y: int) -> None:
    draw.rounded_rectangle([MARGIN, y + 6, MARGIN + 14, y + 20], radius=4, fill=GREEN)
    draw.text((MARGIN + 30, y), brand.upper(), font=font("SemiBold", 26), fill=MUTED)


def _text(draw: ImageDraw.ImageDraw, heading: str, body: str, top: int, bottom: int, h_start: int, b_start: int,
          width: int) -> int:
    """Titolo e testo nella zona [top, bottom]; restituisce la y finale."""
    hf, hl = fit(draw, heading, "Bold", h_start, 50, width, int((bottom - top) * 0.5), 1.14)
    y = top
    for line in hl:
        draw.text((MARGIN, y), line, font=hf, fill=WHITE)
        y += int(hf.size * 1.14)
    draw.rounded_rectangle([MARGIN, y + 20, MARGIN + 120, y + 28], radius=4, fill=PURPLE)
    y += 62
    if body:
        bf, bl = fit(draw, body, "Regular", b_start, 32, width, bottom - y)
        for line in bl:
            draw.text((MARGIN, y), line, font=bf, fill=(214, 219, 236))
            y += int(bf.size * 1.4)
    return y


def slide_image(kind: str, post: Post, brand: str, index: int, total: int, n: int = 0,
                fmt: str = "feed") -> Image.Image:
    """kind: cover | content | cta. fmt: feed (4:5) | story (9:16)."""
    size = FEED if fmt == "feed" else STORY
    w, h = size
    ui = UI[post.lang]
    img = background(size)
    story = fmt != "feed"
    if kind == "cover":
        paste_robot(img, 920 if not story else 900, 80 if not story else 90, 20 if not story else 370)
        _fade_bottom(img, int(h * (0.55 if not story else 0.57)))
        d = ImageDraw.Draw(img)
        _brand(d, brand, 70 if not story else 230)
        if fmt == "story":
            d.rounded_rectangle([MARGIN, 300, MARGIN + 38 + int(d.textlength(ui["story_tag"], font=font("Bold", 28))),
                                 360], radius=30, fill=GREEN)
            d.text((MARGIN + 19, 313), ui["story_tag"], font=font("Bold", 28), fill=(6, 10, 30))
        top = int(h * (0.69 if not story else 0.65))
        d.text((MARGIN, top - 56), post.sub.upper(), font=font("SemiBold", 28), fill=GREEN)
        _text(d, post.title, "", top, h - (230 if story else 150), 100, 40, w - 2 * MARGIN)
        if not story:
            d.text((MARGIN, h - 120), ui["swipe"], font=font("SemiBold", 32), fill=MUTED)
            _dots(d, size, index, total)
    elif kind == "content":
        s = post.slides[n]
        d = ImageDraw.Draw(img)
        _brand(d, brand, 70 if not story else 230)
        numbered = bool(re.match(r"\d\.", s.h))
        top = 150 if not story else 330
        if not numbered:
            d.text((MARGIN, top), f"{n + 1:02d}", font=font("Bold", 100), fill=(70, 60, 120))
            top += 120
        _text(d, s.h, s.b, top, 700 if not story else 1010, 78, 48, w - 2 * MARGIN)
        if story:
            paste_robot(img, 940, 70, 1000)
        else:
            paste_robot(img, 640, 280, 760)
        if not story:
            _dots(ImageDraw.Draw(img), size, index, total)
    else:  # cta: il poster originale con titolo, più etichetta e disclaimer
        paste_poster(img, 0 if not story else 150, 1350 if not story else None)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([MARGIN, 60 if not story else 70, MARGIN + 250, 120 if not story else 130], radius=30,
                            fill=GREEN)
        d.text((MARGIN + 28, 72 if not story else 82), ui["cta_tag"], font=font("Bold", 28), fill=(6, 10, 30))
        small = font("Regular", 24)
        y0 = (1255 if not story else 1620)
        d.rectangle([0, y0 - 14, w, y0 + 70], fill=BG_TOP)
        for i, line in enumerate(wrap(d, DISCLAIMER[post.lang], small, w - 2 * MARGIN)):
            d.text((MARGIN, y0 + i * 32), line, font=small, fill=MUTED)
    return img


def render_post(post: Post, brand: str, out_dir: Path) -> list[Path]:
    """Scrive in out_dir/<id>/: 01.jpg… (carosello del feed) e story.jpg. Restituisce i file del carosello."""
    folder = out_dir / post.id
    folder.mkdir(parents=True, exist_ok=True)
    total = len(post.slides) + 2
    plan = [("cover", 0)] + [("content", i) for i in range(len(post.slides))] + [("cta", 0)]
    paths: list[Path] = []
    for idx, (kind, n) in enumerate(plan):
        path = folder / f"{idx + 1:02d}.jpg"
        slide_image(kind, post, brand, idx, total, n).save(path, "JPEG", quality=92, optimize=True, subsampling=0)
        paths.append(path)
    slide_image("cover", post, brand, 0, total, fmt="story").save(folder / "story.jpg", "JPEG", quality=92,
                                                                  optimize=True, subsampling=0)
    return paths
