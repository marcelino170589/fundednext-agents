# divergence.py
"""Divergencia epistémica entre agentes."""
from difflib import SequenceMatcher


def _sesgo_score(s):
    return {"SHORT": -1.0, "NEUTRAL": 0.0, "LONG": 1.0}.get(s, 0.0)


def _dir_score(d):
    return {"SHORT": -1.0, "LONG": 1.0}.get(d, 0.0)


def divergencia_sesgo(a, c):
    return abs(_sesgo_score(a.get("sesgo", "NEUTRAL")) -
               _dir_score(c.get("direccion", "LONG")))


def divergencia_confianza(a, b, c):
    v = [a.get("confianza", 50), b.get("confianza", 50), c.get("probabilidad_estimada", 50)]
    m = sum(v) / 3
    return (sum((x - m) ** 2 for x in v) / 3) ** 0.5


def divergencia_textual(a, b, c):
    r = [a.get("razon_principal", ""), b.get("razon", ""), c.get("razon", "")]
    r = [x.lower().strip() for x in r if x]
    if len(r) < 3:
        return 0.0
    return (SequenceMatcher(None, r[0], r[1]).ratio() +
            SequenceMatcher(None, r[1], r[2]).ratio() +
            SequenceMatcher(None, r[0], r[2]).ratio()) / 3


def indice_divergencia(a, b, c):
    s = divergencia_sesgo(a, c) / 2.0
    cf = min(divergencia_confianza(a, b, c) / 30.0, 1.0)
    t = divergencia_textual(a, b, c)
    idx = (s * 0.4 + cf * 0.3 + t * 0.3) * 100
    return {"indice": round(idx, 1), "sesgo": round(s * 100, 1),
            "confianza": round(cf * 100, 1), "textual": round(t * 100, 1),
            "colapso": idx < 15}