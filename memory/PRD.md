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
