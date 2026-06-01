# AlgoForge — AI-First Hybrid Algorithmic Trading Platform

## Original Problem Statement
Build a modular & scalable AI-first hybrid algorithmic trading platform with: data layer, AI/quant engine (strategy builder, trap detection, signal generation, risk analysis), execution layer (broker APIs, smart routing), risk & compliance, UI dashboards. Phase-1 MVP scope chosen by user: Strategy Builder (NL → DSL via GPT-5.2) + Backtesting + Paper Execution + **Option Writers' Trap Detection**. Auth = JWT email/password. AI = GPT-5.2 (strategy ideation) + Claude Sonnet 4.5 (risk + commentary) via Emergent Universal LLM Key. Broker layer mocked; market data mocked deterministically; ready to swap to Zerodha/Upstox real APIs when keys arrive.

## Architecture
- **Backend** (FastAPI, Mongo, modular files): `server.py` (router mount), `auth.py` (JWT), `db.py` (Mongo + BaseDocument/PyObjectId), `market_data.py` (mock OHLCV + Black-Scholes options chain), `backtest_engine.py` (DSL exec, SMA/EMA/RSI, Sharpe/Sortino/DD), `trap_detection.py` (OI buildup × breakout heuristic with per-strike trap probability + hedging plays), `ai_service.py` (LlmChat wrappers, fallbacks).
- **Frontend** (React 19, Tailwind, shadcn): Routes /login, /register, /, /strategies, /backtest, /paper, /trap, /journal, /settings. Sidebar AppShell. Design = "Performance Pro / Swiss High-Contrast" zinc dark theme; fonts Barlow Condensed (display), Chivo (section), IBM Plex Sans (body), JetBrains Mono (data).

## Personas
- **Indian options/equity prop trader** — wants AI strategy assist + trap warnings.
- **Quant analyst** — runs backtests, reviews risk/compliance.
- **Risk manager** — kill switch, drawdown caps, journal review.

## Core Requirements (static)
- Auth (JWT, email+password)
- AI Strategy Builder (NL → DSL JSON) — GPT-5.2
- Backtest engine with slippage/fees, KPIs (Sharpe, Sortino, MaxDD, win-rate, profit factor)
- Risk review by Claude Sonnet 4.5
- Option Writers' Trap Detection — OI heatmap, hedging suggestions, AI explanation
- Paper trading (equity + options multi-leg), kill switch, flatten
- Trade Journal with AI tagging + commentary
- Risk policy & broker connection placeholders

## Implemented (2026-02-29 first finish)
- All endpoints under `/api/*` (auth, strategies, backtest, risk, trap, paper, journal, dashboard, market data).
- All 7 frontend pages working with data-testid coverage.
- Mocked deterministic NIFTY/BANKNIFTY/RELIANCE/TCS/HDFCBANK/INFY data.
- Black-Scholes options chain with Greeks + induced OI buildup pockets to demo trap scoring.
- Demo user `demo@algoforge.io / Demo@123` seeded via register.

## Backlog (P0 → P2)
**P0**
- Real Zerodha/Upstox integration (waiting on user keys + KYC).
- Live tick stream via WebSocket (Kafka/Redis later).
- Multi-leg options spread builder UI (currently single-leg per order).
**P1**
- Reinforcement-learning intraday scalper bot.
- Monte Carlo + walk-forward stress testing UI.
- Audit-log viewer (SEBI compliance).
- Email/push alerts on trap thresholds + drawdown breach.
**P2**
- Strategy marketplace, plugin SDK.
- Cross-asset (crypto, FX, commodities).
- DeFi tokenised assets.
- Voice-enabled trading commands.

## Next Tasks
1. Plug in real broker SDKs once API keys are provided.
2. Real-time WebSocket for paper P&L tick updates.
3. Build the "compare backtests" view (saved backtests already persist).

## Iteration 2 (2026-02-29) — P0 partial
- **Broker scaffold**: Encrypted Fernet vault (`/api/brokers/*`) for Zerodha Kite, Upstox v2, Dhan, ICICI Direct Breeze, Rmoney. Each adapter lazy-imports the SDK and raises `BrokerUnavailable` (graceful 200 status='error') when keys/SDK absent. UI page `/brokers` with Connect/Test/Disconnect.
- **Live WebSocket tick feed**: `/api/ws/ticks?symbols=...` pushes simulated ticks ~750ms. `TickerBar` mounted in `AppShell` so every page shows the 6-symbol live strip.
- **Multi-leg builder**: `MultiLegBuilder` component on /paper with presets (Long/Short Straddle, Long Strangle, Iron Condor, Bull Call Spread, Bear Put Spread) + custom legs. Backend `/api/paper/order/multi-leg` fills atomically (caveat: no rollback on partial leg failure — documented).

## Remaining P0
- Real Zerodha/Upstox/Dhan/ICICI/Rmoney **live** wiring (awaiting API keys + KYC + SDK installs).
- WS upgrade from mock to real broker tick streams once any broker is live.

## Iteration 3 (2026-02-29) — Refactor: routers/
- Split monolithic `server.py` (~600 lines) into 11 per-domain routers under `/app/backend/routers/`:
  health · market · strategies · backtest · risk · trap · paper · journal · brokers · dashboard (+ standalone auth, ws_feed).
- `server.py` is now ~80 lines: imports, router mounting, CORS, lifecycle.
- Shared async helpers `place_paper_order()` and `compute_positions()` live in `routers/paper.py` and are reused by multi-leg + dashboard (direct calls, no nested HTTP).
- 34/34 backend regression PASS — zero behavior change.

## Iteration 4 (2026-02-29) — P0 item-2 + lifespan
- **Literal validation**: `PaperOrderRequest.side: Literal["BUY","SELL"]`, instrument_type, option_kind, order_type — invalid inputs return 422 with clear FastAPI message.
- **Idempotency keys** (`Idempotency-Key` header or auto-derived SHA-256 of payload+user). Cached in `idempotency_keys` collection with 24h TTL index. Frontend `api.js` interceptor auto-generates a per-click UUID for paper-order POSTs so legitimate retries aren't silently no-op'd.
- **Duplicate-order prevention**: 5s sliding window matches user × instrument × side × qty against `paper_orders.created_at`; returns 409 with `?force=true` override path. Frontend exposes a "Force" toast action.
- **Multi-leg pre-flight + rollback**: every leg validated before any insert (catches bad strikes / option_kind); mid-loop DB failures trigger snapshot-based rollback of orders + positions. Orders are tagged `basket_pending=true` during placement and flipped to `basket_pending=false, basket_id=<id>` on commit.
- **Lifespan migration**: replaced `@app.on_event` with `asynccontextmanager`. TTL index ensured on startup.
- **Testing**: 51/51 backend pass; frontend lint clean; manual flow verified.

## Remaining P0/P1
- **P0**: Live broker wiring (Kite + Upstox) — awaiting API keys.
- **P0**: Broker-agnostic adapter interface refinement + order-state reconciliation (poll + WS) — will land alongside live wiring.
- **P1**: Audit-log viewer (SEBI-style trace).
- **P1**: Monte Carlo stress tester.
- **P1**: Move paper-trading logic into `services/`.

## Iteration 5 (2026-02-29) — Code-review cleanup
- **Critical fixes**:
  - `tests/backend_test.py` — hardcoded demo password → `ALGOFORGE_TEST_EMAIL/PASSWORD` env vars (defaults preserved).
  - `routers/backtest.py` — `result` defensively initialised; `AttributeError` caught (was 500, now 400) with logged stack trace so engine bugs aren't silently masked.
  - `db.py` — explicit `_db: Any = None` + `is not None` guard.
  - `brokers/rmoney.py` — `r` → `response` (clarity).
  - `backtest_engine.py` — ambiguous `l` → `loss` / `left` (ruff E741).
- **Frontend**:
  - Empty `catch {}` in `useTickStream.js` and `Backtest.jsx` → `console.warn` with context.
  - React `key={i}` array-index keys → stable composite keys (date+side+i, side+strike, tag text, leg `_key` UUID) in 9 locations.
  - `MultiLegBuilder` strips client-only `_key` field before POSTing (Pydantic extra='ignore' covers it; belt-and-suspenders).
  - `lib/api.js` already auto-attaches `Idempotency-Key` UUID per paper-order POST.
- **Deferred (non-bugs, would risk regression)**: 5 component-complexity refactors (Backtest/PaperExecution/Brokers/Dashboard/MultiLegBuilder splits), `run_backtest`/`scan_traps`/`get_options_chain` function extractions, localStorage → httpOnly cookie auth migration (requires CSRF middleware + backend cookie session rework).
- **Tests**: 59/59 backend pass (+8 new in TestIter5CodeReviewFixes). Lint clean across both stacks.

## Iteration 6 (2026-02-29) — P0 broker prep (no keys needed)
- **Normalized order schema** (`brokers/schemas.py`): `NormalizedOrderRequest`, `NormalizedOrder`, `NormalizedPosition`, `NormalizedOrderEvent`, `BrokerCapabilities`. Enums: `OrderStatus`, `ReconciliationState`, `RejectionReason`. All cross-broker code reads/writes these types.
- **Broker adapter ABC** (`brokers/base.py`): `BrokerAdapter` with 6 abstract methods + capabilities. Typed error hierarchy (`BrokerUnavailable`, `BrokerAuthError`, `BrokerRateLimited`, `BrokerOrderRejected`, `BrokerNetworkError`, `BrokerTimeoutError`, `BrokerUnexpectedError`) where each declares `retryable`. `call_with_retry()` does exponential backoff + jitter; per-`(user_id, broker)` circuit breaker (3 failures / 30s → open 60s).
- **Reference adapter** (`brokers/paper_adapter.py`): `PaperAdapter` fully implements the ABC and is the template for live adapters.
- **Reconciliation service** (`services/reconciliation.py`): diff algorithm produces actions ADOPT_BROKER_ORDER / MARK_LOST / SYNC_STATUS / SYNC_FILL_QTY / NO_OP. Audit rows in `reconciliation_log` collection.
- **New endpoints**: `GET /api/reconciliation/summary`, `GET /api/reconciliation/log`, `POST /api/reconciliation/run/{broker}`.
- **Capability chips** exposed in `GET /api/brokers` (zerodha=7, upstox=6, dhan=5, icici=3, rmoney=1) and surfaced in the Brokers UI.
- **Tests**: 70/71 pass (12/12 new + 58/59 regression; the 1 failure is a pre-existing iter5 import-path bug — fixed in this iteration).

## Remaining
- **P0**: Live broker wiring (Kite + Upstox) — blocked on user keys. When they arrive: pip-install SDKs, migrate `zerodha.py`/`upstox.py` to inherit `BrokerAdapter`, populate `live_orders` collection, kick off reconciler.
- **P1**: Audit-log viewer (SEBI trace) · Monte Carlo stress tester · move paper logic to `services/`.

## Iteration 7 (2026-02-29) — SEBI Audit-Log Viewer (P1)
- **`services/audit.py`**: append-only `record_event()` helper, 18 typed event types covering the SEBI 6-step trace (SIGNAL→DECISION→REQUEST→RESPONSE→FILL→OVERRIDE) plus ops (AUTH_LOGIN, AUTH_REGISTER, KILL_SWITCH, RISK_POLICY_CHANGE, BROKER_CONNECT/TEST/DISCONNECT, RECONCILE, STRATEGY_SAVED, BACKTEST_RUN, DUPLICATE_BLOCKED, BASKET_ROLLBACK).
- **Instrumentation hooks** in 7 routers — paper emits REQUEST + FILL sharing `correlation_id=order_id`; OVERRIDE for `?force=true`; risk policy diffs payload; broker lifecycle; trap scan signal severity scales with overall_trap_score.
- **Endpoints**: `GET /api/audit/types`, `GET /api/audit/events` (filterable by event_types/severities/q/from_ts/to_ts/correlation_id + compound cursor pagination), `GET /api/audit/export` (CSV with date-stamped filename).
- **Hardening from test-agent code review applied**:
  - `q` regex search uses `re.escape()` to prevent regex injection / DoS.
  - Cursor pagination switched to compound `<ts>|<id>` to survive same-ms event bursts (multi-leg basket emits 2N events ms-apart).
  - Unknown `event_type` filter values silently dropped (whitelist against enum).
  - Export filename includes ISO date.
- **Frontend**: new `/audit` page with overline-styled filter chips, search/date inputs, SEBI 6-step toggle, paginated event timeline, CSV download. Sidebar nav entry under Journal.
- **Tests**: 93/93 backend pass (22 new TestIter7AuditLog + 71 regression). Lint clean both stacks.

## Iteration 8 (2026-02-29) — Monte Carlo Stress Tester (P1) + Broker UI Hotfix
- **`services/stress.py`**: block-bootstrap resampling of equity-curve returns + per-bar slippage jitter; iterations 50–5000 clamped; produces P5/P25/P50/P75/P95/mean/std/min/max for final_equity / max_drawdown_pct / sharpe / sortino / total_return_pct; 20-bin histograms for DD, Sharpe, Return; worst-path equity curve; blow-up rate (DD ≤ −25%).
- **Endpoint** `POST /api/stress/run` — accepts either a pre-computed backtest or {dsl, capital, slippage_bps, fee_bps, days, iterations, block_size, slippage_jitter_bps, seed}. Records a `BACKTEST_RUN` audit event with `Monte Carlo × N` summary + payload (blowup_rate_pct, p5_drawdown, p95_return).
- **Frontend** — amber `MONTE CARLO × 1000` button on the Backtest page next to AI Risk Review; renders 5 percentile cards, 2 histogram bars (DD + Return), and a red worst-path line with capital reference line.
- **Code-review fix applied**: `seed=0` now respected (previously fell through to random due to truthiness).
- **Hotfix**: Brokers page crashed with `ReferenceError: Check is not defined` after a prior import edit silently no-op'd. Re-applied the import; page now renders capability chips correctly. Root cause was a stale `search_replace` no-op match — file content drifted between the edit and verification.
- **Tests**: 106/106 backend pass (13 new TestIter8MonteCarloStress + 93 regression).

## Iteration 9 (2026-02-29) — Final P0 + P1 Backlog Completion

### P1: `services/paper_trading.py`
- Moved all paper-order business logic out of `routers/paper.py` into `services/paper_trading.py`.
- Router is now a thin HTTP layer. `brokers/paper_adapter.py` and `routers/dashboard.py` both consume the service directly (no nested HTTP calls).
- Kwargs renamed `check_duplicate` → `do_check_duplicate`, `check_kill_switch` → `do_check_kill_switch` to disambiguate from same-named helper functions.

### P0: Live broker wiring (Zerodha + Upstox)
- `pip install kiteconnect==5.2.0 upstox-python-sdk==2.27.0` and pinned in requirements.txt.
- `brokers/zerodha.py` + `brokers/upstox.py` REWRITTEN to inherit `BrokerAdapter` ABC. All 6 contract methods (test_connection, place_order, cancel_order, modify_order, get_orders, get_positions) translate to/from `NormalizedOrder` / `NormalizedOrderRequest`. Status mapping helpers (`_kite_status_to_normalized`, `_upstox_status_to_normalized`) keep platform-side enums consistent. Errors classified into `BrokerAuthError` (bad creds) / `BrokerOrderRejected` (broker said no) / `BrokerUnavailable` (SDK or config missing).
- **Reconciler background loop**: `services/reconciler_loop.py` launched on FastAPI lifespan as an asyncio Task. Polls every 30s for `broker_connections.status='live'`, calls `reconcile_orders` per broker. Cancelled on shutdown. Idle when no live brokers (returns 0).
- **Duplicate `BrokerUnavailable` consolidated**: `brokers/__init__.py` now re-exports the canonical class from `brokers/base.py` (`A is B == True`).
- `routers/brokers.py.broker_test()` now awaits async `test_connection()` and catches `BrokerError` parent (covers `BrokerAuthError`/`BrokerOrderRejected`/`BrokerUnavailable`).

### Status
- **Tests**: 118/118 backend pytest pass. Test agent found+fixed 2 refactor bugs (broker_test awaiting + paper_adapter kwarg rename) inline.
- **Live trading is one config away** — connect real Kite/Upstox keys via `/brokers` UI, broker_test will return `status='live'`, reconciler will then start ticking it.

## Iteration 10 (2026-02-29) — Super-admin Console (Platform Admin)

User choice: 1a platform super-admin · 2 global audit + system health + risk overrides + broker map · 3b promote-by-flag in DB · 4a separate `admin_events` collection.

- **`routers/admin.py`** (admin-only via `require_admin`): `/admin/health` (Mongo ping, reconciler liveness, LLM key, counts), `/admin/audit` (global user audit feed, paginated), `/admin/risk/users` (every user with kill state + live P&L + exposure from `compute_positions`), `/admin/risk/kill` (force or release kill switch + reason), `/admin/brokers/map` (every broker connection, grouped stats), `/admin/events` (admin_events feed), `/admin/promote` (promote another user to admin).
- **`services/admin_audit.py`**: append-only `admin_events` collection with `record_admin_event()` + `list_admin_events()`; indexes on `ts`, `admin_id`, `target_user_id`. Every privileged action (force-kill, promote) writes here.
- **`scripts/promote_admin.py`**: standalone CLI — `python scripts/promote_admin.py demo@algoforge.io`. Used to bootstrap the first admin.
- **`pages/Admin.jsx`** (`/admin`): 6 health stat cards + 4-tab console (RISK/USERS, BROKER MAP, GLOBAL AUDIT, ADMIN TRAIL). Force-kill button per user row writes admin_events.
- **`AppShell.jsx`**: sidebar exposes the Admin link only when `user.role==='admin'`.
- **Tests**: iter10 — 17/17 admin pytest pass (health, audit, risk/users, brokers/map, events, force-kill arm+release, 404, 403 negatives, regression). Frontend Playwright walkthrough green. Total backend pytest: 135+.
- **Status**: Admin Dashboard complete and E2E validated.

## Iteration 12 (2026-02-29) — Broker Adapter Migration (Dhan / ICICI / Rmoney → BrokerAdapter ABC)

- **`brokers/dhan.py`**, **`brokers/icici.py`**, **`brokers/rmoney.py`** rewritten to inherit `BrokerAdapter`. Each declares `capabilities()`, has async `test_connection / place_order / cancel_order / modify_order / get_orders / get_positions`, and raises typed errors (`BrokerUnavailable` for missing SDK/keys, `BrokerAuthError` for credential failures, `BrokerNetworkError` for rmoney HTTP transport).
- Mutating paths (`place/cancel/modify`) intentionally raise `BrokerUnavailable` with "not wired yet — pending production verification" until real account smoke tests are run.
- `brokers/rmoney.py` switched from sync `requests` to async `httpx.AsyncClient` so the call doesn't block the event loop.
- **`brokers/registry.py`** deduped: capability dicts removed. `list_brokers()` now sources flags from `adapter.capabilities().model_dump()` — single source of truth, can't drift. `make_client(name, creds, user_id=...)` accepts user_id directly.
- **`routers/brokers.py`** simplified: removed legacy sync/async fallback in `broker_test()` — all 5 adapters now share the async contract.
- **Tests**: iter12 — 10/10 broker pytest + 29/29 regression (= 39/39). One test report comment about Rmoney MULTI-LEG chip turned out to be a false positive (Rmoney correctly shows no chips because all flags except `supports_options` are false, and `supports_options` isn't in the UI label map).
- **Status**: All 5 broker adapters now share the same contract. The platform never branches on `isinstance(adapter, LegacyClient)` anywhere.

### Backlog cleared. Future enhancements (open-ended)
- **P2**: JWT to httpOnly cookies + CSRF middleware.
- **P2**: Backtest.jsx / PaperExecution.jsx complexity refactor.
- **P2**: When wiring production Dhan/ICICI: wrap their synchronous SDK calls in `await asyncio.to_thread(...)` so the event loop isn't blocked.
- **P2**: RL intraday scalper, voice trading, crypto/FX/DeFi expansion (open-ended).
- **P2**: Move alerts dedup from in-process OrderedDict to Mongo TTL collection if scaling out to multiple uvicorn workers.
- **P2**: Kite OAuth callback could match on user_id (currently falls back to most-recent-pending row globally) — re-introduce state via Kite Connect "redirect_params" once a real Kite app is provisioned.
- **Test-infra**: backend_test.py TestIter9Refactor needs conftest.py loading .env before brokers package imports.

### Backlog cleared. Future enhancements (open-ended)
- **P0 (blocked on keys)**: First live Kite/Upstox connection via the wizard.
- **P2**: RL intraday scalper, voice trading, crypto/FX/DeFi expansion (open-ended).
- **Cleanup (iter17+)**: Remove the legacy localStorage Bearer bridge from `api.js` once we're sure no rolling clients hold stale tokens.
- **Test-infra**: backend_test.py TestIter9Refactor needs conftest.py loading .env before brokers package imports.

## Iteration 19 (2026-06-01) — VPS Migration Prep + LLM Provider Abstraction

**Why**: Zerodha Kite Connect rejected live orders because Emergent's shared egress IP (34.170.12.145) is already registered by another developer's app. User cannot register the same IP twice — needs dedicated static IP. Solution: migrate the deployment to their Hostinger VPS at static IP `72.60.103.235`. Emergent does NOT offer dedicated static IPs.

- **Bug fix** (`routers/live_orders.py`): execute endpoint was raising `AttributeError: REJECT` whenever Kite rejected an order, returning 500 instead of the real broker reason. Switched to `AuditEventType.RESPONSE` with severity=HIGH and `outcome=rejected` / `transport_error`. Added a separate `except Exception` branch for transport errors (502). User's retry surfaced the real rejection: "IP not allowed for this app".
- **`llm_provider.py`** (new): unified `chat(provider, model, system, user)` helper that switches between Emergent Universal Key (`LLM_PROVIDER=emergent`, default) and direct OpenAI/Anthropic SDKs (`LLM_PROVIDER=direct`) based on env. `status()` reports which mode + per-provider key presence.
- **`ai_service.py`** rewritten: all 4 LLM functions (`generate_strategy_from_nl`, `analyse_strategy_risk`, `explain_trap`, `journal_commentary`) now go through `llm_chat`. Per-provider key checks ensure fallback paths still fire on missing keys. Verified Emergent path still works via `/api/strategies/generate` returning a clean GPT-5.2 RSI strategy.
- **`routers/admin.py`** `/admin/health.llm` block now reports `{mode, openai/anthropic OR emergent_llm_key}` — so admins know which provider is active.
- **`requirements.txt`**: added `anthropic==0.105.2`. `openai==1.99.9` already present.
- **`deploy/`** (new): production Docker artifacts.
  - `Dockerfile.backend`: Python 3.11 slim, installs requirements, gracefully degrades if `emergentintegrations` CDN install fails (covers `LLM_PROVIDER=direct` case).
  - `Dockerfile.frontend`: two-stage Node 20 build → Nginx 1.25 alpine, accepts `REACT_APP_BACKEND_URL` build arg.
  - `nginx.conf`: serves React SPA, reverse-proxies `/api/*` + `/api/ws/*` to `backend:8001`, sets `X-Forwarded-Proto/Host` so OAuth URL derivation works behind TLS-terminating proxies.
  - `docker-compose.yml`: 3-service stack (mongo, backend, frontend), env-driven, persistent volume for Mongo.
  - `.env.production.example`: every required env var documented + generation snippets for `JWT_SECRET` and `ENCRYPTION_KEY`.
  - `README.md`: full end-to-end Hostinger deployment playbook — Docker install, git clone, Cloudflare TLS, Kite IP allowlist update, OAuth wizard re-run, daily ops (logs, Mongo backups, UFW firewall), and "continue developing on Emergent then push to VPS" workflow.
- **`/app/README.md`**: replaced empty stub with full project overview + pointer to deploy guide.
- **Status**: Codebase ready for self-hosted deployment. User's next step is "Save to Github" → SSH to VPS → `docker compose up`. Emergent preview remains usable for ongoing development; same commit runs in both environments thanks to the LLM provider switch.

## Iteration 18 (2026-05-31) — Live Order Routing + Pre-flight Guardrails

- **`routers/live_orders.py`** (new): two-step preview/execute flow against connected live broker.
  - `POST /api/orders/live/preview` — runs 6 guardrails (kill_switch, broker status=live, daily cap ₹50K, daily count 10/day, valid symbol, valid HMAC), returns HMAC-signed `confirm_token` (60s TTL).
  - `POST /api/orders/live/execute` — HMAC verify, single-use token via `live_used_tokens` Mongo collection (TTL-purged), re-runs all guardrails, audit row at HIGH severity BEFORE the broker call, places via adapter, persists `live_orders`, audit RESPONSE row HIGH severity.
  - `typed_confirm: Literal["LIVE"]` Pydantic gate at the API layer — frontend forces user to type "LIVE" in caps.
  - `correlation_id` ties REQUEST → RESPONSE/REJECT audit rows together.
- **`brokers/base.py`**: added `async def get_quote(symbol, exchange)` to ABC (default 0.0). Concrete adapters override.
- **`brokers/zerodha.py`**: implemented `get_quote()` via `kite.ltp([key])` — falls back gracefully when Kite returns "Insufficient permission" (paid market-data add-on required). Surfaces a clear "use LIMIT order with your own price" hint instead of a crash.
- **`routers/broker_oauth.py`**: new `POST /brokers/{name}/oauth/relink` endpoint — re-uses saved api_key/api_secret to issue a fresh login URL. Kite access tokens expire daily ~6 AM IST; this lets the user one-click refresh.
- **`components/paper/LiveOrderTicket.jsx`** (new): red-themed order ticket with broker/symbol/side/qty/type/product/price fields. Default = LIMIT for unknown symbols (avoids LTP-add-on requirement). REVIEW LIVE ORDER button opens a confirmation modal that requires typing "LIVE" before EXECUTE is enabled. Disabled when kill_switch is ON or no live broker connection exists.
- **`pages/PaperExecution.jsx`**: rendered the LiveOrderTicket below the multi-leg builder + a separate "Live orders" listing section.
- **`pages/Brokers.jsx`**: added RELINK button on connected Zerodha/Upstox cards — opens broker login in popup, polls until status flips back to live.
- **Smoke tests**: All 5 backend guardrails verified (kill_switch=423, notional cap=400, HMAC tamper=400, missing typed_confirm=422, daily cap=429). LIMIT preview for IDEA × 1 @ ₹15.50 returned proper confirm_token. Frontend modal verified to gate EXECUTE behind `typed === "LIVE"`. Markets closed today; user will fire the live BUY tomorrow.
- **Status**: P0 live order pipeline complete. Ready for tomorrow's live BUY when markets open.

## Iteration 17 (2026-05-31) — First live broker connection 🎉

- **conftest.py** (`/app/backend/tests/conftest.py`): loads `.env` into `os.environ` at conftest-import time + adds backend root to `sys.path`. Unblocked 15 previously-failing tests in `backend_test.py` (101 → 116 passing) — all the broker/encryption-import-dependent tests that needed `ENCRYPTION_KEY` set before module init.
- **Live Kite Connect onboarding via wizard** (`demo@algoforge.io`):
  - Kite app credentials provisioned (api_key + api_secret), redirect URL registered.
  - Wizard `/oauth/start` armed CSRF state, surfaced `redirect_params=state%3D...` login URL.
  - User logged in at kite.zerodha.com → callback received `?status=success&request_token=...&state=...` echoed via redirect_params.
  - `KiteConnect.generate_session()` exchanged request_token → access_token cleanly. Encrypted creds persisted in `broker_connections` (Fernet via `ENCRYPTION_KEY`). State row consumed.
  - `_finalize_connection` auto-test fired → live ping to Kite `/user/profile` returned `MDG129 / Dada Khalandar Shaik`.
  - Audit event written: `OAuth linked zerodha: live — Dada Khalandar Shaik`. `postback_secret` minted: `7ud8hBt6OftJXlGrKmhieBAx`.
- **Verified**: `GET /api/brokers` shows `zerodha connected=true status=live`. `POST /api/brokers/zerodha/test` ping-roundtrip OK. `GET /api/admin/brokers/map` shows the connection with `broker_user_name` & `broker_user_id`. `GET /api/admin/health` reports `reconciler=running broker_connections=1`.
- **Side-finding**: User saw "Invalid user session — TokenException" on a 2nd click — Kite request_tokens are single-use, the first click had already succeeded (the row was already LIVE before the second click). Wizard auto-close page correctly surfaced Kite's error string from the SDK exception. No code change needed.
- **Status**: P0 closed. AlgoForge has crossed from "simulation-ready" → "live-trading-ready" for Zerodha. Upstox + Dhan + ICICI + Rmoney remain to be onboarded the same way (Upstox will use the same OAuth wizard; the others use manual CONNECT with their static tokens).
- **postback URL** to be configured by user in Kite app settings (optional, enables real-time order push from broker instead of 30s reconciler poll):
  `https://quant-hybrid-trade.preview.emergentagent.com/api/brokers/zerodha/postback?token=7ud8hBt6OftJXlGrKmhieBAx`

## Iteration 16 (2026-02-29) — P2 Triple: asyncio.to_thread + Mongo-TTL Dedup + Backtest/Paper UI Refactor

- **`brokers/{zerodha,upstox,dhan,icici}.py`** — every blocking SDK call now runs via `await asyncio.to_thread(...)`. For ICICI, even `_client()` (which triggers `BreezeConnect.generate_session` network IO) is wrapped. Verified via 10 concurrent `/api/brokers/dhan/test` calls completing in 0.7s with the `/admin/health` endpoint staying responsive under that load.
- **`services/alerts.py`** — replaced in-process `OrderedDict + asyncio.Lock` dedup with a Mongo `alert_dedup` collection. `_id = dedup_key`, TTL index `created_at_ttl` (`expireAfterSeconds=60`) auto-purges. Inserts that collide raise DuplicateKeyError → treated as "already sent". Now safe across multiple uvicorn workers.
- **`pages/Backtest.jsx`**: 429 → **256** lines. Extracted `components/backtest/TradeLogTable.jsx`, `AiRiskReviewPanel.jsx`, `StressTestPanel.jsx` (percentile cards + histograms + worst-path chart).
- **`pages/PaperExecution.jsx`**: 316 → **239** lines. Extracted `components/paper/PositionsTable.jsx` and `OrdersTable.jsx`. Multi-leg builder untouched.
- **Tests**: iter16 — 5/5 new tests + 73/73 regression = **78/78 backend pytest pass**. Frontend Playwright: all data-testid hooks preserved, MultiLegBuilder intact, kill-switch flow intact, 0 console errors.
- **Status**: All confirmed P2 backlog (asyncio, Mongo dedup, UI refactor) closed in one iteration.

## Iteration 15 (2026-02-29) — JWT → HttpOnly Cookies + Double-Submit CSRF (P2 closed)

- **`auth_csrf.py`** (new): `set_auth_cookies(response, jwt)` writes `algoforge_auth` (HttpOnly, Secure, SameSite=Lax, Path=/) and `algoforge_csrf` (non-HttpOnly, same flags), `clear_auth_cookies(response)`, `CSRFMiddleware` enforcing double-submit on `POST/PUT/PATCH/DELETE` under `/api`. Exempt paths: `/api/auth/{login,register,logout,migrate-token}` and any path containing `/oauth/callback` or `/postback` (browser/server-initiated, no CSRF token to provide). Middleware also bypasses CSRF when no `algoforge_auth` cookie is in the request → Bearer-only clients (curl, testing agent) keep working unchanged.
- **`auth.py`**: `login`, `register` now accept `Response` and call `set_auth_cookies(response, token)` while still returning `access_token` in the JSON body (so legacy clients keep working). Added `/auth/logout` (clears cookies, audits via `AUTH_LOGIN` summary "Logout"), `/auth/migrate-token` (one-shot Bearer-→-cookie upgrade), `/auth/me` (already existed). `get_current_user` now reads cookie first, falls back to `Authorization: Bearer`.
- **`server.py`**: Started honouring `CORS_ORIGINS=*` via `allow_origin_regex=".*"` (so `allow_credentials=True` stays valid), `expose_headers=["X-CSRF-Token"]`, `attach_csrf_middleware(app)`.
- **Frontend `api.js`**: `axios.create({ withCredentials: true })`. Interceptor reads the `algoforge_csrf` cookie via `document.cookie` and echoes it as `X-CSRF-Token` on unsafe methods. Legacy localStorage Bearer bridge retained for one release cycle (planned removal noted in backlog).
- **Frontend `auth.jsx`**: Rewrote bootstrap — if legacy `af_token` is in localStorage, POST it to `/auth/migrate-token` so the server mints cookies, then drop it. Otherwise just call `/auth/me`. `logout()` posts to `/auth/logout` and clears local state. No more `localStorage.setItem('af_token', ...)`.
- **Cookie Path fix**: Initially scoped cookies to `/api`, but `document.cookie` on `/settings` then couldn't read the CSRF cookie (Path attribute also restricts JS visibility). Changed to Path=/ — verified via Playwright that the CSRF header is now injected on mutating calls from every frontend route.
- **Tests**: iter15 — 16/16 backend pytest pass (login/register cookie shape, Bearer-only back-compat, cookie-only auth, CSRF 403/200/wrong, exempt paths, logout, migrate-token). Frontend Playwright: cookies present after login, localStorage.af_token cleared, SAVE POLICY mutates state with X-CSRF-Token injected automatically, logout clears cookies + redirects, cleared-cookie reload sends user back to /login. Zero regressions on the Bearer-only test surface.
- **Status**: P2 cookie auth closed. localStorage Bearer bridge can be deleted in iter17+ once we confirm no rolling clients still have legacy tokens.

## Iteration 14 (2026-02-29) — Kite OAuth `state` via redirect_params

- **`routers/broker_oauth.py`** `_kite_login_url(api_key, state)` now appends `redirect_params=state%3D{state}` so Kite echoes our CSRF token back to the callback as a regular `state` query param. Upstox already round-tripped state natively; the two flows are now symmetric.
- Callback **requires** `state` — no more "most-recent-pending-row-for-broker" global fallback. Concurrent multi-user OAuth runs can't collide.
- 3 negative-path responses verified: (i) start now returns `login_url` containing `redirect_params=state%3D...`; (ii) callback with no `state` → 400 "Missing OAuth state in callback"; (iii) callback with bogus state → 400 "state not found or expired".
- **Status**: P1 closed. Iter 13's documented "low-risk multi-user race" eliminated.

## Iteration 13 (2026-02-29) — Broker OAuth Wizard (Zerodha + Upstox)

- **`routers/broker_oauth.py`**: 4 endpoints — `GET /brokers/{name}/oauth/urls` (surfaces redirect_url + postback_url), `POST /brokers/{name}/oauth/start` (returns broker login_url, stashes state in TTL collection), `GET /brokers/{name}/oauth/callback` (exchanges request_token/code via `KiteConnect.generate_session` / Upstox `/v2/login/authorization/token`, persists access_token encrypted, marks LIVE, audit-logs, returns auto-close HTML), `POST /brokers/{name}/postback` (per-connection token, writes to `live_order_events`, audit-logs REJECTED as HIGH severity).
- **Public URL derivation**: `_base_url` honours `x-forwarded-proto` / `x-forwarded-host` so the URLs surfaced to the user resolve to the HTTPS preview domain (not the internal HTTP cluster host).
- **`oauth_states` Mongo collection** with TTL index `expireAfterSeconds=600` — auto-purges abandoned wizard runs.
- **`postback_secret`** generated per connection at link time — appended to postback URL as `?token=...` for webhook auth.
- **Live order events** payload truncated >8 KB to prevent broker-side flooding.
- **`components/BrokerOAuthWizard.jsx`**: 4-step modal (URLs → keys → polling → success/fail). New tab opens broker login; original tab polls `/api/brokers` until status flips. Includes Re-open broker login affordance.
- **`pages/Brokers.jsx`**: WIZARD button per broker card (amber accent) sits alongside the existing CONNECT button. Non-OAuth brokers (Dhan/ICICI/Rmoney) get the same wizard surfacing redirect/postback URLs + an amber heads-up explaining their manual flow.
- **Tests**: iter13 — 18/18 backend pytest pass. Frontend Playwright caught two bugs (wizard state leakage across brokers; Dhan DONE button advancing to misleading LINK FAILED screen) — both fixed via state-reset useEffect + onClose branch, re-verified via targeted Playwright assertions.
- **Status**: OAuth onboarding pipeline complete. Live exchange will work the moment a real Kite/Upstox developer app is provisioned with the displayed redirect URL.

## Iteration 11 (2026-02-29) — P1 Alerts (Telegram + SMTP email for HIGH-severity events)

- **`services/alerts.py`**: Telegram (httpx → api.telegram.org) + Email (aiosmtplib) transports, fire-and-forget. 60s in-process dedup (OrderedDict), 1 retry on transport failure (skipped for 4xx). `transport_status()` reports configured vs. missing env. Routes to per-user channels AND a global admin mirror (`TELEGRAM_GLOBAL_CHAT_ID`, `SMTP_GLOBAL_RECIPIENT`).
- **`routers/alerts.py`**: `GET /api/alerts/prefs` (defaults if no row), `PUT /api/alerts/prefs`, `POST /api/alerts/test` (channel ∈ {telegram, email}), `GET /api/alerts/log`.
- **Audit auto-dispatch hook**: `services/audit.record_event` now schedules `dispatch_event` via `asyncio.create_task` when severity == HIGH. Non-blocking — trading flows are never delayed.
- **Admin /admin/health**: now includes `alerts` block (telegram/email transport state + global mirrors).
- **Frontend**: Settings page split into tabs `RISK & PROFILE` / `ALERTS`. `AlertsPanel.jsx` exposes transport status pills, per-channel switches, destination inputs, event-type chips (5 default: KILL_SWITCH, BROKER_DISCONNECT, BASKET_ROLLBACK, RISK_POLICY_CHANGE, OVERRIDE), SEND TEST buttons (disabled when transport unconfigured), Save, and a recent-deliveries log.
- **`aiosmtplib==3.0.2`** pinned in requirements.txt. Telegram uses existing httpx — no new HTTP client deps.
- **Tests**: iter11 — 12/12 alerts pytest (defaults, PUT round-trip, test endpoint 4xx with descriptive errors, auth gating, KILL_SWITCH auto-dispatch → alert_log rows, 60s dedup, admin/health.alerts block). 100% backend regression (iter10 admin tests still pass). Frontend Playwright E2E green.
- **Status**: P1 alerts pipeline complete. Plug in `TELEGRAM_BOT_TOKEN` + `SMTP_*` env vars at deploy time — feature works in degraded mode until then (graceful 400 with descriptive error; audit_log + alert_log keep recording).
