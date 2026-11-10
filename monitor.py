# monitor.py
"""Panel TUI con Rich (alternativa al dashboard web)."""
import argparse
import json
import os
import time
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from state_manager import load, ea_vivo, ultimo_heartbeat
from profit_tracker import ProfitTracker
from config import INITIAL_BALANCE

console = Console()


def _jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def build():
    st = load()
    pt = ProfitTracker.load("default")
    snap = pt.snapshot()
    trades = _jsonl("logs/audit.jsonl")[-10:]

    layout = Layout()
    layout.split_column(
        Layout(name="head", size=3),
        Layout(name="top", size=8),
        Layout(name="bot"),
    )
    layout["top"].split_row(Layout(name="acc"), Layout(name="prog"))

    layout["head"].update(Panel(
        f"[bold cyan]FNL:004 — $100/día[/]  "
        f"EA: {'[green]ON[/]' if ea_vivo(120) else '[red]OFF[/]'}  "
        f"[dim]{time.strftime('%H:%M:%S')}[/]",
        border_style="cyan"))

    acc = Text()
    eq = st.get("equity", INITIAL_BALANCE)
    pnl = eq - INITIAL_BALANCE
    acc.append("Equity: ", style="bold")
    acc.append(f"${eq:,.2f}  ", style="cyan")
    acc.append(f"({pnl:+,.2f})\n", style="green" if pnl >= 0 else "red")
    acc.append("Daily:  ", style="bold")
    acc.append(f"${snap['daily_pnl']:.2f} / $100\n", style="cyan")
    acc.append("Ciclo:  ", style="bold")
    acc.append(f"${snap['total_pnl_ciclo']:.2f}\n", style="cyan")
    acc.append("Mejor:  ", style="bold")
    acc.append(f"${snap['best_day_pnl']:.2f}\n", style="cyan")
    layout["acc"].update(Panel(acc, title="[bold]Cuenta[/]", border_style="cyan"))

    prog = Text()
    rc = snap["ratio_consistencia"]
    prog.append("Consistency: ", style="bold")
    prog.append(f"{rc:.1f}% ", style="green" if rc < 15 else "yellow" if rc < 20 else "red")
    prog.append("(límite 20%)\n")
    prog.append("Trailing: ", style="bold")
    floor = snap["trailing_floor"]
    dist = eq - floor
    prog.append(f"${dist:.0f} / ${eq - floor:.0f}\n",
                style="green" if dist > 1500 else "yellow" if dist > 1000 else "red")
    prog.append("Dilución: ", style="bold")
    prog.append(f"{'ACTIVA' if snap['dilution']['active'] else 'inactiva'}\n",
                style="yellow" if snap["dilution"]["active"] else "green")
    prog.append("Retiro: ", style="bold")
    prog.append(f"{'✅ ' + snap['motivo_retiro'] if snap['puede_retirar'] else '❌ ' + snap['motivo_retiro'][:40]}\n",
                style="green" if snap["puede_retirar"] else "red")
    hb = ultimo_heartbeat()
    prog.append("Heartbeat: ", style="bold")
    prog.append(f"{hb.get('iso', 'nunca')[:19] if hb else 'nunca'}", style="dim")
    layout["prog"].update(Panel(prog, title="[bold]Sistema[/]", border_style="cyan"))

    tbl = Table(show_header=True, header_style="bold cyan", expand=True)
    for c in ("Hora", "Par", "Dir", "Score", "Div"):
        tbl.add_column(c)
    for t in trades:
        tbl.add_row((t.get("ts") or "")[11:19], t.get("symbol", "—"),
                    t.get("direccion", "—"),
                    f"{t.get('score', 0):.1f}" if t.get("score") else "—",
                    f"{t.get('divergencia', 0):.1f}" if t.get("divergencia") else "—")
    layout["bot"].update(Panel(tbl, title="[bold]Últimas decisiones[/]", border_style="cyan"))
    return layout


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    args = p.parse_args()

    if args.once:
        console.print(build())
        return
    try:
        with Live(build(), refresh_per_second=0.5, screen=True):
            while True:
                time.sleep(2)
    except KeyboardInterrupt:
        console.print("[dim]Detenido[/]")


if __name__ == "__main__":
    main()