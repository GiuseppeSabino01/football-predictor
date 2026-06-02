# Football Betting Predictor

App personale per pronostici calcistici in stile betting. Combina API gratuite, RSS italiani, Gemini e modelli statistici semplici.

## Funzioni MVP

- Pronostici partite del giorno.
- Focus Mondiali 2026.
- 1X2, risultato esatto, over/under 2.5, goal/no goal, doppia chance.
- Passaggio turno quando la partita e' da knockout.
- Value betting rispetto alle quote quando disponibili.
- Mercati tiri squadra e giocatore con warning se i dati gratuiti non bastano.
- Forma recente e head-to-head per nazionali tramite storico gratuito martj42/international_results.
- News italiane gratuite via RSS con analisi Gemini.
- Dashboard Streamlit protetta da password.
- CLI locale.

## Setup locale

1. Verifica che il file `.env` sia nella cartella del progetto e contenga:

```env
GEMINI_API_KEY=...
API_FOOTBALL_KEY=...
FOOTBALL_DATA_ORG_KEY=...
THE_ODDS_API_KEY=
ODDS_REGION=eu
SUPABASE_URL=...
SUPABASE_ANON_KEY=...
APP_PASSWORD=...
API_FOOTBALL_FREE_MODE=true
```

2. Installa le dipendenze:

```powershell
python -m pip install -r requirements.txt
```

3. Avvia la dashboard:

```powershell
python -m streamlit run app/streamlit_app.py
```

4. Apri:

```text
http://localhost:8501
```

## CLI

```powershell
python -m app.cli today
python -m app.cli today --worldcup
python -m app.cli predict --home "France" --away "Brazil"
```

## Deploy telefono

Quando la versione locale gira:

1. Crea repository GitHub.
2. Carica il progetto senza `.env`.
3. Su Streamlit Community Cloud crea una app dal repository.
4. Main file: `app/streamlit_app.py`.
5. Inserisci le chiavi in Streamlit secrets usando `.streamlit/secrets.toml.example` come modello.

## Nota dati

Le predizioni non sono consigli finanziari. I mercati tiri e player props dipendono molto dalla copertura gratuita: quando i dati sono incompleti, l'app abbassa la confidenza o segnala dati insufficienti.

Durante il test locale il piano free di API-Football ha rifiutato la stagione 2026. Per i Mondiali l'app usa quindi OpenLigaDB e football-data.org come fonti fixture, mentre API-Football resta opzionale per competizioni e stagioni abilitate dalla tua chiave.

Le quote mostrate come `Quota modello` sono quote eque calcolate dal modello, non quote bookmaker. Quando non sono disponibili quote gratuite automatiche, puoi aprire "Inserisci quote bookmaker manuali" nella scheda partita e incollare quote reali 1X2 per calcolare il value.

Per quote automatiche reali possiamo aggiungere una key gratuita di un provider dedicato come The Odds API. La loro documentazione espone endpoint `/v4/sports/{sport}/odds` con mercati `h2h`, `spreads`, `totals` e regioni come `eu`; il piano free e' limitato, quindi va usato con cache.

Se Python sul PC mostra `CERTIFICATE_VERIFY_FAILED`, puoi aggiungere temporaneamente:

```env
DISABLE_SSL_VERIFY=true
```

Usalo solo se necessario. Su Streamlit Cloud normalmente non serve.
