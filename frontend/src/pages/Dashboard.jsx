import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import StatCard from "@/components/StatCard";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { ArrowRight, ShieldAlert, Activity, Sparkles } from "lucide-react";

const fmt = (n, d = 2) =>
  (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

export default function Dashboard() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);
  const [niftyCandles, setNiftyCandles] = useState([]);
  const [trapPreview, setTrapPreview] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [s, m, t] = await Promise.all([
        api.get("/dashboard/summary"),
        api.get("/market/ohlcv", { params: { symbol: "NIFTY", days: 90 } }),
        api.get("/trap/scan", { params: { symbol: "NIFTY" } }),
      ]);
      setSummary(s.data);
      setNiftyCandles(m.data.candles);
      setTrapPreview(t.data);
    } catch {
      toast.error("Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

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

  const pnl = summary?.total_pnl ?? 0;
  const pnlTone = pnl > 0 ? "profit" : pnl < 0 ? "loss" : "neutral";

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
        {/* KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard
            testid="kpi-total-pnl"
            label="Total P&L (Paper)"
            value={`₹${fmt(pnl)}`}
            sub={`across ${summary?.open_positions ?? 0} positions`}
            tone={pnlTone}
          />
          <StatCard
            testid="kpi-exposure"
            label="Exposure"
            value={`₹${fmt(summary?.exposure ?? 0, 0)}`}
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
