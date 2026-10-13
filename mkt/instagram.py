"""Pubblicazione tramite la Instagram Graph API ufficiale (nessuna automazione dell'app, nessuno scraping).
Flusso: container per ogni immagine -> container carosello -> attesa -> media_publish."""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

import httpx

GRAPH = "https://graph.facebook.com"


class InstagramError(Exception):
    pass


def scrub(text: str, token: str) -> str:
    text = text.replace(token, "***") if token else text
    return re.sub(r"(?i)(access_token=)[^&\s\"']+", r"\1***", text)[:400]


class Instagram:
    def __init__(self, client: httpx.Client, user_id: str, token: str, version: str = "v23.0",
                 sleep: Callable[[float], None] = time.sleep, base: str = GRAPH) -> None:
        self.http, self.uid, self.token, self.sleep = client, user_id, token, sleep
        self.root = f"{base}/{version}"

    def _call(self, method: str, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        params = {**(data or {}), "access_token": self.token}
        try:
            r = self.http.request(method, f"{self.root}/{path}", data=params if method == "POST" else None,
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

    def create_image(self, image_url: str, caption: str | None = None, carousel_item: bool = False) -> str:
        data: dict[str, Any] = {"image_url": image_url}
        if carousel_item:
            data["is_carousel_item"] = "true"
        elif caption:
            data["caption"] = caption
        return str(self._call("POST", f"{self.uid}/media", data)["id"])

    def create_carousel(self, children: list[str], caption: str) -> str:
        if not 2 <= len(children) <= 10:
            raise InstagramError("un carosello ha da 2 a 10 elementi")
        return str(self._call("POST", f"{self.uid}/media", {"media_type": "CAROUSEL", "children": ",".join(children),
                                                            "caption": caption})["id"])

    def create_story(self, image_url: str) -> str:
        return str(self._call("POST", f"{self.uid}/media", {"media_type": "STORIES", "image_url": image_url})["id"])

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
        return str(self._call("POST", f"{self.uid}/media_publish", {"creation_id": container})["id"])

    def quota_used(self) -> tuple[int, int]:
        d = self._call("GET", f"{self.uid}/content_publishing_limit", {"fields": "quota_usage,config"})
        row = (d.get("data") or [{}])[0]
        total = int((row.get("config") or {}).get("quota_total") or 100)
        return int(row.get("quota_usage") or 0), total

    def whoami(self) -> str:
        return str(self._call("GET", self.uid, {"fields": "username"}).get("username"))

    def permalink(self, media_id: str) -> str | None:
        return self._call("GET", media_id, {"fields": "permalink"}).get("permalink")

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
