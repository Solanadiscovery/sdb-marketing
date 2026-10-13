"""Test offline della campagna Instagram: nessuna rete, nessun segreto reale."""
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from PIL import Image

from mkt import ads, cli
from mkt.config import ROOT
from mkt.content import DISCLAIMER, Post, Slide, lint, load_posts
from mkt.instagram import Instagram, InstagramError
from mkt.render import render_post
from mkt.schedule import Slot, build_plan, extend_plan, next_due

POSTS = ROOT / "content" / "posts.json"
TOKEN = "EAAB-secret-token-123"


def make_post(lang="it", caption="Un testo neutro.", slides=None, hashtags=("#solana",)):
    return Post("x", lang, "Titolo", "Sotto", tuple(slides or [Slide("A", "b")]), caption, tuple(hashtags))


@pytest.mark.parametrize("lang", ["it", "en"])
def test_all_posts_are_compliant_and_complete(lang):
    posts = load_posts(POSTS, lang)
    assert len(posts) == 12 and len({p.id for p in posts}) == 12
    for p in posts:
        assert lint(p) == [], p.id
        assert DISCLAIMER[lang] in p.full_caption() and len(p.slides) + 2 <= 10


@pytest.mark.parametrize("bad", ["Guadagno garantito!", "Fai 100x in una settimana", "Compra subito", "Senza rischi",
                                 "Ti consiglio di investire", "Un token sicuro al 100%", "visita https://t.me/bot"])
def test_lint_blocks_promises_and_links(bad):
    assert lint(make_post(caption=bad))


def test_lint_blocks_english_and_missing_disclaimer_is_added():
    assert lint(make_post("en", caption="Guaranteed profit, buy now, no risk"))
    assert lint(make_post("it", caption="Informazione pura.")) == []  # il disclaimer viene aggiunto da full_caption
    assert lint(make_post(hashtags=("#a",) * 9))


def test_render_makes_instagram_ready_jpeg(tmp_path):
    post = load_posts(POSTS, "en")[0]
    paths = render_post(post, "Solana DEX Discovery", tmp_path)
    assert [p.name for p in paths] == [f"{i:02d}.jpg" for i in range(1, len(post.slides) + 3)]
    im = Image.open(paths[0])
    assert im.format == "JPEG" and im.size == (1080, 1350)
    story = Image.open(tmp_path / post.id / "story.jpg")
    assert story.format == "JPEG" and story.size == (1080, 1920)


def test_mascot_is_always_the_original_artwork():
    """Il soggetto non cambia mai: ogni copertina contiene i pixel del poster originale (nessuna variante ridisegnata)."""
    from mkt import render
    post = load_posts(POSTS, "it")[0]
    for fmt, kind, n in (("feed", "cover", 0), ("feed", "content", 0), ("story", "cover", 0)):
        img = render.slide_image(kind, post, "B", 0, 5, n, fmt=fmt)
        assert img.size == (render.FEED if fmt == "feed" else render.STORY)
    assert render.MASCOT.is_file() and render.poster().size == (1086, 1448)


def test_plan_follows_weekdays_and_keeps_local_time_across_dst():
    slots = build_plan([f"p{i}" for i in range(8)], date(2026, 10, 14), ("mon", "wed", "fri"), "18:30", "Europe/Rome")
    posts = [s for s in slots if s.kind == "post"]
    assert [s.when.strftime("%a %d/%m") for s in posts][:4] == ["Wed 14/10", "Fri 16/10", "Mon 19/10", "Wed 21/10"]
    assert posts[0].when.utcoffset() == timedelta(hours=2)
    last = posts[-1].when  # dopo la fine dell'ora legale (25/10/2026) l'ora locale resta 18:30
    assert last.utcoffset() == timedelta(hours=1) and last.hour == 18 and last.minute == 30


def test_each_content_gets_a_story_the_same_day():
    slots = build_plan(["a"], date(2026, 10, 14), ("wed",), "18:30", "Europe/Rome", "12:30")
    assert [(s.kind, s.when.strftime("%a %H:%M")) for s in slots] == [("story", "Wed 12:30"), ("post", "Wed 18:30")]
    assert len({s.key for s in slots}) == 2


def test_plan_never_runs_out_and_cycles_contents():
    ids = [f"p{i}" for i in range(12)]
    args = (("mon", "wed", "fri"), "18:30", "Europe/Rome", "12:30")
    plan = extend_plan([], ids, date(2026, 10, 14), *args)
    assert len([s for s in plan if s.kind == "post"]) == 12
    assert extend_plan(plan, ids, date(2026, 10, 14), *args) == plan  # c'è ancora margine
    later = extend_plan(plan, ids, date(2026, 11, 20), *args)
    posts = [s for s in later if s.kind == "post"]
    assert len(posts) == 24 and [s.id for s in posts] == ids + ids and len({s.key for s in later}) == len(later)


def test_next_due_skips_late_and_published():
    now = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    plan = [Slot("old", now - timedelta(hours=60)), Slot("done", now - timedelta(hours=5)),
            Slot("due", now - timedelta(hours=2)), Slot("future", now + timedelta(hours=3))]
    slot, skipped = next_due(plan, {plan[1].key: {"at": "x"}}, now, 36)
    assert slot is not None and slot.id == "due" and [s.id for s in skipped] == ["old"]
    assert next_due(plan[3:], {}, now, 36) == (None, [])


def test_story_is_published_with_official_fields():
    calls = []

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append((r.url.path, r.content.decode()))
        if r.url.path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "M"})
        if r.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "k1"})
        return httpx.Response(200, json={"status_code": "FINISHED"})

    ig = Instagram(client(handler), "1", TOKEN, sleep=lambda _: None)
    assert ig.publish_story("https://x/story.jpg") == "M"
    bodies = " ".join(b for _, b in calls)
    assert "media_type=STORIES" in bodies and "image_url=" in bodies and "REELS" not in bodies


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_instagram_carousel_flow_in_order():
    calls = []

    def handler(r: httpx.Request) -> httpx.Response:
        body = r.content.decode()
        calls.append((r.method, r.url.path, body))
        assert TOKEN in (body + str(r.url))  # il token viaggia solo verso Meta
        if r.url.path.endswith("/media") and "is_carousel_item" in body:
            return httpx.Response(200, json={"id": f"c{len(calls)}"})
        if r.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "parent"})
        if r.url.path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "M1"})
        return httpx.Response(200, json={"status_code": "FINISHED"})

    ig = Instagram(client(handler), "123", TOKEN, "v23.0", sleep=lambda _: None)
    assert ig.publish_post(["https://x/1.jpg", "https://x/2.jpg"], "caption") == "M1"
    paths = [c[1] for c in calls]
    assert paths[0] == "/v23.0/123/media" and paths[-1] == "/v23.0/123/media_publish"
    assert any("media_type=CAROUSEL" in c[2] and "children=" in c[2] for c in calls)


def test_instagram_errors_never_leak_the_token():
    def handler(r):
        return httpx.Response(400, json={"error": {"message": f"Invalid token {TOKEN}", "code": 190}})
    ig = Instagram(client(handler), "123", TOKEN, sleep=lambda _: None)
    with pytest.raises(InstagramError) as e:
        ig.create_image("https://x/1.jpg", "c")
    assert TOKEN not in str(e.value) and "190" in str(e.value)
    with pytest.raises(InstagramError):
        ig.create_carousel(["a"], "c")  # un carosello ha almeno 2 elementi


def test_whoami_and_quota():
    def handler(r):
        if r.url.path.endswith("content_publishing_limit"):
            return httpx.Response(200, json={"data": [{"quota_usage": 3, "config": {"quota_total": 100}}]})
        return httpx.Response(200, json={"username": "sdb_demo"})
    ig = Instagram(client(handler), "1", TOKEN)
    assert ig.whoami() == "sdb_demo" and ig.quota_used() == (3, 100)


def test_wait_ready_fails_on_error_status():
    ig = Instagram(client(lambda r: httpx.Response(200, json={"status_code": "ERROR"})), "1", TOKEN,
                   sleep=lambda _: None)
    with pytest.raises(InstagramError, match="ERROR"):
        ig.wait_ready("c1")


def test_budget_guards_and_blueprint():
    ads.check_budget(5, 7, 5)
    for args in [(0.5, 7, 5), (6, 7, 5), (30, 7, 100), (5, 30, 5)]:
        with pytest.raises(ValueError):
            ads.check_budget(*args)
    text = ads.blueprint(5, 7)
    assert "35 €" in text and "approvazione scritta" in text and "Non perdere" not in text


def test_ads_are_created_paused_with_end_date_and_euro_only():
    seen = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append((r.method, r.url.path, r.content.decode()))
        if r.method == "GET":
            return httpx.Response(200, json={"currency": "EUR"})
        return httpx.Response(200, json={"id": "1" if "campaigns" in r.url.path else "2"})

    res = ads.Ads(client(handler), "999", TOKEN).create_paused("t", 5, 7, now=datetime(2026, 10, 14, tzinfo=UTC))
    assert res == {"campaign_id": "1", "adset_id": "2"}
    camp, adset = seen[1][2], seen[2][2]
    assert "status=PAUSED" in camp and "FINANCIAL_PRODUCTS_SERVICES" in camp and seen[1][1] == "/v23.0/act_999/campaigns"
    assert "status=PAUSED" in adset and "daily_budget=500" in adset and "end_time=" in adset and "IT" in adset
    usd = client(lambda r: httpx.Response(200, json={"currency": "USD"}))
    with pytest.raises(InstagramError, match="USD"):
        ads.Ads(usd, "999", TOKEN).create_paused("t", 5, 7)


def test_cli_publish_dry_run_posts_nothing(tmp_path, monkeypatch, capsys):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"id": "p01-cos-e", "kind": "story",
                                 "when": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}]))
    monkeypatch.setattr(cli, "PLAN", plan)
    monkeypatch.setattr(cli, "STATE", tmp_path / "state.json")
    monkeypatch.setenv("MEDIA_BASE_URL", "https://media.example/out")
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: pytest.fail("la simulazione non deve usare la rete"))
    assert cli.main(["publish"]) == 0
    out = capsys.readouterr().out
    assert "[simulazione]" in out and "story" in out and DISCLAIMER["it"] in out
    assert not (tmp_path / "state.json").exists()
    first = load_posts(POSTS, "it")[0]
    assert cli.image_urls("https://m/out/", first)[0] == "https://m/out/it/p01-cos-e/01.jpg"
    assert cli.media_urls("https://m", first, "story") == ["https://m/it/p01-cos-e/story.jpg"]
    assert len(cli.media_urls("https://m", first, "post")) == len(first.slides) + 2


def test_no_forbidden_capabilities_in_marketing_code():
    src = " ".join(p.read_text(encoding="utf-8") for p in Path(ROOT / "mkt").glob("*.py")).lower()
    for word in ("shell=true", "os.system", "private_key", "seed_phrase", "verify=false", "sendtransaction"):
        assert word not in src


IG_TOKEN = "IGAAT-secret-token-456"


def test_instagram_login_token_uses_instagram_host_and_finds_account_id():
    seen = []

    def handler(r):
        seen.append(str(r.url))
        if r.url.path.endswith("/me"):
            return httpx.Response(200, json={"data": [{"user_id": "17841400", "username": "sdb"}]})
        return httpx.Response(200, json={"data": [{"quota_usage": 1, "config": {"quota_total": 100}}]})

    ig = Instagram(client(handler), "", IG_TOKEN, "v23.0", sleep=lambda _: None)
    assert ig.instagram_login and ig.account() == ("17841400", "sdb") and ig.quota_used() == (1, 100)
    assert all(u.startswith("https://graph.instagram.com/v23.0/") for u in seen)
    assert "/17841400/content_publishing_limit" in seen[-1]
    flat = Instagram(client(lambda r: httpx.Response(200, json={"user_id": "9", "username": "x"})), "", IG_TOKEN)
    assert flat.account() == ("9", "x")
    fb = Instagram(client(handler), "123", TOKEN)
    assert not fb.instagram_login and fb.root.startswith("https://graph.facebook.com/")


def test_token_refresh_calls_official_endpoint():
    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(200, json={"access_token": IG_TOKEN, "token_type": "bearer", "expires_in": 5183944})

    ig = Instagram(client(handler), "1", IG_TOKEN)
    assert ig.refresh_token() == (IG_TOKEN, 5183944)
    assert calls[0].url.path == "/refresh_access_token" and calls[0].url.params["grant_type"] == "ig_refresh_token"
    with pytest.raises(InstagramError):
        Instagram(client(handler), "1", TOKEN).refresh_token()  # i token della Pagina non si rinnovano così


class FakeIG:
    def __init__(self, token, new=None):
        self.token, self.instagram_login, self.new, self.calls = token, True, new, 0

    def refresh_token(self):
        self.calls += 1
        return (self.new or self.token), 5184000


def test_token_is_renewed_weekly_and_expiry_is_flagged():
    now, state, ig = datetime(2026, 10, 20, 12, tzinfo=UTC), {}, FakeIG(IG_TOKEN)
    assert cli.maintain_token(ig, state, now) == [] and ig.calls == 0  # token appena visto: niente rinnovo
    assert IG_TOKEN not in json.dumps(state)  # il token non viene mai salvato (lo stato è pubblico)
    assert cli.maintain_token(ig, state, now + timedelta(days=7)) == [] and ig.calls == 1
    assert state["_token"]["expires"].startswith("2026-12-26")  # 60 giorni dal rinnovo
    assert cli.maintain_token(ig, state, now + timedelta(days=8)) == [] and ig.calls == 1  # una volta a settimana
    other = FakeIG(IG_TOKEN, new="IGAA-diverso")
    assert "token diverso" in cli.maintain_token(other, state, now + timedelta(days=15))[0]
    late = {"_token": {"fp": cli.fingerprint(IG_TOKEN), "seen": now.isoformat(), "refreshed": now.isoformat(),
                       "expires": (now + timedelta(days=3)).isoformat()}}
    assert "scade il 23/10/2026" in cli.maintain_token(FakeIG(IG_TOKEN), late, now)[0]


def test_problems_alert_at_most_once_a_day():
    now, state = datetime(2026, 10, 20, tzinfo=UTC), {}
    assert cli.notify(state, ["x"], now) == 1
    assert cli.notify(state, ["x"], now + timedelta(hours=1)) == 0
    assert cli.notify(state, ["y"], now + timedelta(hours=2)) == 1
    assert cli.notify(state, ["y"], now + timedelta(hours=27)) == 1
    assert cli.notify(state, [], now + timedelta(hours=28)) == 0 and "_alert" not in state


def test_media_address_defaults_to_github_pages(monkeypatch):
    monkeypatch.delenv("MEDIA_BASE_URL", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "Solanadiscovery/sdb-marketing")
    assert cli.media_base() == "https://solanadiscovery.github.io/sdb-marketing"
    monkeypatch.setenv("MEDIA_BASE_URL", "https://cdn.example/x/")
    assert cli.media_base() == "https://cdn.example/x"


def test_live_publish_without_token_does_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "PLAN", tmp_path / "plan.json")
    monkeypatch.setattr(cli, "STATE", tmp_path / "state.json")
    monkeypatch.delenv("IG_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: pytest.fail("senza token non si usa la rete"))
    assert cli.main(["publish", "--live"]) == 0
    assert "Configurazione incompleta" in capsys.readouterr().out
    assert not (tmp_path / "plan.json").exists() and not (tmp_path / "state.json").exists()


def fake_meta(ok=True):
    calls = []

    def handler(r):
        calls.append((r.method, r.url.path))
        if not ok:
            return httpx.Response(400, json={"error": {"message": "permesso mancante", "code": 10}})
        if r.method == "HEAD":
            return httpx.Response(200, headers={"content-type": "image/jpeg"})
        if r.url.path.endswith("/me"):
            return httpx.Response(200, json={"data": [{"user_id": "178", "username": "sdb"}]})
        if r.url.path.endswith("/content_publishing_limit"):
            return httpx.Response(200, json={"data": [{"quota_usage": 0, "config": {"quota_total": 100}}]})
        if r.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "c1"})
        return httpx.Response(200, json={"status_code": "FINISHED"})

    return calls, handler


@pytest.fixture
def live_env(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "PLAN", tmp_path / "plan.json")
    monkeypatch.setattr(cli, "STATE", tmp_path / "state.json")
    monkeypatch.setenv("IG_ACCESS_TOKEN", IG_TOKEN)
    monkeypatch.delenv("IG_USER_ID", raising=False)
    monkeypatch.setenv("MEDIA_BASE_URL", "https://media.example")
    real = httpx.Client

    def use(handler):
        monkeypatch.setattr(cli.httpx, "Client", lambda *a, **k: real(transport=httpx.MockTransport(handler)))

    return tmp_path, use


def test_first_live_run_verifies_without_publishing_then_creates_plan(live_env, capsys):
    tmp, use = live_env
    calls, handler = fake_meta()
    use(handler)
    assert cli.main(["publish", "--live"]) == 0
    out = capsys.readouterr().out
    assert "verifica riuscita" in out and "@sdb" in out and (tmp / "plan.json").exists()
    assert ("POST", "/v23.0/178/media") in calls  # prova di pubblicazione con un contenitore...
    assert not any(p.endswith("/media_publish") for _, p in calls)  # ...ma nulla viene pubblicato
    saved = (tmp / "state.json").read_text()
    assert IG_TOKEN not in saved and "_token" in saved


def test_broken_configuration_alerts_once_and_never_starts_the_calendar(live_env):
    tmp, use = live_env
    _, handler = fake_meta(ok=False)
    use(handler)
    assert cli.main(["publish", "--live"]) == 1  # job fallito = email di avviso
    assert cli.main(["publish", "--live"]) == 0  # stesso problema entro 24 ore: nessuna seconda email
    assert not (tmp / "plan.json").exists()  # il calendario parte solo quando tutto funziona
    assert IG_TOKEN not in (tmp / "state.json").read_text()
