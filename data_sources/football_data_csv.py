from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(slots=True)
class HistoricalCsvLoader:
    data_dir: Path

    def load_local_csv(self, filename: str) -> pd.DataFrame:
        path = self.data_dir / filename
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path)

