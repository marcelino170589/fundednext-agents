# resample_m1.py
"""Resamplea M1 a M5 y M15. Uso: python resample_m1.py XAUUSD"""
import pandas as pd
from pathlib import Path
import sys


def resample(input_csv, output_csv, rule):
    df = pd.read_csv(input_csv, parse_dates=["time"])
    df = df.set_index("time")
    resampled = df.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    resampled.to_csv(output_csv)
    print(f"✅ {output_csv}: {len(resampled)} velas")


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
    m1_path = f"data/{symbol}_M1.csv"
    if not Path(m1_path).exists():
        print(f"❌ {m1_path} no existe. Descarga M1 primero con:")
        print(f"   duka download {symbol} --from 2024 --tf m1")
        print(f"   duka export {symbol} --from 2024 --tf m1 -o data/{symbol}_M1.csv")
        sys.exit(1)
    resample(m1_path, f"data/{symbol}_M5.csv", "5min")
    resample(m1_path, f"data/{symbol}_M15.csv", "15min")
