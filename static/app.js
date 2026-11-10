(() => {
  'use strict';

  /* ═══════════════════════════════════════════════════════════
     Estado y constantes
     ═══════════════════════════════════════════════════════════ */

  const VIEW_META = {
    overview: {
      title: 'Resumen',
      sub: 'Estado de cuenta, riesgo y señales del ciclo.',
      eyebrow: 'FNL:004 · Instant 50K',
    },
    news: {
      title: 'Noticias',
      sub: 'Calendario, titulares y ventana de bloqueo del activo.',
      eyebrow: 'Flujo fundamental',
    },
    opportunities: {
      title: 'Oportunidades',
      sub: 'Señales del cazador y del consenso de 9 capas.',
      eyebrow: 'Ejecución manual',
    },
    journal: {
      title: 'Journal',
      sub: 'Decisiones, trades, alertas y curva de equity.',
      eyebrow: 'Auditoría del sistema',
    },
    market: {
      title: 'Mercado',
      sub: 'Velas históricas, resumen técnico y backtests.',
      eyebrow: 'Datos OHLC',
    },
    system: {
      title: 'Sistema',
      sub: 'Salud de servicios, configuración y logs.',
      eyebrow: 'Diagnóstico',
    },
  };

  const LAYER_NAMES = {
    1: 'Veto fundamental',
    2: 'Alineación macro',
    3: 'Divergencia',
    4: 'Score mínimo',
    5: 'Veto adversario',
    6: 'Riesgo diario',
    7: 'Filtro HTF',
    8: 'Confluencia',
    9: 'Re-verificación',
  };

  const AGENT_LABELS = {
    agent_trader: 'Trader · sesgo',
    agent_fundamental: 'Fundamental · macro',
    agent_technical: 'Técnico · entrada',
    agent_adversary: 'Adversario · objeciones',
    agent_htf: 'HTF · estructura',
    agent_strategies: 'Estrategias · catálogo',
    prompt_variants: 'Prompt · variantes',
  };

  const DEFAULT_CONFIG = {
    initial_balance: 50000,
    max_loss_usd: 2000,
    daily_loss_limit_pct: 2,
    max_open_risk_pct: 0.5,
    daily_target_usd: 100,
    consistency_limit_pct: 20,
    news_blackout_min: 15,
    symbols: ['XAUUSD', 'USDJPY', 'EURUSD', 'USDCAD'],
  };

  const Store = {
    state: {},
    profit: {},
    stats: {},
    trades: [],
    decisions: [],
    signals: [],
    equity: [],
    alerts: [],
    config: { ...DEFAULT_CONFIG },
    health: {},
    news: {},
    htf: {},
    symbols: [],
    strategies: [],
    backtests: [],
    journal: null,
    market: null,
    currentView: 'overview',
    newsSymbol: 'XAUUSD',
    newsImpact: 'all',
    newsSearch: '',
    newsOnlySymbol: false,
    headlineSent: 'all',
    oppsSearch: '',
    oppsDirection: 'all',
    oppsMinConf: 0,
    journalSearch: '',
    journalFilter: 'all',
    marketSymbol: 'XAUUSD',
    marketTf: 'H1',
    initialized: false,
    loading: { news: false, journal: false, market: false, system: false, opps: false },
    ws: null,
    wsLive: false,
    wsRetry: 0,
    lastUpdate: null,
    lastAlertIds: new Set(),
    sound: (() => {
      try { return localStorage.getItem('fnl_sound') === '1'; } catch { return false; }
    })(),
    audio: null,
  };

  const $ = (id) => document.getElementById(id);
  const $$ = (sel, root = document) => Array.from((root || document).querySelectorAll(sel));

  /* ═══════════════════════════════════════════════════════════
     Utilidades
     ═══════════════════════════════════════════════════════════ */

  const esc = (value) => {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  };

  const num = (value, digits = 2) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    return Number(value).toLocaleString('en-US', {
      minimumFractionDigits: digits, maximumFractionDigits: digits,
    });
  };

  const money = (value, digits = 2) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    return '$' + num(Math.abs(Number(value)) < 0.005 ? 0 : value, digits);
  };

  const signedMoney = (value, digits = 2) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    const n = Number(value);
    return (n >= 0 ? '+' : '−') + money(Math.abs(n), digits);
  };

  const pct = (value, digits = 1) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    return Number(value).toFixed(digits) + '%';
  };

  const clamp = (n, min, max) => Math.max(min, Math.min(max, n));

  const parseUtc = (value) => {
    if (!value) return null;
    if (value instanceof Date) return value;
    let text = String(value).trim();
    if (!text) return null;
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(text)) text = text.replace(' ', 'T');
    if (!/[zZ]$|[+-]\d{2}:?\d{2}$/.test(text)) text += 'Z';
    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date;
  };

  const timeAgo = (value) => {
    const date = parseUtc(value);
    if (!date) return '—';
    const sec = Math.max(0, (Date.now() - date.getTime()) / 1000);
    if (sec < 10) return 'ahora';
    if (sec < 60) return `hace ${Math.floor(sec)} s`;
    if (sec < 3600) return `hace ${Math.floor(sec / 60)} min`;
    if (sec < 86400) return `hace ${Math.floor(sec / 3600)} h`;
    if (sec < 86400 * 7) return `hace ${Math.floor(sec / 86400)} d`;
    return date.toLocaleDateString('es-ES', { day: '2-digit', month: 'short' });
  };

  const fmtTime = (value, withSeconds = false) => {
    const date = value instanceof Date ? value : parseUtc(value);
    if (!date) return '—';
    return date.toLocaleTimeString('es-ES', {
      hour: '2-digit', minute: '2-digit',
      ...(withSeconds ? { second: '2-digit' } : {}),
    });
  };

  const fmtDateLong = (value) => {
    const date = value instanceof Date ? value : parseUtc(value);
    if (!date) return '—';
    return date.toLocaleDateString('es-ES', {
      weekday: 'long', day: 'numeric', month: 'short',
    });
  };

  const fmtDateTime = (value) => {
    const date = value instanceof Date ? value : parseUtc(value);
    if (!date) return '—';
    return date.toLocaleString('es-ES', {
      day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
    });
  };

  const price = (value, symbol = '') => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    const s = String(symbol).toUpperCase();
    let digits = 2;
    const indices = ['SPX', 'NDX', 'US3', 'GER', 'UK1', 'FRA', 'EUS', 'JP2', 'HK5', 'AUS', 'SWI', 'NTH'];
    if (s.startsWith('XAG')) digits = 3;
    else if (s.startsWith('XAU') || s.startsWith('XPT')) digits = 2;
    else if (s === 'UKOUSD' || s === 'USOUSD') digits = 2;
    else if (s.includes('JPY')) digits = 3;
    else if (indices.some((prefix) => s.startsWith(prefix))) digits = 1;
    else if (s.includes('USD')) digits = 5;
    return Number(value).toLocaleString('en-US', {
      minimumFractionDigits: digits, maximumFractionDigits: digits,
    });
  };

  const countdown = (value) => {
    const date = parseUtc(value);
    if (!date) return '—';
    const minutes = Math.round((date.getTime() - Date.now()) / 60000);
    const abs = Math.abs(minutes);
    if (abs < 1) return 'ahora';
    if (abs < 60) return minutes > 0 ? `en ${abs} min` : `hace ${abs} min`;
    if (abs < 1440) {
      const h = Math.floor(abs / 60), m = abs % 60;
      return minutes > 0 ? `en ${h} h ${m} min` : `hace ${h} h`;
    }
    return minutes > 0 ? `en ${Math.floor(abs / 1440)} d` : `hace ${Math.floor(abs / 1440)} d`;
  };

  const safeUrl = (value) => {
    const text = String(value || '');
    return /^https?:\/\//i.test(text) ? text : '#';
  };

  const parseMaybe = (value) => {
    if (typeof value === 'string') {
      try { return JSON.parse(value); } catch { return {}; }
    }
    return value && typeof value === 'object' ? value : {};
  };

  const asArray = (value) => {
    if (Array.isArray(value)) return value;
    if (typeof value === 'string' && value.trim()) {
      return value.split(',').map((v) => v.trim()).filter(Boolean);
    }
    return [];
  };

  const statusClass = (status) => {
    if (status === 'ok') return 'dot';
    if (status === 'stale') return 'dot dot-amber';
    if (status === 'disabled') return 'dot dot-muted';
    return 'dot dot-red';
  };

  const statusText = (status) => ({
    ok: 'OK', stale: 'cache', error: 'error', disabled: 'sin configurar', unknown: '—',
  }[status] || status || '—');

  /* ═══════════════════════════════════════════════════════════
     API / toasts / sonido
     ═══════════════════════════════════════════════════════════ */

  async function api(path, options = {}) {
    const { timeout = 20000, headers = {}, ...rest } = options;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(path, {
        ...rest,
        headers: { Accept: 'application/json', ...headers },
        signal: controller.signal,
      });
      if (!response.ok) {
        let detail = response.statusText;
        try {
          const body = await response.json();
          detail = body.detail || body.message || detail;
        } catch { /* noop */ }
        throw new Error(`${response.status} · ${detail}`);
      }
      const type = response.headers.get('content-type') || '';
      return type.includes('application/json') ? response.json() : response.text();
    } finally {
      clearTimeout(timer);
    }
  }

  function toast(title, body = '', kind = 'info', ms = 6000) {
    const root = $('toasts');
    if (!root) return;
    const item = document.createElement('div');
    item.className = 'toast ' + (kind === 'error' ? 'err' : kind === 'warning' ? 'warn' : kind === 'success' ? 'ok' : '');
    item.innerHTML = `<div class="toast-title">${esc(title)}</div>${body ? `<div class="toast-body">${esc(body)}</div>` : ''}`;
    root.appendChild(item);
    setTimeout(() => {
      item.style.opacity = '0';
      item.style.transition = 'opacity .3s';
      setTimeout(() => item.remove(), 320);
    }, ms);
  }

  function setSound(enabled) {
    Store.sound = Boolean(enabled);
    try { localStorage.setItem('fnl_sound', Store.sound ? '1' : '0'); } catch { /* noop */ }
    $('sound-btn')?.classList.toggle('is-on', Store.sound);
    if (Store.sound) {
      try {
        Store.audio = Store.audio || new (window.AudioContext || window.webkitAudioContext)();
        if (Store.audio.state === 'suspended') Store.audio.resume();
      } catch { /* noop */ }
    }
    toast(Store.sound ? 'Sonido activado' : 'Sonido desactivado', Store.sound ? 'Las alertas nuevas sonarán.' : '', 'info', 2500);
  }

  function beep(severity = 'INFO') {
    if (!Store.sound) return;
    try {
      Store.audio = Store.audio || new (window.AudioContext || window.webkitAudioContext)();
      const ctx = Store.audio;
      if (ctx.state === 'suspended') ctx.resume();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.type = 'sine';
      osc.frequency.value = severity === 'CRITICAL' ? 1040 : severity === 'WARNING' ? 820 : 620;
      gain.gain.setValueAtTime(0.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35);
      osc.start(); osc.stop(ctx.currentTime + 0.36);
      if (severity === 'CRITICAL') {
        setTimeout(() => beep('CRITICAL'), 220);
        setTimeout(() => beep('CRITICAL'), 440);
      }
    } catch { /* noop */ }
  }

  function notifyBrowser(title, body) {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    try {
      new Notification(title, { body, tag: 'fnl-' + Date.now(), silent: !Store.sound });
    } catch { /* noop */ }
  }

  /* ═══════════════════════════════════════════════════════════
     WebSocket y refresco
     ═══════════════════════════════════════════════════════════ */

  function connectWS() {
    if (Store.ws && [WebSocket.OPEN, WebSocket.CONNECTING].includes(Store.ws.readyState)) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    let ws;
    try { ws = new WebSocket(`${proto}://${location.host}/ws`); }
    catch { scheduleWSReconnect(); return; }
    Store.ws = ws;

    ws.onopen = () => {
      Store.wsLive = true;
      Store.wsRetry = 0;
      renderChrome();
    };
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data && data.type === 'snapshot') applySnapshot(data);
      } catch { /* noop */ }
    };
    ws.onerror = () => { try { ws.close(); } catch { /* noop */ } };
    ws.onclose = () => {
      Store.wsLive = false;
      renderChrome();
      scheduleWSReconnect();
    };
  }

  function scheduleWSReconnect() {
    Store.wsRetry = Math.min(8, Store.wsRetry + 1);
    setTimeout(connectWS, Math.min(15000, 1500 * Store.wsRetry));
  }

  async function refreshLight() {
    if (Store.wsLive) return;
    const tasks = [
      api('/api/state').catch(() => null),
      api('/api/profit').catch(() => null),
      api('/api/alerts?limit=20').catch(() => null),
      api('/api/equity?limit=200').catch(() => null),
    ];
    const [state, profit, alerts, equity] = await Promise.all(tasks);
    if (state) Store.state = state;
    if (profit) Store.profit = profit;
    if (alerts) Store.alerts = alerts;
    if (equity) Store.equity = equity;
    Store.lastUpdate = new Date();
    renderChrome();
    renderLive();
  }

  function applySnapshot(data) {
    if (data.state) Store.state = data.state;
    if (data.profit) Store.profit = data.profit;
    if (data.stats) Store.stats = data.stats;
    if (data.equity && data.equity.length) Store.equity = data.equity;
    if (data.alerts) Store.alerts = data.alerts;
    if (data.signals && data.signals.length) Store.signals = data.signals;
    if (data.trades && data.trades.length) Store.trades = data.trades;
    if (data.decisions && data.decisions.length && Store.currentView !== 'journal') {
      Store.decisions = data.decisions;
    }
    if (data.news) {
      Store.news = Store.news || {};
      if (data.news.blackout) Store.news.blackout = data.news.blackout;
      if (data.news.sentiment) Store.news.sentiment = data.news.sentiment;
      if (data.news.health) {
        Store.news.health = Store.news.health || {};
        Store.news.health.sources = data.news.health;
      }
      Store.news.headlines_count_ws = data.news.headlines_count;
      Store.news.calendar_count_ws = data.news.calendar_count;
    }
    Store.lastUpdate = new Date();
    detectNewAlerts();
    renderChrome();
    renderLive();
  }

  function detectNewAlerts() {
    const unread = (Store.alerts || []).filter((a) => !a.leida);
    const ids = new Set((Store.alerts || []).map((a) => a.id));
    if (!Store.initialized) {
      Store.lastAlertIds = ids;
      return;
    }
    const fresh = unread.filter((a) => !Store.lastAlertIds.has(a.id));
    Store.lastAlertIds = ids;
    if (fresh.length === 0) return;
    fresh.slice(0, 3).forEach((alert) => {
      const severity = alert.severity || 'INFO';
      toast(
        alert.tipo === 'opportunity' ? 'Nueva oportunidad' : 'Nueva alerta',
        alert.symbol ? `${alert.symbol} · ${alert.message || ''}` : (alert.message || ''),
        severity === 'CRITICAL' ? 'error' : 'warning',
      );
      beep(severity);
      if (severity === 'CRITICAL') {
        notifyBrowser('FNL:004 · Alerta crítica', alert.message || 'Revisa el dashboard');
      } else if (alert.tipo === 'opportunity') {
        notifyBrowser('FNL:004 · Oportunidad', alert.message || 'Revisa el dashboard');
      }
    });
  }

  /* ═══════════════════════════════════════════════════════════
     Carga inicial
     ═══════════════════════════════════════════════════════════ */

  async function loadInitial() {
    const hash = (location.hash || '').replace('#', '');
    if (VIEW_META[hash]) Store.currentView = hash;
    try {
      await loadBootstrap(Store.newsSymbol);
      Store.initialized = true;
      switchView(Store.currentView, false);
    } catch (error) {
      toast('No se pudo cargar el dashboard', String(error.message || error), 'error', 9000);
      switchView('overview', false);
      renderChrome();
    }
    loadSymbols();
    connectWS();
  }

  async function loadBootstrap(symbol = Store.newsSymbol) {
    const data = await api(`/api/bootstrap?symbol=${encodeURIComponent(symbol)}`, { timeout: 35000 });
    Store.state = data.state || {};
    Store.profit = data.profit || {};
    Store.stats = data.stats || {};
    Store.trades = data.trades || [];
    Store.decisions = data.decisions || [];
    Store.signals = data.signals || [];
    Store.equity = data.equity || [];
    Store.alerts = data.alerts || [];
    Store.config = data.config || { ...DEFAULT_CONFIG };
    Store.health = data.health || {};
    Store.news = data.news || {};
    Store.htf = data.htf || {};
    Store.lastUpdate = new Date();
    if (!Store.initialized) {
      Store.lastAlertIds = new Set((Store.alerts || []).map((a) => a.id));
    }
    populateSymbolSelects();
    renderChrome();
    renderCurrentView();
  }

  async function loadSymbols() {
    try {
      const data = await api('/api/symbols', { timeout: 12000 });
      Store.symbols = data.symbols || [];
      populateSymbolSelects();
    } catch { /* opcional */ }
  }

  async function refreshCurrent() {
    const button = $('refresh-btn');
    const icon = $('refresh-ico');
    button?.classList.add('is-loading');
    if (icon) icon.textContent = '◌';
    try {
      if (Store.currentView === 'news') await loadNews(true);
      else if (Store.currentView === 'journal') await loadJournal();
      else if (Store.currentView === 'market') await loadMarket();
      else if (Store.currentView === 'system') await loadSystem();
      else if (Store.currentView === 'opportunities') await loadOpps(true);
      else {
        await loadBootstrap(Store.newsSymbol);
        await loadNews(false);
      }
      toast('Datos actualizados', '', 'success', 2200);
    } catch (error) {
      toast('Error al actualizar', String(error.message || error), 'error');
    } finally {
      button?.classList.remove('is-loading');
      if (icon) icon.textContent = '↻';
    }
  }

  /* ═══════════════════════════════════════════════════════════
     Navegación / chrome
     ═══════════════════════════════════════════════════════════ */

  function switchView(view, pushHash = true) {
    if (!VIEW_META[view]) view = 'overview';
    Store.currentView = view;
    $$('.nav-item').forEach((item) => item.classList.toggle('is-active', item.dataset.view === view));
    $$('.view').forEach((section) => section.classList.toggle('is-active', section.dataset.view === view));
    const meta = VIEW_META[view];
    $('page-title').textContent = meta.title;
    $('page-subtitle').textContent = meta.sub;
    $('page-eyebrow').textContent = meta.eyebrow;
    if (pushHash && location.hash !== '#' + view) history.replaceState(null, '', '#' + view);
    $('main')?.scrollTo?.(0, 0);
    window.scrollTo({ top: 0, behavior: 'instant' in window ? 'instant' : 'auto' });

    if (view === 'news') ensureNews();
    else if (view === 'opportunities') loadOpps(false);
    else if (view === 'journal') ensureJournal();
    else if (view === 'market') ensureMarket();
    else if (view === 'system') ensureSystem();
    else renderOverview();
    renderChrome();
  }

  function eaStatusInfo() {
    const state = Store.state || {};
    const health = Store.health || {};
    const alive = Boolean(state.ea_alive);
    const hbAge = health.ea?.heartbeat_age_sec
      ?? (state.last_heartbeat?.ts ? Math.max(0, Math.floor(Date.now() / 1000 - state.last_heartbeat.ts)) : null);
    const monitor = health.ea?.monitor || {};
    if (alive) {
      return { alive: true, label: 'EA online', cls: 'pill-green', dot: '', value: 'online', status: 'ok', age: hbAge };
    }
    if (hbAge != null) {
      return { alive: false, label: 'EA sin heartbeat', cls: 'pill-amber', dot: 'dot-amber', value: 'sin heartbeat', status: 'warn', age: hbAge };
    }
    if (monitor.running) {
      return { alive: false, label: 'EA sin datos ZMQ', cls: 'pill-amber', dot: 'dot-amber', value: 'sin datos ZMQ', status: 'warn', age: null };
    }
    return { alive: false, label: 'EA offline', cls: 'pill-red', dot: 'dot-red', value: 'offline', status: 'error', age: null };
  }

  function renderChrome() {
    const state = Store.state || {};
    const ea = Boolean(state.ea_alive);
    const eaInfo = eaStatusInfo();
    const news = Store.news || {};
    const sources = (news.health && news.health.sources) || {};
    const calendar = sources.calendar || {};
    const google = sources.google_news || {};
    const wsOk = Store.wsLive;

    const eaPill = $('ea-pill');
    if (eaPill) {
      eaPill.className = 'pill ' + eaInfo.cls;
      eaPill.innerHTML = `<span class="dot ${eaInfo.dot}"></span> ${eaInfo.label}`;
    }
    const modePill = $('mode-pill');
    if (modePill) modePill.textContent = 'Manual';

    const count = (Store.alerts || []).filter((a) => !a.leida).length;
    const badge = $('alerts-count');
    if (badge) {
      badge.hidden = count === 0;
      badge.textContent = count > 99 ? '99+' : String(count);
    }
    const drawerSub = $('drawer-sub');
    if (drawerSub) drawerSub.textContent = `${count} sin leer · ${Store.alerts.length} recientes`;

    const statusEA = $('status-ea');
    if (statusEA) statusEA.textContent = eaInfo.label;
    const dotEA = $('status-ea-dot');
    if (dotEA) dotEA.className = 'dot ' + (eaInfo.dot || 'dot-muted');

    const newsStatus = calendar.status === 'ok' ? 'Noticias OK' : calendar.status === 'stale' ? 'Noticias en caché' : 'Noticias sin datos';
    const statusNews = $('status-news');
    if (statusNews) statusNews.textContent = newsStatus;
    const dotNews = $('status-news-dot');
    if (dotNews) dotNews.className = statusClass(calendar.status);

    const statusWS = $('status-ws');
    if (statusWS) statusWS.textContent = wsOk ? 'WebSocket en vivo' : 'WebSocket reconectando';
    const dotWS = $('status-ws-dot');
    if (dotWS) dotWS.className = 'dot ' + (wsOk ? '' : 'dot-amber');

    const sideDot = $('sidebar-dot');
    if (sideDot) sideDot.className = 'dot ' + (wsOk || ea || calendar.status === 'ok' ? '' : 'dot-amber');
    const sideText = $('sidebar-status-text');
    if (sideText) sideText.textContent = wsOk ? 'Sistema en vivo' : 'Reconectando…';

    const last = $('status-last');
    if (last) last.textContent = Store.lastUpdate ? timeAgo(Store.lastUpdate) : '—';

    const soundBtn = $('sound-btn');
    if (soundBtn) {
      soundBtn.classList.toggle('is-on', Store.sound);
      soundBtn.title = Store.sound ? 'Sonido activado' : 'Activar sonido';
    }
    const mode = $('mode-pill');
    if (mode && Store.config && Store.config.mode) mode.textContent = Store.config.mode === 'manual' ? 'Manual' : Store.config.mode;
  }

  function renderLive() {
    renderHeader();
    renderRiskGauges();
    renderKpis();
    renderOverviewAlerts();
    if (Store.currentView === 'overview') {
      renderOverviewDecisions();
      renderEquityCanvas();
      renderSpark();
    }
    if (Store.currentView === 'news') {
      renderNewsBlackout();
    }
    if (Store.currentView === 'journal' && Store.journal) {
      renderJournalTrades();
    }
  }

  /* ═══════════════════════════════════════════════════════════
     Render: resumen
     ═══════════════════════════════════════════════════════════ */

  function renderCurrentView() {
    if (Store.currentView === 'overview') renderOverview();
    else if (Store.currentView === 'news') renderNews();
    else if (Store.currentView === 'opportunities') renderOpps();
    else if (Store.currentView === 'journal') renderJournal();
    else if (Store.currentView === 'market') renderMarket();
    else if (Store.currentView === 'system') renderSystem();
  }

  function renderOverview() {
    renderHeader();
    renderRiskGauges();
    renderKpis();
    renderEquityCanvas();
    renderSpark();
    renderNextEvents();
    renderOverviewOpps();
    renderOverviewHealth();
    renderOverviewDecisions();
    renderOverviewAlerts();
    renderOverviewBanner();
  }

  function renderHeader() {
    const state = Store.state || {};
    const profit = Store.profit || {};
    const config = Store.config || DEFAULT_CONFIG;
    const equity = Number(state.equity ?? config.initial_balance ?? 0);
    const balance = Number(state.balance ?? config.initial_balance ?? 0);
    const daily = Number(profit.daily_pnl ?? 0);
    const cycle = Number(profit.total_pnl_ciclo ?? (equity - Number(config.initial_balance || 0)));

    const heroEquity = $('hero-equity');
    if (heroEquity) heroEquity.textContent = money(equity);
    const delta = $('hero-delta');
    if (delta) {
      delta.innerHTML = `<strong class="${daily >= 0 ? 'green' : 'red'}">${signedMoney(daily)}</strong> hoy · `
        + `<span class="${cycle >= 0 ? 'green' : 'red'}">${signedMoney(cycle)}</span> ciclo`;
    }
    const stats = $('hero-stats');
    if (stats) {
      const openPositions = Number(state.open_positions ?? 0);
      const buffer = Number(profit.trailing_floor ? equity - profit.trailing_floor : 0);
      stats.innerHTML = [
        ['Balance', money(balance)],
        ['P&L hoy', signedMoney(daily)],
        ['P&L ciclo', signedMoney(cycle)],
        ['Abiertas', String(openPositions)],
      ].map(([k, v]) => `<div class="hero-stat"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join('');
      void buffer;
    }
    const updated = $('risk-updated');
    if (updated) updated.textContent = Store.lastUpdate ? timeAgo(Store.lastUpdate) : '—';
  }

  function gauge(label, value, sub, percent, color) {
    const p = clamp(Number(percent) || 0, 0, 100);
    const circumference = 2 * Math.PI * 21;
    const offset = circumference * (1 - p / 100);
    return `
      <div class="gauge ${color}">
        <svg viewBox="0 0 52 52" aria-hidden="true">
          <circle cx="26" cy="26" r="21" fill="none" stroke="#1d2b3f" stroke-width="5"></circle>
          <circle cx="26" cy="26" r="21" fill="none" stroke="currentColor" stroke-width="5"
            stroke-linecap="round" stroke-dasharray="${circumference.toFixed(1)}"
            stroke-dashoffset="${offset.toFixed(1)}"></circle>
        </svg>
        <div class="g-copy">
          <div class="g-label">${esc(label)}</div>
          <div class="g-value">${esc(value)}</div>
          <div class="g-sub">${esc(sub)}</div>
        </div>
      </div>`;
  }

  function renderRiskGauges() {
    const root = $('risk-gauges');
    if (!root) return;
    const state = Store.state || {};
    const profit = Store.profit || {};
    const config = Store.config || DEFAULT_CONFIG;
    const initial = Number(config.initial_balance || 50000);
    const equity = Number(state.equity ?? initial);

    const floor = Number(profit.trailing_floor ?? Math.max(initial - 2000, (profit.peak_equity || equity) - 2000));
    const buffer = Math.max(0, equity - floor);
    const maxBuffer = 2000;
    const bufferPct = clamp((1 - buffer / maxBuffer) * 100, 0, 100);
    const bufferColor = buffer > 1500 ? 'green' : buffer > 1000 ? 'amber' : 'red';

    const ratio = Number(profit.ratio_consistencia ?? 0);
    const ratioPct = clamp((ratio / 20) * 100, 0, 100);
    const ratioColor = ratio < 15 ? 'green' : ratio < 20 ? 'amber' : 'red';

    const dailyLoss = Math.max(0, Number(state.perdida_hoy ?? 0));
    const dailyLimit = initial * (Number(config.daily_loss_limit_pct || 2) / 100);
    const dailyPct = clamp((dailyLoss / dailyLimit) * 100, 0, 100);
    const dailyColor = dailyPct < 50 ? 'green' : dailyPct < 80 ? 'amber' : 'red';

    const openRisk = Math.max(0, Number(state.riesgo_abierto ?? 0));
    const riskLimit = initial * (Number(config.max_open_risk_pct || 0.5) / 100);
    const riskPct = clamp((openRisk / riskLimit) * 100, 0, 100);
    const riskColor = riskPct < 50 ? 'green' : riskPct < 80 ? 'amber' : 'red';

    root.innerHTML = [
      gauge('Buffer trailing DD', money(buffer), `floor ${money(floor)}`, bufferPct, bufferColor),
      gauge('Consistency', pct(ratio), 'límite 20%', ratioPct, ratioColor),
      gauge('Pérdida diaria', money(dailyLoss), `límite ${money(dailyLimit)}`, dailyPct, dailyColor),
      gauge('Riesgo abierto', money(openRisk), `límite ${money(riskLimit)}`, riskPct, riskColor),
    ].join('');
  }

  function renderKpis() {
    const root = $('overview-kpis');
    if (!root) return;
    const profit = Store.profit || {};
    const config = Store.config || DEFAULT_CONFIG;
    const daily = Number(profit.daily_pnl ?? 0);
    const target = Number(profit.objetivo_diario_efectivo ?? config.daily_target_usd ?? 100);
    const targetPct = target > 0 ? clamp((daily / target) * 100, 0, 100) : 0;
    const best = Number(profit.best_day_pnl ?? 0);
    const cycle = Number(profit.total_pnl_ciclo ?? 0);
    const canWithdraw = Boolean(profit.puede_retirar);
    const falta = Number(profit.falta_para_20pct ?? 0);

    const cards = [
      {
        k: 'P&L ciclo', v: signedMoney(cycle), s: `best day ${money(best)}`,
        cls: cycle >= 0 ? 'green' : 'red',
      },
      {
        k: 'Objetivo diario', v: money(daily) + ' / ' + money(target), s: `${targetPct.toFixed(0)}% del objetivo`,
        cls: daily >= target ? 'green' : daily > 0 ? 'blue' : 'muted',
        extra: `<div class="mini-bar"><i style="width:${targetPct}%;background:${daily >= target ? 'var(--green)' : 'var(--blue)'}"></i></div>`,
      },
      {
        k: 'Retiro', v: canWithdraw ? 'Disponible' : 'No disponible',
        s: canWithdraw ? (profit.motivo_retiro || 'Cumple reglas') : `Faltan ${money(falta)} para 20%`,
        cls: canWithdraw ? 'green' : 'amber',
      },
      {
        k: 'Días / operaciones', v: `${Number(Store.stats.total ?? 0)} trades`,
        s: `${Store.stats.wins ?? 0} wins · ${Store.stats.losses ?? 0} losses`,
        cls: 'blue',
      },
    ];
    root.innerHTML = cards.map((card) => `
      <article class="card kpi">
        <div class="k">${esc(card.k)}</div>
        <div class="v ${card.cls}">${esc(card.v)}</div>
        <div class="s">${esc(card.s)}</div>
        ${card.extra || ''}
      </article>`).join('');
  }

  function renderSpark() {
    const canvas = $('hero-spark');
    if (!canvas) return;
    const values = (Store.equity || []).map((row) => Number(row.equity)).filter((n) => Number.isFinite(n));
    drawSpark(canvas, values.length ? values : [Number(Store.state?.equity || 0)]);
  }

  function renderEquityCanvas() {
    const canvas = $('equity-chart');
    const empty = $('equity-empty');
    if (!canvas) return;
    const rows = Store.equity || [];
    const values = rows.map((row) => Number(row.equity)).filter((n) => Number.isFinite(n));
    if (values.length < 2) {
      canvas.style.display = 'none';
      if (empty) empty.hidden = false;
      return;
    }
    canvas.style.display = 'block';
    if (empty) empty.hidden = true;
    drawLineChart(canvas, rows, {
      color: '#54a9ff',
      fill: 'rgba(84,169,255,.12)',
      valueOf: (row) => Number(row.equity),
      labelOf: (row) => fmtTime(row.ts),
    });
    const range = $('equity-range');
    if (range && rows.length) {
      range.textContent = `${fmtDateTime(rows[0].ts)} → ${fmtDateTime(rows[rows.length - 1].ts)}`;
    }
  }

  function renderNextEvents() {
    const root = $('next-events');
    if (!root) return;
    const news = Store.news || {};
    const events = (news.calendar_symbol && news.calendar_symbol.length ? news.calendar_symbol : news.calendar) || [];
    const upcoming = events
      .filter((event) => {
        const date = parseUtc(event.dt_utc || event.Date);
        return date && date.getTime() > Date.now() - 15 * 60000;
      })
      .sort((a, b) => (parseUtc(a.dt_utc || a.Date)?.getTime() || 0) - (parseUtc(b.dt_utc || b.Date)?.getTime() || 0))
      .slice(0, 4);
    if (!upcoming.length) {
      root.innerHTML = '<div class="empty"><strong>Sin eventos próximos</strong>El calendario no tiene eventos de alto impacto para este activo.</div>';
      return;
    }
    root.innerHTML = upcoming.map((event) => `
      <div class="row-item">
        <div class="row-main">
          <div class="row-title">${esc(event.Event || event.event || 'Evento')}</div>
          <div class="row-sub">${esc(event.Currency || '')} · ${esc(event.Impact || '')} · ${esc(fmtDateTime(event.dt_utc || event.Date))}</div>
        </div>
        <div class="row-side">
          <span class="pill ${Number(event.Importance) >= 3 ? 'pill-red' : 'pill-amber'}" data-countdown data-ts="${esc(event.dt_utc || event.Date)}">${esc(countdown(event.dt_utc || event.Date))}</span>
        </div>
      </div>`).join('');
  }

  function renderOverviewOpps() {
    const root = $('overview-opps');
    if (!root) return;
    const opps = getOpps().slice(0, 3);
    if (!opps.length) {
      root.innerHTML = '<div class="empty"><strong>Sin oportunidades recientes</strong>El cazador no ha publicado señales en las últimas 24 h.</div>';
      return;
    }
    root.innerHTML = opps.map((op) => `
      <div class="row-item">
        <span class="symbol-chip">${esc(op.symbol)}</span>
        <span class="dir ${op.direction === 'LONG' ? 'long' : 'short'}">${esc(op.direction)}</span>
        <div class="row-main">
          <div class="row-title">Entrada ${esc(price(op.entry, op.symbol))} · SL ${esc(price(op.sl, op.symbol))} · TP ${esc(price(op.tp, op.symbol))}</div>
          <div class="row-sub">${esc(op.confluence || 0)} confluencias · score ${esc(op.score ?? '—')} · ${esc(timeAgo(op.ts))}</div>
        </div>
        <button class="link-btn" data-goto="opportunities">Ver</button>
      </div>`).join('');
  }

  function renderOverviewHealth() {
    const root = $('overview-health');
    if (!root) return;
    const health = Store.health || {};
    const files = health.files || {};
    const news = Store.news || {};
    const sources = (news.health && news.health.sources) || {};
    const calendar = sources.calendar || {};
    const google = sources.google_news || {};
    const eaInfo = eaStatusInfo();
    const orchAge = files.orchestrator_log?.age_sec;
    const htf = Object.keys((Store.htf && Store.htf.symbols) || {}).length;
    const rows = [
      ['EA / MT5', eaInfo.value + (eaInfo.age != null ? ` · ${timeAgo(new Date(Date.now() - eaInfo.age * 1000))}` : ''), eaInfo.status],
      ['Orquestador', orchAge == null ? 'sin log' : timeAgo(new Date(Date.now() - orchAge * 1000)), orchAge != null && orchAge < 1200 ? 'ok' : 'warn'],
      ['Calendario', calendar.status === 'ok' ? `${calendar.count || 0} eventos` : statusText(calendar.status), calendar.status],
      ['Titulares', google.status === 'ok' ? `${google.count || 0} titulares` : statusText(google.status), google.status],
      ['HTF', `${htf} activos`, htf > 0 ? 'ok' : 'warn'],
      ['Journal', `${health.db?.decisions ?? 0} decisiones`, 'ok'],
    ];
    root.innerHTML = rows.map(([label, value, status]) => `
      <div class="health-row">
        <span class="${statusClass(status === 'warn' ? 'stale' : status)}"></span>
        <span class="health-label">${esc(label)}</span>
        <span class="health-val">${esc(value)}</span>
      </div>`).join('');
  }

  function renderOverviewDecisions() {
    const root = $('overview-decisions');
    if (!root) return;
    const rows = (Store.decisions || []).slice(0, 6);
    if (!rows.length) {
      root.innerHTML = '<div class="empty"><strong>Sin decisiones</strong>El orquestador no ha registrado ciclos.</div>';
      return;
    }
    root.innerHTML = `<div class="table-wrap" style="max-height:none">
      <table class="data"><thead><tr><th>Hora</th><th>Símbolo</th><th>Resultado</th><th>Motivo</th></tr></thead><tbody>
      ${rows.map((row) => `
        <tr class="clickable" data-decision-id="${row.id}">
          <td class="num">${esc(fmtTime(row.ts))}</td>
          <td><span class="symbol-chip">${esc(row.symbol)}</span></td>
          <td>${row.operar ? '<span class="pill pill-green">operar</span>' : `<span class="pill pill-quiet">veto · capa ${esc(row.capa ?? '—')}</span>`}</td>
          <td class="wrap" title="${esc(row.motivo || '')}">${esc(row.motivo || '—')}</td>
        </tr>`).join('')}
      </tbody></table></div>`;
  }

  function renderOverviewAlerts() {
    const root = $('overview-alerts');
    if (!root) return;
    const alerts = (Store.alerts || []).slice(0, 5);
    if (!alerts.length) {
      root.innerHTML = '<div class="empty"><strong>Sin alertas</strong>No hay eventos locales registrados.</div>';
      return;
    }
    root.innerHTML = alerts.map((alert) => alertRow(alert)).join('');
  }

  function renderOverviewBanner() {
    const root = $('overview-banner');
    if (!root) return;
    const blackout = Store.news?.blackout || {};
    const profit = Store.profit || {};
    const parts = [];
    if (blackout.blocked) {
      parts.push(`<div class="banner banner-danger"><div class="banner-ico">⛔</div><div><div class="banner-title">Ventana de noticias activa</div><div class="banner-text">${esc(blackout.reason || 'Evento de alto impacto en la ventana de bloqueo.')} · no se generan señales nuevas.</div></div></div>`);
    } else if (blackout.event) {
      parts.push(`<div class="banner banner-info"><div class="banner-ico">◷</div><div><div class="banner-title">Próximo evento de alto impacto</div><div class="banner-text">${esc(blackout.event.Event || 'Evento')} (${esc(blackout.event.Currency || '')}) ${esc(countdown(blackout.event.dt_utc || blackout.event.Date))} · ventana ±${esc(blackout.minutes || 15)} min.</div></div></div>`);
    }
    if (profit.dilution && profit.dilution.active) {
      parts.push(`<div class="banner banner-warning"><div class="banner-ico">⚠</div><div><div class="banner-title">Modo dilución activo</div><div class="banner-text">Objetivo diario reducido a ${esc(money(profit.dilution.current_daily_target))} · faltan ${esc(money(profit.dilution.falta))} para el 20%.</div></div></div>`);
    }
    if (!Store.wsLive) {
      parts.push(`<div class="banner banner-warning"><div class="banner-ico">⟳</div><div><div class="banner-title">WebSocket reconectando</div><div class="banner-text">La vista se actualiza por polling cada pocos segundos.</div></div></div>`);
    }
    root.innerHTML = parts.join('');
  }

  /* ═══════════════════════════════════════════════════════════
     Noticias
     ═══════════════════════════════════════════════════════════ */

  function ensureNews() {
    const current = Store.news || {};
    const stale = !current.generated_at
      || (current.symbol && current.symbol !== Store.newsSymbol)
      || (Date.now() - (parseUtc(current.generated_at)?.getTime() || 0) > 5 * 60000);
    renderNews();
    if (stale) loadNews(false);
  }

  async function loadNews(force = false) {
    if (Store.loading.news) return;
    Store.loading.news = true;
    const updated = $('news-updated');
    if (updated) updated.textContent = 'actualizando…';
    try {
      const data = await api(`/api/news?symbol=${encodeURIComponent(Store.newsSymbol)}&days=3${force ? '&refresh=1' : ''}`, { timeout: 40000 });
      Store.news = data;
      Store.newsSymbol = data.symbol || Store.newsSymbol;
      renderNews();
      renderChrome();
    } catch (error) {
      toast('No se pudieron actualizar las noticias', String(error.message || error), 'error');
      if (updated) updated.textContent = 'error de actualización';
    } finally {
      Store.loading.news = false;
    }
  }

  function renderNews() {
    const news = Store.news || {};
    const updated = $('news-updated');
    const meta = news.headlines_meta || {};
    if (updated) {
      updated.textContent = news.generated_at
        ? `Actualizado ${timeAgo(news.generated_at)} · ${meta.count || 0} titulares`
        : 'sin datos';
    }
    const select = $('news-symbol');
    if (select) select.value = Store.newsSymbol;
    const sub = $('calendar-sub');
    if (sub) sub.textContent = `Próximas 72 h · ${news.currencies ? news.currencies.join(' / ') : 'todas las divisas'} · hora local`;
    const hsub = $('headlines-sub');
    if (hsub) hsub.textContent = `${meta.query ? 'Búsqueda: ' + meta.query : 'Google News RSS'} · ${meta.stale ? 'caché' : 'en vivo'}`;
    $('news-only-symbol').checked = Store.newsOnlySymbol;
    renderNewsBlackout();
    renderCalendar();
    renderHeadlines();
    renderSentiment();
    renderPipeline();
    renderNewsHealth();
  }

  function renderNewsBlackout() {
    const root = $('news-blackout');
    if (!root) return;
    const blackout = Store.news?.blackout || {};
    if (blackout.blocked) {
      root.innerHTML = `<div class="banner banner-danger">
        <div class="banner-ico">⛔</div>
        <div><div class="banner-title">Bloqueo por noticia activo</div>
        <div class="banner-text">${esc(blackout.reason || 'Evento de alto impacto dentro de la ventana.')} · ventana ±${esc(blackout.minutes || 15)} min · el orquestador no generará señales para este activo.</div></div>
      </div>`;
      return;
    }
    const event = blackout.event;
    if (event) {
      root.innerHTML = `<div class="banner banner-info">
        <div class="banner-ico">◷</div>
        <div><div class="banner-title">Sin bloqueo · próximo evento</div>
        <div class="banner-text">${esc(event.Event || 'Evento')} (${esc(event.Currency || '')}) ${esc(countdown(event.dt_utc || event.Date))} · el veto se activa ±${esc(blackout.minutes || 15)} min.</div></div>
      </div>`;
      return;
    }
    root.innerHTML = `<div class="banner banner-info">
      <div class="banner-ico">○</div>
      <div><div class="banner-title">Sin bloqueo por noticias</div>
      <div class="banner-text">No hay eventos de alto impacto próximos para ${esc(Store.newsSymbol)}.</div></div>
    </div>`;
  }

  function renderCalendar() {
    const root = $('calendar-list');
    if (!root) return;
    const news = Store.news || {};
    const all = news.calendar || [];
    const currencies = new Set(news.currencies || []);
    const query = Store.newsSearch.trim().toLowerCase();
    const events = all.filter((event) => {
      const importance = Number(event.Importance || 0);
      if (Store.newsImpact === 'high' && importance < 3) return false;
      if (Store.newsImpact === 'medium' && importance >= 3) return false;
      if (Store.newsOnlySymbol && !currencies.has(String(event.Currency || '').toUpperCase())) return false;
      if (query && !(`${event.Event || ''} ${event.Currency || ''}`.toLowerCase().includes(query))) return false;
      return true;
    });
    const count = $('calendar-count');
    if (count) count.textContent = `${events.length} evento${events.length === 1 ? '' : 's'}`;
    if (!events.length) {
      root.innerHTML = '<div class="empty"><strong>Sin eventos con estos filtros</strong>Prueba a quitar el filtro de impacto o de activo.</div>';
      return;
    }
    const groups = new Map();
    events.forEach((event) => {
      const date = parseUtc(event.dt_utc || event.Date);
      const key = date ? date.toLocaleDateString('es-ES', { year: 'numeric', month: '2-digit', day: '2-digit' }) : 'sin fecha';
      if (!groups.has(key)) groups.set(key, { date, rows: [] });
      groups.get(key).rows.push(event);
    });
    root.innerHTML = Array.from(groups.values()).map((group) => `
      <div class="day-group">
        <div class="day-label">${esc(group.date ? fmtDateLong(group.date) : 'Sin fecha')}</div>
        ${group.rows.map((event) => {
          const date = parseUtc(event.dt_utc || event.Date);
          const ts = event.dt_utc || event.Date;
          const minutes = date ? (date.getTime() - Date.now()) / 60000 : 9999;
          const past = minutes < -5;
          const imminent = Math.abs(minutes) <= 15;
          const high = Number(event.Importance) >= 3;
          return `<div class="event impact-${high ? 'high' : 'medium'} ${past ? 'is-past' : ''} ${imminent ? 'is-imminent' : ''}">
            <div class="event-time">${esc(fmtTime(ts))}<br><span class="tiny muted" data-countdown data-ts="${esc(ts)}">${esc(countdown(ts))}</span></div>
            <div class="event-main">
              <div class="event-title">${esc(event.Event || 'Evento')}</div>
              <div class="event-meta"><span class="cur">${esc(event.Currency || '—')}</span><span>${high ? 'Alto impacto' : 'Impacto medio'}</span>${event.Actual ? `<span>Actual: <b class="mono">${esc(event.Actual)}</b></span>` : ''}</div>
            </div>
            <div class="event-vals">
              <div>Fcst<b>${esc(event.Forecast || '—')}</b></div>
              <div>Prev<b>${esc(event.Previous || '—')}</b></div>
            </div>
          </div>`;
        }).join('')}
      </div>`).join('');
  }

  function renderHeadlines() {
    const root = $('headlines-list');
    if (!root) return;
    const news = Store.news || {};
    const meta = news.headlines_meta || {};
    const query = Store.newsSearch.trim().toLowerCase();
    const items = (news.headlines || []).filter((item) => {
      if (Store.headlineSent === 'positive' && Number(item.impact) <= 0.4) return false;
      if (Store.headlineSent === 'negative' && Number(item.impact) >= -0.4) return false;
      if (query && !(`${item.title || ''} ${item.source || ''}`.toLowerCase().includes(query))) return false;
      return true;
    });
    if (!items.length) {
      root.innerHTML = `<div class="empty"><strong>Sin titulares${meta.stale ? ' actualizados' : ''}</strong>
        ${meta.stale ? 'La fuente falló; se muestra la última caché disponible.' : 'Google News no devolvió titulares relevantes para este activo.'}</div>`;
      return;
    }
    root.innerHTML = items.map((item) => {
      const impact = Number(item.impact || 0);
      const cls = impact > 0.4 ? 'pos' : impact < -0.4 ? 'neg' : 'neu';
      const label = impact > 0.4 ? 'alcista' : impact < -0.4 ? 'bajista' : 'neutro';
      const rel = clamp((Number(item.relevance || 0) / 8) * 100, 0, 100);
      return `<article class="headline">
        <div>
          <a class="headline-title" href="${esc(safeUrl(item.url))}" target="_blank" rel="noopener">${esc(item.title || 'Titular')}</a>
          <div class="headline-meta">
            <span>${esc(item.source || 'Google News')}</span>
            <span>·</span>
            <span>${esc(timeAgo(item.published))}</span>
            <span class="impact-chip ${cls}">${label}</span>
            <span class="rel"><span class="rel-bar"><i style="width:${rel}%"></i></span>${esc(item.relevance ?? '—')}</span>
          </div>
        </div>
      </article>`;
    }).join('');
  }

  function renderSentiment() {
    const root = $('sentiment-card');
    if (!root) return;
    const sentiment = Store.news?.sentiment || {};
    if (!sentiment.available) {
      root.innerHTML = `<div class="card-head"><div><h2>Sentimiento</h2><p>Heurístico sobre titulares</p></div></div>
        <div class="empty"><strong>Sin datos suficientes</strong>El sentimiento no se usa como veto cuando no hay titulares.</div>`;
      return;
    }
    const label = sentiment.label || 'NEUTRAL';
    const color = label === 'BULLISH' ? 'green' : label === 'BEARISH' ? 'red' : 'muted';
    const marker = clamp(50 + Number(sentiment.score || 0) / 2, 0, 100);
    root.innerHTML = `
      <div class="card-head"><div><h2>Sentimiento</h2><p>Heurístico · lexicon-v1</p></div>
        <span class="pill pill-quiet">conf. ${esc(sentiment.confidence ?? 0)}%</span></div>
      <div class="sentiment-head">
        <div class="sent-label ${color}">${esc(label)}</div>
        <div class="sent-score">${Number(sentiment.score) >= 0 ? '+' : ''}${esc(sentiment.score ?? 0)} / 100</div>
      </div>
      <div class="sent-track"><div class="sent-marker" style="left:${marker}%"></div></div>
      <div class="sent-scale"><span>bajista</span><span>neutro</span><span>alcista</span></div>
      <div class="pill-row" style="margin-top:10px">
        <span class="pill pill-green">${esc(sentiment.positives ?? 0)} alcistas</span>
        <span class="pill pill-red">${esc(sentiment.negatives ?? 0)} bajistas</span>
        <span class="pill pill-quiet">${esc(sentiment.neutrals ?? 0)} neutras</span>
      </div>
      <div class="sent-drivers">
        ${(sentiment.drivers || []).slice(0, 3).map((driver) => `
          <div class="driver"><b class="${Number(driver.impact) >= 0 ? 'green' : 'red'}">${Number(driver.impact) >= 0 ? '+' : ''}${esc(driver.impact)}</b><span title="${esc(driver.title)}">${esc(driver.title)}</span></div>`).join('')}
      </div>
      <div class="tiny muted" style="margin-top:10px">${esc(sentiment.summary || '')}</div>`;
  }

  function renderPipeline() {
    const root = $('news-pipeline');
    if (!root) return;
    const news = Store.news || {};
    const health = news.health || {};
    const sources = health.sources || {};
    const calendar = sources.calendar || {};
    const google = sources.google_news || {};
    const meta = news.headlines_meta || {};
    const blackout = news.blackout || {};
    const cacheAge = health.calendar_age_sec;
    const steps = [
      ['ForexFactory JSON', `${calendar.count || 0} eventos`, calendar.status, calendar.latency_ms != null ? `${calendar.latency_ms} ms` : '—'],
      ['Normalización UTC', news.currencies ? news.currencies.join('/') : '—', 'ok', 'offset aplicado'],
      ['Caché + reintentos', cacheAge != null ? timeAgo(new Date(Date.now() - cacheAge * 1000)) : '—', calendar.status === 'error' ? 'error' : 'ok', 'TTL 15 min'],
      ['Google News RSS', `${meta.count || 0} titulares`, google.status, google.latency_ms != null ? `${google.latency_ms} ms` : '—'],
      ['Relevancia + dedupe', `${meta.count || 0} relevantes`, meta.count ? 'ok' : 'stale', 'score por activo'],
      ['Sentimiento', news.sentiment?.available ? news.sentiment.label : 'sin datos', news.sentiment?.available ? 'ok' : 'stale', 'lexicon-v1'],
      ['Contexto LLM', (news.calendar?.length || meta.count) ? 'listo' : 'sin datos', (news.calendar?.length || meta.count) ? 'ok' : 'stale', 'agente fundamental'],
      ['Veto ±15 min', blackout.blocked ? 'BLOQUEADO' : 'libre', blackout.blocked ? 'warn' : 'ok', blackout.blocked ? blackout.reason : 'sin evento'],
    ];
    root.innerHTML = steps.map(([name, sub, status, value]) => {
      const dotClass = status === 'ok' ? 'ok' : status === 'error' ? 'err' : status === 'warn' ? 'warn' : status === 'stale' ? 'warn' : '';
      const ico = dotClass === 'ok' ? '✓' : dotClass === 'warn' ? '!' : dotClass === 'err' ? '×' : '•';
      return `<div class="pipe">
        <div class="pipe-dot ${dotClass}">${ico}</div>
        <div><div class="pipe-name">${esc(name)}</div><div class="pipe-sub">${esc(sub)}</div></div>
        <div class="pipe-val">${esc(value ?? '—')}</div>
      </div>`;
    }).join('');
  }

  function renderNewsHealth() {
    const root = $('news-health');
    if (!root) return;
    const sources = Store.news?.health?.sources || {};
    const order = ['calendar', 'google_news', 'finnhub'];
    root.innerHTML = order.map((key) => {
      const source = sources[key] || {};
      return `<div class="health-row">
        <span class="${statusClass(source.status)}"></span>
        <span class="health-label">${esc(source.label || key)}</span>
        <span class="health-val" title="${esc(source.last_error || '')}">${esc(statusText(source.status))} · ${esc(source.count ?? 0)} · ${source.latency_ms != null ? esc(source.latency_ms) + ' ms' : '—'}</span>
      </div>`;
    }).join('') + `<div class="health-row"><span class="dot dot-muted"></span><span class="health-label">Caché de disco</span><span class="health-val">${esc(Store.news?.health?.saved_at ? timeAgo(Store.news.health.saved_at) : '—')}</span></div>`;
  }

  /* ═══════════════════════════════════════════════════════════
     Oportunidades
     ═══════════════════════════════════════════════════════════ */

  function normalizeOpp(raw, source) {
    const data = parseMaybe(raw.data);
    const symbol = raw.symbol || data.symbol || data.activo || '—';
    const direction = String(raw.direction || data.direction || data.direccion || '—').toUpperCase();
    const entry = data.entry ?? data.entrada;
    const sl = data.sl ?? data.stop_loss;
    const tp = data.tp ?? data.take_profit;
    const lot = data.lotaje ?? data.lotage;
    const score = data.score ?? data.score_consenso;
    const confluence = data.confluencia ?? data.confluence ?? data.count ?? 0;
    const rr = data.rr ?? (entry != null && sl != null && tp != null && Math.abs(entry - sl) > 0
      ? Math.abs(tp - entry) / Math.abs(entry - sl) : null);
    return {
      key: `${source}-${raw.id ?? raw.ts ?? Math.random()}`,
      id: raw.id,
      source,
      ts: raw.ts,
      symbol: String(symbol).toUpperCase(),
      direction: direction === 'LONG' || direction === 'SHORT' ? direction : '—',
      entry, sl, tp, lot, score, confluence, rr,
      risk: data.riesgo_usd ?? data.risk_usd ?? null,
      strategies: asArray(data.estrategias ?? data.strategies),
      timeframes: asArray(data.timeframes),
      macro: data.macro || null,
      message: raw.message || '',
      severity: raw.severity || 'INFO',
      raw,
    };
  }

  function getOpps() {
    const out = [];
    (Store.alerts || []).forEach((alert) => {
      if (alert.tipo !== 'opportunity') return;
      out.push(normalizeOpp(alert, 'alert'));
    });
    (Store.signals || []).forEach((signal) => {
      out.push(normalizeOpp(signal, 'signal'));
    });
    const seen = new Set();
    return out
      .filter((op) => {
        const key = `${op.symbol}|${op.direction}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .filter((op) => {
        const date = parseUtc(op.ts);
        return !date || Date.now() - date.getTime() < 48 * 3600 * 1000;
      })
      .sort((a, b) => (parseUtc(b.ts)?.getTime() || 0) - (parseUtc(a.ts)?.getTime() || 0));
  }

  async function loadOpps(force = false) {
    if (Store.loading.opps) return;
    Store.loading.opps = true;
    try {
      const [alerts, signals] = await Promise.all([
        api('/api/alerts?limit=200', { timeout: 12000 }),
        api('/api/signals?limit=100', { timeout: 12000 }),
      ]);
      Store.alerts = alerts || Store.alerts;
      Store.signals = signals || Store.signals;
      renderOpps();
      renderChrome();
    } catch (error) {
      if (force) toast('No se pudieron cargar las oportunidades', String(error.message || error), 'error');
    } finally {
      Store.loading.opps = false;
    }
  }

  function renderOpps() {
    const all = getOpps();
    const query = Store.oppsSearch.trim().toLowerCase();
    const filtered = all.filter((op) => {
      if (Store.oppsDirection !== 'all' && op.direction !== Store.oppsDirection) return false;
      if (Number(op.confluence || 0) < Number(Store.oppsMinConf || 0)) return false;
      if (query && !(`${op.symbol} ${op.strategies.join(' ')} ${op.direction}`.toLowerCase().includes(query))) return false;
      return true;
    });
    const kpis = $('opps-kpis');
    if (kpis) {
      const longs = all.filter((op) => op.direction === 'LONG').length;
      const shorts = all.filter((op) => op.direction === 'SHORT').length;
      const avg = all.length ? all.reduce((sum, op) => sum + Number(op.confluence || 0), 0) / all.length : 0;
      kpis.innerHTML = [
        ['Oportunidades 48 h', String(all.length), 'blue'],
        ['LONG', String(longs), 'green'],
        ['SHORT', String(shorts), 'red'],
        ['Confluencia media', avg.toFixed(1), 'purple'],
      ].map(([k, v, cls]) => `<article class="card kpi"><div class="k">${esc(k)}</div><div class="v ${cls}">${esc(v)}</div></article>`).join('');
    }
    const grid = $('opps-grid');
    if (grid) {
      grid.innerHTML = filtered.length
        ? filtered.map(oppCard).join('')
        : `<div class="card empty"><strong>Sin oportunidades con estos filtros</strong>El cazador publica cuando hay confluencia ≥ ${esc(Store.config.min_confluencia ?? 2)} y el macro no veta.</div>`;
    }
    const updated = $('opps-updated');
    if (updated) updated.textContent = all.length ? `Última: ${timeAgo(all[0].ts)}` : 'sin señales recientes';
    renderSignalsTable();
    renderOppsAlerts();
  }

  function oppCard(op) {
    const dirCls = op.direction === 'LONG' ? 'long' : 'short';
    const score = Number(op.score || 0);
    const conf = Number(op.confluence || 0);
    return `<article class="opp-card ${dirCls}" data-opp-key="${esc(op.key)}">
      <div class="opp-top">
        <div><span class="opp-symbol">${esc(op.symbol)}</span> <span class="dir ${dirCls}">${esc(op.direction)}</span></div>
        <span class="pill ${conf >= 3 ? 'pill-purple' : conf >= 2 ? 'pill-blue' : 'pill-quiet'}">${conf} confluencias</span>
      </div>
      <div class="opp-prices">
        <div class="opp-price"><div class="k">Entrada</div><div class="v">${esc(price(op.entry, op.symbol))}</div></div>
        <div class="opp-price"><div class="k">Stop</div><div class="v red">${esc(price(op.sl, op.symbol))}</div></div>
        <div class="opp-price"><div class="k">Target</div><div class="v green">${esc(price(op.tp, op.symbol))}</div></div>
      </div>
      <div class="opp-meta">
        <span>Lote <b class="mono">${esc(op.lot ?? '—')}</b></span>
        <span>R:R <b class="mono">${op.rr != null ? '1:' + Number(op.rr).toFixed(2) : '—'}</b></span>
        <span>Score <b class="mono">${score ? score.toFixed(1) : '—'}</b></span>
        ${op.risk != null ? `<span>Riesgo <b class="mono">${money(op.risk)}</b></span>` : ''}
        <span>${esc(timeAgo(op.ts))}</span>
      </div>
      <div class="opp-foot">
        <div class="opp-tags">${op.strategies.slice(0, 3).map((s) => `<span class="tag">${esc(s)}</span>`).join('')}${op.macro?.veredicto ? `<span class="tag">macro ${esc(op.macro.veredicto)}</span>` : ''}</div>
        <div class="opp-actions">
          <button data-copy-opp="${esc(op.key)}" title="Copiar plan">Copiar</button>
          <button data-detail-opp="${esc(op.key)}" title="Ver JSON">Detalle</button>
        </div>
      </div>
    </article>`;
  }

  function renderSignalsTable() {
    const root = $('signals-table');
    if (!root) return;
    const rows = (Store.signals || []).slice(0, 20);
    if (!rows.length) {
      root.innerHTML = '<div class="empty"><strong>Sin señales registradas</strong>El consenso no ha superado todas las capas todavía.</div>';
      return;
    }
    root.innerHTML = `<div class="table-wrap" style="max-height:330px"><table class="data">
      <thead><tr><th>Hora</th><th>Símbolo</th><th>Dir</th><th>Entrada</th><th>SL</th><th>TP</th><th>Lote</th><th>Score</th></tr></thead><tbody>
      ${rows.map((row) => `<tr>
        <td class="num">${esc(fmtTime(row.ts))}</td>
        <td><span class="symbol-chip">${esc(row.symbol)}</span></td>
        <td><span class="dir ${row.direction === 'LONG' ? 'long' : 'short'}">${esc(row.direction)}</span></td>
        <td class="num">${esc(price(row.entry, row.symbol))}</td>
        <td class="num red">${esc(price(row.sl, row.symbol))}</td>
        <td class="num green">${esc(price(row.tp, row.symbol))}</td>
        <td class="num">${esc(row.lotage ?? '—')}</td>
        <td class="num">${esc(row.score ?? '—')}</td>
      </tr>`).join('')}
      </tbody></table></div>`;
  }

  function renderOppsAlerts() {
    const root = $('opps-alerts');
    if (!root) return;
    const alerts = (Store.alerts || []).filter((alert) => alert.tipo === 'opportunity').slice(0, 8);
    if (!alerts.length) {
      root.innerHTML = '<div class="empty"><strong>Sin alertas del cazador</strong>Las oportunidades aparecerán aquí.</div>';
      return;
    }
    root.innerHTML = alerts.map((alert) => alertRow(alert)).join('');
  }

  function copyOpp(key) {
    const op = getOpps().find((item) => item.key === key);
    if (!op) return;
    const text = [
      `FNL:004 · ${op.symbol} ${op.direction}`,
      `Entrada: ${price(op.entry, op.symbol)}`,
      `SL: ${price(op.sl, op.symbol)}`,
      `TP: ${price(op.tp, op.symbol)}`,
      `Lote: ${op.lot ?? '—'}`,
      `R:R: ${op.rr != null ? '1:' + Number(op.rr).toFixed(2) : '—'}`,
      `Confluencia: ${op.confluence ?? '—'} (${op.strategies.join(', ') || '—'})`,
      `Score: ${op.score ?? '—'}`,
      `Macro: ${op.macro?.veredicto || '—'}`,
      `Generado: ${op.ts || '—'}`,
      'Ejecución manual. Verifica precio y spread en MT5.',
    ].join('\n');
    const copyText = async (value) => {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(value);
        return;
      }
      const area = document.createElement('textarea');
      area.value = value;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      document.execCommand('copy');
      area.remove();
    };
    copyText(text).then(
      () => toast('Plan copiado', `${op.symbol} ${op.direction}`, 'success', 2500),
      () => toast('No se pudo copiar', 'El navegador bloqueó el portapapeles.', 'error'),
    );
  }

  async function openOpp(key) {
    const op = getOpps().find((item) => item.key === key);
    if (!op) return;
    openModal(`${op.symbol} · ${op.direction}`, 'Detalle de la oportunidad', `
      <div class="detail-block">
        <div class="detail-kpis">
          <div class="detail-kpi"><div class="k">Entrada</div><div class="v">${esc(price(op.entry, op.symbol))}</div></div>
          <div class="detail-kpi"><div class="k">Stop</div><div class="v red">${esc(price(op.sl, op.symbol))}</div></div>
          <div class="detail-kpi"><div class="k">Target</div><div class="v green">${esc(price(op.tp, op.symbol))}</div></div>
          <div class="detail-kpi"><div class="k">Lote</div><div class="v">${esc(op.lot ?? '—')}</div></div>
        </div>
      </div>
      <div class="detail-block"><h3>Plan</h3><div class="agent-card">
        <div class="kv">
          <span class="k">Confluencia</span><span class="v">${esc(op.confluence ?? '—')}</span>
          <span class="k">Estrategias</span><span class="v">${esc(op.strategies.join(', ') || '—')}</span>
          <span class="k">Score</span><span class="v">${esc(op.score ?? '—')}</span>
          <span class="k">Macro</span><span class="v">${esc(op.macro?.veredicto || '—')}</span>
          <span class="k">Generado</span><span class="v">${esc(fmtDateTime(op.ts))}</span>
        </div>
      </div></div>
      <div class="detail-block"><h3>Payload</h3><pre class="agent-json">${esc(JSON.stringify(op.raw, null, 2))}</pre></div>
    `);
  }

  /* ═══════════════════════════════════════════════════════════
     Journal
     ═══════════════════════════════════════════════════════════ */

  function ensureJournal() {
    if (!Store.journal) loadJournal();
    else renderJournal();
  }

  async function loadJournal() {
    if (Store.loading.journal) return;
    Store.loading.journal = true;
    try {
      const [summary, decisions, trades, alerts, equity] = await Promise.all([
        api('/api/journal/summary?days=30', { timeout: 12000 }),
        api('/api/decisions?limit=120&compact=1', { timeout: 12000 }),
        api('/api/trades?limit=100', { timeout: 12000 }),
        api('/api/alerts?limit=200', { timeout: 12000 }),
        api('/api/equity?limit=500', { timeout: 12000 }),
      ]);
      Store.journal = { summary, decisions, trades, alerts, equity };
      Store.alerts = alerts || Store.alerts;
      renderJournal();
      renderChrome();
    } catch (error) {
      toast('No se pudo cargar el journal', String(error.message || error), 'error');
    } finally {
      Store.loading.journal = false;
    }
  }

  function renderJournal() {
    const journal = Store.journal;
    if (!journal) {
      $('journal-kpis').innerHTML = '<div class="card kpi"><div class="skeleton" style="height:40px"></div></div>'.repeat(4);
      return;
    }
    const summary = journal.summary || {};
    const decisions = journal.decisions || [];
    const trades = journal.trades || [];
    const alerts = journal.alerts || [];
    const operate = decisions.filter((row) => row.operar).length;
    const vetos = decisions.length - operate;
    const tradePnl = Number(summary.trades?.pnl ?? 0);
    const kpis = $('journal-kpis');
    if (kpis) {
      kpis.innerHTML = [
        ['Decisiones 30 d', String(decisions.length), 'blue'],
        ['Operar', String(operate), 'green'],
        ['Vetos', String(vetos), 'amber'],
        ['P&L trades', signedMoney(tradePnl), tradePnl >= 0 ? 'green' : 'red'],
      ].map(([k, v, cls]) => `<article class="card kpi"><div class="k">${esc(k)}</div><div class="v ${cls}">${esc(v)}</div></article>`).join('');
    }
    renderJournalChart(journal.equity || []);
    renderJournalLayers(summary.por_capa || []);
    renderJournalDecisions();
    renderJournalTrades();
    renderJournalAlerts();
    const alertExp = $('journal-alerts-export');
    if (alertExp) alertExp.onclick = () => { window.location.href = '/api/export/alerts.csv'; };
  }

  function renderJournalChart(rows) {
    const canvas = $('journal-chart');
    if (!canvas) return;
    if (!rows || rows.length < 2) {
      canvas.style.display = 'none';
      return;
    }
    canvas.style.display = 'block';
    drawLineChart(canvas, rows, {
      color: '#2ee6a6',
      fill: 'rgba(46,230,166,.10)',
      valueOf: (row) => Number(row.equity),
      labelOf: (row) => fmtTime(row.ts),
      secondLine: { color: 'rgba(140,160,184,.55)', valueOf: (row) => Number(row.balance) },
    });
  }

  function renderJournalLayers(layers) {
    const root = $('journal-layers');
    if (!root) return;
    if (!layers.length) {
      root.innerHTML = '<div class="empty">Sin datos de capas.</div>';
      return;
    }
    const max = Math.max(...layers.map((row) => Number(row.n || 0)), 1);
    root.innerHTML = layers.map((row) => {
      const layer = Number(row.capa || 0);
      const name = LAYER_NAMES[layer] || `Capa ${layer}`;
      return `<div class="layer-row">
        <span class="layer-name">${layer || '—'}</span>
        <div><div class="layer-track"><div class="layer-fill" style="width:${(Number(row.n) / max) * 100}%"></div></div>
        <div class="tiny muted">${esc(name)}</div></div>
        <span class="layer-num">${esc(row.n)}</span>
      </div>`;
    }).join('');
  }

  function renderJournalDecisions() {
    const root = $('decisions-table');
    if (!root) return;
    const all = (Store.journal?.decisions) || [];
    const query = Store.journalSearch.trim().toLowerCase();
    const rows = all.filter((row) => {
      if (Store.journalFilter === 'yes' && !row.operar) return false;
      if (Store.journalFilter === 'no' && row.operar) return false;
      if (query && !(`${row.symbol} ${row.motivo}`.toLowerCase().includes(query))) return false;
      return true;
    });
    if (!rows.length) {
      root.innerHTML = '<div class="empty"><strong>Sin decisiones</strong>No hay filas con estos filtros.</div>';
      return;
    }
    root.innerHTML = `<table class="data">
      <thead><tr><th>Hora</th><th>Símbolo</th><th>Resultado</th><th>Capa</th><th>Score</th><th>Divergencia</th><th>Motivo</th></tr></thead><tbody>
      ${rows.map((row) => `<tr class="clickable" data-decision-id="${row.id}">
        <td class="num">${esc(fmtDateTime(row.ts))}</td>
        <td><span class="symbol-chip">${esc(row.symbol)}</span></td>
        <td>${row.operar ? '<span class="pill pill-green">operar</span>' : '<span class="pill pill-quiet">veto</span>'}</td>
        <td>${row.capa ? `<span title="${esc(LAYER_NAMES[row.capa] || '')}">${esc(row.capa)}</span>` : '—'}</td>
        <td class="num">${row.score != null ? esc(Number(row.score).toFixed(1)) : '—'}</td>
        <td class="num">${row.divergencia != null ? esc(Number(row.divergencia).toFixed(1)) : '—'}</td>
        <td class="wrap" title="${esc(row.motivo || '')}">${esc(row.motivo || '—')}</td>
      </tr>`).join('')}
      </tbody></table>`;
  }

  function renderJournalTrades() {
    const root = $('trades-table');
    if (!root) return;
    const rows = (Store.journal?.trades) || Store.trades || [];
    if (!rows.length) {
      root.innerHTML = '<div class="empty"><strong>Sin trades</strong>El journal no ha registrado operaciones cerradas.</div>';
      return;
    }
    root.innerHTML = `<table class="data">
      <thead><tr><th>Apertura</th><th>Símbolo</th><th>Dir</th><th>Vol</th><th>PnL</th><th>Resultado</th></tr></thead><tbody>
      ${rows.slice(0, 25).map((row) => {
        const pnl = Number(row.pnl || 0);
        return `<tr>
          <td class="num">${esc(fmtDateTime(row.ts_open))}</td>
          <td><span class="symbol-chip">${esc(row.symbol)}</span></td>
          <td><span class="dir ${row.direction === 'LONG' ? 'long' : 'short'}">${esc(row.direction || '—')}</span></td>
          <td class="num">${esc(row.volume ?? '—')}</td>
          <td class="num ${pnl >= 0 ? 'green' : 'red'}">${esc(signedMoney(pnl))}</td>
          <td>${esc(row.result || '—')}</td>
        </tr>`;
      }).join('')}
      </tbody></table>`;
  }

  function renderJournalAlerts() {
    const root = $('journal-alerts');
    if (!root) return;
    const alerts = Store.journal?.alerts || Store.alerts || [];
    if (!alerts.length) {
      root.innerHTML = '<div class="empty">Sin alertas registradas.</div>';
      return;
    }
    root.innerHTML = alerts.slice(0, 30).map((alert) => alertRow(alert)).join('');
  }

  async function openDecision(id) {
    openModal('Decisión', 'Cargando detalle…', '<div class="skeleton" style="height:180px"></div>');
    try {
      const row = await api(`/api/decisions/${id}`, { timeout: 12000 });
      const agents = Object.keys(AGENT_LABELS).filter((key) => row[key] && Object.keys(row[key]).length);
      const body = `
        <div class="detail-block">
          <div class="detail-kpis">
            <div class="detail-kpi"><div class="k">Símbolo</div><div class="v">${esc(row.symbol)}</div></div>
            <div class="detail-kpi"><div class="k">Operar</div><div class="v ${row.operar ? 'green' : 'amber'}">${row.operar ? 'sí' : 'no'}</div></div>
            <div class="detail-kpi"><div class="k">Capa</div><div class="v">${esc(row.capa ?? '—')} ${row.capa ? '· ' + esc(LAYER_NAMES[row.capa] || '') : ''}</div></div>
            <div class="detail-kpi"><div class="k">Score</div><div class="v">${row.score != null ? esc(Number(row.score).toFixed(1)) : '—'}</div></div>
          </div>
        </div>
        <div class="detail-block"><h3>Motivo del consenso</h3><div class="agent-card"><div class="kv"><span class="k">Motivo</span><span class="v">${esc(row.motivo || '—')}</span><span class="k">Divergencia</span><span class="v">${row.divergencia != null ? esc(row.divergencia) : '—'}</span><span class="k">Dirección</span><span class="v">${esc(row.direction || '—')}</span><span class="k">Fecha</span><span class="v">${esc(fmtDateTime(row.ts))}</span></div></div></div>
        <div class="detail-block"><h3>Agentes</h3><div class="agent-grid">${agents.map((key) => agentCard(key, row[key])).join('')}</div></div>
      `;
      openModal(`${row.symbol} · decisión #${row.id}`, row.operar ? 'El consenso autorizó operar' : `Veto en capa ${row.capa || '—'}`, body);
    } catch (error) {
      toast('No se pudo cargar la decisión', String(error.message || error), 'error');
      closeModal();
    }
  }

  function agentCard(key, value) {
    const keysByAgent = {
      agent_trader: ['sesgo', 'confianza', 'razon_principal', 'horizonte', '_variant'],
      agent_fundamental: ['veredicto', 'confianza', 'razon', 'catalizador_principal', 'bloqueado_por_noticia'],
      agent_technical: ['direccion', 'entrada', 'stop_loss', 'take_profit', 'probabilidad_estimada', 'patron', 'razon'],
      agent_adversary: ['objecion_valida', 'gravedad', 'objecion_principal', '_variant'],
      agent_htf: ['recomendacion', 'probabilidad_continuacion', 'calidad_entrada', 'razon'],
      agent_strategies: ['strategy', 'consensus', 'signals'],
      prompt_variants: [],
    };
    const keys = keysByAgent[key] || Object.keys(value || {}).slice(0, 8);
    const flat = (val) => {
      if (val === null || val === undefined) return '—';
      if (typeof val === 'object') return JSON.stringify(val);
      return String(val);
    };
    const rows = keys
      .filter((k) => value && value[k] !== undefined && value[k] !== null && value[k] !== '')
      .map((k) => `<span class="k">${esc(k)}</span><span class="v">${esc(flat(value[k]))}</span>`).join('');
    const json = esc(JSON.stringify(value, null, 2));
    return `<div class="agent-card"><h4>${esc(AGENT_LABELS[key] || key)}</h4>
      <div class="kv">${rows || '<span class="k">sin datos</span><span class="v">—</span>'}</div>
      <details><summary class="tiny muted" style="cursor:pointer;margin-top:6px">JSON</summary><pre class="agent-json">${json}</pre></details>
    </div>`;
  }

  /* ═══════════════════════════════════════════════════════════
     Mercado
     ═══════════════════════════════════════════════════════════ */

  function availableTimeframes(symbol) {
    const row = (Store.symbols || []).find((item) => item.symbol === symbol);
    return (row && row.timeframes) || (Store.market && Store.market.symbol === symbol ? Store.market.available_timeframes : []) || [];
  }

  function chooseTimeframe(symbol) {
    const available = availableTimeframes(symbol);
    if (available.length && !available.includes(Store.marketTf)) Store.marketTf = available.includes('H1') ? 'H1' : available[0];
  }

  function ensureMarket() {
    chooseTimeframe(Store.marketSymbol);
    if (!Store.market) loadMarket();
    else renderMarket();
    loadMarketMeta();
  }

  async function loadMarketMeta() {
    if (!Store.backtests.length) {
      try { Store.backtests = await api('/api/backtests', { timeout: 12000 }); } catch { /* noop */ }
    }
    if (!Store.strategies.length) {
      try {
        const data = await api('/api/strategies', { timeout: 12000 });
        Store.strategies = data.strategies || [];
        Store.validated = data.validated || [];
      } catch { /* noop */ }
    }
    if (Store.currentView === 'market') renderMarketMeta();
  }

  async function loadMarket() {
    if (Store.loading.market) return;
    Store.loading.market = true;
    const updated = $('market-updated');
    if (updated) updated.textContent = 'cargando…';
    try {
      const data = await api(`/api/market/${encodeURIComponent(Store.marketSymbol)}?tf=${encodeURIComponent(Store.marketTf)}&limit=220`, { timeout: 20000 });
      Store.market = data;
      Store.marketTf = data.timeframe;
      renderMarket();
    } catch (error) {
      Store.market = null;
      renderMarket();
      toast('No se pudo cargar el mercado', String(error.message || error), 'error');
      if (updated) updated.textContent = 'sin datos';
    } finally {
      Store.loading.market = false;
    }
  }

  function renderMarket() {
    const data = Store.market;
    const updated = $('market-updated');
    if (updated) updated.textContent = data ? `Fuente: ${data.file}` : 'sin datos';
    if (!data) {
      $('market-summary').innerHTML = '';
      $('market-title').textContent = `${Store.marketSymbol} · ${Store.marketTf}`;
      $('market-source').textContent = 'sin datos';
      $('market-stale').innerHTML = '<div class="banner banner-warning"><div class="banner-ico">⚠</div><div><div class="banner-title">Sin CSV para este símbolo/timeframe</div><div class="banner-text">Prueba otro timeframe o símbolo. Los datos en vivo requieren el EA de MT5.</div></div></div>';
      $('market-chart').style.display = 'none';
      $('market-table').innerHTML = '<div class="empty">Sin velas disponibles.</div>';
      const available = availableTimeframes(Store.marketSymbol);
      renderMarketTfs({ available_timeframes: available, timeframe: Store.marketTf });
      renderMarketMeta();
      return;
    }
    $('market-chart').style.display = 'block';
    $('market-title').textContent = `${data.symbol} · ${data.timeframe}`;
    $('market-source').textContent = data.source === 'csv_historico' ? 'CSV histórico' : data.source;
    const stale = $('market-stale');
    if (stale) {
      stale.innerHTML = data.stale
        ? `<div class="banner banner-warning"><div class="banner-ico">⚠</div><div><div class="banner-title">Datos históricos desactualizados</div><div class="banner-text">Última vela: ${esc(fmtDateTime(data.last_time))} · ${esc(data.stale_sec ? Math.round(data.stale_sec / 86400) + ' días' : '—')}. Para precio en vivo necesitas el EA publicando por ZMQ.</div></div></div>`
        : `<div class="banner banner-info"><div class="banner-ico">◫</div><div><div class="banner-title">Datos CSV</div><div class="banner-text">Última vela: ${esc(fmtDateTime(data.last_time))}. No es una cotización en vivo.</div></div></div>`;
    }
    const summary = data.summary || {};
    $('market-summary').innerHTML = [
      ['Último', price(summary.last, data.symbol), 'blue'],
      ['Cambio', (summary.change_pct >= 0 ? '+' : '') + pct(summary.change_pct, 2), summary.change_pct >= 0 ? 'green' : 'red'],
      ['Rango', `${price(summary.low, data.symbol)} — ${price(summary.high, data.symbol)}`, 'purple'],
      ['ATR 14', price(summary.atr14, data.symbol), 'amber'],
      ['SMA 20', price(summary.sma20, data.symbol), 'blue'],
      ['SMA 50', price(summary.sma50, data.symbol), 'blue'],
    ].map(([k, v, cls]) => `<article class="card kpi"><div class="k">${esc(k)}</div><div class="v ${cls}" style="font-size:16px">${esc(v)}</div></article>`).join('');
    drawCandles($('market-chart'), data.candles || [], data.symbol);
    renderMarketTable(data);
    renderMarketTfs(data);
    renderMarketMeta();
  }

  function renderMarketTable(data) {
    const root = $('market-table');
    if (!root) return;
    const rows = (data.candles || []).slice(-15).reverse();
    $('market-table-sub').textContent = `${rows.length} velas · ${data.timeframe}`;
    root.innerHTML = `<table class="data">
      <thead><tr><th>Hora</th><th>Open</th><th>High</th><th>Low</th><th>Close</th></tr></thead><tbody>
      ${rows.map((row) => `<tr>
        <td class="num">${esc(fmtDateTime(row.time))}</td>
        <td class="num">${esc(price(row.open, data.symbol))}</td>
        <td class="num green">${esc(price(row.high, data.symbol))}</td>
        <td class="num red">${esc(price(row.low, data.symbol))}</td>
        <td class="num">${esc(price(row.close, data.symbol))}</td>
      </tr>`).join('')}
      </tbody></table>`;
  }

  function renderMarketTfs(data) {
    const root = $('market-tfs');
    if (!root) return;
    root.innerHTML = (data.available_timeframes || []).map((tf) => `<button data-tf="${esc(tf)}" class="${tf === data.timeframe ? 'is-active' : ''}">${esc(tf)}</button>`).join('');
  }

  function renderMarketMeta() {
    const back = $('backtests-grid');
    if (back) {
      back.innerHTML = Store.backtests.length
        ? Store.backtests.map((item) => {
          if (item.kind === 'grid') {
            const best = item.best || {};
            return `<div class="row-item"><div class="row-main"><div class="row-title">${esc(item.symbol)} · grid</div><div class="row-sub">PF ${esc(best.profit_factor ?? '—')} · ${esc(best.trades ?? '—')} trades · ${esc(item.meta?.mtime ? fmtDateTime(item.meta.mtime) : '')}</div></div><span class="pill pill-quiet">grid</span></div>`;
          }
          const m = item.metrics || {};
          return `<div class="row-item"><div class="row-main"><div class="row-title">${esc(item.symbol)} · backtest</div><div class="row-sub">PF ${esc(m.profit_factor ?? '—')} · hit ${esc(m.hit_rate ?? '—')}% · ${esc(m.trades ?? '—')} trades · DD ${esc(m.max_dd_r ?? '—')}R</div></div><span class="pill ${Number(m.profit_factor) >= 1 ? 'pill-green' : 'pill-red'}">PF ${esc(m.profit_factor ?? '—')}</span></div>`;
        }).join('')
        : '<div class="empty">Sin backtests guardados.</div>';
    }
    const strategies = $('strategies-table');
    if (strategies) {
      const validated = Store.validated || [];
      strategies.innerHTML = `<table class="data">
        <thead><tr><th>Estrategia</th><th>Timeframes</th><th>Descripción</th><th>Validación</th></tr></thead><tbody>
        ${(Store.strategies || []).map((row) => {
          const v = validated.find((item) => row.name.includes(item.strategy.split(' ')[0]));
          return `<tr><td><b>${esc(row.name)}</b></td><td class="num">${esc(row.timeframes)}</td><td class="muted">${esc(row.desc)}</td><td>${v ? `<span class="pill pill-green">PF ${esc(v.profit_factor)} · ${esc(v.symbol)}</span>` : '<span class="pill pill-quiet">—</span>'}</td></tr>`;
        }).join('')}
        </tbody></table>`;
    }
  }

  /* ═══════════════════════════════════════════════════════════
     Sistema
     ═══════════════════════════════════════════════════════════ */

  function ensureSystem() {
    renderSystem();
    loadSystem();
    loadLogs();
  }

  async function loadSystem() {
    if (Store.loading.system) return;
    Store.loading.system = true;
    try {
      const [health, config] = await Promise.all([
        api('/api/health', { timeout: 12000 }),
        api('/api/config', { timeout: 12000 }),
      ]);
      Store.health = health || Store.health;
      Store.config = config || Store.config;
      renderSystem();
      renderChrome();
    } catch (error) {
      toast('No se pudo cargar el sistema', String(error.message || error), 'error');
    } finally {
      Store.loading.system = false;
    }
  }

  function renderSystem() {
    const health = Store.health || {};
    const db = health.db || {};
    const files = health.files || {};
    const sources = health.news?.sources || Store.news?.health?.sources || {};
    const calendar = sources.calendar || {};
    const google = sources.google_news || {};
    const cards = $('system-cards');
    const eaInfo = eaStatusInfo();
    const apiOk = health.api?.status === 'ok';
    const monitor = health.ea?.monitor || {};
    if (cards) {
      cards.innerHTML = [
        ['API', apiOk ? 'OK' : 'degradada', apiOk ? 'green' : 'red', `uptime ${Math.floor((health.api?.uptime_sec || health.uptime_sec || 0) / 60)} min`],
        ['EA / MT5', eaInfo.value, eaInfo.status === 'ok' ? 'green' : eaInfo.status === 'warn' ? 'amber' : 'red',
          eaInfo.age != null ? `hb ${timeAgo(new Date(Date.now() - eaInfo.age * 1000))}` : (monitor.running ? 'monitor ZMQ escuchando' : 'sin heartbeat')],
        ['Calendario', statusText(calendar.status), calendar.status === 'ok' ? 'green' : 'amber', `${calendar.count || 0} eventos`],
        ['Titulares', statusText(google.status), google.status === 'ok' ? 'green' : 'amber', `${google.count || 0} items`],
        ['Journal', String(db.decisions ?? 0), 'blue', `${db.alerts ?? 0} alertas · ${db.equity_snapshots ?? 0} snapshots`],
        ['Orquestador', files.orchestrator_log?.age_sec != null ? timeAgo(new Date(Date.now() - files.orchestrator_log.age_sec * 1000)) : '—', files.orchestrator_log?.age_sec < 1200 ? 'green' : 'amber', 'último log'],
        ['Telegram', health.telegram?.enabled ? 'activo' : health.telegram?.configured ? 'desactivado' : 'sin configurar', health.telegram?.enabled ? 'green' : 'amber', `${health.telegram?.sent ?? 0} enviados · ${health.telegram?.queue ?? 0} en cola`],
        ['LLM router', `${health.llm?.available_providers ?? 0}/${health.llm?.provider_count ?? 0}`, (health.llm?.available_providers ?? 0) > 0 ? 'green' : 'amber', `${health.llm?.total_calls ?? 0} llamadas · ${health.llm?.prompt_tokens ?? 0}+${health.llm?.completion_tokens ?? 0} tokens`],
      ].map(([k, v, cls, s]) => `<article class="card kpi"><div class="k">${esc(k)}</div><div class="v ${cls}" style="font-size:17px">${esc(v)}</div><div class="s">${esc(s)}</div></article>`).join('');
    }
    const banner = $('system-banner');
    if (banner) {
      const reasons = health.status_reasons || [];
      banner.innerHTML = reasons.length
        ? `<div class="banner banner-warning"><div class="banner-ico">⚠</div><div><div class="banner-title">Estado del sistema: ${esc(health.status || 'degraded')}</div><div class="banner-text">${reasons.map((reason) => `• ${esc(reason)}`).join('<br>')}</div></div></div>`
        : '<div class="banner banner-info"><div class="banner-ico">✓</div><div><div class="banner-title">Sistema operativo</div><div class="banner-text">API, EA y fuentes de noticias sin incidencias reportadas.</div></div></div>';
    }
    renderLLMProviders();
    renderConfigTable();
    renderAnalysis();
  }

  function renderLLMProviders() {
    const root = $('llm-providers');
    const summary = $('llm-summary');
    if (!root) return;
    const llm = Store.health?.llm || {};
    const providers = llm.providers || [];
    if (summary) {
      summary.textContent = llm.provider_count
        ? `${llm.available_providers}/${llm.provider_count} disponibles · ${llm.total_calls ?? 0} llamadas`
        : 'sin proveedores';
    }
    if (!providers.length) {
      root.innerHTML = '<div class="empty"><strong>Sin proveedores LLM</strong>Configura LLM_PROVIDER_1_* en .env. Ver docs/LLM_ROUTER.md.</div>';
      return;
    }
    root.innerHTML = `<table class="data">
      <thead><tr><th>Proveedor</th><th>Modelo</th><th>Prio</th><th>Claves</th><th>Llamadas</th><th>Tokens in/out</th><th>Estado</th></tr></thead><tbody>
      ${providers.map((provider) => {
        const available = Number(provider.available_keys || 0);
        const cooling = (provider.key_slots || []).filter((slot) => Number(slot.cooldown_sec) > 0).length;
        const state = available > 0 ? 'disponible' : cooling > 0 ? `cooldown ${Math.max(...(provider.key_slots || []).map((slot) => Number(slot.cooldown_sec) || 0))}s` : 'sin claves';
        const cls = available > 0 ? 'green' : 'amber';
        return `<tr>
          <td><b>${esc(provider.name)}</b></td>
          <td class="mono tiny">${esc(provider.model)}</td>
          <td class="num">${esc(provider.priority)}</td>
          <td class="num">${available}/${provider.keys}</td>
          <td class="num">${esc(provider.calls ?? 0)}</td>
          <td class="num">${esc(provider.prompt_tokens ?? 0)} / ${esc(provider.completion_tokens ?? 0)}</td>
          <td class="${cls}">${esc(state)}${provider.last_error ? ` · ${esc(String(provider.last_error).slice(0, 45))}` : ''}</td>
        </tr>`;
      }).join('')}
      </tbody></table>`;
  }

  function renderConfigTable() {
    const root = $('config-table');
    if (!root) return;
    const config = Store.config || {};
    const rows = [];
    const walk = (obj, prefix = '') => {
      Object.entries(obj || {}).forEach(([key, value]) => {
        const label = prefix ? `${prefix}.${key}` : key;
        if (value && typeof value === 'object' && !Array.isArray(value)) walk(value, label);
        else rows.push([label, Array.isArray(value) ? value.join(', ') : typeof value === 'boolean' ? (value ? 'sí' : 'no') : value]);
      });
    };
    walk(config);
    root.innerHTML = `<table class="data"><thead><tr><th>Parámetro</th><th>Valor</th></tr></thead><tbody>
      ${rows.map(([k, v]) => `<tr><td class="muted">${esc(k)}</td><td class="num">${esc(v)}</td></tr>`).join('')}
    </tbody></table>`;
  }

  function renderAnalysis() {
    const root = $('analysis-panel');
    if (!root) return;
    const items = [
      ['Módulo único', 'news_feed.py concentra calendario, titulares, sentimiento, veto y salud. Antes había 3 rutas duplicadas y el orquestador usaba un stub sin titulares.'],
      ['UTC correcto', 'ForexFactory entrega offsets (p. ej. -05:00). Antes se recortaba el offset y la ventana de noticias se desplazaba 5 horas.'],
      ['Sin bloqueos de 10 s', 'biquote tenía timeout de 10 s por símbolo; ahora hay caché en memoria + disco, timeouts de 8 s y backoff de 60 s.'],
      ['Titulares reales', 'Google News RSS vía requests + feedparser; Finnhub opcional. Deduplicación por similitud y score de relevancia por activo.'],
      ['Sentimiento etiquetado', 'lexicon-v1 sobre titulares, con etiqueta de heurístico y sin usarlo como veto. No requiere API de pago.'],
      ['Veto explícito', 'El orquestador comprueba ±15 min antes de llamar al LLM. El flag bloqueado_por_noticia se normaliza para no vetar por falta de datos.'],
      ['Índices corregidos', 'GER30→EUR, UK100→GBP, JP225→JPY. El mapeo anterior usaba DE/GB/JP y nunca casaba con el calendario.'],
      ['Telemetría visible', 'Estado, latencia, última OK y errores de cada fuente se muestran en Noticias y Sistema.'],
    ];
    root.innerHTML = items.map(([title, text]) => `<div class="analysis-item"><span class="ok">✓</span><div><b>${esc(title)}.</b> ${esc(text)}</div></div>`).join('');
  }

  async function loadLogs() {
    const name = $('log-service')?.value || 'orchestrator';
    const lines = Number($('log-lines')?.value || 200);
    const output = $('log-output');
    if (output) output.textContent = 'Cargando…';
    try {
      const data = await api(`/api/logs?name=${encodeURIComponent(name)}&lines=${lines}`, { timeout: 12000 });
      if (output) {
        output.textContent = (data.lines || []).join('\n') || 'Log vacío.';
        output.scrollTop = output.scrollHeight;
      }
    } catch (error) {
      if (output) output.textContent = `No se pudo cargar el log: ${error.message || error}`;
    }
  }

  /* ═══════════════════════════════════════════════════════════
     Alertas / drawer / modal
     ═══════════════════════════════════════════════════════════ */

  function alertRow(alert) {
    const severity = alert.severity || 'INFO';
    const data = parseMaybe(alert.data);
    const dir = alert.direction || data.direction || data.direccion;
    const icon = severity === 'CRITICAL' ? '⛔' : alert.tipo === 'opportunity' ? '◎' : alert.tipo === 'risk' ? '⚠' : '•';
    const cls = severity === 'CRITICAL' ? 'critical' : alert.tipo === 'opportunity' ? 'opportunity' : '';
    return `<div class="row-item alert-row ${cls} ${alert.leida ? '' : 'unread'}" data-alert-id="${alert.id}">
      <span class="banner-ico" style="font-size:14px">${icon}</span>
      <div class="row-main">
        <div class="row-title">${alert.symbol ? `<span class="symbol-chip">${esc(alert.symbol)}</span> ` : ''}${dir ? `<span class="dir ${dir === 'LONG' ? 'long' : 'short'}">${esc(dir)}</span> ` : ''}${esc(alert.message || alert.tipo || 'Alerta')}</div>
        <div class="row-sub">${esc(alert.tipo || '')} · ${esc(severity)} · ${esc(timeAgo(alert.ts))}</div>
      </div>
      <div class="row-side"><span class="row-time">${esc(fmtTime(alert.ts))}</span></div>
    </div>`;
  }

  function renderDrawerAlerts() {
    const root = $('drawer-alerts');
    if (!root) return;
    const alerts = Store.alerts || [];
    if (!alerts.length) {
      root.innerHTML = '<div class="empty"><strong>Sin alertas</strong>El orquestador no ha registrado eventos.</div>';
      return;
    }
    root.innerHTML = alerts.map((alert) => alertRow(alert)).join('');
    $('drawer-sub').textContent = `${alerts.filter((a) => !a.leida).length} sin leer · ${alerts.length} recientes`;
  }

  function openDrawer() {
    $('alert-drawer').classList.add('is-open');
    $('alert-drawer').setAttribute('aria-hidden', 'false');
    $('drawer-backdrop').hidden = false;
    renderDrawerAlerts();
  }

  function closeDrawer() {
    $('alert-drawer').classList.remove('is-open');
    $('alert-drawer').setAttribute('aria-hidden', 'true');
    $('drawer-backdrop').hidden = true;
  }

  async function markAlertRead(id) {
    try {
      await fetch(`/api/alerts/${id}/read`, { method: 'POST' });
      const alert = Store.alerts.find((a) => a.id === id);
      if (alert) alert.leida = 1;
      renderChrome();
      renderDrawerAlerts();
      renderOverviewAlerts();
    } catch { /* noop */ }
  }

  async function markAllAlerts() {
    try {
      await fetch('/api/alerts/read-all', { method: 'POST' });
      Store.alerts.forEach((a) => { a.leida = 1; });
      renderChrome(); renderDrawerAlerts(); renderOverviewAlerts();
      toast('Alertas marcadas como leídas', '', 'success', 2200);
    } catch { /* noop */ }
  }

  async function clearAlerts() {
    try {
      await fetch('/api/alerts/clear', { method: 'POST' });
      Store.alerts = Store.alerts.filter((a) => !a.leida);
      renderChrome(); renderDrawerAlerts(); renderOverviewAlerts();
      toast('Alertas leídas eliminadas', '', 'success', 2200);
    } catch { /* noop */ }
  }

  function openModal(title, subtitle, html) {
    $('modal-title').textContent = title;
    $('modal-sub').textContent = subtitle || '';
    $('modal-body').innerHTML = html;
    $('modal-root').hidden = false;
    $('modal-body').scrollTop = 0;
  }

  function closeModal() {
    $('modal-root').hidden = true;
  }

  /* ═══════════════════════════════════════════════════════════
     Gráficos canvas
     ═══════════════════════════════════════════════════════════ */

  function setupCanvas(canvas) {
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(10, rect.width);
    const height = Math.max(10, rect.height);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    return { ctx, width, height };
  }

  function drawSpark(canvas, values) {
    const setup = setupCanvas(canvas);
    if (!setup) return;
    const { ctx, width, height } = setup;
    if (!values || values.length < 2) {
      ctx.fillStyle = '#63788f';
      ctx.font = '11px system-ui';
      ctx.fillText('Sin historial de equity', 10, height / 2);
      return;
    }
    const min = Math.min(...values), max = Math.max(...values);
    const span = max - min || 1;
    const pad = 6;
    const x = (i) => pad + (i / (values.length - 1)) * (width - pad * 2);
    const y = (v) => pad + (1 - (v - min) / span) * (height - pad * 2);
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, 'rgba(84,169,255,.30)');
    gradient.addColorStop(1, 'rgba(84,169,255,0)');
    ctx.beginPath();
    values.forEach((v, i) => { if (i === 0) ctx.moveTo(x(i), y(v)); else ctx.lineTo(x(i), y(v)); });
    ctx.lineTo(x(values.length - 1), height - pad);
    ctx.lineTo(x(0), height - pad);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();
    ctx.beginPath();
    values.forEach((v, i) => { if (i === 0) ctx.moveTo(x(i), y(v)); else ctx.lineTo(x(i), y(v)); });
    ctx.strokeStyle = '#54a9ff';
    ctx.lineWidth = 1.8;
    ctx.stroke();
    const last = values[values.length - 1];
    ctx.beginPath();
    ctx.arc(x(values.length - 1), y(last), 2.5, 0, Math.PI * 2);
    ctx.fillStyle = '#2ee6a6';
    ctx.fill();
  }

  function drawLineChart(canvas, rows, options = {}) {
    const setup = setupCanvas(canvas);
    if (!setup) return;
    const { ctx, width, height } = setup;
    const valueOf = options.valueOf || ((row) => Number(row));
    const values = rows.map(valueOf).filter((n) => Number.isFinite(n));
    if (values.length < 2) {
      ctx.fillStyle = '#63788f';
      ctx.font = '11px system-ui';
      ctx.fillText('Sin datos suficientes', 12, height / 2);
      return;
    }
    const pad = { l: 50, r: 12, t: 12, b: 22 };
    const plotW = width - pad.l - pad.r;
    const plotH = height - pad.t - pad.b;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || Math.max(1, Math.abs(max) * 0.001);
    const low = min - span * 0.08;
    const high = max + span * 0.08;
    const x = (i) => pad.l + (i / (values.length - 1)) * plotW;
    const y = (v) => pad.t + (1 - (v - low) / (high - low)) * plotH;

    ctx.font = '9.5px ui-monospace, monospace';
    ctx.fillStyle = '#63788f';
    ctx.strokeStyle = 'rgba(29,43,63,.8)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i += 1) {
      const gy = pad.t + (i / 4) * plotH;
      ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(width - pad.r, gy); ctx.stroke();
      const value = high - (i / 4) * (high - low);
      ctx.fillText(money(value, 0), 4, gy + 3);
    }
    const gradient = ctx.createLinearGradient(0, pad.t, 0, height - pad.b);
    gradient.addColorStop(0, options.fill || 'rgba(84,169,255,.15)');
    gradient.addColorStop(1, 'rgba(84,169,255,0)');

    const trace = () => {
      ctx.beginPath();
      values.forEach((v, i) => { if (i === 0) ctx.moveTo(x(i), y(v)); else ctx.lineTo(x(i), y(v)); });
    };
    trace();
    ctx.lineTo(x(values.length - 1), height - pad.b);
    ctx.lineTo(x(0), height - pad.b);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    if (options.secondLine && rows.length) {
      const secondValues = rows.map(options.secondLine.valueOf).filter((n) => Number.isFinite(n));
      if (secondValues.length === values.length) {
        ctx.beginPath();
        secondValues.forEach((v, i) => { if (i === 0) ctx.moveTo(x(i), y(v)); else ctx.lineTo(x(i), y(v)); });
        ctx.strokeStyle = options.secondLine.color;
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    trace();
    ctx.strokeStyle = options.color || '#54a9ff';
    ctx.lineWidth = 2;
    ctx.stroke();

    const last = values[values.length - 1];
    ctx.beginPath();
    ctx.arc(x(values.length - 1), y(last), 3, 0, Math.PI * 2);
    ctx.fillStyle = options.color || '#54a9ff';
    ctx.fill();

    const label = options.labelOf || (() => '');
    const indexes = [0, Math.floor((rows.length - 1) / 2), rows.length - 1];
    ctx.fillStyle = '#63788f';
    ctx.font = '9.5px ui-monospace, monospace';
    indexes.forEach((idx) => {
      const text = label(rows[idx]);
      if (!text) return;
      const tw = ctx.measureText(text).width;
      let tx = x(idx) - tw / 2;
      tx = clamp(tx, 2, width - tw - 2);
      ctx.fillText(text, tx, height - 6);
    });
  }

  function drawCandles(canvas, candles, symbol) {
    const setup = setupCanvas(canvas);
    if (!setup) return;
    const { ctx, width, height } = setup;
    if (!candles || candles.length < 2) {
      ctx.fillStyle = '#63788f';
      ctx.font = '11px system-ui';
      ctx.fillText('Sin velas suficientes', 12, height / 2);
      return;
    }
    const pad = { l: 10, r: 66, t: 12, b: 20 };
    const volH = Math.min(55, height * 0.16);
    const priceH = height - pad.t - pad.b - volH - 8;
    const plotW = width - pad.l - pad.r;
    const lows = candles.map((c) => c.low);
    const highs = candles.map((c) => c.high);
    const min = Math.min(...lows);
    const max = Math.max(...highs);
    const span = max - min || 1;
    const low = min - span * 0.04;
    const high = max + span * 0.04;
    const y = (v) => pad.t + (1 - (v - low) / (high - low)) * priceH;
    const step = plotW / candles.length;
    const bodyW = Math.max(1, Math.min(8, step * 0.62));
    const maxVol = Math.max(...candles.map((c) => Number(c.volume || 0)), 1);

    ctx.strokeStyle = 'rgba(29,43,63,.8)';
    ctx.fillStyle = '#63788f';
    ctx.font = '9.5px ui-monospace, monospace';
    for (let i = 0; i <= 4; i += 1) {
      const gy = pad.t + (i / 4) * priceH;
      ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(width - pad.r, gy); ctx.stroke();
      ctx.fillText(price(high - (i / 4) * (high - low), symbol), width - pad.r + 6, gy + 3);
    }

    candles.forEach((candle, i) => {
      const cx = pad.l + i * step + step / 2;
      const up = candle.close >= candle.open;
      const color = up ? '#2ee6a6' : '#ff6076';
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(cx, y(candle.high));
      ctx.lineTo(cx, y(candle.low));
      ctx.stroke();
      const top = y(Math.max(candle.open, candle.close));
      const bottom = y(Math.min(candle.open, candle.close));
      ctx.fillRect(cx - bodyW / 2, top, bodyW, Math.max(1, bottom - top));
      const volTop = height - pad.b - (Number(candle.volume || 0) / maxVol) * volH;
      ctx.globalAlpha = 0.32;
      ctx.fillRect(cx - bodyW / 2, volTop, bodyW, height - pad.b - volTop);
      ctx.globalAlpha = 1;
    });

    const last = candles[candles.length - 1];
    const lastY = y(last.close);
    ctx.strokeStyle = 'rgba(84,169,255,.55)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(pad.l, lastY); ctx.lineTo(width - pad.r, lastY); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#54a9ff';
    ctx.fillRect(width - pad.r + 2, lastY - 8, 60, 16);
    ctx.fillStyle = '#04121f';
    ctx.font = 'bold 9.5px ui-monospace, monospace';
    ctx.fillText(price(last.close, symbol), width - pad.r + 6, lastY + 3.5);

    ctx.fillStyle = '#63788f';
    ctx.font = '9.5px ui-monospace, monospace';
    [0, Math.floor(candles.length / 2), candles.length - 1].forEach((idx) => {
      const text = fmtDateTime(candles[idx].time);
      const tw = ctx.measureText(text).width;
      let tx = pad.l + idx * step + step / 2 - tw / 2;
      tx = clamp(tx, 2, width - pad.r - tw);
      ctx.fillText(text, tx, height - 5);
    });
  }

  /* ═══════════════════════════════════════════════════════════
     Poblado de selects
     ═══════════════════════════════════════════════════════════ */

  function populateSymbolSelects() {
    const newsSelect = $('news-symbol');
    const marketSelect = $('market-symbol');
    const all = Store.symbols && Store.symbols.length
      ? Store.symbols
      : (Store.config.symbols || DEFAULT_CONFIG.symbols).map((symbol) => ({ symbol, main: true, group: 'forex' }));
    const main = all.filter((row) => row.main);
    const rest = all.filter((row) => !row.main);
    const build = (select, includeAll) => {
      if (!select) return;
      const current = select.value || (select === newsSelect ? Store.newsSymbol : Store.marketSymbol);
      const options = [];
      if (main.length) {
        options.push('<optgroup label="Principales">');
        main.forEach((row) => options.push(`<option value="${esc(row.symbol)}">${esc(row.symbol)}</option>`));
        options.push('</optgroup>');
      }
      if (includeAll && rest.length) {
        const groups = {};
        rest.forEach((row) => { (groups[row.group] ||= []).push(row); });
        Object.entries(groups).forEach(([group, rows]) => {
          options.push(`<optgroup label="${esc(group)}">`);
          rows.forEach((row) => options.push(`<option value="${esc(row.symbol)}">${esc(row.symbol)}</option>`));
          options.push('</optgroup>');
        });
      }
      select.innerHTML = options.join('');
      select.value = current;
      if (!select.value) select.value = main[0]?.symbol || all[0]?.symbol || 'XAUUSD';
    };
    build(newsSelect, true);
    build(marketSelect, true);
  }

  /* ═══════════════════════════════════════════════════════════
     Eventos
     ═══════════════════════════════════════════════════════════ */

  function bindEvents() {
    $$('.nav-item').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.view)));
    document.addEventListener('click', (event) => {
      const goto = event.target.closest('[data-goto]');
      if (goto) { switchView(goto.dataset.goto); return; }
      const close = event.target.closest('[data-close-modal]');
      if (close) { closeModal(); return; }
      const copy = event.target.closest('[data-copy-opp]');
      if (copy) { copyOpp(copy.dataset.copyOpp); return; }
      const detail = event.target.closest('[data-detail-opp]');
      if (detail) { openOpp(detail.dataset.detailOpp); return; }
      const tf = event.target.closest('[data-tf]');
      if (tf) {
        Store.marketTf = tf.dataset.tf;
        loadMarket();
        return;
      }
      const alert = event.target.closest('[data-alert-id]');
      if (alert) {
        const id = Number(alert.dataset.alertId);
        const row = Store.alerts.find((a) => a.id === id);
        if (row?.tipo === 'opportunity') {
          const op = getOpps().find((item) => item.source === 'alert' && item.id === id);
          if (op) { openOpp(op.key); return; }
        }
        markAlertRead(id);
      }
    });

    $('refresh-btn').addEventListener('click', refreshCurrent);
    $('sound-btn').addEventListener('click', () => setSound(!Store.sound));
    $('alerts-btn').addEventListener('click', openDrawer);
    $('drawer-close').addEventListener('click', closeDrawer);
    $('drawer-backdrop').addEventListener('click', closeDrawer);
    $('alerts-read-all').addEventListener('click', markAllAlerts);
    $('alerts-clear').addEventListener('click', clearAlerts);
    $('overview-alerts-open').addEventListener('click', openDrawer);
    $('notify-btn').addEventListener('click', async () => {
      if (!('Notification' in window)) { toast('Sin soporte', 'Este navegador no soporta notificaciones.', 'warning'); return; }
      if (Notification.permission === 'granted') { toast('Notificaciones activadas', '', 'success'); return; }
      const permission = await Notification.requestPermission();
      toast(permission === 'granted' ? 'Notificaciones activadas' : 'Notificaciones bloqueadas', '', permission === 'granted' ? 'success' : 'warning');
    });

    $('news-symbol').addEventListener('change', (event) => {
      Store.newsSymbol = event.target.value;
      loadNews(false);
    });
    $('news-impact').addEventListener('change', (event) => { Store.newsImpact = event.target.value; renderCalendar(); });
    $('news-search').addEventListener('input', (event) => { Store.newsSearch = event.target.value; renderCalendar(); renderHeadlines(); });
    $('news-only-symbol').addEventListener('change', (event) => { Store.newsOnlySymbol = event.target.checked; renderCalendar(); });
    $('news-refresh').addEventListener('click', () => loadNews(true));
    $$('#headline-filter button').forEach((button) => button.addEventListener('click', () => {
      Store.headlineSent = button.dataset.sent;
      $$('#headline-filter button').forEach((item) => item.classList.toggle('is-active', item === button));
      renderHeadlines();
    }));

    $('opps-search').addEventListener('input', (event) => { Store.oppsSearch = event.target.value; renderOpps(); });
    $('opps-direction').addEventListener('change', (event) => { Store.oppsDirection = event.target.value; renderOpps(); });
    $('opps-minconf').addEventListener('input', (event) => { Store.oppsMinConf = Number(event.target.value || 0); renderOpps(); });
    $('opps-refresh').addEventListener('click', () => { loadOpps(true); loadNews(false); });

    $('journal-search').addEventListener('input', (event) => { Store.journalSearch = event.target.value; renderJournalDecisions(); });
    $('journal-filter').addEventListener('change', (event) => { Store.journalFilter = event.target.value; renderJournalDecisions(); });
    $('journal-export').addEventListener('click', () => { window.location.href = '/api/export/decisions.csv'; });
    $('decisions-table').addEventListener('click', (event) => {
      const row = event.target.closest('[data-decision-id]');
      if (row) openDecision(row.dataset.decisionId);
    });
    $('overview-decisions').addEventListener('click', (event) => {
      const row = event.target.closest('[data-decision-id]');
      if (row) openDecision(row.dataset.decisionId);
    });

    $('market-symbol').addEventListener('change', (event) => {
      Store.marketSymbol = event.target.value;
      Store.marketTf = 'H1';
      chooseTimeframe(Store.marketSymbol);
      loadMarket();
      renderMarketTfs({ available_timeframes: availableTimeframes(Store.marketSymbol), timeframe: Store.marketTf });
    });
    $('market-refresh').addEventListener('click', loadMarket);

    $('system-reload').addEventListener('click', loadSystem);
    $('log-refresh').addEventListener('click', loadLogs);
    $('log-service').addEventListener('change', loadLogs);
    $('log-lines').addEventListener('change', loadLogs);

    document.addEventListener('keydown', (event) => {
      const tag = (event.target.tagName || '').toLowerCase();
      if (['input', 'select', 'textarea'].includes(tag)) return;
      if (event.key === 'Escape') { closeModal(); closeDrawer(); return; }
      if (event.key === 'r' || event.key === 'R') { refreshCurrent(); return; }
      const map = { '1': 'overview', '2': 'news', '3': 'opportunities', '4': 'journal', '5': 'market', '6': 'system' };
      if (map[event.key]) switchView(map[event.key]);
    });

    window.addEventListener('hashchange', () => {
      const view = (location.hash || '').replace('#', '');
      if (VIEW_META[view] && view !== Store.currentView) switchView(view, false);
    });
    window.addEventListener('resize', () => {
      if (Store.currentView === 'overview') { renderSpark(); renderEquityCanvas(); }
      if (Store.currentView === 'journal') renderJournalChart(Store.journal?.equity || []);
      if (Store.currentView === 'market' && Store.market) drawCandles($('market-chart'), Store.market.candles || [], Store.market.symbol);
    });
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && !Store.wsLive) refreshLight();
    });
  }

  /* ═══════════════════════════════════════════════════════════
     Reloj / countdowns / auto-refresh
     ═══════════════════════════════════════════════════════════ */

  function tick() {
    const now = new Date();
    const local = $('clock-local');
    if (local) local.textContent = now.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const utc = $('clock-utc');
    if (utc) utc.textContent = 'UTC ' + now.toLocaleTimeString('es-ES', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit' });
    const statusLast = $('status-last');
    if (statusLast) statusLast.textContent = Store.lastUpdate ? timeAgo(Store.lastUpdate) : '—';
    $$('[data-countdown]').forEach((element) => {
      element.textContent = countdown(element.dataset.ts);
    });
    if (!Store.wsLive && !document.hidden) {
      Store.lastPoll = Store.lastPoll || 0;
      if (Date.now() - Store.lastPoll > 12000) { Store.lastPoll = Date.now(); refreshLight(); }
    }
  }

  function autoRefreshNews() {
    if (document.hidden || Store.currentView !== 'news' || Store.loading.news) return;
    loadNews(false);
  }

  /* ═══════════════════════════════════════════════════════════
     Init
     ═══════════════════════════════════════════════════════════ */

  function initPWA() {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').catch(() => { /* requiere HTTPS o localhost */ });
    }
    let deferredPrompt = null;
    const installBtn = $('install-btn');
    window.addEventListener('beforeinstallprompt', (event) => {
      event.preventDefault();
      deferredPrompt = event;
      if (installBtn) installBtn.hidden = false;
    });
    installBtn?.addEventListener('click', async () => {
      if (!deferredPrompt) {
        toast('Instalar en el móvil', 'Abre el menú del navegador y elige “Añadir a pantalla de inicio”.', 'info', 7000);
        return;
      }
      deferredPrompt.prompt();
      await deferredPrompt.userChoice.catch(() => null);
      deferredPrompt = null;
      installBtn.hidden = true;
    });
    window.addEventListener('appinstalled', () => {
      if (installBtn) installBtn.hidden = true;
      toast('App instalada', 'FNL:004 ya está en tu pantalla de inicio.', 'success');
    });
  }

  function init() {
    bindEvents();
    initPWA();
    renderChrome();
    setSound(Store.sound);
    // Quita el toast de "sonido desactivado" del arranque.
    const firstToast = $('toasts')?.lastElementChild;
    if (firstToast) setTimeout(() => firstToast.remove(), 50);
    setInterval(tick, 1000);
    setInterval(autoRefreshNews, 90000);
    tick();
    loadInitial();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
