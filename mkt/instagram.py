"""Pubblicazione tramite le API ufficiali di Instagram (nessuna automazione dell'app, nessuno scraping).
Il tipo di token si riconosce da solo:
- token "Instagram Login" (generato nella dashboard Meta, non inizia con EAA): host graph.instagram.com,
  l'ID dell'account si ricava dal token, il token si rinnova da solo ogni settimana;
- token della Pagina Facebook (inizia con EAA): host graph.facebook.com, serve IG_USER_ID.
Flusso: container per ogni immagine -> container carosello -> attesa -> media_publish."""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

import httpx

GRAPH = "https://graph.facebook.com"
IG_GRAPH = "https://graph.instagram.com"


class InstagramError(Exception):
    pass


def scrub(text: str, token: str) -> str:
    text = text.replace(token, "***") if token else text
    return re.sub(r"(?i)(access_token=)[^&\s\"']+", r"\1***", text)[:400]


def host_for(token: str) -> str:
    """I token della Pagina Facebook iniziano con EAA; gli altri sono token Instagram Login."""
    return GRAPH if token.startswith("EAA") else IG_GRAPH


class Instagram:
    def __init__(self, client: httpx.Client, user_id: str, token: str, version: str = "v23.0",
                 sleep: Callable[[float], None] = time.sleep, base: str | None = None) -> None:
        self.http, self.uid, self.token, self.sleep = client, user_id, token, sleep
        self.base = base or host_for(token)
        self.root = f"{self.base}/{version}"

    @property
    def instagram_login(self) -> bool:
        return self.base == IG_GRAPH

    def _call(self, method: str, path: str, data: dict[str, Any] | None = None,
              versioned: bool = True) -> dict[str, Any]:
        params = {**(data or {}), "access_token": self.token}
        url = f"{self.root if versioned else self.base}/{path}"
        try:
            r = self.http.request(method, url, data=params if method == "POST" else None,
                                  params=params if method == "GET" else None, timeout=60)
        except httpx.HTTPError as e:
            raise InstagramError(scrub(f"rete: {e}", self.token)) from None
        try:
            body = r.json()
        except ValueError:
            raise InstagramError(f"risposta non valida (HTTP {r.status_code})") from None
        if r.status_code >= 400 or (isinstance(body, dict) and "error" in body):
            err = body.get("error", {}) if isinstance(body, dict) else {}
            raise InstagramError(scrub(f"HTTP {r.status_code}: {err.get('message', 'errore')} (codice {err.get('code')})",
                                       self.token))
        if not isinstance(body, dict):
            raise InstagramError("risposta inattesa")
        return body

    def account(self) -> tuple[str, str]:
        """(ID, nome utente) dell'account professionale. Con un token Instagram Login l'ID si ricava dal token."""
        if self.instagram_login:
            d = self._call("GET", "me", {"fields": "user_id,username"})
            rows = d.get("data")
            row = rows[0] if isinstance(rows, list) and rows else d
            self.uid = str(row.get("user_id") or self.uid or "")
            name = str(row.get("username") or "")
        else:
            if not self.uid:
                raise InstagramError("manca IG_USER_ID (serve con i token della Pagina Facebook)")
            name = str(self._call("GET", self.uid, {"fields": "username"}).get("username") or "")
        if not self.uid:
            raise InstagramError("impossibile ricavare l'ID dell'account Instagram dal token")
        return self.uid, name

    def _need_uid(self) -> str:
        if not self.uid:
            self.account()
        return self.uid

    def create_image(self, image_url: str, caption: str | None = None, carousel_item: bool = False) -> str:
        data: dict[str, Any] = {"image_url": image_url}
        if carousel_item:
            data["is_carousel_item"] = "true"
        elif caption:
            data["caption"] = caption
        return str(self._call("POST", f"{self._need_uid()}/media", data)["id"])

    def create_carousel(self, children: list[str], caption: str) -> str:
        if not 2 <= len(children) <= 10:
            raise InstagramError("un carosello ha da 2 a 10 elementi")
        return str(self._call("POST", f"{self._need_uid()}/media",
                              {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption})["id"])

    def create_story(self, image_url: str) -> str:
        return str(self._call("POST", f"{self._need_uid()}/media",
                              {"media_type": "STORIES", "image_url": image_url})["id"])

    def wait_ready(self, container: str, attempts: int = 40, interval: float = 3.0) -> None:
        for _ in range(attempts):
            status = str(self._call("GET", container, {"fields": "status_code"}).get("status_code"))
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise InstagramError(f"elaborazione del contenuto fallita ({status})")
            self.sleep(interval)
        raise InstagramError("tempo scaduto in attesa dell'elaborazione")

    def publish(self, container: str) -> str:
        return str(self._call("POST", f"{self._need_uid()}/media_publish", {"creation_id": container})["id"])

    def quota_used(self) -> tuple[int, int]:
        d = self._call("GET", f"{self._need_uid()}/content_publishing_limit", {"fields": "quota_usage,config"})
        row = (d.get("data") or [{}])[0]
        total = int((row.get("config") or {}).get("quota_total") or 100)
        return int(row.get("quota_usage") or 0), total

    def whoami(self) -> str:
        return self.account()[1]

    def permalink(self, media_id: str) -> str | None:
        return self._call("GET", media_id, {"fields": "permalink"}).get("permalink")

    def probe(self, image_url: str) -> None:
        """Prova di pubblicazione SENZA pubblicare: crea un contenitore (scade da solo in 24 ore) e attende che
        Instagram lo accetti. Verifica permessi e raggiungibilità delle immagini."""
        self.wait_ready(self.create_image(image_url))

    def refresh_token(self) -> tuple[str, int]:
        """Rinnova un token Instagram Login (età minima 24 ore): valido altri 60 giorni da oggi."""
        if not self.instagram_login:
            raise InstagramError("il rinnovo automatico vale solo per i token Instagram Login")
        d = self._call("GET", "refresh_access_token", {"grant_type": "ig_refresh_token"}, versioned=False)
        new = str(d.get("access_token") or "")
        if not new:
            raise InstagramError("rinnovo del token: risposta senza token")
        return new, int(d.get("expires_in") or 0)

    def publish_post(self, image_urls: list[str], caption: str) -> str:
        if len(image_urls) == 1:
            container = self.create_image(image_urls[0], caption)
        else:
            children = []
            for url in image_urls:
                child = self.create_image(url, carousel_item=True)
                self.wait_ready(child)
                children.append(child)
            container = self.create_carousel(children, caption)
        self.wait_ready(container)
        return self.publish(container)

    def publish_story(self, image_url: str) -> str:
        container = self.create_story(image_url)
        self.wait_ready(container)
        return self.publish(container)
