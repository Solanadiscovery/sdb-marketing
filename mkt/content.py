"""Contenuti dei post e controllo di conformità (niente promesse, niente consigli, disclaimer sempre presente)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DISCLAIMER = {
    "it": "Solo informazione, non è un consiglio finanziario. Nessun controllo garantisce che un token sia sicuro.",
    "en": "Information only, not financial advice. No check can guarantee that a token is safe.",
}
MAX_CAPTION = 2200  # limite di Instagram
MAX_HASHTAGS = 8
MAX_SLIDES = 10  # limite dei caroselli di Instagram (copertina e ultima slide incluse)

# Formulazioni vietate: promesse di guadagno, urgenza, consigli personalizzati, garanzie di sicurezza.
BANNED = {
    "it": [r"garantit\w*", r"guadagn\w*", r"profitt\w*", r"rendiment\w*", r"senza rischi", r"rischio zero",
           r"\bx\s?\d{2,}\b", r"\b\d{2,}\s?x\b", r"ricc(o|hi|hezza)\b", r"\b(compra|acquista)\b\s*(ora|subito|adesso|!)", r"investi\w*",
           r"consigli\w*", r"\bsicur[oiae]\b", r"ultima occasione", r"non perdere", r"to the moon",
           r"\bgemm[ae]\b"],
    "en": [r"guarantee\w*", r"profit\w*", r"returns?\b", r"earn\w*", r"risk[- ]free", r"no risk", r"\bx\s?\d{2,}\b",
           r"\b\d{2,}\s?x\b", r"get rich", r"\brich\b", r"\bbuy now\b", r"\binvest\w*", r"\badvice\b", r"\bsafe\b",
           r"last chance", r"don'?t miss", r"to the moon", r"\bgems?\b"],
}
# Frasi consentite che contengono parole vietate (negazioni e disclaimer): vengono tolte prima del controllo.
ALLOWED = {
    "it": [DISCLAIMER["it"], r"non è un consiglio finanziario", r"non consigli finanziari", r"nessuna garanzia", r"non garantisce\w*",
           r"non garantiscono", r"non (è|vuol dire|significa) sicur\w*", r"revocata non vuol dire sicuro",
           r"garantisce che un token sia sicuro", r"mai trattato come sicuro", r"non rendono un token sicuro"],
    "en": [DISCLAIMER["en"], r"not financial advice", r"not a guarantee", r"no guarantee", r"does not guarantee", r"cannot guarantee",
           r"do not guarantee", r"does not mean safe", r"is not safe", r"not safe",
           r"guarantee that a token is safe", r"never treated as safe", r"do not make a token safe"],
}


@dataclass(frozen=True)
class Slide:
    h: str
    b: str


@dataclass(frozen=True)
class Post:
    id: str
    lang: str
    title: str
    sub: str
    slides: tuple[Slide, ...]
    caption: str
    hashtags: tuple[str, ...]

    def full_caption(self) -> str:
        return f"{self.caption}\n\n{DISCLAIMER[self.lang]}\n\n{' '.join(self.hashtags)}"


def load_posts(path: Path, lang: str) -> list[Post]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    out: list[Post] = []
    for p in data["posts"]:
        t = p[lang]
        out.append(Post(id=p["id"], lang=lang, title=t["title"], sub=t["sub"],
                        slides=tuple(Slide(s["h"], s["b"]) for s in t["slides"]), caption=t["caption"],
                        hashtags=tuple(t["hashtags"])))
    return out


def lint(post: Post) -> list[str]:
    """Elenco dei problemi di conformità (vuoto = ok). Un post con problemi non viene mai pubblicato."""
    issues: list[str] = []
    text = " ".join([post.title, post.sub, post.caption] + [f"{s.h} {s.b}" for s in post.slides])
    for allowed in ALLOWED[post.lang]:
        text = re.sub(allowed, " ", text, flags=re.IGNORECASE)
    for pattern in BANNED[post.lang]:
        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            issues.append(f"formulazione vietata: '{m.group(0)}'")
    full = post.full_caption()
    if DISCLAIMER[post.lang] not in full:
        issues.append("manca il disclaimer")
    if len(full) > MAX_CAPTION:
        issues.append(f"didascalia troppo lunga ({len(full)} > {MAX_CAPTION})")
    if len(post.hashtags) > MAX_HASHTAGS or any(not re.fullmatch(r"#\w+", h) for h in post.hashtags):
        issues.append("hashtag non validi o troppi")
    if not 1 <= len(post.slides) + 2 <= MAX_SLIDES:  # + copertina + slide finale
        issues.append("numero di slide non valido")
    if re.search(r"https?://|www\.|t\.me/", full, flags=re.IGNORECASE):
        issues.append("link nella didascalia: su Instagram non sono cliccabili, usa 'link in bio'")
    return issues
