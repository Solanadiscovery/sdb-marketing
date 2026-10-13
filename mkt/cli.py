"""Riga di comando: python -m mkt <comando>. Per sicurezza `publish` e `ads-create` simulano finché non si aggiunge --live."""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import UTC, date, datetime, timedelta
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
TOKEN_DAYS = 60                       # durata dei token Instagram Login generati nella dashboard Meta
REFRESH_EVERY = timedelta(days=7)     # rinnovo automatico del token
WARN_BEFORE = timedelta(days=7)       # avviso prima della scadenza
ALERT_EVERY = timedelta(hours=24)     # lo stesso problema genera al massimo un avviso (email di GitHub) al giorno


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


def media_base() -> str:
    """Indirizzo pubblico di post e storie: MEDIA_BASE_URL oppure, su GitHub, il sito Pages del repository."""
    value = os.environ.get("MEDIA_BASE_URL", "").strip().rstrip("/")
    if value:
        return value
    owner, _, name = os.environ.get("GITHUB_REPOSITORY", "").partition("/")
    if owner and name:
        host = f"{owner.lower()}.github.io"
        return f"https://{host}" if name.lower() == host else f"https://{host}/{name}"
    raise RuntimeError("MEDIA_BASE_URL non impostato (indirizzo pubblico delle immagini)")


def fingerprint(token: str) -> str:
    """Impronta non reversibile del token: serve solo a capire se è stato sostituito (il token non viene mai salvato)."""
    return hashlib.sha256(token.encode()).hexdigest()[:12]


def maintain_token(ig: Instagram, state: dict[str, dict[str, str]], now: datetime) -> list[str]:
    """Rinnova ogni settimana il token Instagram Login (così non scade) e avvisa 7 giorni prima di una scadenza."""
    fp, info = fingerprint(ig.token), dict(state.get("_token", {}))
    if info.get("fp") != fp:  # primo avvio o token sostituito
        expires = (now + timedelta(days=TOKEN_DAYS)).isoformat() if ig.instagram_login else ""
        info = {"fp": fp, "seen": now.isoformat(), "expires": expires, "refreshed": ""}
    problems: list[str] = []
    if ig.instagram_login and now >= datetime.fromisoformat(info["refreshed"] or info["seen"]) + REFRESH_EVERY:
        try:
            new, expires_in = ig.refresh_token()
        except InstagramError as e:
            problems.append(f"rinnovo automatico del token non riuscito: {e}")
        else:
            info["refreshed"] = now.isoformat()
            if new == ig.token:
                info["expires"] = (now + timedelta(seconds=expires_in or TOKEN_DAYS * 86400)).isoformat()
            else:
                problems.append("Meta ha restituito un token diverso: genera un token nuovo nella dashboard Meta "
                                "e aggiorna il segreto IG_ACCESS_TOKEN")
    if info["expires"] and datetime.fromisoformat(info["expires"]) - now < WARN_BEFORE:
        problems.append(f"il token Instagram scade il {datetime.fromisoformat(info['expires']):%d/%m/%Y}: generane uno "
                        "nuovo nella dashboard Meta e aggiorna il segreto IG_ACCESS_TOKEN")
    state["_token"] = info
    return problems


def notify(state: dict[str, dict[str, str]], problems: list[str], now: datetime) -> int:
    """Segnala i problemi facendo fallire il job (GitHub manda un'email), al massimo una volta al giorno per problema."""
    if not problems:
        state.pop("_alert", None)
        return 0
    for p in problems:
        print(f"PROBLEMA: {p}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("".join(f"- {p}\n" for p in problems))
    key = hashlib.sha256("|".join(problems).encode()).hexdigest()[:12]
    last = state.get("_alert", {})
    if last.get("key") == key and now - datetime.fromisoformat(last["at"]) < ALERT_EVERY:
        print("(già segnalato nelle ultime 24 ore: nessuna nuova email)")
        return 0
    state["_alert"] = {"key": key, "at": now.isoformat()}
    return 1


def verify(ig: Instagram, http: httpx.Client, base: str, cfg: Config) -> str:
    """Controllo completo SENZA pubblicare: account, quota, immagini online e permesso di pubblicazione."""
    uid, name = ig.account()
    used, total = ig.quota_used()
    first = load_posts(POSTS, cfg.language)[0]
    urls = [media_urls(base, first, kind)[0] for kind in ("post", "story")]
    for u in urls:
        check_media(http, u)
    ig.probe(urls[0])
    return f"account @{name} (ID {uid}), pubblicazioni usate oggi {used}/{total}"


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
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not live:
        return _simulate(cfg)
    if not token:
        print("Configurazione incompleta: manca il segreto IG_ACCESS_TOKEN. Nessuna azione.")
        return 0
    state, now, problems = load_state(STATE), datetime.now(UTC), []
    try:
        with httpx.Client() as http:
            ig = Instagram(http, os.environ.get("IG_USER_ID", "").strip(), token, cfg.graph_version)
            problems += maintain_token(ig, state, now)
            base = media_base()
            if not PLAN.is_file():  # primo avvio: il calendario parte solo se la configurazione funziona davvero
                print(f"Primo avvio, verifica riuscita: {verify(ig, http, base, cfg)}. Creo il calendario.")
            problems += _publish_due(cfg, ig, http, base, state, now)
    except (InstagramError, RuntimeError) as e:
        problems.append(str(e))
    code = notify(state, problems, now)
    save_state(STATE, state)
    return code


def _publish_due(cfg: Config, ig: Instagram, http: httpx.Client, base: str, state: dict[str, dict[str, str]],
                 now: datetime) -> list[str]:
    plan = ensure_plan(cfg)
    posts = {p.id: p for p in load_posts(POSTS, cfg.language)}
    slot, skipped = next_due(plan, state, now, cfg.max_late_hours)
    for s in skipped:
        state[s.key] = {"at": now.isoformat(), "skipped": "troppo in ritardo"}
    if slot is None:
        print("Niente da pubblicare adesso.")
        return []
    post = posts[slot.id]
    if issues := lint(post):
        state[slot.key] = {"at": now.isoformat(), "skipped": "non conforme"}
        return [f"{post.id} NON pubblicato, problemi di conformità: {'; '.join(issues)}"]
    urls = media_urls(base, post, slot.kind)
    for u in urls:
        check_media(http, u)
    used, total = ig.quota_used()
    if used >= total * 0.8:
        print(f"Limite giornaliero quasi raggiunto ({used}/{total}): riprovo più tardi.")
        return []
    media = ig.publish_post(urls, post.full_caption()) if slot.kind == "post" else ig.publish_story(urls[0])
    state[slot.key] = {"at": now.isoformat(), "media_id": media}
    try:
        link = ig.permalink(media)
    except InstagramError:
        link = None
    print(f"Pubblicato {slot.kind} {post.id}: {link or media}")
    return []


def _simulate(cfg: Config) -> int:
    """Senza --live: mostra cosa uscirebbe adesso, senza rete e senza pubblicare."""
    plan = ensure_plan(cfg)
    posts = {p.id: p for p in load_posts(POSTS, cfg.language)}
    slot, _ = next_due(plan, load_state(STATE), datetime.now(UTC), cfg.max_late_hours)
    if slot is None:
        print("Niente da pubblicare adesso.")
        return 0
    post = posts[slot.id]
    if issues := lint(post):
        print(f"{post.id} NON pubblicabile, problemi di conformità: {'; '.join(issues)}")
        return 1
    urls = media_urls(media_base(), post, slot.kind)
    print(f"[simulazione] pubblicherei {slot.kind} {post.id} ({len(urls)} file) previsto per {slot.when:%d/%m %H:%M}")
    print(post.full_caption())
    return 0


def cmd_check(cfg: Config) -> int:
    """Verifica completa senza pubblicare nulla: token, account, quota, immagini online e permesso di pubblicazione."""
    token = secret("IG_ACCESS_TOKEN")
    with httpx.Client() as http:
        ig = Instagram(http, os.environ.get("IG_USER_ID", "").strip(), token, cfg.graph_version)
        kind = "Instagram Login" if ig.instagram_login else "Pagina Facebook"
        print(f"Token {kind}: {verify(ig, http, media_base(), cfg)}")
    print("Tutto pronto: post e storie usciranno da soli secondo il calendario.")
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
