# Datos históricos

Este repositorio incluye los CSV de **D1, H4 y H1** de los símbolos principales
para que el dashboard de mercado y los backtests funcionen al clonar el
proyecto. Los archivos M1, M5 y M15 pesan cientos de MB y se excluyen del
control de versiones.

## Formato esperado

```csv
time,open,high,low,close,volume
2026-11-06 20:00:00,4063.415,4069.135,4060.295,4065.685,2.355715
```

`time` se interpreta como UTC. `volume` es opcional; si falta, la app usa 0.

## Regenerar los datos

Opciones:

1. Exportar desde MT5 (`Herramientas → Historial → Exportar`).
2. Usar `dukascopy-downloader` (ya está en el entorno) y convertir con
   `convertir_parquet.py` para D1.
3. Copiar los CSV que ya existen en tu instalación local a `data/`.

Nombres esperados: `{SIMBOLO}_{TIMEFRAME}.csv`, por ejemplo
`XAUUSD_H1.csv`, `EURUSD_D1.csv`, `USDJPY_H4.csv`.

## Por qué no están todos

El repositorio debe ser ligero. Los CSV M1/M5/M15 son datos de trabajo, no
código fuente; se pueden reconstruir y no conviene versionarlos. Si necesitas
un espejo completo, usa Git LFS o un bucket externo.
