# convertir_parquet.py
"""
Convierte los archivos Parquet de dukascopy-downloader a CSV
con el formato que espera backtest_fozzy.py: time,open,high,low,close
"""
import os
from pathlib import Path
import pandas as pd

# Mapeo de nombres de duka a nombres estándar
PARES = {
    "EUR-USD": "EURUSD",
    "GBP-USD": "GBPUSD",
    "USD-JPY": "USDJPY",
    "AUD-USD": "AUDUSD",
    "USD-CAD": "USDCAD",
    "NZD-USD": "NZDUSD",
    "XAU-USD": "XAUUSD",
}

BASE_DIR = Path("data/d1/Forex")
OUTPUT_DIR = Path("data")
OUTPUT_DIR.mkdir(exist_ok=True)

print("═══ CONVERSIÓN PARQUET → CSV ═══\n")

for duka_name, std_name in PARES.items():
    # Buscar el archivo Parquet
    parquet_files = list(BASE_DIR.rglob(f"{duka_name}/BID/all.parquet"))
    if not parquet_files:
        print(f"⚠ No encontrado: {duka_name}")
        continue

    parquet_path = parquet_files[0]
    print(f"Leyendo {parquet_path}...")

    try:
        df = pd.read_parquet(parquet_path)
    except Exception as e:
        print(f"  ❌ Error leyendo Parquet: {e}")
        continue

    # Ver las columnas del DataFrame
    print(f"  Columnas: {list(df.columns)}")

    # Renombrar columnas al formato estándar
    rename_map = {}
    for col in df.columns:
        c = col.lower()
        if c in ("timestamp", "time", "date", "datetime"):
            rename_map[col] = "time"
        elif c in ("open", "o"):
            rename_map[col] = "open"
        elif c in ("high", "h"):
            rename_map[col] = "high"
        elif c in ("low", "l"):
            rename_map[col] = "low"
        elif c in ("close", "c"):
            rename_map[col] = "close"
        elif c in ("volume", "vol", "v"):
            rename_map[col] = "volume"

    df = df.rename(columns=rename_map)

    # Verificar que están todas las columnas necesarias
    requeridas = ["time", "open", "high", "low", "close"]
    faltantes = [c for c in requeridas if c not in df.columns]
    if faltantes:
        print(f"  ❌ Faltan columnas: {faltantes}")
        continue

    # Convertir time a string si es datetime
    if pd.api.types.is_datetime64_any_dtype(df["time"]):
        df["time"] = df["time"].dt.strftime("%Y-%m-%d %H:%M:%S")

    # Guardar como CSV
    output_path = OUTPUT_DIR / f"{std_name}_D1.csv"
    df[["time", "open", "high", "low", "close"]].to_csv(output_path, index=False)
    print(f"  ✓ {output_path} ({len(df)} filas)\n")

print("═══ CONVERSIÓN COMPLETADA ═══")
