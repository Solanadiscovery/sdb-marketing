# Campagna Instagram · Solana DEX Discovery

Strumento **separato** dal bot: non si collega al VPS, al database né a Telegram. Contiene 12 contenuti già pronti
(italiano e inglese; carosello 1080×1350 e storia 1080×1920 con la mascotte originale), il controllo di conformità,
la pubblicazione automatica con l'API ufficiale di Instagram e un modulo per le inserzioni a pagamento (sempre create **in pausa**).

## Dove si trova
- Repository (pubblico, nessun segreto dentro): https://github.com/Solanadiscovery/sdb-marketing
- Immagini e pagine legali online (GitHub Pages): https://solanadiscovery.github.io/sdb-marketing/
  - privacy: `privacy.html` · eliminazione dati: `privacy.html#cancellazione-dati` · condizioni d'uso: `terms.html`
- Automazioni (scheda *Actions*): **Crea e pubblica i file multimediali** (a ogni modifica), **Pubblica su Instagram**
  (ogni 30 minuti), **Verifica configurazione** (a mano, non pubblica nulla).

## Cosa resta da fare (una volta, solo il titolare dell'account)
1. **Meta** → app *SDB Publisher* → *Casi d'uso* → Instagram → *Personalizza* / *Autorizzazioni e funzioni*: aggiungi
   `instagram_business_content_publish` (serve per pubblicare).
2. *Ruoli dell'app* → *Aggiungi persone* → **Tester di Instagram** → nome utente Instagram del profilo. Accetta l'invito su
   https://www.instagram.com/accounts/manage_access/ (scheda *Inviti tester*).
3. Caso d'uso Instagram → *Genera i token d'accesso* → *Aggiungi account* → **Genera token** → copia il token.
4. **GitHub** → https://github.com/Solanadiscovery/sdb-marketing/settings/secrets/actions/new → nome `IG_ACCESS_TOKEN`,
   valore = il token → *Add secret*. Mai incollarlo altrove (chat, file, email).
5. Facoltativo: Meta → *Impostazioni app → Generali*: URL privacy, condizioni d'uso ed eliminazione dati (indirizzi sopra).

Poi non serve altro: al primo giro il workflow verifica account, immagini e permesso di pubblicazione **senza pubblicare**,
crea il calendario dal giorno dopo e da lì pubblica da solo. Per un controllo immediato: *Actions → Verifica configurazione → Run workflow*.

## Come funziona
- **Calendario:** carosello lun/mer/ven alle 18:30, storia ("oggi nel feed") lo stesso giorno alle 12:30 (`config.toml`).
  Dopo 12 contenuti ricomincia; un contenuto rimasto indietro di oltre 36 ore viene saltato, mai pubblicato in blocco.
- **Token:** riconosciuto da solo. Token *Instagram Login* (dalla dashboard Meta) → `graph.instagram.com`, l'ID dell'account
  si ricava dal token e il token si **rinnova da solo ogni settimana** (dura 60 giorni dall'ultimo rinnovo). Token della Pagina
  Facebook (`EAA…`) → `graph.facebook.com` e serve anche il segreto `IG_USER_ID`.
- **Avvisi:** se qualcosa non va (token scaduto o in scadenza entro 7 giorni, permesso mancante, immagine non raggiungibile)
  il job fallisce e GitHub manda un'email, **al massimo una al giorno** per lo stesso problema. Senza token non fa nulla e non dà errori.
- **Sicurezza:** il token sta solo nei segreti di GitHub. `state.json` (pubblico) contiene solo un'impronta non reversibile
  del token, mai il token. `MEDIA_BASE_URL` su GitHub non serve (si calcola dal repository).

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
**non aggirare** la revisione. I post organici non costano nulla, ma restano soggetti alle regole della community.

## Comandi (`python -m mkt <comando>`, anche dal PC con un file `.env`)
| Comando | Cosa fa |
|---|---|
| `lint` | controlla la conformità di tutti i post |
| `render [--all]` | crea carosello e storia in `out/` |
| `check` | verifica token, account, immagini e permesso di pubblicazione (non pubblica) |
| `publish [--live]` | pubblica il contenuto in scadenza (senza `--live`: simulazione) |
| `status` | calendario e cosa è già uscito |
| `plan --start AAAA-MM-GG` | (facoltativo) riparte il calendario da una data |
| `export` | `calendario_<lingua>.md` per pubblicare a mano (Meta Business Suite) |
| `ads-blueprint --budget 5 --days 7` | scrive `ads_plan.md` (struttura, misure, regole di arresto) |
| `ads-create [--live]` | crea campagna **in pausa** (tetto 20 €/giorno e 14 giorni nel codice) |

## Personalizzare
- Lingua del profilo, giorni, ora: `config.toml` (`language = "en"` per un profilo inglese).
- Testi: `content/posts.json` (una voce per post, `it` e `en`); al salvataggio su GitHub immagini e storie si rigenerano da sole.
- Grafica: `mkt/render.py` (layout; la mascotte non si tocca). Font Inter (licenza OFL).
- Nuovi post: aggiungine in `posts.json` e rigenera il piano. Con 3 post a settimana i 12 attuali coprono 4 settimane.

## Misurare e crescere (senza toccare il bot)
- Instagram Insights: salvataggi e condivisioni contano più dei like; i caroselli educativi si salvano molto.
- Nel bot (solo admin) `/stato` mostra gli utenti attivi: confronta prima e dopo i post. Il bot non ha un parametro di provenienza,
  quindi l'attribuzione è approssimata.
- Rispondi ai commenti con il link ufficiale in bio e segnala i falsi profili che imitano il bot (sono il rischio più comune).

## Limiti onesti
- **Non ancora provato dal vivo** con l'account reale: i 33 test sono offline (rete simulata). Il primo avvio verifica tutto con un contenitore di prova che non viene pubblicato.
- Il rinnovo automatico del token presuppone che Meta restituisca lo stesso token (comportamento osservato, non documentato): se ne restituisce uno diverso arriva un avviso.
- Niente reel (esclusi per scelta); le storie non hanno sticker-link (l'API non lo permette): il link resta in bio.
- Il logo Solana nella mascotte è un marchio di terzi: verifica che l'uso nel profilo sia ok per te.
- L'API pubblica un carosello alla volta, massimo ~100 pubblicazioni al giorno; la versione API è in `config.toml` (`graph_version`) e va aggiornata se Meta la ritira.
- I campi delle inserzioni (categoria speciale finanziaria, budget a livello di gruppo) possono cambiare: se l'API risponde con errore, creane una a mano da Ads Manager.
- Contenuti informativi, non consulenza: la parte legale/fiscale del servizio a pagamento non è risolta (vedi `docs` del bot).
