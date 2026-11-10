# consensus_v2.py
"""
Consenso de 9 capas con jerarquía profesional.
Capa 1: Veto fundamental (vinculante)
Capa 2: Alineación técnico-fundamental
Capa 3: Divergencia epistémica
Capa 4: Score mínimo
Capa 5: Veto adversario
Capa 6: Objetivo diario + 20% consistency
Capa 7: Filtro HTF
Capa 8: Confluencia estrategias
Capa 9: Re-verificación final
"""
import logging
from divergence import indice_divergencia
from config import (
    MIN_SCORE_CONSENSUS, MIN_DIVERGENCE_INDEX, MAX_ADVERSARY_GRAVITY,
    MAX_DAILY_PROFIT_USD, CONSISTENCY_LIMIT, PENALTY_NEAR_LIMIT,
    MIN_PROBABILITY_CONTINUATION,
)

log = logging.getLogger("consensus")


def consenso_v2(a, b, c, adversary, profit_snapshot,
                htf_validation=None, strategy_result=None):
    # ═══ CAPA 1: VETO FUNDAMENTAL (vinculante) ═══
    veredicto = b.get("veredicto", "NO_TRADE")
    if veredicto == "NO_TRADE" or b.get("bloqueado_por_noticia"):
        return {
            "operar": False,
            "motivo": f"Veto fundamental: {b.get('razon', 'NO_TRADE')[:60]}",
            "capa": 1,
        }

    # ═══ CAPA 2: ALINEACIÓN TÉCNICO-FUNDAMENTAL ═══
    direccion = c.get("direccion", "NONE")
    if direccion == "NONE":
        return {"operar": False, "motivo": "Técnico no propuso entrada", "capa": 2}

    if veredicto == "BULLISH" and direccion != "LONG":
        return {"operar": False,
                "motivo": f"Técnico {direccion} contradice macro BULLISH", "capa": 2}
    if veredicto == "BEARISH" and direccion != "SHORT":
        return {"operar": False,
                "motivo": f"Técnico {direccion} contradice macro BEARISH", "capa": 2}

    # ═══ CAPA 3: DIVERGENCIA EPISTÉMICA ═══
    div = indice_divergencia(a, b, c)
    if div["indice"] < MIN_DIVERGENCE_INDEX:
        return {"operar": False,
                "motivo": f"Colapso epistémico ({div['indice']})",
                "capa": 3, "divergencia": div}

    # ═══ CAPA 4: SCORE MÍNIMO ═══
    sesgo_trader = a.get("sesgo", "NEUTRAL")
    if sesgo_trader == direccion:
        peso = 1.0
    elif sesgo_trader == "NEUTRAL":
        peso = 0.6
    else:
        peso = 0.2

    score = (a.get("confianza", 0) * 0.25 +
             b.get("confianza", 0) * 0.35 +  # Fundamental pesa más
             c.get("probabilidad_estimada", 0) * 0.40) * peso

    if div["indice"] < 30:
        score *= 0.85

    if score < MIN_SCORE_CONSENSUS:
        return {"operar": False,
                "motivo": f"Score {score:.1f} < {MIN_SCORE_CONSENSUS}",
                "capa": 4, "score": round(score, 1), "divergencia": div}

    # ═══ CAPA 5: VETO ADVERSARIO ═══
    if adversary.get("objecion_valida") and \
       adversary.get("gravedad", 0) >= MAX_ADVERSARY_GRAVITY:
        return {"operar": False,
                "motivo": f"Veto adversario (g={adversary['gravedad']})",
                "capa": 5, "score": round(score, 1), "divergencia": div}

    # ═══ CAPA 6: OBJETIVO DIARIO + 20% CONSISTENCY ═══
    if profit_snapshot:
        dilution = profit_snapshot.get("dilution", {})
        objetivo = profit_snapshot.get("objetivo_diario_efectivo", MAX_DAILY_PROFIT_USD)

        if profit_snapshot.get("objetivo_alcanzado"):
            motivo = f"Objetivo diario (${profit_snapshot['daily_pnl']:.0f}/{objetivo:.0f})"
            if dilution.get("active"):
                motivo += " [DILUCIÓN]"
            return {"operar": False, "motivo": motivo, "capa": 6,
                    "score": round(score, 1), "dilution": dilution}

        ratio = profit_snapshot.get("ratio_consistencia", 0) / 100.0
        if ratio >= CONSISTENCY_LIMIT:
            return {"operar": False,
                    "motivo": f"Consistency {ratio*100:.1f}% ≥ 20%",
                    "capa": 6, "score": round(score, 1), "dilution": dilution}

        if dilution.get("active"):
            score *= 0.90
        elif ratio > PENALTY_NEAR_LIMIT:
            score *= 0.85

    # ═══ CAPA 7: FILTRO HTF ═══
    if htf_validation:
        rec = htf_validation.get("recomendacion", "")
        prob = htf_validation.get("probabilidad_continuacion", 0)

        if rec in ("REVERSAL_WATCH", "AVOID"):
            return {"operar": False, "motivo": f"HTF: {rec}", "capa": 7,
                    "score": round(score, 1)}

        h4 = htf_validation.get("h4", {}).get("trend_direction")
        if h4 and h4 != direccion:
            return {"operar": False,
                    "motivo": f"HTF H4 {h4} vs {direccion}", "capa": 7,
                    "score": round(score, 1)}

        if prob < MIN_PROBABILITY_CONTINUATION:
            return {"operar": False,
                    "motivo": f"HTF prob {prob}% < {MIN_PROBABILITY_CONTINUATION}%",
                    "capa": 7, "score": round(score, 1)}

        if rec == "ENTER_WITH_TREND":
            score *= 1.0 + (htf_validation.get("calidad_entrada", 50) / 100.0) * 0.25

    # ═══ CAPA 8: CONFLUENCIA ESTRATEGIAS ═══
    if strategy_result and strategy_result.get("consensus"):
        sc = strategy_result["consensus"]
        if sc["direction"] == direccion:
            score *= 1.15
        else:
            score *= 0.85

    # ═══ CAPA 9: RE-VERIFICACIÓN ═══
    if score < MIN_SCORE_CONSENSUS:
        return {"operar": False,
                "motivo": f"Score final {score:.1f} < {MIN_SCORE_CONSENSUS}",
                "capa": 9, "score": round(score, 1), "divergencia": div}

    return {
        "operar": True,
        "score": round(score, 1),
        "direccion": direccion,
        "tecnico": c,
        "divergencia": div,
        "veredicto_macro": veredicto,
        "dilution": profit_snapshot.get("dilution", {}) if profit_snapshot else {},
    }
