"""Grafica di feed (1080x1350) e storie (1080x1920), sempre con la STESSA mascotte (assets/mascot.png).
La mascotte non viene mai ridisegnata né sostituita: si usano i pixel dell'immagine originale (ritaglio o intera)."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
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
UI = {"it": {"swipe": "Scorri  →", "cta_tag": "LINK IN BIO"},
      "en": {"swipe": "Swipe  →", "cta_tag": "LINK IN BIO"}}
# Ogni contenuto cambia colore d'accento, etichetta e frase della storia: il feed non risulta monotono.
ACCENTS = [GREEN, (0, 205, 255), (255, 196, 61), (190, 140, 255), (255, 120, 150), (120, 230, 120)]
STORY_TAGS = {"it": ["OGGI NEL FEED", "NUOVO POST", "IMPARA IN 1 MINUTO", "DA SAPERE", "GUIDA RAPIDA", "SPIEGATO SEMPLICE"],
              "en": ["TODAY IN THE FEED", "NEW POST", "LEARN IN 1 MINUTE", "GOOD TO KNOW", "QUICK GUIDE", "EXPLAINED SIMPLY"]}
STORY_LINES = {"it": ["Provalo gratis su Telegram", "Apri il bot dal link in bio", "Analisi dei token in 30 secondi",
                      "Il bot è su Telegram, gratis"],
               "en": ["Try it free on Telegram", "Open the bot from the link in bio", "Token analysis in 30 seconds",
                      "The bot is on Telegram, free"]}


def variant(post: Post) -> int:
    """Numero del contenuto (p07-… → 6): decide colore, etichetta e frase."""
    m = re.match(r"p(\d+)", post.id)
    return int(m.group(1)) - 1 if m else sum(map(ord, post.id))


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


def background(size: tuple[int, int], v: int = 0) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, BG_TOP)
    px = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        px.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM, strict=True)))
    glow = Image.new("RGB", size, (0, 0, 0))
    g = ImageDraw.Draw(glow)
    ax, bx = (w - 520, -300) if v % 2 == 0 else (-260, w - 420)
    g.ellipse([ax, -260, ax + 780, 520], fill=(40, 20, 100))
    g.ellipse([bx, h - 420, bx + 720, h + 300], fill=(0, 50, 56))
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


# Ritagli del poster originale (coordinate 1086x1448): stessa mascotte, inquadrature diverse.
CROPS = {"full": (90, 250, 930, 1010), "head": (300, 290, 760, 700), "scan": (100, 520, 900, 1000),
         "bust": (200, 300, 760, 800)}
CUT_X, CUT_Y = 725, 730  # a destra di CUT_X e sopra CUT_Y c'è il menu del poster: va escluso
# Umore = colore del bagliore (celeste originale, rosso allarme, ambra attenzione, verde ok, magenta, oro).
HUES = {"cyan": None, "red": 250, "amber": 20, "green": 85, "magenta": 215, "gold": 30}


@dataclass(frozen=True)
class Scene:
    crop: str = "full"
    width: int = 920  # larghezza nel feed (la storia usa 0.98 di questo)
    dx: int = 0  # spostamento orizzontale (px)
    rot: float = 0.0  # inclinazione in gradi
    hue: str = "cyan"
    icon: str = ""


# Una scena per ogni contenuto: posa, inquadratura, inclinazione, umore (colore) e simbolo cambiano a ogni uscita.
SCENES = {
    "p01-cos-e": Scene("full", 940, 0, 0, "cyan", "magnifier"),
    "p02-allarmi": Scene("head", 800, 40, -7, "red", "warning"),
    "p03-mint": Scene("bust", 860, -50, 5, "amber", "lock"),
    "p04-holder": Scene("full", 900, 60, -5, "magenta", "pie"),
    "p05-liquidita": Scene("scan", 1000, -20, 4, "cyan", "drop"),
    "p06-vendita": Scene("scan", 960, 30, -6, "amber", "question"),
    "p07-attesa": Scene("head", 760, -60, 8, "green", "hourglass"),
    "p08-punteggio": Scene("bust", 880, 40, -4, "green", "gauge"),
    "p09-progetto": Scene("full", 880, -40, 6, "cyan", "doc"),
    "p10-nessun-wallet": Scene("head", 820, 30, -8, "green", "stop"),
    "p11-free-premium": Scene("bust", 840, -30, 7, "gold", "star"),
    "p12-provalo": Scene("full", 960, 50, -9, "cyan", "plane"),
}
CONTENT_CROPS = ["scan", "bust", "head", "full", "scan", "bust"]


def scene_of(post: Post) -> Scene:
    return SCENES.get(post.id) or Scene(CONTENT_CROPS[variant(post) % 4], 900, 0, (variant(post) % 5 - 2) * 3,
                                        list(HUES)[variant(post) % len(HUES)])


@lru_cache(maxsize=32)
def _crop(name: str, hue: str) -> tuple[Image.Image, Image.Image]:
    """Ritaglio della mascotte originale + maschera morbida (esclude il menu); l'umore ruota solo il celeste."""
    box = CROPS[name]
    crop = poster().crop(box)
    target = HUES[hue]
    if target is not None:
        hch, sch, vch = crop.convert("HSV").split()
        sel = ImageChops.multiply(hch.point(lambda x: 255 if 108 < x < 150 else 0),
                                  sch.point(lambda x: 255 if x > 70 else 0))
        crop = Image.merge("HSV", (Image.composite(Image.new("L", crop.size, target), hch, sel), sch, vch)).convert("RGB")
    fade = min(70, min(crop.size) // 6)
    mask = _edge_fade(crop.size, fade)
    cut = Image.new("L", crop.size, 255)
    ImageDraw.Draw(cut).rectangle([CUT_X - box[0], 0, crop.size[0], CUT_Y - box[1]], fill=0)
    return crop, ImageChops.multiply(mask, cut.filter(ImageFilter.GaussianBlur(28)))


def paste_scene(img: Image.Image, sc: Scene, width: int, bottom: int, cx: int) -> None:
    """Incolla la mascotte con l'inquadratura/inclinazione della scena, appoggiata a 'bottom', centrata su cx."""
    crop, mask = _crop(sc.crop, sc.hue)
    h = round(crop.size[1] * width / crop.size[0])
    pic = crop.resize((width, h), Image.LANCZOS).convert("RGBA")
    pic.putalpha(mask.resize((width, h), Image.LANCZOS))
    if sc.rot:
        pic = pic.rotate(sc.rot, resample=Image.BICUBIC, expand=True)
    img.paste(pic, (cx - pic.size[0] // 2, bottom - pic.size[1]), pic)


def paste_robot(img: Image.Image, width: int, x: int, y: int) -> None:
    """Compatibilità: mascotte intera, senza variazioni."""
    paste_scene(img, Scene("full", width), width * 760 // 840 + y, x + width // 2)


def draw_icon(d: ImageDraw.ImageDraw, kind: str, cx: int, cy: int, acc: tuple[int, int, int]) -> None:
    """Simbolo dell'argomento in un disco, vicino alla mascotte (disegnato, nessun file esterno)."""
    d.ellipse([cx - 92, cy - 92, cx + 92, cy + 92], fill=(10, 14, 40), outline=acc, width=6)
    w = 9
    if kind == "magnifier":
        d.ellipse([cx - 44, cy - 50, cx + 22, cy + 16], outline=acc, width=w)
        d.line([cx + 16, cy + 12, cx + 52, cy + 48], fill=acc, width=w + 3)
    elif kind == "warning":
        d.polygon([(cx, cy - 55), (cx + 58, cy + 42), (cx - 58, cy + 42)], outline=acc, width=w)
        d.text((cx, cy + 6), "!", font=font("Bold", 62), fill=acc, anchor="mm")
    elif kind == "lock":
        d.arc([cx - 30, cy - 62, cx + 30, cy + 2], 180, 360, fill=acc, width=w)
        d.rounded_rectangle([cx - 44, cy - 16, cx + 44, cy + 50], radius=10, fill=acc)
        d.ellipse([cx - 8, cy + 2, cx + 8, cy + 18], fill=(10, 14, 40))
    elif kind == "pie":
        d.ellipse([cx - 52, cy - 52, cx + 52, cy + 52], outline=acc, width=w)
        d.pieslice([cx - 52, cy - 52, cx + 52, cy + 52], -90, 40, fill=acc)
    elif kind == "drop":
        d.polygon([(cx, cy - 58), (cx + 34, cy + 6), (cx - 34, cy + 6)], fill=acc)
        d.ellipse([cx - 36, cy - 8, cx + 36, cy + 52], fill=acc)
    elif kind == "question":
        d.text((cx, cy + 2), "?", font=font("Bold", 110), fill=acc, anchor="mm")
    elif kind == "hourglass":
        d.polygon([(cx - 40, cy - 54), (cx + 40, cy - 54), (cx, cy)], outline=acc, width=w)
        d.polygon([(cx, cy), (cx + 40, cy + 54), (cx - 40, cy + 54)], fill=acc)
    elif kind == "gauge":
        d.arc([cx - 56, cy - 48, cx + 56, cy + 64], 180, 360, fill=acc, width=w)
        d.line([cx, cy + 8, cx + 34, cy - 30], fill=acc, width=w)
        d.ellipse([cx - 9, cy - 1, cx + 9, cy + 17], fill=acc)
    elif kind == "doc":
        d.rounded_rectangle([cx - 36, cy - 54, cx + 36, cy + 54], radius=8, outline=acc, width=w)
        for k in range(3):
            d.line([cx - 20, cy - 24 + k * 22, cx + 20, cy - 24 + k * 22], fill=acc, width=7)
    elif kind == "stop":
        d.ellipse([cx - 52, cy - 52, cx + 52, cy + 52], outline=acc, width=w + 2)
        d.line([cx - 38, cy + 38, cx + 38, cy - 38], fill=acc, width=w + 2)
    elif kind == "star":
        pts = [(cx + (58 if k % 2 == 0 else 24) * math.sin(k * math.pi / 5),
                cy - (58 if k % 2 == 0 else 24) * math.cos(k * math.pi / 5)) for k in range(10)]
        d.polygon(pts, fill=acc)
    elif kind == "plane":
        d.polygon([(cx - 56, cy - 4), (cx + 58, cy - 46), (cx + 20, cy + 50), (cx - 2, cy + 14)], fill=acc)
        d.line([(cx - 2, cy + 14), (cx + 58, cy - 46)], fill=(10, 14, 40), width=6)


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


def _dots(draw: ImageDraw.ImageDraw, size: tuple[int, int], index: int, total: int, acc=GREEN) -> None:
    for i in range(total):
        x = MARGIN + i * 34
        draw.rounded_rectangle([x, size[1] - 70, x + 22, size[1] - 64], radius=3,
                               fill=acc if i == index else (70, 76, 104))


def _brand(draw: ImageDraw.ImageDraw, brand: str, y: int, acc=GREEN) -> None:
    draw.rounded_rectangle([MARGIN, y + 6, MARGIN + 14, y + 20], radius=4, fill=acc)
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


def _story_cta(d: ImageDraw.ImageDraw, post: Post, v: int, acc: tuple[int, int, int]) -> None:
    """Fascia in basso a ogni storia: LINK IN BIO ben visibile, con una frase che cambia da un giorno all'altro."""
    w = STORY[0]
    label, line = UI[post.lang]["cta_tag"], STORY_LINES[post.lang][v % len(STORY_LINES[post.lang])]
    big = font("Bold", 64)
    box_w = min(w - 2 * MARGIN, 90 + int(d.textlength(label + "  ↑", font=big)))
    x0 = (w - box_w) // 2
    d.rounded_rectangle([x0, 1700, x0 + box_w, 1810], radius=55, fill=acc)
    d.text((w // 2, 1755), label + "  ↑", font=big, fill=(6, 10, 30), anchor="mm")
    d.text((w // 2, 1850), line, font=font("SemiBold", 32), fill=WHITE, anchor="mm")


def slide_image(kind: str, post: Post, brand: str, index: int, total: int, n: int = 0,
                fmt: str = "feed") -> Image.Image:
    """kind: cover | content | cta. fmt: feed (4:5) | story (9:16)."""
    size = FEED if fmt == "feed" else STORY
    w, h = size
    ui = UI[post.lang]
    v = variant(post)
    acc = ACCENTS[v % len(ACCENTS)]
    img = background(size, v)
    story = fmt != "feed"
    if kind == "cover":
        sc = scene_of(post)
        custom = ROOT / "assets" / "mascot_variants" / f"{post.id}.png"
        if custom.is_file():  # eventuale illustrazione nuova (posa/espressione diversa) fornita dal titolare
            art = Image.open(custom).convert("RGBA")
            aw = 960 if not story else 940
            art = art.resize((aw, round(art.size[1] * aw / art.size[0])), Image.LANCZOS)
            img.paste(art, ((w - aw) // 2, (850 if not story else 1190) - art.size[1]), art)
        else:
            paste_scene(img, sc, round(sc.width * (1 if not story else 0.98)), 850 if not story else 1190,
                        w // 2 + sc.dx)
        _fade_bottom(img, int(h * (0.55 if not story else 0.57)))
        d = ImageDraw.Draw(img)
        _brand(d, brand, 70 if not story else 230, acc)
        if sc.icon:
            draw_icon(d, sc.icon, w - 170, 200 if not story else 520, acc)
        if fmt == "story":
            tag = STORY_TAGS[post.lang][v % len(STORY_TAGS[post.lang])]
            d.rounded_rectangle([MARGIN, 300, MARGIN + 38 + int(d.textlength(tag, font=font("Bold", 28))), 360],
                                radius=30, fill=acc)
            d.text((MARGIN + 19, 313), tag, font=font("Bold", 28), fill=(6, 10, 30))
        top = int(h * (0.69 if not story else 0.65))
        d.text((MARGIN, top - 56), post.sub.upper(), font=font("SemiBold", 28), fill=acc)
        _text(d, post.title, "", top, h - (250 if story else 150), 100, 40, w - 2 * MARGIN)
        if not story:
            d.text((MARGIN, h - 120), ui["swipe"], font=font("SemiBold", 32), fill=MUTED)
            _dots(d, size, index, total, acc)
        else:
            _story_cta(d, post, v, acc)
    elif kind == "content":
        s = post.slides[n]
        d = ImageDraw.Draw(img)
        _brand(d, brand, 70 if not story else 230, acc)
        numbered = bool(re.match(r"\d\.", s.h))
        top = 150 if not story else 330
        if not numbered:
            d.text((MARGIN, top), f"{n + 1:02d}", font=font("Bold", 100), fill=(70, 60, 120))
            top += 120
        _text(d, s.h, s.b, top, 700 if not story else 1010, 78, 48, w - 2 * MARGIN)
        sc = scene_of(post)
        alt = Scene(CONTENT_CROPS[(variant(post) + n) % len(CONTENT_CROPS)], 640 if not story else 940,
                    (-1) ** (variant(post) + n) * 160, sc.rot / 2 + (n % 3 - 1) * 2, sc.hue)
        paste_scene(img, alt, alt.width, 1340 if not story else 1860, w // 2 + (alt.dx if not story else 0))
        if not story:
            _dots(ImageDraw.Draw(img), size, index, total, acc)
    else:  # cta: il poster originale con titolo, più etichetta e disclaimer
        paste_poster(img, 0 if not story else 150, 1350 if not story else None)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([MARGIN, 60 if not story else 70, MARGIN + 250, 120 if not story else 130], radius=30,
                            fill=acc)
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
