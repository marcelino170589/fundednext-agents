# scheduler.py
"""Tareas programadas (FNL:004)."""
import logging, os, shutil
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

log = logging.getLogger("scheduler")
_sched = None


def job_auto_blacklist():
    from bias_auditor import auto_blacklist
    try: auto_blacklist(); log.info("[job] blacklist OK")
    except Exception as e: log.error(f"[job] blacklist: {e}")


def job_detectar_sesgos():
    from bias_auditor import detectar_sesgos
    from notifier import notify
    try:
        sesgos = detectar_sesgos()
        if sesgos:
            msg = "*Sesgos:*\n" + "\n".join(f"• `{k}`: {v}" for k, v in sesgos.items())
            notify("WARNING", msg, dedup_key="bias")
    except Exception as e: log.error(f"[job] sesgos: {e}")


def job_health_check():
    from state_manager import load, ea_vivo
    try:
        st = load(); ea_ok = ea_vivo(120)
        if not ea_ok:
            from notifier import notify_ea_status
            notify_ea_status(False)
        log.debug(f"[health] equity={st.get('equity')} ea_ok={ea_ok}")
    except Exception as e: log.error(f"[health] {e}")


def job_rotar_logs():
    os.makedirs("logs/archive", exist_ok=True)
    limite = datetime.utcnow() - timedelta(days=7)
    for f in os.listdir("logs"):
        ruta = os.path.join("logs", f)
        if not os.path.isfile(ruta) or f.endswith(".jsonl"): continue
        mt = datetime.utcfromtimestamp(os.path.getmtime(ruta))
        if mt < limite:
            shutil.move(ruta, f"logs/archive/{f}.{mt.strftime('%Y%m%d')}")


def job_daily_summary():
    from profit_tracker import ProfitTracker
    from notifier import notify
    from datetime import date
    pt = ProfitTracker.load("default")
    snap = pt.snapshot()
    msg = (f"*Resumen {date.today()} — FNL:004*\n\n"
           f"P&L hoy: ${snap['daily_pnl']:.2f} / $100\n"
           f"P&L ciclo: ${snap['total_pnl_ciclo']:.2f}\n"
           f"Mejor día: ${snap['best_day_pnl']:.2f}\n"
           f"Consistency: {snap['ratio_consistencia']:.1f}% (límite 20%)\n"
           f"Trailing floor: ${snap['trailing_floor']:.0f}\n"
           f"{'✅ Puedes retirar' if snap['puede_retirar'] else '❌ ' + snap['motivo_retiro']}")
    notify("INFO", msg, dedup_key=f"daily_{date.today()}")


def job_backup_db():
    from datetime import date
    if not os.path.exists("data/journal.db"): return
    os.makedirs("backups", exist_ok=True)
    shutil.copy("data/journal.db", f"backups/journal_{date.today()}.db")
    corte = datetime.utcnow() - timedelta(days=30)
    for f in os.listdir("backups"):
        ruta = os.path.join("backups", f)
        if os.path.isfile(ruta):
            mt = datetime.utcfromtimestamp(os.path.getmtime(ruta))
            if mt < corte: os.remove(ruta)


def start():
    global _sched
    if _sched and _sched.running: return _sched
    _sched = BackgroundScheduler(timezone="UTC")
    _sched.add_job(job_auto_blacklist, CronTrigger(day_of_week="sun", hour=3),
                   id="blacklist", misfire_grace_time=3600)
    _sched.add_job(job_detectar_sesgos, CronTrigger(hour=23, minute=55),
                   id="sesgos", misfire_grace_time=600)
    _sched.add_job(job_health_check, IntervalTrigger(minutes=5),
                   id="health", misfire_grace_time=120)
    _sched.add_job(job_rotar_logs, CronTrigger(hour=0, minute=5),
                   id="logs", misfire_grace_time=600)
    _sched.add_job(job_daily_summary, CronTrigger(hour=23, minute=50),
                   id="summary", misfire_grace_time=600)
    _sched.add_job(job_backup_db, CronTrigger(hour=2, minute=0),
                   id="backup", misfire_grace_time=3600)
    _sched.start()
    log.info(f"[scheduler] {len(_sched.get_jobs())} jobs activos")
    return _sched


def stop():
    global _sched
    if _sched and _sched.running: _sched.shutdown(wait=False)


def next_runs():
    if not _sched: return []
    return [{"id": j.id, "name": j.name,
             "next": j.next_run_time.isoformat() if j.next_run_time else None}
            for j in _sched.get_jobs()]