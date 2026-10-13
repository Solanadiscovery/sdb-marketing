"""Configurazione: config.toml (pubblica) e .env (segreti, mai nei log)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        k, sep, v = line.partition("=")
        if sep and not line.lstrip().startswith("#") and k.strip() and k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip()


@dataclass(frozen=True)
class Config:
    language: str
    timezone: str
    post_days: tuple[str, ...]
    post_time: str
    max_late_hours: int
    graph_version: str
    brand: str
    story_time: str = "12:30"

    @staticmethod
    def load(path: Path = ROOT / "config.toml") -> Config:
        t = tomllib.loads(path.read_text(encoding="utf-8"))
        lang = t.get("language", "it")
        if lang not in ("it", "en"):
            raise ValueError("language deve essere 'it' o 'en'")
        days = tuple(t.get("post_days", ["mon", "wed", "fri"]))
        if not days or any(d not in ("mon", "tue", "wed", "thu", "fri", "sat", "sun") for d in days):
            raise ValueError("post_days non valido")
        return Config(lang, t.get("timezone", "Europe/Rome"), days, t.get("post_time", "18:30"),
                      int(t.get("max_late_hours", 36)), t.get("graph_version", "v23.0"), t.get("brand", "Solana DEX Discovery"),
                      t.get("story_time", "12:30"))


def secret(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"{name} non impostato nel file .env")
    return v
