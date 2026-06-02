from __future__ import annotations

from schemas import MatchPrediction


def compact_text_report(prediction: MatchPrediction) -> str:
    match = prediction.match
    lines = [
        f"{match.label} ({match.competition})",
        prediction.summary,
        f"Confidenza: {prediction.confidence}",
        "",
        "Mercati principali:",
    ]
    for pick in prediction.picks[:10]:
        llm_text = f"{pick.llm_probability:.1%}" if pick.llm_probability is not None else "-"
        odd_text = f", quota media {1 / pick.average_probability:.2f}" if pick.average_probability else ""
        lines.append(
            f"- {pick.market}: {pick.selection} stat {pick.probability:.1%}, "
            f"LLM {llm_text}, media {pick.average_probability:.1%}{odd_text}"
        )
    if prediction.llm_summary:
        lines.append("")
        lines.append(f"Sintesi Gemini: {prediction.llm_summary}")
    if prediction.news_signals:
        lines.append("")
        lines.append("News rilevanti:")
        for signal in prediction.news_signals:
            lines.append(
                f"- {signal.team}: {signal.signal_type} {signal.severity}, "
                f"{signal.certainty} ({signal.confidence:.0%})"
            )
    if prediction.news_articles:
        lines.append("")
        lines.append("Articoli trovati:")
        for article in prediction.news_articles[:5]:
            lines.append(f"- {article.source} | {article.freshness_label}: {article.title}")
    if prediction.stats_notes:
        lines.append("")
        lines.append("Statistiche usate:")
        lines.extend(f"- {note}" for note in prediction.stats_notes)
    if prediction.stats_tables:
        lines.append("")
        lines.append("Risultati recenti:")
        for title, rows in prediction.stats_tables.items():
            if not rows:
                continue
            lines.append(f"- {title}:")
            for row in rows[:5]:
                lines.append(
                    f"  {row['Data']} | {row['Partita']} | {row['Risultato']} | "
                    f"vincitore: {row['Vincitore']}"
                )
    if prediction.warnings:
        lines.append("")
        lines.append("Warning:")
        lines.extend(f"- {warning}" for warning in prediction.warnings)
    return "\n".join(lines)
