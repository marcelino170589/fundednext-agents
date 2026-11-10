# symbol_config.py
"""Configuración por símbolo (forex, índices, commodities, metales)."""
from dataclasses import dataclass


@dataclass
class SymbolConfig:
    name: str
    pip_size: float
    pip_value_per_lot: float
    min_atr_impulse: float
    min_pullback_pct: float
    max_pullback_pct: float
    key_zone_tolerance_pct: float
    volatility_window: int
    atr_period: int = 14
    impulse_min_candles: int = 3


DEFAULT_CONFIGS = {
    # ═══════════════════════════════════════════════════════════
    # FOREX MAJORS (7)
    # ═══════════════════════════════════════════════════════════
    "EURUSD": SymbolConfig("EURUSD", 0.0001, 10.0, 2.5, 25.0, 70.0, 3.0, 50),
    "GBPUSD": SymbolConfig("GBPUSD", 0.0001, 10.0, 2.5, 25.0, 70.0, 3.0, 50),
    "USDJPY": SymbolConfig("USDJPY", 0.01,   6.8, 2.5, 25.0, 70.0, 3.0, 50),
    "USDCHF": SymbolConfig("USDCHF", 0.0001, 11.0, 2.5, 25.0, 70.0, 3.0, 50),
    "AUDUSD": SymbolConfig("AUDUSD", 0.0001, 10.0, 2.5, 25.0, 70.0, 3.0, 50),
    "NZDUSD": SymbolConfig("NZDUSD", 0.0001, 10.0, 2.5, 25.0, 70.0, 3.0, 50),
    "USDCAD": SymbolConfig("USDCAD", 0.0001,  7.3, 2.5, 25.0, 70.0, 3.0, 50),

    # ═══════════════════════════════════════════════════════════
    # FOREX CROSSES (23)
    # ═══════════════════════════════════════════════════════════
    "EURGBP": SymbolConfig("EURGBP", 0.0001, 12.7, 2.2, 25.0, 70.0, 3.0, 50),
    "EURJPY": SymbolConfig("EURJPY", 0.01,   6.8, 2.2, 25.0, 70.0, 3.0, 50),
    "EURCHF": SymbolConfig("EURCHF", 0.0001, 11.0, 2.2, 25.0, 70.0, 3.0, 50),
    "EURAUD": SymbolConfig("EURAUD", 0.0001,  6.6, 2.2, 25.0, 70.0, 3.0, 50),
    "EURNZD": SymbolConfig("EURNZD", 0.0001,  6.0, 2.2, 25.0, 70.0, 3.0, 50),
    "EURCAD": SymbolConfig("EURCAD", 0.0001,  7.3, 2.2, 25.0, 70.0, 3.0, 50),
    "GBPJPY": SymbolConfig("GBPJPY", 0.01,   6.8, 2.0, 25.0, 70.0, 3.0, 50),
    "GBPCHF": SymbolConfig("GBPCHF", 0.0001, 11.0, 2.2, 25.0, 70.0, 3.0, 50),
    "GBPAUD": SymbolConfig("GBPAUD", 0.0001,  6.6, 2.2, 25.0, 70.0, 3.0, 50),
    "GBPNZD": SymbolConfig("GBPNZD", 0.0001,  6.0, 2.2, 25.0, 70.0, 3.0, 50),
    "GBPCAD": SymbolConfig("GBPCAD", 0.0001,  7.3, 2.2, 25.0, 70.0, 3.0, 50),
    "AUDJPY": SymbolConfig("AUDJPY", 0.01,   6.8, 2.2, 25.0, 70.0, 3.0, 50),
    "AUDCAD": SymbolConfig("AUDCAD", 0.0001,  7.3, 2.2, 25.0, 70.0, 3.0, 50),
    "AUDNZD": SymbolConfig("AUDNZD", 0.0001,  6.0, 2.2, 25.0, 70.0, 3.0, 50),
    "AUDCHF": SymbolConfig("AUDCHF", 0.0001, 11.0, 2.2, 25.0, 70.0, 3.0, 50),
    "NZDJPY": SymbolConfig("NZDJPY", 0.01,   6.8, 2.2, 25.0, 70.0, 3.0, 50),
    "NZDCAD": SymbolConfig("NZDCAD", 0.0001,  7.3, 2.2, 25.0, 70.0, 3.0, 50),
    "NZDCHF": SymbolConfig("NZDCHF", 0.0001, 11.0, 2.2, 25.0, 70.0, 3.0, 50),
    "CADJPY": SymbolConfig("CADJPY", 0.01,   6.8, 2.2, 25.0, 70.0, 3.0, 50),
    "CADCHF": SymbolConfig("CADCHF", 0.0001, 11.0, 2.2, 25.0, 70.0, 3.0, 50),
    "CHFJPY": SymbolConfig("CHFJPY", 0.01,   6.8, 2.2, 25.0, 70.0, 3.0, 50),
    "EURSGD": SymbolConfig("EURSGD", 0.0001,  7.5, 2.2, 25.0, 70.0, 3.0, 50),
    "GBPSGD": SymbolConfig("GBPSGD", 0.0001,  7.5, 2.2, 25.0, 70.0, 3.0, 50),
    "AUDSGD": SymbolConfig("AUDSGD", 0.0001,  7.5, 2.2, 25.0, 70.0, 3.0, 50),
    "NZDSGD": SymbolConfig("NZDSGD", 0.0001,  7.5, 2.2, 25.0, 70.0, 3.0, 50),
    "SGDJPY": SymbolConfig("SGDJPY", 0.01,   6.8, 2.2, 25.0, 70.0, 3.0, 50),
    "USDCNH": SymbolConfig("USDCNH", 0.0001,  1.4, 2.5, 25.0, 70.0, 3.0, 50),
    "USDMXN": SymbolConfig("USDMXN", 0.0001,  0.5, 2.5, 25.0, 70.0, 3.0, 50),
    "USDZAR": SymbolConfig("USDZAR", 0.0001,  0.5, 2.5, 25.0, 70.0, 3.0, 50),
    "USDNOK": SymbolConfig("USDNOK", 0.0001,  0.9, 2.5, 25.0, 70.0, 3.0, 50),
    "USDSEK": SymbolConfig("USDSEK", 0.0001,  0.9, 2.5, 25.0, 70.0, 3.0, 50),
    "USDDKK": SymbolConfig("USDDKK", 0.0001,  1.4, 2.5, 25.0, 70.0, 3.0, 50),
    "USDHUF": SymbolConfig("USDHUF", 0.01,    0.3, 2.5, 25.0, 70.0, 3.0, 50),
    "EURHKD": SymbolConfig("EURHKD", 0.0001,  1.3, 2.2, 25.0, 70.0, 3.0, 50),
    "EURNOK": SymbolConfig("EURNOK", 0.0001,  0.9, 2.2, 25.0, 70.0, 3.0, 50),

    # ═══════════════════════════════════════════════════════════
    # METALES (3)
    # ═══════════════════════════════════════════════════════════
    "XAUUSD": SymbolConfig("XAUUSD", 0.01, 1.0, 2.5, 25.0, 70.0, 3.0, 50),
    "XAGUSD": SymbolConfig("XAGUSD", 0.001, 5.0, 2.0, 22.0, 70.0, 6.0, 50),
    "XPTUSD": SymbolConfig("XPTUSD", 0.01, 1.0, 2.0, 22.0, 70.0, 6.0, 50),

    # ═══════════════════════════════════════════════════════════
    # PETRÓLEO (2)
    # ═══════════════════════════════════════════════════════════
    "UKOUSD": SymbolConfig("UKOUSD", 0.01, 1.0, 2.0, 22.0, 70.0, 6.0, 50),
    "USOUSD": SymbolConfig("USOUSD", 0.01, 1.0, 2.0, 22.0, 70.0, 6.0, 50),

    # ═══════════════════════════════════════════════════════════
    # ÍNDICES (13)
    # ═══════════════════════════════════════════════════════════
    "AUS200": SymbolConfig("AUS200", 1.0, 1.0, 2.0, 22.0, 70.0, 6.0, 50),
    "EUSTX50": SymbolConfig("EUSTX50", 1.0, 1.0, 2.0, 22.0, 70.0, 6.0, 50),
    "FRA40": SymbolConfig("FRA40", 1.0, 1.0, 2.0, 22.0, 70.0, 6.0, 50),
    "GER30": SymbolConfig("GER30", 1.0, 1.0, 2.0, 22.0, 70.0, 6.0, 50),
    "HK50": SymbolConfig("HK50", 1.0, 1.0, 2.0, 22.0, 70.0, 6.0, 50),
    "SPX500": SymbolConfig("SPX500", 0.1, 1.0, 2.0, 22.0, 70.0, 6.0, 50),
    "NDX100": SymbolConfig("NDX100", 0.1, 1.0, 2.0, 22.0, 70.0, 6.0, 50),
    "NTH25": SymbolConfig("NTH25", 0.1, 1.0, 2.0, 22.0, 70.0, 6.0, 50),
    "SWI20": SymbolConfig("SWI20", 1.0, 1.0, 2.0, 22.0, 70.0, 6.0, 50),
    "UK100": SymbolConfig("UK100", 1.0, 1.0, 2.0, 22.0, 70.0, 6.0, 50),
    "US30": SymbolConfig("US30", 1.0, 1.0, 2.0, 22.0, 70.0, 6.0, 50),
    "US2000": SymbolConfig("US2000", 0.1, 1.0, 2.0, 22.0, 70.0, 6.0, 50),
    "JP225": SymbolConfig("JP225", 1.0, 1.0, 2.0, 22.0, 70.0, 6.0, 50),
}


def get_config(symbol):
    return DEFAULT_CONFIGS.get(symbol.upper())


def supported_symbols():
    return list(DEFAULT_CONFIGS.keys())
