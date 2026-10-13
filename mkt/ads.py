"""Inserzioni a pagamento (Marketing API). Prudenza prima di tutto: tutto nasce IN PAUSA, con budget massimo,
durata massima e fine automatica. L'utente attiva a mano da Ads Manager dopo aver scelto il post da promuovere."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from mkt.instagram import GRAPH, InstagramError, scrub

HARD_MAX_DAILY_EUR = 20.0  # tetto assoluto nel codice: nemmeno il .env può superarlo
HARD_MAX_DAYS = 14

BLUEPRINT = """# Piano inserzioni Instagram: Solana DEX Discovery

> Punti di partenza da verificare, non risultati garantiti. Nessun dato di rendimento è promesso.

## Prima di spendere
1. **Autorizzazione Meta:** gli annunci su criptovalute e servizi collegati possono richiedere un'approvazione scritta
   preventiva e dipendono dal Paese. Controlla le norme "Criptovalute" e "Prodotti e servizi finanziari" nel Centro
   per la trasparenza di Meta PRIMA di creare le creatività; se servono documenti, preparali.
2. **Categoria speciale:** la campagna viene creata con la categoria "Prodotti e servizi finanziari" (limita alcune opzioni
   di targeting): è voluto.
3. **Contenuti:** usa solo post già pubblicati e conformi (`python -m mkt lint`). Niente promesse di guadagno, niente
   testimonianze inventate, niente confronti di rendimento.

## Struttura consigliata
- 1 campagna, obiettivo **Traffico**, 1 gruppo di inserzioni, Italia, 22–45 anni, solo Instagram (Feed e Storie).
- Budget iniziale **{budget:.0f} €/giorno per {days} giorni** (totale {total:.0f} €), con data di fine automatica.
- 3 creatività a confronto: i caroselli `p02-allarmi`, `p10-nessun-wallet`, `p12-provalo` (usa "Usa post esistente").
- Pulsante: "Altro" / "Scopri di più" verso il link del bot Telegram.

## Come misurare
- In Ads Manager: impression, CPC sul link, click.
- Nel bot (solo admin): `/stato` mostra gli utenti attivi; confronta il numero prima/dopo ogni campagna.
- Il bot non ha un parametro di provenienza: l'attribuzione è approssimata (nuovi utenti nei giorni di campagna).

## Regole di arresto (suggerite)
- Dopo 15 € di spesa senza click di qualità o con CPC molto sopra la media del settore: ferma e cambia creatività.
- Se Meta rifiuta o limita gli annunci: non aggirare la revisione (niente account alternativi, niente testi mascherati).
- Se compaiono commenti di truffa o falsi profili: segnala e rispondi solo con il link ufficiale in bio.
"""


def blueprint(budget: float, days: int) -> str:
    return BLUEPRINT.format(budget=budget, days=days, total=budget * days)


def check_budget(daily_eur: float, days: int, env_max: float) -> None:
    cap = min(env_max, HARD_MAX_DAILY_EUR)
    if not 1 <= daily_eur <= cap:
        raise ValueError(f"budget giornaliero non valido: ammesso da 1 a {cap:.0f} €")
    if not 1 <= days <= HARD_MAX_DAYS:
        raise ValueError(f"durata non valida: da 1 a {HARD_MAX_DAYS} giorni")


class Ads:
    def __init__(self, client: httpx.Client, account_id: str, token: str, version: str = "v23.0") -> None:
        self.http, self.token = client, token
        self.account = account_id if account_id.startswith("act_") else f"act_{account_id}"
        self.root = f"{GRAPH}/{version}"

    def _call(self, method: str, path: str, data: dict[str, Any]) -> dict[str, Any]:
        params = {**data, "access_token": self.token}
        try:
            r = self.http.request(method, f"{self.root}/{path}", data=params if method == "POST" else None,
                                  params=params if method == "GET" else None, timeout=60)
            body = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise InstagramError(scrub(f"errore di rete o risposta non valida: {e}", self.token)) from None
        if r.status_code >= 400 or "error" in body:
            err = body.get("error", {})
            raise InstagramError(scrub(f"HTTP {r.status_code}: {err.get('message', 'errore')} (codice {err.get('code')})",
                                       self.token))
        return body

    def create_paused(self, name: str, daily_eur: float, days: int, now: datetime | None = None) -> dict[str, str]:
        """Crea campagna e gruppo di inserzioni IN PAUSA (nessuna spesa finché non li attivi tu)."""
        cur = self._call("GET", self.account, {"fields": "currency"}).get("currency")
        if cur != "EUR":
            raise InstagramError(f"l'account pubblicitario usa {cur}, non EUR: il budget in euro non è applicabile")
        start = (now or datetime.now(UTC)) + timedelta(hours=1)
        camp = self._call("POST", f"{self.account}/campaigns", {
            "name": name, "objective": "OUTCOME_TRAFFIC", "status": "PAUSED", "buying_type": "AUCTION",
            "special_ad_categories": json.dumps(["FINANCIAL_PRODUCTS_SERVICES"]),
            "is_adset_budget_sharing_enabled": "false"})
        adset = self._call("POST", f"{self.account}/adsets", {
            "name": f"{name} - Italia 22-45", "campaign_id": camp["id"], "status": "PAUSED",
            "daily_budget": str(round(daily_eur * 100)), "billing_event": "IMPRESSIONS",
            "optimization_goal": "LINK_CLICKS", "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "start_time": start.isoformat(), "end_time": (start + timedelta(days=days)).isoformat(),
            "targeting": json.dumps({"geo_locations": {"countries": ["IT"]}, "age_min": 22, "age_max": 45,
                                     "publisher_platforms": ["instagram"]})})
        return {"campaign_id": str(camp["id"]), "adset_id": str(adset["id"])}
