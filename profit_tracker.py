# profit_tracker.py
"""
Tracker de rentabilidad adaptado a FNL:004.

- La consistency rule es PERPETUA: best_day_pnl NUNCA se resetea.
- El ciclo se resetea en cada retiro (total_pnl vuelve a 0 para el ciclo).
- Dilución se activa mucho antes (15%) por el límite del 20%.
"""
import json, os
from datetime import datetime, date, timedelta
from config import (
    DILUTION_ENTRY_RATIO, DILUTION_EXIT_RATIO, DILUTION_DAILY_FACTOR,
    DILUTION_MIN_DAILY_USD, MAX_DAILY_PROFIT_USD, INITIAL_BALANCE,
    MAX_PAYOUT_USD, PROFIT_SPLIT,
)


STATE_FILE = "data/profit_state.json"


class ProfitTracker:
    def __init__(self, account_id: str, initial_balance: float = INITIAL_BALANCE):
        self.account_id = account_id
        self.initial_balance = initial_balance
        self.daily_pnl: dict[str, float] = {}
        self.total_pnl: float = 0.0          # Beneficio del CICLO actual
        self.best_day_pnl: float = 0.0       # Récord PERPETUO (nunca se resetea)
        self.best_day_date: str | None = None
        self.peak_equity: float = initial_balance
        self.last_payout_date: str | None = None

    @classmethod
    def load(cls, account_id: str, initial_balance: float = INITIAL_BALANCE):
        os.makedirs("data", exist_ok=True)
        pt = cls(account_id, initial_balance)
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    data = json.load(f).get(account_id, {})
                pt.daily_pnl = data.get("daily_pnl", {})
                pt.total_pnl = data.get("total_pnl", 0.0)
                pt.best_day_pnl = data.get("best_day_pnl", 0.0)
                pt.best_day_date = data.get("best_day_date")
                pt.peak_equity = data.get("peak_equity", initial_balance)
                pt.last_payout_date = data.get("last_payout_date")
            except Exception:
                pass
        return pt

    def save(self):
        os.makedirs("data", exist_ok=True)
        all_state = {}
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                all_state = json.load(f)
        all_state[self.account_id] = {
            "daily_pnl": self.daily_pnl,
            "total_pnl": self.total_pnl,
            "best_day_pnl": self.best_day_pnl,
            "best_day_date": self.best_day_date,
            "peak_equity": self.peak_equity,
            "last_payout_date": self.last_payout_date,
            "updated_at": datetime.utcnow().isoformat(),
        }
        with open(STATE_FILE, "w") as f:
            json.dump(all_state, f, indent=2)

    def registrar_trade(self, pnl: float, fecha: str = None):
        fecha = fecha or str(date.today())
        self.daily_pnl[fecha] = self.daily_pnl.get(fecha, 0.0) + pnl
        self.total_pnl += pnl
        # El récord es PERPETUO: solo sube, nunca se resetea
        if self.daily_pnl[fecha] > self.best_day_pnl:
            self.best_day_pnl = self.daily_pnl[fecha]
            self.best_day_date = fecha
        self.save()

    def actualizar_peak(self, equity: float):
        """Actualiza el pico de equity para el trailing drawdown."""
        if equity > self.peak_equity:
            self.peak_equity = equity
            self.save()

    def daily_pnl_hoy(self) -> float:
        return self.daily_pnl.get(str(date.today()), 0.0)

    def ratio_consistencia(self) -> float:
        """best_day / total del ciclo. Debe ser <= 0.20."""
        if self.total_pnl <= 0:
            return 0.0
        return self.best_day_pnl / self.total_pnl

    def cumple_20pct(self) -> bool:
        return self.ratio_consistencia() <= 0.20

    def total_necesario_para_20pct(self) -> float:
        """Total del ciclo necesario para que el récord quede en 20%."""
        if self.best_day_pnl <= 0:
            return 0.0
        return self.best_day_pnl / 0.20

    def falta_para_cumplir(self) -> float:
        return max(0.0, self.total_necesario_para_20pct() - self.total_pnl)

    def puede_retirar(self) -> tuple[bool, str]:
        """
        Verifica si se cumplen las condiciones de retiro:
        - Superar buffer ($2,100)
        - Beneficio mínimo sobre buffer ($800)
        - Consistency 20%
        - Retiro <= $1,200
        """
        equity = self.initial_balance + self.total_pnl
        buffer_level = self.initial_balance + 2_100.0
        if equity < buffer_level + 800.0:
            return False, f"Beneficio insuficiente sobre buffer (equity {equity:.0f} < {buffer_level + 800:.0f})"
        if not self.cumple_20pct():
            return False, f"Consistency {self.ratio_consistencia()*100:.1f}% > 20%"
        bruto_disponible = self.total_pnl - 800.0
        retiro_neto = min(bruto_disponible * PROFIT_SPLIT, MAX_PAYOUT_USD)
        if retiro_neto < 800.0:
            return False, f"Retiro neto {retiro_neto:.0f} < mínimo 800"
        return True, f"Puedes retirar hasta ${retiro_neto:.0f}"

    def resetear_ciclo_tras_retiro(self):
        """Resetea el ciclo pero MANTIENE el récord perpetuo."""
        self.total_pnl = 0.0
        self.daily_pnl = {}
        self.last_payout_date = str(date.today())
        self.save()

    def _objetivo_efectivo(self) -> float:
        dm = get_dilution_manager(self.account_id)
        if dm.active:
            return dm.current_daily_target
        return MAX_DAILY_PROFIT_USD

    def presupuesto_restante(self) -> float:
        return max(0.0, self._objetivo_efectivo() - self.daily_pnl_hoy())

    def objetivo_alcanzado(self) -> bool:
        return self.daily_pnl_hoy() >= self._objetivo_efectivo()

    def snapshot(self) -> dict:
        dm = get_dilution_manager(self.account_id)
        dilution_snap = dm.evaluar(self)
        puede, motivo = self.puede_retirar()
        return {
            "account_id": self.account_id,
            "daily_pnl": round(self.daily_pnl_hoy(), 2),
            "total_pnl_ciclo": round(self.total_pnl, 2),
            "best_day_pnl": round(self.best_day_pnl, 2),
            "best_day_date": self.best_day_date,
            "ratio_consistencia": round(self.ratio_consistencia() * 100, 1),
            "cumple_20pct": self.cumple_20pct(),
            "falta_para_20pct": round(self.falta_para_cumplir(), 2),
            "peak_equity": round(self.peak_equity, 2),
            "trailing_floor": round(max(self.initial_balance - 2000, self.peak_equity - 2000), 2),
            "presupuesto_restante_hoy": round(self.presupuesto_restante(), 2),
            "objetivo_alcanzado": self.objetivo_alcanzado(),
            "objetivo_diario_efectivo": round(self._objetivo_efectivo(), 2),
            "puede_retirar": puede,
            "motivo_retiro": motivo,
            "dilution": dilution_snap,
        }


class DilutionManager:
    def __init__(self, account_id: str):
        self.account_id = account_id
        self.active = False
        self.activated_at: str | None = None
        self.current_daily_target = MAX_DAILY_PROFIT_USD
        self.days_elapsed = 0
        self.load()

    @classmethod
    def load(cls, account_id: str):
        dm = cls.__new__(cls)
        dm.account_id = account_id
        dm.active = False
        dm.activated_at = None
        dm.current_daily_target = MAX_DAILY_PROFIT_USD
        dm.days_elapsed = 0
        path = f"data/dilution_state_{account_id}.json"
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                dm.active = data.get("active", False)
                dm.activated_at = data.get("activated_at")
                dm.current_daily_target = data.get("current_daily_target", MAX_DAILY_PROFIT_USD)
                dm.days_elapsed = data.get("days_elapsed", 0)
            except Exception:
                pass
        return dm

    def save(self):
        os.makedirs("data", exist_ok=True)
        with open(f"data/dilution_state_{self.account_id}.json", "w") as f:
            json.dump({
                "active": self.active,
                "activated_at": self.activated_at,
                "current_daily_target": self.current_daily_target,
                "days_elapsed": self.days_elapsed,
            }, f, indent=2)

    def evaluar(self, tracker: ProfitTracker) -> dict:
        ratio = tracker.ratio_consistencia()

        if not self.active and ratio > DILUTION_ENTRY_RATIO:
            self.active = True
            self.activated_at = datetime.utcnow().isoformat()
            self.days_elapsed = 0
        elif self.active and ratio < DILUTION_EXIT_RATIO:
            self.active = False
            self.current_daily_target = MAX_DAILY_PROFIT_USD
            self.save()
            return self._snapshot(tracker, "exited")

        if self.active:
            self.current_daily_target = max(
                DILUTION_MIN_DAILY_USD,
                min(tracker.best_day_pnl * DILUTION_DAILY_FACTOR, MAX_DAILY_PROFIT_USD)
            )
            if self.activated_at:
                try:
                    start = datetime.fromisoformat(self.activated_at)
                    self.days_elapsed = (datetime.utcnow() - start).days
                except Exception:
                    pass

        self.save()
        return self._snapshot(tracker, "active" if self.active else "normal")

    def _snapshot(self, tracker: ProfitTracker, reason: str) -> dict:
        needed = tracker.total_necesario_para_20pct()
        falta = max(0, needed - tracker.total_pnl)
        dias = falta / self.current_daily_target if self.current_daily_target > 0 else 0
        return {
            "active": self.active,
            "reason": reason,
            "current_daily_target": round(self.current_daily_target, 2),
            "target_ratio": 0.20,
            "ratio_actual": round(tracker.ratio_consistencia(), 4),
            "best_day": round(tracker.best_day_pnl, 2),
            "total_ciclo": round(tracker.total_pnl, 2),
            "total_necesario": round(needed, 2),
            "falta": round(falta, 2),
            "dias_estimados": round(dias, 1),
            "dias_transcurridos": self.days_elapsed,
        }


_cache: dict[str, DilutionManager] = {}

def get_dilution_manager(account_id: str) -> DilutionManager:
    if account_id not in _cache:
        _cache[account_id] = DilutionManager.load(account_id)
    return _cache[account_id]