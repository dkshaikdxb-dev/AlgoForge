# AlgoForge — AI-First Hybrid Algorithmic Trading Platform

A production-grade modular platform for AI-assisted strategy design, backtest,
Monte Carlo stress testing, paper execution, live broker routing, and SEBI-style
audit trails. Supports Zerodha, Upstox, Dhan, ICICI Direct, and Rmoney brokers.

## Quick start

### Local development (Emergent preview)
- Open the running preview URL. Demo account: `demo@algoforge.io / Demo@123`.
- LLM provider defaults to **Emergent** (uses Universal Key).
- See [`memory/PRD.md`](memory/PRD.md) for full architecture + iteration history.

### Production deploy on your own VPS
See **[`deploy/README.md`](deploy/README.md)** for full Hostinger / generic
Ubuntu VPS deployment with Docker Compose, including Kite IP allowlist setup
and TLS via Cloudflare.

## Architecture

```
/app/
├── backend/                    # FastAPI + motor/Mongo
│   ├── brokers/                # BrokerAdapter ABC (zerodha, upstox, dhan, icici, rmoney)
│   ├── routers/                # admin, alerts, audit, backtest, brokers, broker_oauth,
│   │                           # dashboard, journal, live_orders, paper, risk, strategies, ...
│   ├── services/               # admin_audit, alerts, audit, backtest_engine,
│   │                           # paper_trading, reconciler_loop, stress, trap_detection
│   ├── ai_service.py           # LLM wrappers (GPT-5.2 strategy ideation, Claude risk)
│   ├── llm_provider.py         # Emergent vs direct OpenAI/Anthropic switch
│   ├── auth.py + auth_csrf.py  # JWT + HttpOnly cookies + CSRF double-submit
│   └── server.py
├── frontend/                   # React + Tailwind + Shadcn
│   ├── src/components/         # AppShell, MultiLegBuilder, BrokerOAuthWizard, LiveOrderTicket, ...
│   ├── src/pages/              # Admin, AuditLog, Backtest, Brokers, Dashboard, Journal,
│   │                           # Login, PaperExecution, Register, Settings, StrategyBuilder, ...
│   └── src/lib/                # api.js, auth.jsx, useTickStream.js
├── deploy/                     # Production Docker artifacts (compose, Dockerfiles, nginx)
└── memory/
    ├── PRD.md                  # Living product roadmap + iteration log
    └── test_credentials.md     # Demo account + admin promotion notes
```

## Key features

- **AI Strategy Builder** — natural language → DSL JSON via GPT-5.2.
- **Backtest + Monte Carlo** — bootstrap resampling with percentile metrics.
- **Paper Execution** — multi-leg basket builder with idempotency & kill-switch.
- **Live Order Routing** — two-step HMAC-signed confirm with 6 guardrails,
  per-broker adapter, real-time postback webhooks.
- **Broker OAuth Wizard** — copy-paste redirect URL → auto token capture for
  Zerodha + Upstox; manual flow for Dhan/ICICI/Rmoney.
- **SEBI-style Audit Trail** — every event from SIGNAL→DECISION→REQUEST
  →RESPONSE→FILL with correlation IDs.
- **Super-admin Dashboard** — global audit, system health, risk overrides,
  force kill-switch with admin_events log.
- **Alerts** — Telegram + SMTP for HIGH-severity audit events, with Mongo TTL
  dedup that's safe across workers.
- **Reconciler Loop** — background poll merges broker order book with local state.

## Test credentials

See [`memory/test_credentials.md`](memory/test_credentials.md). Demo admin:
`demo@algoforge.io / Demo@123`.

## License

Proprietary — all rights reserved.
