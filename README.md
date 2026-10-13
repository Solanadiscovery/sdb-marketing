# Campagna Instagram · Solana DEX Discovery

Strumento **separato** dal bot: non si collega al VPS, al database né a Telegram. Contiene 12 contenuti già pronti
(italiano e inglese; feed 1080×1350, storie 1080×1920), il controllo di conformità, la pubblicazione automatica con l'API ufficiale
di Instagram e un modulo per le inserzioni a pagamento (sempre create **in pausa**).

## Cosa fa e cosa NON fa
- Pubblica 3 caroselli a settimana (+ una storia al giorno di uscita) con la **Graph API ufficiale**. Nessuna automazione dell'app, nessuno scraping.
- Ogni post passa da un controllo (`lint`): niente promesse di guadagno, niente "sicuro/garantito", niente consigli,
  disclaimer sempre presente. Un post che non lo supera **non esce**.
- **Non** compra follower, **non** mette like/commenti/messaggi automatici (violano le regole di Instagram e portano al blocco).
- **Non** usa dati del bot (nessun rendimento, nessuna statistica inventata): contenuti educativi e sulle funzioni.
- Le inserzioni nascono in pausa, con budget massimo e data di fine: spendi solo quando attivi tu da Ads Manager.

## ⚠️ Prima di spendere un euro: regole di Meta
Gli annunci su criptovalute e servizi collegati possono richiedere **un'approvazione scritta preventiva** di Meta e variano
per Paese ([norme Meta](https://transparency.meta.com/policies/ad-standards/restricted-goods-services/cryptocurrency-products-and-services)).
Non ho potuto verificare il caso Italia/UE: controlla le norme e, se serve, richiedi l'autorizzazione. Se Meta rifiuta,
**non aggirare** la revisione (niente account alternativi o testi mascherati). I post organici non costano nulla e
partono senza autorizzazione, ma restano soggetti alle regole della community (niente truffe, niente promesse).

## Avvio (tutto il resto è automatico)
La mascotte (`assets/mascot.png`) è **sempre la stessa**: ogni post e storia usa i pixel dell'immagine originale, mai ridisegnata.
Ogni contenuto genera da solo: **carosello** nel feed (lun/mer/ven 18:30), **storia** lo stesso giorno (12:30, "oggi nel feed"). Il calendario si allunga da solo (giro di 12 contenuti, poi ricomincia).

**Cose che solo tu puoi fare (una tantum, ~20 minuti):**
1. Account Instagram **professionale** collegato a una **Pagina Facebook**.
2. Su [developers.facebook.com](https://developers.facebook.com): app Business con prodotto Instagram e permesso di pubblicazione ([guida](https://developers.facebook.com/docs/instagram-platform/content-publishing)). Ricava **ID account Instagram** e **token di lunga durata** (si rinnova entro ~60 giorni: segna una scadenza).
3. Repository GitHub **pubblico** vuoto; doppio clic su `carica_su_github.cmd` e incolla l'indirizzo.
4. GitHub → Settings → **Pages** → Source = *GitHub Actions*. Settings → Secrets → Actions: `IG_USER_ID`, `IG_ACCESS_TOKEN`, `MEDIA_BASE_URL` (= `https://TUOUTENTE.github.io/NOMEREPO`, senza barra finale).
5. Tab *Actions* → "Crea e pubblica i file multimediali" → *Run workflow* (crea e mette online immagini). Poi `python -m mkt check` (o lascia fare al primo giro) verifica account e file.
6. Nel profilo Instagram, link in bio verso il bot (`https://t.me/NOMEDELBOT`).

Da lì in poi il workflow "Pubblica su Instagram" (ogni 30 minuti, gratis, anche a PC spento) pubblica e salva calendario e stato. In alternativa dal PC: `install_task.cmd` (PC acceso).
*Strada manuale senza API:* `python -m mkt render`, poi `python -m mkt export` e carichi tu in Meta Business Suite.

## Comandi (`python -m mkt <comando>`)
| Comando | Cosa fa |
|---|---|
| `lint` | controlla la conformità di tutti i post |
| `render [--all]` | crea post e storie in `out/` |
| `plan --start AAAA-MM-GG` | (facoltativo) riparte il calendario da una data; di norma si crea da solo |
| `export` | `calendario_<lingua>.md` per pubblicare a mano |
| `check` | verifica token, account e immagini (non pubblica) |
| `publish [--live]` | pubblica il prossimo contenuto in scadenza (senza `--live`: simulazione) |
| `status` | cosa è già uscito |
| `ads-blueprint --budget 5 --days 7` | scrive `ads_plan.md` (struttura, misure, regole di arresto) |
| `ads-create [--live]` | crea campagna **in pausa** (tetto 20 €/giorno e 14 giorni nel codice; `MAX_DAILY_BUDGET_EUR` nel `.env`, default 5) |

## Personalizzare
- Lingua del profilo, giorni, ora: `config.toml` (`language = "en"` per un profilo inglese).
- Testi: `content/posts.json` (una voce per post, `it` e `en`); poi `lint`, `render`, `plan`.
- Grafica: `mkt/render.py` (layout; la mascotte non si tocca). Font Inter (licenza OFL).
- Nuovi post: aggiungine in `posts.json` e rigenera il piano. Con 3 post a settimana i 12 attuali coprono 4 settimane.

## Misurare e crescere (senza toccare il bot)
- Instagram Insights: salvataggi e condivisioni contano più dei like; i caroselli educativi si salvano molto.
- Nel bot (solo admin) `/stato` mostra gli utenti attivi: confronta prima e dopo i post. Il bot non ha un parametro di provenienza,
  quindi l'attribuzione è approssimata.
- Rispondi ai commenti con il link ufficiale in bio e segnala i falsi profili che imitano il bot (sono il rischio più comune).

## Limiti onesti
- **Mai provato dal vivo** con un account Instagram reale: i test sono offline (rete simulata). Alla prima prova usa `check` e un post di test.
- Niente reel (esclusi per scelta); le storie non hanno sticker-link (l'API non lo permette): il link resta in bio.
- Il logo Solana nella mascotte è un marchio di terzi: verifica che l'uso nel profilo sia ok per te.
- L'API pubblica un carosello alla volta, massimo ~100 pubblicazioni al giorno; la versione API è in `config.toml` (`graph_version`) e va aggiornata se Meta la ritira.
- I campi delle inserzioni (categoria speciale finanziaria, budget a livello di gruppo) possono cambiare: se l'API risponde con errore, creane una a mano da Ads Manager.
- Contenuti informativi, non consulenza: la parte legale/fiscale del servizio a pagamento non è risolta (vedi `docs` del bot).
