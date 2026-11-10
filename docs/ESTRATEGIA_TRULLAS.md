# Estrategia Trullás (MACD triple divergencia)

> **Aviso:** esta es una aproximación técnica basada en descripciones públicas
> de la operativa de David Trullás Vila. No es el método oficial registrado por
> el autor, no cuenta con su validación ni afiliación, y no garantiza sus
> resultados de competición. Debe backtestearse y adaptarse antes de usar dinero
> real.

## Quién es y por qué se añade

David Trullás Vila es un trader y formador español (Manresa, 1974), fundador de
Live in Trading. Fuentes públicas lo describen como campeón de la World Cup
Trading Championships en la división de futuros y con varias ediciones
ganadas. En 2026 se le atribuyen primeros puestos en la Q2 y Q3 de la
competición y una racha de seis títulos.

Fuentes consultadas:

- [Rankia — ¿Quién es David Trullas?](https://www.rankia.com/colaboradores/david-trullas)
- [Rankia — Especulando con MACD y Fibonacci (conferencia)](https://www.rankia.com/blog/opiniones/2202148-especulando-macd-fibonacci-conferencia-david-trullas-iv-foro-finanzas-personales)
- [Resumen público de su operativa: MACD triple divergencia, RSI, volumen y Fibonacci](https://threadreaderapp.com/thread/2115662418009620517.html)

## Reglas públicas resumidas

Las descripciones públicas coinciden en estos elementos:

1. **Divergencia MACD como señal no negociable.** Sin divergencia no hay trade.
   Las versiones más recientes hablan de **triple divergencia**: tres pivotes de
   precio en la misma dirección con el MACD haciendo máximos/mínimos cada vez
   menores/mayores.
2. **Confirmación con RSI y volumen.** Más confirmaciones = más tamaño; menos
   confirmaciones = menos tamaño o no operar.
3. **Niveles primero, señal después.** Marca soportes/resistencias y Fibonacci;
   espera a que el precio llegue a la zona, no anticipa el rebote.
4. **Stop que solo se mueve a favor.** Nunca se aleja; a breakeven cuando la
   operación ya está en beneficio.
5. **Primer objetivo.** Para aprender, cerrar en el primer target; no perseguir
   R:R de 1:7 o 1:10 desde el primer día.
6. **Límite de pérdida diario y parada al objetivo.** Riesgo máximo equivalente
   a 2–3 stops; si llega al objetivo del día, deja de operar.
7. **Evitar la primera hora** en fases de aprendizaje.

La conferencia de 2014 añade el uso de Fibonacci: tras una divergencia en un
nuevo máximo, se dibuja Fibonacci y se busca el corto al romper el primer nivel,
con objetivo en el siguiente (por ejemplo, 23,6% → 38,2%), en operaciones de
5–10 minutos.

## Implementación en este proyecto

Archivo: [`strategies/trullas.py`](../strategies/trullas.py)

Identificador: `trullas_macd_triple_divergence`

Timeframes: **M5, M15, H1, H4**. Se integra en:

- `strategies/catalog.py` → disponible para `agent_strategies` y el consenso.
- `agents/agent_opportunity_hunter.py` → escaneo de los 60 instrumentos.
- `api_server.py` → aparece en el catálogo del dashboard.

Lógica conservadora:

1. Calcula EMA 12/26, MACD 9, RSI 14, ATR 14 y volumen medio 20.
2. Detecta pivotes confirmados (2 velas a cada lado) y exige tres pivotes
   separados al menos 3 velas.
3. Busca precio y MACD divergentes; RSI como confirmación adicional.
4. Exige que el precio esté dentro de una zona Fibonacci (±0,45 ATR) del último
   impulso.
5. Entra al cierre, SL más allá del pivote + 0,35 ATR, TP a 1,5R.
6. Confianza 52–88 según RSI, volumen y zona. El cazador sigue aplicando su
   filtro de confluencia, correlación y macro.

No se envía ninguna orden: la señal solo se publica en el dashboard, el journal
y Telegram, como el resto del sistema.

## Por qué es una aproximación y no una copia

El “Método Trullás”, “Método HLIT” y “Método Cyborg Techs” están registrados por
el autor. Los detalles exactos de sus parámetros, gestión de tamaño y reglas de
salida no son públicos. Lo implementado es una traducción de las reglas
descritas públicamente, con decisiones conservadoras propias:

- Se exige triple divergencia, no una divergencia simple.
- Se exige zona Fibonacci; si no, no hay señal.
- El objetivo es 1,5R, no los objetivos grandes de competición.
- No se replica el aumento de lotaje por “evidencia”; el lotaje lo calcula el
  risk manager del sistema según el riesgo por trade.

## Cómo validarla

Antes de usarla en vivo:

```bash
# 1. Asegúrate de tener datos M5/M15/H1/H4 en data/
# 2. Ejecuta el escaneo y revisa cuántas señales produce
python - <<'PY'
import csv
from strategies.trullas import trullas_macd_triple_divergence
velas = []
with open('data/XAUUSD_M15.csv', encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        velas.append({
            'time': r['time'], 'open': float(r['open']), 'high': float(r['high']),
            'low': float(r['low']), 'close': float(r['close']),
            'volume': float(r.get('volume') or 0),
        })
print(trullas_macd_triple_divergence(velas[-600:], 'XAUUSD', {}))
PY
```

Después:

- Backtest con costes, spread y slippage.
- Compara en M5, M15, H1 y H4.
- Mide win rate, profit factor, max DD y número de señales.
- Si el profit factor no supera 1,2–1,3 con una muestra suficiente, no la actives
  en real.

## Riesgos

- Es una estrategia de **momentum/divergencia**: puede fallar en tendencias
  fuertes y en mercados con noticias.
- El MACD es un indicador retardado; la divergencia no garantiza reversión.
- Los resultados de competición no son reproducibles ni equivalen a una cuenta
  de fondeo con trailing drawdown.
- La atribución a una persona no implica endorsement. Revisa la licencia y los
  términos de cualquier contenido que reutilices.
