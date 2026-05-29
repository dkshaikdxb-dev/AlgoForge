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
