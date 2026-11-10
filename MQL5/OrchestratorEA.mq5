//+------------------------------------------------------------------+
//| OrchestratorEA.mq5 — FNL:004 — Local                            |
//| MT5 en Windows + Python en WSL/Linux, ambos con 127.0.0.1       |
//+------------------------------------------------------------------+
#property strict
#property version "5.0"

#include <Zmq/Zmq.mqh>
#include <Trade\Trade.mqh>

// ─── ZMQ (LOCAL) ───
input string  ZMQ_PYTHON_HOST  = "tcp://127.0.0.1";   // Python en localhost
input int     ZMQ_SIGNAL_PORT  = 5555;
input string  ZMQ_LOCAL_BIND   = "tcp://127.0.0.1";   // EA publica en localhost
input int     ZMQ_STATE_PORT   = 5556;
input int     ZMQ_OHLC_PORT    = 5557;

// ─── HUMANIZACIÓN ───
input bool    HUMANIZE_ENABLED = true;
input int     DELAY_MIN_MS     = 3000;
input int     DELAY_MAX_MS     = 10000;
input double  LOT_VARIANCE_PCT = 4.0;
input int     TICK_NOISE_MAX   = 1;
input int     SKIP_ONE_EVERY_N = 10;
input bool    BLANK_COMMENT    = true;
input int     MAGIC_BASE       = 20261014;

// ─── FNL:004 ($50K) ───
input double  INITIAL_BALANCE      = 50000.0;
input double  MAX_LOSS_USD         = 2000.0;    // 4%
input double  OPERATIONAL_RISK_PCT = 0.005;     // 0.5% = $250 (operativo)
input double  MAX_LOT              = 0.08;
input int     MIN_TRADE_DURATION_S = 30;

// ─── ESTADO ───
Context   g_ctx;
Socket    g_subSignal(g_ctx, ZMQ_SUB);
Socket    g_pubState(g_ctx, ZMQ_PUB);
Socket    g_pubOhlc(g_ctx, ZMQ_PUB);
CTrade    g_trade;

ulong     g_rngState = 0;
int       g_signalCounter = 0;
datetime  g_lastOpenTime = 0;
double    g_dayStartBalance = 0;
double    g_peakEquity = 0;
datetime  g_lastHeartbeat = 0;

// ═══════════════════════════════════════════════════════════════
// PRNG splitmix64
// ═══════════════════════════════════════════════════════════════
ulong NextRand64() {
   g_rngState += 0x9E3779B97F4A7C15ULL;
   ulong z = g_rngState;
   z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
   z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
   return z ^ (z >> 31);
}
double NextDouble() { return (double)(NextRand64() >> 11) / 9007199254740992.0; }
int NextInt(int a, int b) {
   if(b <= a) return a;
   return a + (int)(NextRand64() % (ulong)(b - a + 1));
}

void InitRNG() {
   ulong login = (ulong)AccountInfoInteger(ACCOUNT_LOGIN);
   ulong combined = login ^ ((ulong)MAGIC_BASE * 0x9E3779B97F4A7C15ULL);
   ulong z = combined + 0x9E3779B97F4A7C15ULL;
   z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
   z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
   g_rngState = z ^ (z >> 31);
   for(int i = 0; i < 10; i++) NextRand64();
   PrintFormat("RNG seed=0x%016I64X login=%I64d", g_rngState, login);
}

// ═══════════════════════════════════════════════════════════════
int OnInit() {
   g_subSignal.connect(ZMQ_PYTHON_HOST + ":" + IntegerToString(ZMQ_SIGNAL_PORT));
   g_subSignal.subscribe("");
   g_pubState.bind(ZMQ_LOCAL_BIND + ":" + IntegerToString(ZMQ_STATE_PORT));
   g_pubOhlc.bind(ZMQ_LOCAL_BIND + ":" + IntegerToString(ZMQ_OHLC_PORT));

   g_trade.SetExpertMagicNumber(MAGIC_BASE);
   g_trade.SetDeviationInPoints(20);
   g_trade.SetTypeFillingBySymbol(_Symbol);

   InitRNG();
   g_dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_peakEquity = AccountInfoDouble(ACCOUNT_EQUITY);

   EventSetTimer(2);
   Print("EA v5.0 iniciado FNL:004. Balance=", INITIAL_BALANCE, " ZMQ=", ZMQ_PYTHON_HOST);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   string msg = StringFormat(
      "{\"type\":\"shutdown\",\"account\":\"%I64d\",\"reason\":%d,\"open_positions\":%d}",
      AccountInfoInteger(ACCOUNT_LOGIN), reason, PositionsTotal());
   ZmqMsg m(msg);
   g_pubState.send(m);
   EventKillTimer();
   g_ctx.shutdown();
}

void OnTimer() {
   ResetDailyIfNeeded();
   UpdatePeakEquity();
   PublishHeartbeat();
   PublishState();
   PublishOHLC();

   ZmqMsg msg;
   if(g_subSignal.recv(msg, ZMQ_DONTWAIT)) {
      ProcessSignal(msg.getData());
   }
}

void ResetDailyIfNeeded() {
   MqlDateTime n, l;
   TimeToStruct(TimeCurrent(), n);
   TimeToStruct(TimeCurrent() - 86400, l);
   if(n.day != l.day) {
      g_dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   }
}

void UpdatePeakEquity() {
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(eq > g_peakEquity) g_peakEquity = eq;
}

void PublishHeartbeat() {
   if(TimeCurrent() - g_lastHeartbeat < 30) return;
   g_lastHeartbeat = TimeCurrent();
   string msg = StringFormat(
      "{\"type\":\"heartbeat\",\"account\":\"%I64d\","
      "\"balance\":%.2f,\"equity\":%.2f,\"peak_equity\":%.2f,\"open_positions\":%d}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY),
      g_peakEquity, PositionsTotal());
   ZmqMsg m(msg);
   g_pubState.send(m);
}

void PublishState() {
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double risk = 0;
   int n = 0;
   for(int i = 0; i < PositionsTotal(); i++) {
      ulong t = PositionGetTicket(i);
      if(!PositionSelectByTicket(t)) continue;
      n++;
      double sl = PositionGetDouble(POSITION_SL);
      double op = PositionGetDouble(POSITION_PRICE_OPEN);
      double vol = PositionGetDouble(POSITION_VOLUME);
      string sym = PositionGetString(POSITION_SYMBOL);
      if(sl > 0) {
         risk += MathAbs(op - sl) / PipSize(sym) * PipValue(sym) * vol;
      }
   }
   double dl = MathMax(0, g_dayStartBalance - eq);
   string json = StringFormat(
      "{\"equity\":%.2f,\"balance\":%.2f,\"peak_equity\":%.2f,"
      "\"open_risk\":%.2f,\"daily_loss\":%.2f,\"open_positions\":%d}",
      eq, bal, g_peakEquity, risk, dl, n);
   ZmqMsg m(json);
   g_pubState.send(m);
}

void PublishOHLC() {
   string syms[] = {"XAUUSD","EURUSD","GBPUSD","USDJPY","USDCHF",
                    "AUDUSD","NZDUSD","USDCAD","EURGBP","EURJPY",
                    "GBPJPY","AUDJPY","EURAUD","EURNZD","GBPAUD","GBPNZD"};
   string payload = "{";
   for(int i = 0; i < ArraySize(syms); i++) {
      string s = syms[i];
      if(!SymbolSelect(s, true)) continue;
      if(i > 0) payload += ",";
      payload += "\"" + s + "\":{";
      payload += "\"h1_velas\":[";
      for(int j = 99; j >= 0; j--) {
         if(j < 99) payload += ",";
         payload += CandleJson(s, PERIOD_H1, j);
      }
      payload += "],\"h4_velas\":[";
      for(int k = 99; k >= 0; k--) {
         if(k < 99) payload += ",";
         payload += CandleJson(s, PERIOD_H4, k);
      }
      payload += "]}";
   }
   payload += "}";
   ZmqMsg m(payload);
   g_pubOhlc.send(m);
}

string CandleJson(const string s, ENUM_TIMEFRAMES tf, int shift) {
   return StringFormat(
      "{\"time\":\"%s\",\"open\":%.5f,\"high\":%.5f,\"low\":%.5f,\"close\":%.5f}",
      TimeToString(iTime(s, tf, shift), TIME_DATE|TIME_MINUTES),
      iOpen(s, tf, shift), iHigh(s, tf, shift),
      iLow(s, tf, shift), iClose(s, tf, shift));
}

void ProcessSignal(const string raw) {
   Print("═══ Señal: ", raw);
   g_signalCounter++;

   string sym = JsonGet(raw, "activo");
   string dir = JsonGet(raw, "direccion");
   double entry = StringToDouble(JsonGet(raw, "entrada"));
   double sl = StringToDouble(JsonGet(raw, "sl"));
   double tp = StringToDouble(JsonGet(raw, "tp"));
   double lot = StringToDouble(JsonGet(raw, "lotaje"));
   int durMin = (int)StringToInteger(JsonGet(raw, "duracion_estimada_min"));

   if(sym == "" || dir == "") { Print("✗ malformada"); return; }

   // HUMANIZACIÓN 1: omisión
   if(HUMANIZE_ENABLED && SKIP_ONE_EVERY_N > 0 && g_signalCounter % SKIP_ONE_EVERY_N == 0) {
      Print("👤 Señal omitida (distracción)");
      return;
   }

   if(!ValidateRules(sym, entry, sl, lot, durMin)) return;

   // HUMANIZACIÓN 2: retraso
   if(HUMANIZE_ENABLED) {
      int delay = NextInt(DELAY_MIN_MS, DELAY_MAX_MS);
      Print("👤 Retraso ", delay, "ms");
      Sleep(delay);
   }

   // HUMANIZACIÓN 3: variación lotaje
   double finalLot = lot;
   if(HUMANIZE_ENABLED) {
      double v = 1.0 + (NextDouble() - 0.5) * (LOT_VARIANCE_PCT / 100.0) * 2;
      finalLot = lot * v;
      double mn = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
      double mx = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
      double st = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
      finalLot = MathMax(mn, MathMin(mx, finalLot));
      finalLot = MathRound(finalLot / st) * st;
   }

   // HUMANIZACIÓN 4: ruido SL/TP
   double finalSL = sl, finalTP = tp;
   if(HUMANIZE_ENABLED && TICK_NOISE_MAX > 0) {
      double ts = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
      finalSL = NormalizeDouble(sl + NextInt(-TICK_NOISE_MAX, TICK_NOISE_MAX) * ts, _Digits);
      finalTP = NormalizeDouble(tp + NextInt(-TICK_NOISE_MAX, TICK_NOISE_MAX) * ts, _Digits);
   }

   // HUMANIZACIÓN 5: sesión (oro)
   if(HUMANIZE_ENABLED && StringFind(sym, "XAU") >= 0) {
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      if(dt.hour < 7 || dt.hour >= 20) {
         Print("👤 Fuera de sesión Londres/NY");
         return;
      }
   }

   MqlTick tick;
   if(!SymbolInfoTick(sym, tick)) return;
   double price = (dir == "LONG") ? tick.ask : tick.bid;
   string comment = BLANK_COMMENT ? "" : "ORD";

   ENUM_ORDER_TYPE ot = (dir == "LONG") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   g_trade.SetExpertMagicNumber(MAGIC_BASE + NextInt(0, 99));
   bool ok = g_trade.PositionOpen(sym, ot, finalLot, price, finalSL, finalTP, comment);

   if(ok) {
      g_lastOpenTime = TimeCurrent();
      Print("✓ Orden ticket=", g_trade.ResultOrder(),
            " lot=", finalLot, " price=", price);
   } else {
      Print("✗ OrderSend: ", g_trade.ResultRetcode(),
            " - ", g_trade.ResultRetcodeDescription());
   }
}

bool ValidateRules(const string sym, const double entry, const double sl,
                    const double lot, const int durMin) {
   if(durMin < 5) { Print("✗ quick strike"); return false; }
   if(lot <= 0 || lot > MAX_LOT) { Print("✗ lotaje"); return false; }
   if(PositionsTotal() > 0) { Print("✗ posición abierta"); return false; }

   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskOrd = MathAbs(entry - sl) / PipSize(sym) * PipValue(sym) * lot;

   // Trailing drawdown
   double trailingFloor = MathMax(INITIAL_BALANCE - MAX_LOSS_USD, g_peakEquity - MAX_LOSS_USD);
   if(eq - riskOrd < trailingFloor) {
      Print("✗ trailing drawdown (eq=", eq, " risk=", riskOrd, " floor=", trailingFloor, ")");
      return false;
   }

   // Riesgo abierto operativo (0.5%)
   double riskTot = OpenRisk();
   double maxR = INITIAL_BALANCE * OPERATIONAL_RISK_PCT;
   if(riskTot + riskOrd > maxR) {
      Print("✗ riesgo abierto operativo (", riskTot + riskOrd, " > ", maxR, ")");
      return false;
   }

   if(g_lastOpenTime > 0 && TimeCurrent() - g_lastOpenTime < MIN_TRADE_DURATION_S) {
      Print("✗ cooldown"); return false;
   }
   return true;
}

double PipSize(const string sym) {
   return (StringFind(sym, "JPY") >= 0) ? 0.01 : 0.0001;
}

double PipValue(const string sym) {
   double tv = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   return ts > 0 ? (PipSize(sym) / ts) * tv : 10.0;
}

double OpenRisk() {
   double t = 0;
   for(int i = 0; i < PositionsTotal(); i++) {
      ulong tk = PositionGetTicket(i);
      if(!PositionSelectByTicket(tk)) continue;
      double sl = PositionGetDouble(POSITION_SL);
      double op = PositionGetDouble(POSITION_PRICE_OPEN);
      double vol = PositionGetDouble(POSITION_VOLUME);
      string sym = PositionGetString(POSITION_SYMBOL);
      if(sl > 0) t += MathAbs(op - sl) / PipSize(sym) * PipValue(sym) * vol;
   }
   return t;
}

string JsonGet(const string json, const string key) {
   string pat = "\"" + key + "\":";
   int p = StringFind(json, pat);
   if(p < 0) return "";
   p += StringLen(pat);
   while(p < StringLen(json) && StringGetCharacter(json, p) == ' ') p++;
   if(StringGetCharacter(json, p) == '"') {
      p++;
      return StringSubstr(json, p, StringFind(json, "\"", p) - p);
   }
   int e = p;
   while(e < StringLen(json) && StringGetCharacter(json, e) != ',' &&
         StringGetCharacter(json, e) != '}') e++;
   return StringSubstr(json, p, e - p);
}