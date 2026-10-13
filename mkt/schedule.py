"""Calendario editoriale: date di pubblicazione, stato dei post già usciti, scelta del prossimo da pubblicare."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


@dataclass(frozen=True)
class Slot:
    id: str
    when: datetime  # con fuso orario
    kind: str = "post"  # post (carosello nel feed) | story

    @property
    def key(self) -> str:
        return f"{self.id}:{self.kind}:{self.when:%Y%m%d}"


def _at(day: date, hhmm: str, zone: ZoneInfo) -> datetime:
    hh, mm = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(hh, mm), zone)


def build_plan(post_ids: list[str], start: date, days: tuple[str, ...], at: str, tz: str,
               story_at: str = "12:30") -> list[Slot]:
    """Per ogni contenuto: carosello nel giorno di pubblicazione e storia lo stesso giorno."""
    zone, wanted = ZoneInfo(tz), {DAYS[d] for d in days}
    slots, day = [], start
    for pid in post_ids:
        while day.weekday() not in wanted:
            day += timedelta(days=1)
        slots += [Slot(pid, _at(day, story_at, zone), "story"), Slot(pid, _at(day, at, zone), "post")]
        day += timedelta(days=1)
    return sorted(slots, key=lambda s: s.when)


def extend_plan(plan: list[Slot], post_ids: list[str], today: date, days: tuple[str, ...], at: str, tz: str,
                story_at: str, horizon_days: int = 14) -> list[Slot]:
    """Il calendario non finisce mai: quando restano meno di `horizon_days` giorni si aggiunge un altro giro di contenuti."""
    last = max((s.when.date() for s in plan), default=None)
    if last is not None and (last - today).days >= horizon_days:
        return plan
    done = sum(s.kind == "post" for s in plan)
    ids = [post_ids[(done + i) % len(post_ids)] for i in range(len(post_ids))]
    start = max(today, last + timedelta(days=1)) if last else today + timedelta(days=1)
    return sorted([*plan, *build_plan(ids, start, days, at, tz, story_at)], key=lambda s: s.when)


def save_plan(path: Path, slots: list[Slot]) -> None:
    path.write_text(json.dumps([{"id": s.id, "kind": s.kind, "when": s.when.isoformat()} for s in slots], indent=1),
                    encoding="utf-8")


def load_plan(path: Path) -> list[Slot]:
    return [Slot(r["id"], datetime.fromisoformat(r["when"]), r.get("kind", "post"))
            for r in json.loads(path.read_text(encoding="utf-8"))]


def load_state(path: Path) -> dict[str, dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def save_state(path: Path, state: dict[str, dict[str, str]]) -> None:
    path.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


def next_due(plan: list[Slot], state: dict[str, dict[str, str]], now: datetime,
             max_late_h: int) -> tuple[Slot | None, list[Slot]]:
    """Il primo contenuto scaduto e non ancora uscito; quelli troppo in ritardo si saltano, mai recuperati in blocco."""
    skipped: list[Slot] = []
    for slot in sorted(plan, key=lambda s: s.when):
        if slot.key in state or slot.when > now.astimezone(UTC):
            continue
        if now - slot.when > timedelta(hours=max_late_h):
            skipped.append(slot)
            continue
        return slot, skipped
    return None, skipped
