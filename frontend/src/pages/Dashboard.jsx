import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import StatCard from "@/components/StatCard";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { ArrowRight, ShieldAlert, Activity, Sparkles, Pause, Play, RefreshCw } from "lucide-react";

const fmt = (n, d = 2) =>
  (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

const AUTO_REFRESH_MS = 5000;

export default function Dashboard() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);
  const [niftyCandles, setNiftyCandles] = useState([]);
  const [trapPreview, setTrapPreview] = useState(null);
  const [mode, setMode] = useState("combined"); // 'paper' | 'live' | 'combined'
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [secondsAgo, setSecondsAgo] = useState(0);

  // useCallback so the function identity is stable for useEffect deps.
  const load = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    try {
      const [s, m, t] = await Promise.all([
        api.get("/dashboard/summary"),
        api.get("/market/ohlcv", { params: { symbol: "NIFTY", days: 90 } }),
        api.get("/trap/scan", { params: { symbol: "NIFTY" } }),
      ]);
      setSummary(s.data);
      setNiftyCandles(m.data.candles);
      setTrapPreview(t.data);
      setLastRefresh(new Date());
    } catch {
      if (!silent) toast.error("Failed to load dashboard");
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  /* eslint-disable */
  // Initial load.
  useEffect(() => {
    load();
  }, [load]);

  // 5-second auto-refresh — silent (no spinner / no toast on failure).
  useEffect(() => {
    if (!autoRefresh) return undefined;
    const id = setInterval(() => { load({ silent: true }); }, AUTO_REFRESH_MS);
    return () => clearInterval(id);
  }, [autoRefresh, load]);

  // Tick the "Xs ago" label every second without re-running load().
  useEffect(() => {
    if (!lastRefresh) return undefined;
    const tick = () => setSecondsAgo(Math.max(0, Math.floor((Date.now() - lastRefresh.getTime()) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [lastRefresh]);
  /* eslint-enable */

  const toggleKill = async (val) => {
    if (!summary?.risk_limits) return;
    try {
      await api.put("/risk/limits", { ...summary.risk_limits, kill_switch: val });
      toast[val ? "warning" : "success"](val ? "Kill switch ACTIVE" : "Kill switch released");
      load();
    } catch {
      toast.error("Could not toggle kill switch");
    }
  };

  // Pick the right slice based on toggle. Default 'combined' merges paper + live.
  const slice = (() => {
    if (!summary) return { total_pnl: 0, exposure: 0, open_positions: 0 };
    if (mode === "paper") return summary.paper || summary;
    if (mode === "live") return { ...summary.live, open_positions: summary.live?.positions?.length || 0 };
    return summary.combined || summary;
  })();
  const pnl = slice.total_pnl ?? 0;
  const pnlTone = pnl > 0 ? "profit" : pnl < 0 ? "loss" : "neutral";
  const liveBrokerCount = summary?.live?.broker_count ?? 0;

  return (
    <AppShell>
      <PageHeader
        overline="Cockpit"
        title="Trading Cockpit"
        description="Live read on your strategies, paper P&L, exposure and trap exposure across your watchlist."
        actions={
          <>
            <div className="flex items-center gap-3 panel px-3 py-2">
              <ShieldAlert className={`w-4 h-4 ${summary?.kill_switch ? "txt-loss" : "txt-muted"}`} />
              <div className="overline">Kill switch</div>
              <Switch
                data-testid="cockpit-kill-switch"
                checked={!!summary?.kill_switch}
                onCheckedChange={toggleKill}
              />
            </div>
            <Button
              data-testid="cockpit-new-strategy-btn"
              onClick={() => navigate("/strategies")}
              className="rounded-none bg-white text-black hover:bg-zinc-200 font-section tracking-wider"
            >
              <Sparkles className="w-4 h-4 mr-2" /> NEW STRATEGY
            </Button>
          </>
        }
      />

      <div className="p-8 space-y-8" data-testid="dashboard-content">
        {/* Mode toggle + auto-refresh control */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-1 panel inline-flex p-1 w-fit">
            {[
              { v: "paper", label: "PAPER" },
              { v: "live", label: `LIVE${liveBrokerCount > 0 ? ` · ${liveBrokerCount}` : ""}` },
              { v: "combined", label: "COMBINED" },
            ].map((opt) => (
              <button
                key={opt.v}
                data-testid={`dashboard-mode-${opt.v}`}
                onClick={() => setMode(opt.v)}
                className={`px-4 py-1.5 text-xs font-section tracking-wider ${
                  mode === opt.v ? "bg-white text-black" : "text-zinc-400 hover:text-white"
                }`}
              >
                {opt.label}
              </button>
            ))}
            {liveBrokerCount === 0 && (
              <span className="ml-3 text-xs txt-muted self-center">
                · no live broker connected
              </span>
            )}
          </div>

          <div className="flex items-center gap-3 text-xs font-mono-data">
            {lastRefresh && (
              <span className="txt-muted" data-testid="dashboard-last-refresh">
                updated {secondsAgo}s ago
              </span>
            )}
            <Button
              data-testid="dashboard-manual-refresh"
              size="sm"
              variant="ghost"
              onClick={() => load()}
              disabled={loading}
              className="rounded-none h-7 px-2"
              title="Refresh now"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            </Button>
            <Button
              data-testid="dashboard-auto-refresh-toggle"
              size="sm"
              variant="ghost"
              onClick={() => setAutoRefresh((v) => !v)}
              className={`rounded-none h-7 px-2 ${autoRefresh ? "txt-profit" : "txt-muted"}`}
              title={autoRefresh ? "Pause auto-refresh" : "Resume 5s auto-refresh"}
            >
              {autoRefresh ? <Pause className="w-3.5 h-3.5 mr-1" /> : <Play className="w-3.5 h-3.5 mr-1" />}
              {autoRefresh ? "AUTO 5s" : "PAUSED"}
            </Button>
          </div>
        </div>

        {/* KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard
            testid="kpi-total-pnl"
            label={`Total P&L (${mode})`}
            value={`₹${fmt(pnl)}`}
            sub={`across ${slice.open_positions ?? 0} positions`}
            tone={pnlTone}
          />
          <StatCard
            testid="kpi-exposure"
            label={`Exposure (${mode})`}
            value={`₹${fmt(slice.exposure ?? 0, 0)}`}
            sub="net notional value"
          />
          <StatCard
            testid="kpi-strategies"
            label="Strategies"
            value={summary?.strategies ?? 0}
            sub={`${summary?.backtests ?? 0} backtests run`}
          />
          <StatCard
            testid="kpi-trap-score"
            label="NIFTY Trap Score"
            value={trapPreview ? `${(trapPreview.overall_trap_score * 100).toFixed(0)}%` : "—"}
            sub={trapPreview ? `spot ${fmt(trapPreview.spot)} · expiry ${trapPreview.expiry}` : ""}
            tone={trapPreview && trapPreview.overall_trap_score > 0.6 ? "warn" : "neutral"}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* NIFTY chart */}
          <div className="panel lg:col-span-2 p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="overline">NIFTY 50 · 90D</div>
                <div className="font-display text-3xl">{fmt(niftyCandles.at(-1)?.close ?? 0)}</div>
              </div>
              <Activity className="w-5 h-5 txt-muted" />
            </div>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={niftyCandles}>
                  <CartesianGrid stroke="#27272a" strokeDasharray="2 4" vertical={false} />
                  <XAxis
                    dataKey="date"
                    stroke="#52525b"
                    fontSize={10}
                    tickFormatter={(v) => v.slice(5)}
                    interval="preserveStartEnd"
                  />
                  <YAxis stroke="#52525b" fontSize={10} domain={["dataMin - 100", "dataMax + 100"]} />
                  <Tooltip
                    contentStyle={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 0, fontFamily: "JetBrains Mono" }}
                    labelStyle={{ color: "#a1a1aa" }}
                  />
                  <Line type="monotone" dataKey="close" stroke="#3b82f6" strokeWidth={1.5} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Trap preview */}
          <div className="panel p-5">
            <div className="overline">Top trap alerts · NIFTY</div>
            <div className="space-y-3 mt-3">
              {!trapPreview && <div className="txt-muted text-sm">Scanning…</div>}
              {trapPreview?.suggestions?.length === 0 && (
                <div className="txt-muted text-sm">No high-confidence traps. All clear.</div>
              )}
              {trapPreview?.suggestions?.map((s, i) => (
                <div key={`${s.side}-${s.strike}`} className="border border-[var(--border)] p-3" data-testid={`dashboard-trap-${i}`}>
                  <div className="flex items-center justify-between">
                    <div className={`overline ${s.level === "HIGH" ? "txt-loss" : "txt-warn"}`}>
                      {s.level} · {s.side}
                    </div>
                    <div className="font-mono-data text-xs">{s.strike}</div>
                  </div>
                  <div className="text-sm mt-1.5">{s.headline}</div>
                </div>
              ))}
              <Button
                data-testid="dashboard-trap-open"
                variant="ghost"
                size="sm"
                onClick={() => navigate("/trap")}
                className="w-full justify-between rounded-none text-zinc-400 hover:text-white hover:bg-[var(--bg-surface-2)]"
              >
                Open trap detection <ArrowRight className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </div>

        {/* Live broker positions */}
        {summary?.live?.positions?.length > 0 && (
          <div className="panel p-5" data-testid="dashboard-live-positions">
            <div className="flex items-center justify-between mb-3">
              <div className="overline txt-loss">Live broker positions · real money</div>
              <span className="text-xs font-mono-data txt-loss border border-red-500/40 px-2 py-0.5">
                {summary.live.positions.length} OPEN
              </span>
            </div>
            <div className="space-y-1 text-xs font-mono-data">
              <div className="grid grid-cols-7 gap-2 txt-muted border-b border-[var(--border)] pb-2 overline">
                <span>Broker</span>
                <span>Symbol</span>
                <span>Product</span>
                <span className="text-right">Qty</span>
                <span className="text-right">Avg</span>
                <span className="text-right">LTP</span>
                <span className="text-right">P&L</span>
              </div>
              {summary.live.positions.map((p, i) => (
                <div
                  key={`${p.broker}-${p.symbol}-${i}`}
                  className="grid grid-cols-7 gap-2 py-1.5 border-b border-[var(--border)]"
                  data-testid={`dashboard-live-pos-${i}`}
                >
                  <span className="font-section">{p.broker.toUpperCase()}</span>
                  <span>{p.symbol}</span>
                  <span className="txt-muted">{p.product}</span>
                  <span className={`text-right ${p.qty > 0 ? "txt-profit" : "txt-loss"}`}>{p.qty}</span>
                  <span className="text-right">{fmt(p.avg_price)}</span>
                  <span className="text-right">{fmt(p.last_price)}</span>
                  <span className={`text-right ${p.pnl > 0 ? "txt-profit" : p.pnl < 0 ? "txt-loss" : ""}`}>
                    {fmt(p.pnl)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Risk strip */}
        {summary?.risk_limits && (
          <div className="panel p-5">
            <div className="overline mb-3">Risk policy</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-6 font-mono-data text-sm">
              <div>
                <div className="overline">Max drawdown</div>
                <div className="kpi-num text-2xl mt-1">{summary.risk_limits.max_drawdown_pct}%</div>
              </div>
              <div>
                <div className="overline">Daily loss cap</div>
                <div className="kpi-num text-2xl mt-1">₹{fmt(summary.risk_limits.daily_loss_cap, 0)}</div>
              </div>
              <div>
                <div className="overline">Position limit</div>
                <div className="kpi-num text-2xl mt-1">{summary.risk_limits.position_limit}</div>
              </div>
              <div>
                <div className="overline">Mode</div>
                <div className={`kpi-num text-2xl mt-1 ${summary.kill_switch ? "txt-loss" : "txt-profit"}`}>
                  {summary.kill_switch ? "HALTED" : "ARMED"}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
