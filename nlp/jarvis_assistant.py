from __future__ import annotations

from dataclasses import dataclass, field

from nlp.gemini_client import GeminiClient
from schemas import MatchPrediction, MarketPick


@dataclass(slots=True)
class JarvisReply:
    answer: str
    warnings: list[str] = field(default_factory=list)


class JarvisAssistant:
    def __init__(self, gemini: GeminiClient):
        self.gemini = gemini

    def answer_text(self, prediction: MatchPrediction, question: str) -> JarvisReply:
        question = question.strip()
        if not question:
            return JarvisReply("Dimmi cosa vuoi analizzare su questa partita.")
        if not self.gemini.settings.has_gemini:
            return JarvisReply(_fallback_answer(prediction), ["Gemini non configurato: risposta basata sul modello statistico."])

        prompt = _jarvis_prompt(prediction, question)
        try:
            answer = self.gemini.generate_text(prompt)
        except Exception as exc:
            return JarvisReply(_fallback_answer(prediction), [f"GiGi Gemini non disponibile: {exc}"])
        return JarvisReply(answer.strip() or _fallback_answer(prediction))

    def answer_audio(self, prediction: MatchPrediction, audio_bytes: bytes, mime_type: str) -> JarvisReply:
        if not audio_bytes:
            return JarvisReply("Non ho ricevuto audio da analizzare.")
        if not self.gemini.settings.has_gemini:
            return JarvisReply(_fallback_answer(prediction), ["Gemini non configurato: audio non trascrivibile."])

        prompt = (
            "Trascrivi mentalmente la domanda audio dell'utente e rispondi come GiGi in italiano. "
            "Usa solo il contesto partita qui sotto. Se il dato richiesto non esiste, dillo chiaramente.\n\n"
            f"{_prediction_context(prediction)}"
        )
        try:
            answer = self.gemini.generate_text_with_audio(prompt, audio_bytes, mime_type)
        except Exception as exc:
            return JarvisReply(
                "Non riesco a interpretare questo audio con il modello attuale. Scrivimi la domanda in chat.",
                [f"Audio GiGi non disponibile: {exc}"],
            )
        return JarvisReply(answer.strip() or "Ho ricevuto l'audio, ma non ho ottenuto una risposta utile.")


def _jarvis_prompt(prediction: MatchPrediction, question: str) -> str:
    return (
        "Sei GiGi, assistente personale per analisi calcistica e betting responsabile.\n"
        "Rispondi in italiano, tono sicuro ma non assoluto, massimo 8-10 righe.\n"
        "Usa SOLO i dati della partita forniti. Non inventare infortuni, quote reali o notizie non presenti.\n"
        "Se l'utente chiede una quota consigliata, dai una soglia minima coerente con la probabilita/fair odd del modello, "
        "e specifica che non e' una certezza e non e' consulenza finanziaria.\n"
        "Se la domanda riguarda tiri o angoli, usa i mercati tiri/angoli stimati e ricorda che hanno confidenza bassa.\n\n"
        f"{_prediction_context(prediction)}\n\n"
        f"Domanda utente: {question}\n"
        "Risposta GiGi:"
    )


def _prediction_context(prediction: MatchPrediction) -> str:
    match = prediction.match
    lines = [
        f"Partita: {match.label}",
        f"Competizione: {match.competition}",
        f"Data: {match.match_date.isoformat()}",
        f"Sintesi modello: {prediction.summary}",
        f"Risultato esatto stimato: {prediction.exact_score}",
        f"Confidenza generale: {prediction.confidence}",
        "",
        "Mercati disponibili:",
    ]
    for pick in _ordered_picks(prediction.picks)[:32]:
        avg = pick.average_probability
        fair = (1 / avg) if avg else None
        llm = f", modello LLM {pick.llm_probability:.1%}" if pick.llm_probability is not None else ""
        fair_text = f", quota fair {fair:.2f}" if fair else ""
        notes = f", note: {' '.join(pick.notes[:2])}" if pick.notes else ""
        lines.append(
            f"- {pick.market} | {pick.selection}: statistica {pick.probability:.1%}{llm}, "
            f"media {avg:.1%}{fair_text}, segnale {pick.recommendation}, confidenza {pick.confidence}{notes}"
        )

    if prediction.stats_notes:
        lines.append("")
        lines.append("Statistiche storiche:")
        lines.extend(f"- {note}" for note in prediction.stats_notes[:8])

    if prediction.stats_tables:
        lines.append("")
        lines.append("Risultati recenti:")
        for title, rows in prediction.stats_tables.items():
            if not rows:
                continue
            lines.append(title)
            for row in rows[:6]:
                lines.append(
                    f"- {row.get('Data', '')}: {row.get('Partita', '')} "
                    f"{row.get('Risultato', '')}, vincitore {row.get('Vincitore', '')}"
                )

    if prediction.news_articles:
        lines.append("")
        lines.append("News trovate:")
        for article in prediction.news_articles[:6]:
            lines.append(f"- {article.source}: {article.title}. {article.summary}")

    if prediction.warnings:
        lines.append("")
        lines.append("Warning modello:")
        lines.extend(f"- {warning}" for warning in prediction.warnings[:6])

    return "\n".join(lines)


def _ordered_picks(picks: list[MarketPick]) -> list[MarketPick]:
    priority = {
        "1X2": 0,
        "Doppia chance": 1,
        "Over/Under 2.5": 2,
        "Goal/No Goal": 3,
    }
    return sorted(picks, key=lambda pick: (priority.get(pick.market, 10), -pick.average_probability))


def _fallback_answer(prediction: MatchPrediction) -> str:
    one_x_two = [pick for pick in prediction.picks if pick.market == "1X2"]
    top = max(one_x_two, key=lambda pick: pick.average_probability) if one_x_two else None
    if not top:
        return "Non ho abbastanza dati per dare un parere su questa partita."
    fair = 1 / top.average_probability if top.average_probability else 0
    return (
        f"GiGi offline: dal modello statistico il pick principale e' {top.selection} "
        f"al {top.average_probability:.1%}. Quota fair circa {fair:.2f}. "
        f"Risultato esatto stimato: {prediction.exact_score}. "
        "Usa questa lettura come supporto probabilistico, non come certezza."
    )
