from __future__ import annotations

import argparse
from datetime import date

from config.settings import load_settings
from services.predictor import PredictionService
from services.report_builder import compact_text_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Football betting predictor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    today_parser = subparsers.add_parser("today", help="Pronostici per una data")
    today_parser.add_argument("--date", default=date.today().isoformat())
    today_parser.add_argument("--worldcup", action="store_true")

    predict_parser = subparsers.add_parser("predict", help="Pronostico manuale")
    predict_parser.add_argument("--home", required=True)
    predict_parser.add_argument("--away", required=True)
    predict_parser.add_argument("--competition", default="Manuale")

    args = parser.parse_args()
    service = PredictionService(load_settings())

    if args.command == "today":
        predictions, errors = service.predictions_for_date(date.fromisoformat(args.date), args.worldcup)
        for error in errors:
            print(f"[warning] {error}")
        if not predictions:
            print("Nessuna partita trovata per la data richiesta.")
            return
        for prediction in predictions:
            print(compact_text_report(prediction))
            print("\n" + "=" * 72 + "\n")
        return

    if args.command == "predict":
        prediction = service.predict_single(args.home, args.away, args.competition)
        print(compact_text_report(prediction))


if __name__ == "__main__":
    main()

