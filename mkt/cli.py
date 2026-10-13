"""Riga di comando: python -m mkt <comando>. Per sicurezza `publish` e `ads-create` simulano finché non si aggiunge --live."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import httpx

from mkt import ads as ads_mod
from mkt.config import ROOT, Config, load_env, secret
from mkt.content import Post, lint, load_posts
from mkt.instagram import Instagram, InstagramError
from mkt.render import render_post
from mkt.schedule import (
    Slot,
    build_plan,
    extend_plan,
    load_plan,
    load_state,
    next_due,
    save_plan,
    save_state,
)

POSTS, OUT, PLAN, STATE = ROOT / "content" / "posts.json", ROOT / "out", ROOT / "plan.json", ROOT / "state.json"


def image_urls(base: str, post: Post) -> list[str]:
    n = len(post.slides) + 2
    return [f"{base.rstrip('/')}/{post.lang}/{post.id}/{i:02d}.jpg" for i in range(1, n + 1)]


def media_urls(base: str, post: Post, kind: str) -> list[str]:
    root = f"{base.rstrip('/')}/{post.lang}/{post.id}"
    return {"post": image_urls(base, post), "story": [f"{root}/story.jpg"]}[kind]


def check_media(client: httpx.Client, url: str) -> None:
    r = client.head(url, timeout=30, follow_redirects=True)
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/jpeg"):
        raise InstagramError(f"file non raggiungibile o formato errato: {url} (HTTP {r.status_code})")


check_image = check_media  # nome storico


def ensure_plan(cfg: Config, today: date | None = None) -> list[Slot]:
    """Calendario sempre pieno: lo crea se manca e lo allunga prima che finisca (nessun intervento manuale)."""
    today = today or datetime.now(ZoneInfo(cfg.timezone)).date()
    plan = load_plan(PLAN) if PLAN.is_file() else []
    ids = [p.id for p in load_posts(POSTS, cfg.language)]
    new = extend_plan(plan, ids, today, cfg.post_days, cfg.post_time, cfg.timezone, cfg.story_time)
    if new != plan:
        save_plan(PLAN, new)
    return new


def cmd_lint(cfg: Config) -> int:
    bad = 0
    for p in load_posts(POSTS, cfg.language):
        for issue in lint(p):
            print(f"{p.id}: {issue}")
            bad += 1
    print("Tutti i post sono conformi." if not bad else f"{bad} problemi.")
    return int(bool(bad))


def cmd_render(cfg: Config, all_langs: bool = False) -> int:
    total = 0
    for lang in ("it", "en") if all_langs else (cfg.language,):
        for p in load_posts(POSTS, lang):
            render_post(p, cfg.brand, OUT / lang)
            total += 1
    print(f"Creati post e storie di {total} contenuti in {OUT}")
    return 0


def cmd_plan(cfg: Config, start: date) -> int:
    ids = [p.id for p in load_posts(POSTS, cfg.language)]
    slots = build_plan(ids, start, cfg.post_days, cfg.post_time, cfg.timezone, cfg.story_time)
    save_plan(PLAN, slots)
    for s in slots:
        print(f"{s.when:%a %d/%m/%Y %H:%M}  {s.kind:5s} {s.id}")
    return 0


def cmd_export(cfg: Config) -> int:
    """Calendario leggibile (date, immagini, didascalie): per pubblicare a mano o con il pianificatore di Meta Business Suite."""
    plan = [s for s in ensure_plan(cfg) if s.kind == "post"]
    posts = {p.id: p for p in load_posts(POSTS, cfg.language)}
    lines = [f"# Calendario Instagram ({cfg.language})\n"]
    for s in plan:
        p = posts[s.id]
        lines += [f"## {s.when:%a %d/%m/%Y %H:%M} · {p.id}", (f"Immagini: out/{cfg.language}/{p.id}/01.jpg … {len(p.slides) + 2:02d}.jpg (in ordine, come carosello)"),
                  "", "```", p.full_caption(), "```", ""]
    path = ROOT / f"calendario_{cfg.language}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Calendario scritto in {path}")
    return 0


def cmd_status(cfg: Config) -> int:
    state, plan = load_state(STATE), ensure_plan(cfg)
    for s in plan:
        done = state.get(s.key)
        print(f"{s.when:%d/%m %H:%M}  {s.kind:5s} {s.id:20s} "
              f"{('saltato' if 'skipped' in done else 'pubblicato ' + done['at']) if done else 'in attesa'}")
    return 0


def cmd_publish(cfg: Config, live: bool) -> int:
    plan = ensure_plan(cfg)
    posts = {p.id: p for p in load_posts(POSTS, cfg.language)}
    state, now = load_state(STATE), datetime.now(UTC)
    slot, skipped = next_due(plan, state, now, cfg.max_late_hours)
    for s in skipped:
        state[s.key] = {"at": now.isoformat(), "skipped": "troppo in ritardo"}
    if skipped and live:
        save_state(STATE, state)
    if slot is None:
        print("Niente da pubblicare adesso.")
        return 0
    post = posts[slot.id]
    if issues := lint(post):
        print(f"{post.id} NON pubblicato, problemi di conformità: {'; '.join(issues)}")
        return 1
    urls = media_urls(secret("MEDIA_BASE_URL"), post, slot.kind)
    if not live:
        print(f"[simulazione] pubblicherei {slot.kind} {post.id} ({len(urls)} file) previsto per {slot.when:%d/%m %H:%M}")
        print(post.full_caption())
        return 0
    with httpx.Client() as http:
        for u in urls:
            check_media(http, u)
        ig = Instagram(http, secret("IG_USER_ID"), secret("IG_ACCESS_TOKEN"), cfg.graph_version)
        used, total = ig.quota_used()
        if used >= total * 0.8:
            print(f"Limite giornaliero quasi raggiunto ({used}/{total}): riprovo più tardi.")
            return 0
        media = (ig.publish_post(urls, post.full_caption()) if slot.kind == "post"
                 else ig.publish_story(urls[0]))
        state[slot.key] = {"at": now.isoformat(), "media_id": media}
        save_state(STATE, state)
        print(f"Pubblicato {slot.kind} {post.id}: {ig.permalink(media) or media}")
    return 0


def cmd_check(cfg: Config) -> int:
    """Verifica che token e account funzionino e che le immagini siano raggiungibili: non pubblica nulla."""
    base = secret("MEDIA_BASE_URL")
    with httpx.Client() as http:
        ig = Instagram(http, secret("IG_USER_ID"), secret("IG_ACCESS_TOKEN"), cfg.graph_version)
        used, total = ig.quota_used()
        print(f"Account Instagram: @{ig.whoami()} · pubblicazioni usate oggi: {used}/{total}")
        first = load_posts(POSTS, cfg.language)[0]
        for kind in ('post', 'story'):
            check_media(http, media_urls(base, first, kind)[0])
        print("Post e storie sono raggiungibili da internet: tutto pronto.")
    return 0


def cmd_ads_blueprint(budget: float, days: int) -> int:
    path = ROOT / "ads_plan.md"
    path.write_text(ads_mod.blueprint(budget, days), encoding="utf-8")
    print(f"Piano scritto in {path}")
    return 0


def cmd_ads_create(cfg: Config, budget: float, days: int, live: bool) -> int:
    ads_mod.check_budget(budget, days, float(os.environ.get("MAX_DAILY_BUDGET_EUR", "5")))
    if not live:
        print(f"[simulazione] creerei una campagna IN PAUSA da {budget:.0f} €/giorno per {days} giorni "
              f"(massimo {budget * days:.0f} €). Aggiungi --live per crearla.")
        return 0
    with httpx.Client() as http:
        res = ads_mod.Ads(http, secret("META_AD_ACCOUNT_ID"), secret("META_ADS_TOKEN"), cfg.graph_version).create_paused(
            f"SDB Traffico {datetime.now(UTC):%Y-%m-%d}", budget, days)
    print(f"Creata in pausa: campagna {res['campaign_id']}, gruppo {res['adset_id']}. "
          "Apri Ads Manager, scegli il post da promuovere e attiva tu.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mkt", description="Campagna Instagram di Solana DEX Discovery")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lint")
    p = sub.add_parser("render")
    p.add_argument("--all", action="store_true", help="anche l'altra lingua")
    sub.add_parser("status")
    sub.add_parser("check")
    sub.add_parser("export")
    p = sub.add_parser("plan")
    p.add_argument("--start", required=True, help="AAAA-MM-GG")
    p = sub.add_parser("publish")
    p.add_argument("--live", action="store_true", help="pubblica davvero (senza: simulazione)")
    p = sub.add_parser("ads-blueprint")
    p.add_argument("--budget", type=float, default=5)
    p.add_argument("--days", type=int, default=7)
    p = sub.add_parser("ads-create")
    p.add_argument("--budget", type=float, default=5)
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--live", action="store_true")
    args = ap.parse_args(argv)
    load_env(ROOT / ".env")
    cfg = Config.load()
    try:
        return {"lint": lambda: cmd_lint(cfg), "render": lambda: cmd_render(cfg, getattr(args, "all", False)), "status": lambda: cmd_status(cfg), "check": lambda: cmd_check(cfg), "export": lambda: cmd_export(cfg),
                "plan": lambda: cmd_plan(cfg, date.fromisoformat(getattr(args, "start", "2000-01-01"))),
                "publish": lambda: cmd_publish(cfg, getattr(args, "live", False)),
                "ads-blueprint": lambda: cmd_ads_blueprint(getattr(args, "budget", 5), getattr(args, "days", 7)),
                "ads-create": lambda: cmd_ads_create(cfg, getattr(args, "budget", 5), getattr(args, "days", 7),
                                                     getattr(args, "live", False))}[args.cmd]()
    except (InstagramError, RuntimeError, ValueError) as e:
        print(f"Errore: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
