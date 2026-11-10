# Acceso móvil, APK y monetización

> Documento de producto y arquitectura. No es asesoría legal ni financiera.
> Fecha: 2026-11-10.

---

## 1. Veredicto rápido

| Camino | Probabilidad técnica | Esfuerzo | Cuándo usarlo |
|---|---:|---|---|
| **PWA instalable** (implementada) | **99 %** | 1–2 días | Acceso móvil rápido sin tienda. Es lo que ya está en `static/manifest.webmanifest` + `sw.js`. |
| **APK con TWA/Bubblewrap** | **95 %** | 1–3 días | Quieres un `.apk`/`.aab` de tu propia web HTTPS. Es el camino más corto a Android. |
| **APK con Capacitor** | **90 %** | 3–7 días | Necesitas cámara, push nativo, biometría, SQLite local o publicar en Play Store. |
| **App nativa Android/iOS** | **30 %** (no recomendable por ahora) | 4–8 semanas | Solo si el producto crece mucho y necesitas rendimiento/notificaciones avanzadas. |
| **SaaS multi-usuario con licencias** | **80 %** técnico | 4–8 semanas para MVP | Monetizar con suscripciones. No es “una APK”: es backend multi-tenant + auth + pagos. |

La app móvil **no debe ejecutar el sistema de trading**. Debe ser un cliente que consume una API alojada en un servidor con HTTPS. El orquestador, SQLite, el EA y el LLM siguen en el servidor/VPS.

---

## 2. Lo que ya se implementó para móvil

- `static/manifest.webmanifest`: nombre, iconos 192/512, `standalone`, atajos a Noticias, Oportunidades y Journal.
- `static/sw.js`: service worker con shell cacheado; la API siempre intenta red para no mostrar datos de trading viejos como si fueran live.
- `static/icon-192.png` y `static/icon-512.png`.
- Botón “Instalar app” en la barra lateral cuando el navegador soporta `beforeinstallprompt`.
- Metadatos iOS (`apple-mobile-web-app-*`) y `theme-color`.

Para probar en el móvil:

```bash
# En el servidor, escuchar en la red local (solo para pruebas)
uvicorn api_server:app --host 0.0.0.0 --port 8000
# Abrir http://IP_DEL_SERVIDOR:8000 en el móvil
```

Para que la PWA se pueda instalar y el service worker funcione, el navegador exige **HTTPS** (o `localhost`). En producción usa un dominio con Caddy/Nginx y certificado; no publiques HTTP plano.

---

## 3. APK: dos caminos concretos

### Opción A — TWA con Bubblewrap (recomendada)

Requisitos: la PWA ya desplegada en `https://app.tudominio.com`, Node.js y Java/Android SDK.

```bash
npm install -g @bubblewrap/cli
bubblewrap init --manifest https://app.tudominio.com/static/manifest.webmanifest
bubblewrap build
# genera app-release-signed.apk y app-release-bundle.aab
```

Ventajas: reutiliza la misma web, cambios de UI se publican sin re-publicar la APK, experiencia casi nativa. Desventajas: necesita HTTPS y Digital Asset Links (`assetlinks.json`) para que no se vea la barra del navegador.

### Opción B — Capacitor

```bash
npm init -y
npm install @capacitor/core @capacitor/cli @capacitor/android
npx cap init "FNL:004" com.tudominio.fnl004 --web-dir=static
npx cap add android
npx cap open android
# Android Studio → Build → Generate Signed Bundle / APK
```

En `capacitor.config.ts`, apunta `server.url` a la web alojada o copia el frontend dentro de la app. Si la app es solo un contenedor de la web, necesitas:

- API con URL absoluta configurable.
- CORS restringido al dominio de la app.
- Login/token para no exponer el dashboard.
- Push nativo (FCM) si quieres notificaciones fuera de Telegram.

### Firma y distribución

- **APK directo** (web, Telegram, clientes): no requiere Play Store, pero Android avisa de “instalar apps desconocidas”. Firma con keystore y guarda la contraseña.
- **Google Play**: subir `.aab`, cuenta de desarrollador (25 USD único), política de privacidad, data safety, y revisar que no se presente como asesoría financiera.
- **iOS**: TestFlight/App Store requiere cuenta Apple (99 USD/año) y revisión más estricta.

### Qué NO hacer

- No metas el token de Telegram, la API key del LLM ni el `.env` dentro de la APK.
- No ejecutes el orquestador en el teléfono.
- No pongas la API en HTTP abierto a Internet sin autenticación.
- No prometas rentabilidad; la app debe mostrar el disclaimer.

---

## 4. Acceso para terceros: modelos

### Modelo 1 — Web privada + login (más rápido)

- Un dominio, HTTPS, login por email/Google.
- Cada usuario ve su cuenta y sus señales.
- Precio: suscripción mensual.
- Ventaja: no hay APK; se actualiza al instante.
- Riesgo: hay que construir auth, multiusuario y aislamiento de datos.

### Modelo 2 — Telegram como canal de distribución

- El bot ya envía señales completas.
- Un bot por cliente o un canal privado por plan.
- Precio: suscripción al canal.
- Ventaja: llegada inmediata al móvil, sin tienda.
- Riesgo: Telegram no es seguro para secretos; no sustituye al journal ni al dashboard.

### Modelo 3 — APK de marca blanca

- La misma PWA empaquetada por cliente, con su logo/colores.
- Precio: licencia de instalación + soporte.
- Ventaja: percepción de producto propio.
- Riesgo: mantener N versiones; automatiza con flavors/fastlane.

### Modelo 4 — Licencia para empresas de fondeo

- La empresa paga por un panel de administración de sus traders.
- Tú vendes la infraestructura, no las señales.
- Precio: por trader/mes o contrato anual.
- Requisito: multiusuario, roles, reglas por firma, auditoría y SLA.

---

## 5. Licenciamiento técnico

Para cobrar por uso necesitas, como mínimo:

1. **Usuarios**: tabla `users` (email, hash de contraseña, rol, plan, estado).
2. **Sesiones**: JWT corto + refresh token; nunca guardar contraseñas en claro.
3. **Tenants/cuentas**: cada trader tiene una o varias cuentas (`account_id`, firma, tamaño, fase).
4. **Aislamiento**: todas las consultas filtran por `user_id`/`account_id`; el journal actual es de una sola cuenta.
5. **Planes y límites**: `plan`, `max_accounts`, `max_instruments`, `telegram_enabled`, `api_calls`.
6. **Pagos**: Stripe Checkout + webhook; `customer_id`, `subscription_id`, `status`.
7. **Licencias offline** (si hay APK): clave firmada (Ed25519), validación periódica y revocación.
8. **Auditoría**: login, cambios de plan, exportaciones, accesos.
9. **Operación**: backups, logs sin secretos, rate limiting, HTTPS, WAF.
10. **Legal**: términos, privacidad, disclaimer, y revisar si tu país considera “señales” como asesoría financiera.

### Licencia del código

El repo actual dice **MIT**. MIT permite que cualquiera use, modifique y venda el código. Si quieres monetizar:

- Si el repo es público, cualquiera puede clonarlo y competir.
- Cambiar a una licencia **propietaria** o **dual** (open-core) para las partes nuevas.
- No puedes “revocar” MIT sobre lo ya publicado, pero sí cambiar la licencia de versiones nuevas.
- Alternativa: repo privado + SaaS; el código no se distribuye.

---

## 6. Adaptación a cualquier empresa de fondeo

Sí es posible, pero hoy las reglas están en `config.py` como constantes globales. Hay que extraerlas a **perfiles de cuenta**. Esquema propuesto:

```python
# firm_profiles.py (propuesta)
from dataclasses import dataclass

@dataclass(frozen=True)
class FirmProfile:
    firm_id: str
    name: str
    account_size: float
    max_loss_pct: float          # trailing o static
    trailing_dd: bool
    daily_loss_pct: float | None
    consistency_pct: float | None
    risk_per_trade_pct: float
    max_open_risk_pct: float
    max_lot: float
    daily_target_usd: float
    hard_daily_cap_usd: float
    news_blackout_min: int
    sessions: dict
    payout_rules: dict

PROFILES = {
    "fundednext_fnl004_50k": FirmProfile(...),
    "ftmo_swing_100k": FirmProfile(...),
    "topstep_50k": FirmProfile(...),
}
```

Cambios necesarios:

- `profit_tracker.py`: recibir `FirmProfile` en vez de leer constantes globales.
- `fundednext_rules.py`: renombrar a `risk_rules.py` y evaluar el perfil activo.
- `orchestrator.py`: cargar el perfil de la cuenta seleccionada.
- `state_manager.py`: guardar `firm_id`, `account_id`, `account_size`, `phase`.
- `journal.py`: añadir `firm_id` y `account_id` a decisiones/señales.
- Dashboard: selector “Empresa / Tipo de cuenta / Fase” y validación al cambiar.
- Migración: no romper la cuenta actual; `default` = FNL:004 50K.

Lo que **no** se puede resolver solo con configuración:

- APIs de cada firma para leer posiciones/equity (cada una es distinta).
- Reglas ambiguas o que cambian por fase.
- Sincronización con MT5/otra plataforma.
- Responsabilidad legal si el trader pierde la cuenta.

Para un MVP multi-firma: empieza con 2–3 perfiles (FundedNext, FTMO, Topstep), validación manual del tipo de cuenta y el trader seleccionando el perfil. Después automatiza la integración.

---

## 7. Modelo de negocio sugerido

### Precios de referencia (orientativos)

| Plan | Precio | Incluye |
|---|---:|---|
| Starter | 29–49 USD/mes | 1 cuenta, dashboard, journal, noticias, Telegram. |
| Pro | 79–149 USD/mes | 3 cuentas, más símbolos, alertas prioritarias, histórico. |
| Elite / White-label | 299–999 USD/mes | Multi-cuenta, marca propia, soporte, API. |
| Firma de fondeo | 1 000–5 000 USD/mes | Panel de administración, SLA, reglas por firma. |

### Qué vender

- **Análisis y organización**, no “señales mágicas”.
- Ahorro de tiempo: journal automático, auditoría, alertas completas.
- Control de riesgo: un trader que no viola el trailing DD vale más que una señal acertada.
- Multi-firma: un solo panel para varias cuentas.
- Datos y reportes para rendir cuentas.

### Qué evitar

- Garantizar rentabilidad.
- Gestionar dinero de terceros sin licencia.
- Copiar señales de terceros sin licencia.
- Usar marcas de las firmas sin permiso.
- Prometer “cuenta aprobada” o “payout garantizado”.

---

## 8. Roadmap recomendado

| Fase | Entregable | Tiempo |
|---|---|---|
| 0 | PWA + Telegram completo (hecho) | 1–2 días |
| 1 | HTTPS + dominio + login simple + backups | 1 semana |
| 2 | Multi-cuenta + perfiles FundedNext/FTMO/Topstep | 2–3 semanas |
| 3 | Stripe + planes + límites + panel admin | 2–3 semanas |
| 4 | APK TWA con Bubblewrap + firma | 2–4 días |
| 5 | Push nativo / Play Store / white-label | 2–4 semanas |

**Mi recomendación:** no empieces por la APK. Empieza por **PWA + Telegram + login + Stripe**. La APK es un envoltorio de la PWA y se hace en días cuando el producto ya se cobra.

---

## 9. Advertencias finales

- El sistema actual es de **una sola cuenta** y está pensado para uso local.
- El journal SQLite no es multiusuario; no lo expongas a Internet sin autenticación.
- El EA `OrchestratorEA.mq5` conserva una ruta de ejecución; si el producto es “solo señales”, desactívala.
- Revisa los términos de ForexFactory/Google News/Finnhub antes de revender sus datos.
- Consulta a un abogado de tu jurisdicción antes de cobrar por señales o análisis.
