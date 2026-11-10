# journal.py
"""Journal SQLite: decisiones, señales, trades, equity, alertas locales."""
import sqlite3
import json
import os
from datetime import datetime, date, timedelta
from contextlib import contextmanager

DB_PATH = "data/journal.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, symbol TEXT NOT NULL, operar INTEGER NOT NULL,
    motivo TEXT, capa INTEGER, score REAL, divergencia REAL, direction TEXT,
    agent_trader JSON, agent_fundamental JSON, agent_technical JSON,
    agent_adversary JSON, agent_htf JSON, agent_strategies JSON, prompt_variants JSON
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, decision_id INTEGER,
    symbol TEXT NOT NULL, direction TEXT NOT NULL, entry REAL, sl REAL, tp REAL,
    lotage REAL, score REAL, divergence REAL, duration_est_min INTEGER
);
CREATE TABLE IF NOT EXISTS rule_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, signal_id INTEGER,
    check_name TEXT, passed INTEGER, value REAL, limit_value REAL, detail TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ticket INTEGER UNIQUE,
    ts_open TEXT NOT NULL, ts_close TEXT, symbol TEXT NOT NULL, direction TEXT,
    volume REAL, entry REAL, sl REAL, tp REAL, close_price REAL, pnl REAL,
    duration_sec INTEGER, signal_id INTEGER, result TEXT
);
CREATE TABLE IF NOT EXISTS equity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, equity REAL,
    balance REAL, open_risk REAL, daily_loss REAL, open_positions INTEGER
);
CREATE TABLE IF NOT EXISTS local_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
    severity TEXT NOT NULL, tipo TEXT NOT NULL, symbol TEXT, direction TEXT,
    message TEXT NOT NULL, data JSON, leida INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_dec_ts ON decisions(ts);
CREATE INDEX IF NOT EXISTS idx_trd_ts ON trades(ts_open);
CREATE INDEX IF NOT EXISTS idx_eq_ts ON equity_snapshots(ts);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON local_alerts(ts);
"""


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        conn.executescript(SCHEMA)


def log_decision(symbol, cons, agents, variants):
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO decisions
            (ts, symbol, operar, motivo, capa, score, divergencia, direction,
             agent_trader, agent_fundamental, agent_technical, agent_adversary,
             agent_htf, agent_strategies, prompt_variants)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.utcnow().isoformat(), symbol,
            1 if cons.get("operar") else 0, cons.get("motivo"),
            cons.get("capa"), cons.get("score"),
            cons.get("divergencia", {}).get("indice") if cons.get("divergencia") else None,
            cons.get("direccion"),
            json.dumps(agents.get("a", {}), default=str),
            json.dumps(agents.get("b", {}), default=str),
            json.dumps(agents.get("c", {}), default=str),
            json.dumps(agents.get("d", {}), default=str),
            json.dumps(agents.get("htf", {}), default=str),
            json.dumps(agents.get("strat", {}), default=str),
            json.dumps(variants, default=str),
        ))
        return cur.lastrowid


def log_signal(decision_id, signal):
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO signals
            (ts, decision_id, symbol, direction, entry, sl, tp, lotage,
             score, divergence, duration_est_min)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.utcnow().isoformat(), decision_id, signal["activo"],
            signal["direccion"], signal["entrada"], signal["sl"], signal["tp"],
            signal["lotaje"], signal.get("score_consenso"),
            signal.get("divergencia_indice"), signal.get("duracion_estimada_min"),
        ))
        return cur.lastrowid


def log_rule_check(signal_id, check_name, passed, value, limit_value, detail=""):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO rule_checks
            (ts, signal_id, check_name, passed, value, limit_value, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (datetime.utcnow().isoformat(), signal_id, check_name,
              1 if passed else 0, value, limit_value, detail))


def log_equity(equity, balance, open_risk, daily_loss, open_positions):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO equity_snapshots
            (ts, equity, balance, open_risk, daily_loss, open_positions)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.utcnow().isoformat(), equity, balance,
              open_risk, daily_loss, open_positions))


def log_local_alert(severity, tipo, message, symbol=None, direction=None, data=None):
    """Registra alerta local con deduplicación (misma alerta en 5 min se agrupa)."""
    with get_db() as conn:
        hace_5min = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
        row = conn.execute("""
            SELECT id, data FROM local_alerts
            WHERE tipo = ? AND COALESCE(symbol, '') = ? AND COALESCE(direction, '') = ?
              AND ts >= ? AND leida = 0
            ORDER BY ts DESC LIMIT 1
        """, (tipo, symbol or '', direction or '', hace_5min)).fetchone()

        if row:
            old_data = {}
            try:
                old_data = json.loads(row["data"]) if row["data"] else {}
            except Exception:
                pass
            merged = {**old_data, **(data or {}), "count": old_data.get("count", 1) + 1}
            conn.execute("""
                UPDATE local_alerts
                SET ts = ?, message = ?, data = ?
                WHERE id = ?
            """, (datetime.utcnow().isoformat(), message,
                  json.dumps(merged, default=str), row["id"]))
            return row["id"]
        else:
            cur = conn.execute("""
                INSERT INTO local_alerts
                (ts, severity, tipo, symbol, direction, message, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (datetime.utcnow().isoformat(), severity, tipo, symbol,
                  direction, message, json.dumps(data or {}, default=str)))
            return cur.lastrowid


def get_alerts(limit=50, solo_no_leidas=False):
    with get_db() as conn:
        sql = "SELECT * FROM local_alerts"
        if solo_no_leidas:
            sql += " WHERE leida = 0"
        sql += " ORDER BY ts DESC LIMIT ?"
        rows = [dict(r) for r in conn.execute(sql, (limit,))]
        for r in rows:
            if r.get("data"):
                try:
                    r["data"] = json.loads(r["data"])
                except Exception:
                    r["data"] = {}
        return rows


def mark_alert_read(alert_id):
    with get_db() as conn:
        conn.execute("UPDATE local_alerts SET leida = 1 WHERE id = ?", (alert_id,))


def mark_all_alerts_read():
    with get_db() as conn:
        conn.execute("UPDATE local_alerts SET leida = 1 WHERE leida = 0")


def clear_read_alerts():
    with get_db() as conn:
        conn.execute("DELETE FROM local_alerts WHERE leida = 1")


def get_unread_count():
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) as n FROM local_alerts WHERE leida = 0").fetchone()
        return row["n"] if row else 0


def upsert_trade(t):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO trades
            (ticket, ts_open, ts_close, symbol, direction, volume,
             entry, sl, tp, close_price, pnl, duration_sec, signal_id, result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticket) DO UPDATE SET
                ts_close=excluded.ts_close, close_price=excluded.close_price,
                pnl=excluded.pnl, duration_sec=excluded.duration_sec,
                result=excluded.result
        """, (t.get("ticket"), t.get("ts_open"), t.get("ts_close"),
              t.get("symbol"), t.get("direction"), t.get("volume"),
              t.get("entry"), t.get("sl"), t.get("tp"), t.get("close_price"),
              t.get("pnl"), t.get("duration_sec"), t.get("signal_id"),
              t.get("result")))


def get_recent_decisions(limit=50):
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM decisions ORDER BY ts DESC LIMIT ?", (limit,))]


def get_recent_trades(limit=100):
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM trades ORDER BY ts_open DESC LIMIT ?", (limit,))]


def get_equity_curve(limit=500):
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT ts, equity, balance, daily_loss, open_risk "
            "FROM equity_snapshots ORDER BY ts DESC LIMIT ?", (limit,))]
        return list(reversed(rows))


def get_stats_today():
    hoy = str(date.today())
    with get_db() as conn:
        row = conn.execute("""
            SELECT COUNT(*) as total,
                   COALESCE(SUM(CASE WHEN result='win' THEN 1 ELSE 0 END), 0) as wins,
                   COALESCE(SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END), 0) as losses,
                   COALESCE(SUM(pnl),0) as total_pnl
            FROM trades WHERE ts_open LIKE ?
        """, (f"{hoy}%",)).fetchone()
        return dict(row) if row else {"total": 0, "wins": 0, "losses": 0, "total_pnl": 0}


def get_decision(decision_id: int):
    """Devuelve una decisión con todos sus agentes ya parseados."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM decisions WHERE id = ?",
                           (decision_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        for key in ("agent_trader", "agent_fundamental", "agent_technical",
                    "agent_adversary", "agent_htf", "agent_strategies",
                    "prompt_variants"):
            if isinstance(data.get(key), str):
                try:
                    data[key] = json.loads(data[key])
                except Exception:
                    data[key] = {}
        return data


def get_recent_signals(limit: int = 50):
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM signals ORDER BY ts DESC LIMIT ?", (limit,))]


def get_counts() -> dict:
    with get_db() as conn:
        counts = {}
        for table in ("decisions", "signals", "trades", "equity_snapshots",
                      "local_alerts", "rule_checks"):
            try:
                counts[table] = conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            except Exception:
                counts[table] = 0
        return counts


def get_journal_summary(days: int = 30) -> dict:
    """Resumen agregado para la vista Journal (sin bloquear con datos enormes)."""
    since = (datetime.utcnow() - timedelta(days=max(1, int(days)))).isoformat()
    with get_db() as conn:
        totals = dict(conn.execute("""
            SELECT COUNT(*) AS decisiones,
                   SUM(CASE WHEN operar = 1 THEN 1 ELSE 0 END) AS operar,
                   MIN(ts) AS primera, MAX(ts) AS ultima
            FROM decisions WHERE ts >= ?
        """, (since,)).fetchone() or {})
        por_capa = [dict(r) for r in conn.execute("""
            SELECT COALESCE(capa, 0) AS capa, COUNT(*) AS n
            FROM decisions WHERE ts >= ?
            GROUP BY COALESCE(capa, 0) ORDER BY capa
        """, (since,))]
        por_simbolo = [dict(r) for r in conn.execute("""
            SELECT symbol, COUNT(*) AS n,
                   SUM(CASE WHEN operar = 1 THEN 1 ELSE 0 END) AS operar
            FROM decisions WHERE ts >= ?
            GROUP BY symbol ORDER BY n DESC LIMIT 20
        """, (since,))]
        trades = dict(conn.execute("""
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END), 0) AS wins,
                   COALESCE(SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END), 0) AS losses,
                   COALESCE(SUM(pnl), 0) AS pnl
            FROM trades WHERE ts_open >= ?
        """, (since,)).fetchone() or {})
        alerts = dict(conn.execute("""
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN leida = 0 THEN 1 ELSE 0 END), 0) AS no_leidas
            FROM local_alerts WHERE ts >= ?
        """, (since,)).fetchone() or {})
    return {
        "desde": since,
        "dias": days,
        "decisiones": totals,
        "por_capa": por_capa,
        "por_simbolo": por_simbolo,
        "trades": trades,
        "alerts": alerts,
    }
