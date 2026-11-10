# bias_auditor.py
"""Auditoría de sesgos y rendimiento por variante."""
import json, os
from collections import defaultdict


def registrar_decision(signal, agents, resultado=None):
    os.makedirs("logs", exist_ok=True)
    entry = {"ts": signal.get("timestamp"), "symbol": signal.get("activo"),
             "direccion": signal.get("direccion"),
             "divergencia": signal.get("divergencia_indice"),
             "score": signal.get("score_consenso"),
             "agente_trader": agents.get("a"), "agente_fundamental": agents.get("b"),
             "agente_tecnico": agents.get("c"), "resultado": resultado}
    with open("logs/audit.jsonl", "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def detectar_sesgos(ventana=100):
    path = "logs/audit.jsonl"
    if not os.path.exists(path): return {}
    with open(path) as f:
        entradas = [json.loads(l) for l in f.readlines()[-ventana:]]
    if not entradas: return {}
    sesgos = {}
    longs = sum(1 for e in entradas if e.get("agente_tecnico", {}).get("direccion") == "LONG")
    if longs / len(entradas) > 0.70: sesgos["tecnico_long_bias"] = f"{longs}/{len(entradas)}"
    neutral = sum(1 for e in entradas if e.get("agente_trader", {}).get("sesgo") == "NEUTRAL")
    if neutral / len(entradas) > 0.50: sesgos["trader_neutral_bias"] = f"{neutral}/{len(entradas)}"
    divs = [e.get("divergencia", 50) for e in entradas if e.get("divergencia")]
    if divs and sum(divs) / len(divs) < 20:
        sesgos["colapso_cronico"] = f"div media {sum(divs)/len(divs):.1f}"
    return sesgos


def rendimiento_por_variante():
    uso_path = "logs/prompt_usage.jsonl"
    audit_path = "logs/audit.jsonl"
    if not os.path.exists(uso_path) or not os.path.exists(audit_path): return {}
    with open(audit_path) as f:
        ops = [json.loads(l) for l in f.readlines()]
    res_by_key = {}
    for op in ops:
        if op.get("resultado"):
            res_by_key[(op.get("symbol"), op["ts"][:16])] = op["resultado"]
    stats = defaultdict(lambda: defaultdict(lambda: {"n": 0, "wins": 0}))
    with open(uso_path) as f:
        for line in f:
            u = json.loads(line)
            r = res_by_key.get((u["symbol"], u["ts"][:16]))
            if r is None: continue
            stats[u["agent"]][u["variant"]]["n"] += 1
            if r == "win": stats[u["agent"]][u["variant"]]["wins"] += 1
    resumen = {}
    for ag, vars_ in stats.items():
        resumen[ag] = {}
        for v, s in vars_.items():
            if s["n"] >= 5:
                resumen[ag][v] = {"n": s["n"],
                                   "win_rate": round(s["wins"] / s["n"] * 100, 1)}
    return resumen


def auto_blacklist(muestra=20, wr_min=30.0):
    from prompt_rotator import update_blacklist
    rend = rendimiento_por_variante()
    for ag, vars_ in rend.items():
        for v, m in vars_.items():
            if m["n"] >= muestra and m["win_rate"] < wr_min:
                update_blacklist(ag, v, f"WR {m['win_rate']}% (n={m['n']})")