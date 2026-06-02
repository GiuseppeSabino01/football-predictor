NEWS_EXTRACTION_PROMPT = """
Sei un analista calcistico. Estrai SOLO segnali utili per pronostici betting dalle notizie.

Squadre della partita: {teams}

Articolo:
Fonte: {source}
Titolo: {title}
Sommario: {summary}
URL: {url}

Restituisci JSON valido con questa forma:
[
  {{
    "team": "nome squadra coinvolta",
    "player": "nome giocatore o null",
    "signal_type": "injury|suspension|rotation|morale|tactical|lineup|other",
    "availability": "out|doubtful|available|unknown|null",
    "severity": "low|medium|high",
    "certainty": "concrete|rumor|unknown",
    "confidence": 0.0,
    "reason": "breve motivo"
  }}
]

Regole:
- Non inventare informazioni.
- Se l'articolo non contiene segnali concreti, restituisci [].
- Usa certainty="rumor" se la notizia e' formulata come indiscrezione, ipotesi o voce.
- Usa certainty="concrete" solo se il testo e' esplicito.
- Usa confidence alta solo se il testo e' esplicito.
- Usa solo JSON, senza markdown.
"""


LLM_MARKET_PROBABILITY_PROMPT = """
Sei un secondo modello di analisi calcistica. Devi stimare probabilita' basandoti SOLO sui dati ricevuti:
statistiche recenti, risultati, head-to-head, news e probabilita' statistiche gia' calcolate.

Partita: {match_label}
Competizione: {competition}

Statistiche sintetiche:
{stats_notes}

Risultati storici:
{stats_tables}

News e segnali:
{news_context}

Mercati da stimare:
{markets}

Restituisci JSON valido con questa forma:
{{
  "summary": "breve spiegazione in italiano, massimo 2 frasi",
  "probabilities": [
    {{
      "market": "nome mercato identico",
      "selection": "selezione identica",
      "probability": 0.0,
      "confidence": "low|medium|high",
      "reason": "motivo breve"
    }}
  ]
}}

Regole:
- Non inventare dati non presenti.
- Mantieni le probabilita' tra 0 e 1.
- Per il mercato 1X2 le tre probabilita' devono sommare circa 1.
- Per mercati binari come Over/Under 2.5 e Goal/No Goal, le due probabilita' devono sommare circa 1.
- Per mercati Over/Under tiri o angoli con stessa linea e stessa squadra, le due probabilita' devono sommare circa 1.
- Non copiare meccanicamente la probabilita' statistica: puoi correggerla se risultati recenti, H2H o news lo suggeriscono.
- Se i dati sono scarsi, resta vicino alla probabilita' statistica e segnala confidence low.
- Usa solo JSON, senza markdown.
"""
