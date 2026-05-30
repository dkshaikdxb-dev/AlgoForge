import { useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import StatCard from "@/components/StatCard";
import AiRiskReviewPanel from "@/components/backtest/AiRiskReviewPanel";
import StressTestPanel from "@/components/backtest/StressTestPanel";
import TradeLogTable from "@/components/backtest/TradeLogTable";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Loader2, Play, ShieldCheck, Activity } from "lucide-react";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { toast } from "sonner";

const fmt = (n, d = 2) =>
  (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

export default function Backtest() {
  const [strategies, setStrategies] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [capital, setCapital] = useState(500000);
  const [slippage, setSlippage] = useState(5);
  const [feeBps, setFeeBps] = useState(2);
  const [days, setDays] = useState(180);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [risk, setRisk] = useState(null);
  const [riskLoading, setRiskLoading] = useState(false);
  const [stress, setStress] = useState(null);
  const [stressLoading, setStressLoading] = useState(false);
  const [stressIter, setStressIter] = useState(1000);

  useEffect(() => {
    api.get("/strategies").then(({ data }) => {
      setStrategies(data.items);
      // pre-select from session storage if user came from Strategy page
      const stored = sessionStorage.getItem("af_backtest_dsl");
      if (stored) {
        try {
          const parsed = JSON.parse(stored);
          if (parsed.id) setSelectedId(parsed.id);
        } catch (parseErr) {
          console.warn("[Backtest] could not parse stored DSL", parseErr);
        }
        sessionStorage.removeItem("af_backtest_dsl");
      } else if (data.items.length > 0) {
        setSelectedId(data.items[0].id);
      }
    });
  }, []);

  const selected = useMemo(
    () => strategies.find((s) => s.id === selectedId),
    [strategies, selectedId],
  );

  const run = async () => {
    if (!selected) {
      toast.error("Select a strategy first");
      return;
    }
    setLoading(true);
    setResult(null);
    setRisk(null);
    setStress(null);
    try {
      const { data } = await api.post("/backtest/run", {
        dsl: selected.dsl,
        capital,
        slippage_bps: Number(slippage),
        fee_bps: Number(feeBps),
        days: Number(days),
        save: true,
        strategy_id: selected.id,
      });
      setResult(data);
      toast.success("Backtest complete");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Backtest failed");
    } finally {
      setLoading(false);
    }
  };

  const analyse = async () => {
    if (!result || !selected) return;
    setRiskLoading(true);
    try {
      const { data } = await api.post("/risk/analyse", {
        dsl: selected.dsl,
        backtest: result,
      });
      setRisk(data);
    } catch {
      toast.error("Risk analysis failed");
    } finally {
      setRiskLoading(false);
    }
  };

  const stressTest = async () => {
    if (!result) return;
    setStressLoading(true);
    try {
      const { data } = await api.post("/stress/run", {
        backtest: result,
        iterations: Number(stressIter),
      });
      setStress(data);
      toast.success(`Monte Carlo × ${data.iterations} done — blowup ${data.blowup_rate_pct}%`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Stress test failed");
    } finally {
      setStressLoading(false);
    }
  };

  const ret = result?.total_return_pct ?? 0;
  const retTone = ret > 0 ? "profit" : ret < 0 ? "loss" : "neutral";

  return (
    <AppShell>
      <PageHeader
        overline="Backtest"
        title="Historical replay"
        description="Walk the strategy through mock tick-level history with slippage & fees. Then have Claude Sonnet 4.5 score its risk profile."
      />

      <div className="p-8 space-y-6">
        {/* Config */}
        <div className="panel p-5">
          <div className="grid grid-cols-1 md:grid-cols-6 gap-4">
            <div className="md:col-span-2">
              <Label className="overline">Strategy</Label>
              <Select value={selectedId} onValueChange={setSelectedId}>
                <SelectTrigger data-testid="backtest-strategy-select" className="mt-2 rounded-none bg-[var(--bg-surface)] border-[var(--border)]">
                  <SelectValue placeholder="Choose a saved strategy" />
                </SelectTrigger>
                <SelectContent className="rounded-none bg-[var(--bg-surface)] border-[var(--border)]">
                  {strategies.map((s) => (
                    <SelectItem key={s.id} value={s.id}>{s.name} · {s.dsl?.symbol}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="overline">Capital ₹</Label>
              <Input data-testid="backtest-capital" type="number" value={capital} onChange={(e) => setCapital(Number(e.target.value))} className="mt-2 rounded-none bg-[var(--bg-surface)] border-[var(--border)] font-mono-data" />
            </div>
            <div>
              <Label className="overline">Slippage (bps)</Label>
              <Input data-testid="backtest-slippage" type="number" value={slippage} onChange={(e) => setSlippage(Number(e.target.value))} className="mt-2 rounded-none bg-[var(--bg-surface)] border-[var(--border)] font-mono-data" />
            </div>
            <div>
              <Label className="overline">Fees (bps)</Label>
              <Input data-testid="backtest-fees" type="number" value={feeBps} onChange={(e) => setFeeBps(Number(e.target.value))} className="mt-2 rounded-none bg-[var(--bg-surface)] border-[var(--border)] font-mono-data" />
            </div>
            <div>
              <Label className="overline">Days</Label>
              <Input data-testid="backtest-days" type="number" value={days} onChange={(e) => setDays(Number(e.target.value))} className="mt-2 rounded-none bg-[var(--bg-surface)] border-[var(--border)] font-mono-data" />
            </div>
          </div>
          <div className="flex gap-3 mt-5">
            <Button
              data-testid="backtest-run-btn"
              onClick={run}
              disabled={loading || !selected}
              className="rounded-none bg-white text-black hover:bg-zinc-200 font-section tracking-wider h-10"
            >
              {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Play className="w-4 h-4 mr-2" />}
              {loading ? "RUNNING…" : "RUN BACKTEST"}
            </Button>
            {result && (
              <Button
                data-testid="backtest-analyse-btn"
                onClick={analyse}
                disabled={riskLoading}
                variant="outline"
                className="rounded-none border-white text-white hover:bg-white hover:text-black h-10 font-section tracking-wider"
              >
                {riskLoading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <ShieldCheck className="w-4 h-4 mr-2" />}
                {riskLoading ? "ANALYSING…" : "AI RISK REVIEW"}
              </Button>
            )}
            {result && (
              <Button
                data-testid="backtest-stress-btn"
                onClick={stressTest}
                disabled={stressLoading}
                variant="outline"
                className="rounded-none border-amber-500 text-amber-400 hover:bg-amber-500 hover:text-black h-10 font-section tracking-wider"
              >
                {stressLoading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Activity className="w-4 h-4 mr-2" />}
                {stressLoading ? `STRESSING × ${stressIter}…` : `MONTE CARLO × ${stressIter}`}
              </Button>
            )}
          </div>
        </div>

        {result && (
          <>
            {/* KPIs */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <StatCard testid="bt-kpi-return" label="Return" value={`${fmt(ret)}%`} tone={retTone} sub={`final ₹${fmt(result.final_equity, 0)}`} />
              <StatCard testid="bt-kpi-sharpe" label="Sharpe" value={fmt(result.sharpe)} sub="ann. risk-adj." />
              <StatCard testid="bt-kpi-sortino" label="Sortino" value={fmt(result.sortino)} sub="downside-only" />
              <StatCard testid="bt-kpi-drawdown" label="Max DD" value={`${fmt(result.max_drawdown_pct)}%`} tone="loss" />
              <StatCard testid="bt-kpi-winrate" label="Win rate" value={`${fmt(result.win_rate_pct)}%`} sub={`${result.total_trades} trades`} />
            </div>

            {/* Equity curve */}
            <div className="panel p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="overline">Equity curve</div>
                <div className="font-mono-data text-xs txt-muted">
                  Profit factor {fmt(result.profit_factor)} · avg win ₹{fmt(result.avg_win, 0)} · avg loss ₹{fmt(result.avg_loss, 0)}
                </div>
              </div>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={result.equity_curve}>
                    <defs>
                      <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.18} />
                        <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="#27272a" strokeDasharray="2 4" vertical={false} />
                    <XAxis dataKey="date" stroke="#52525b" fontSize={10} tickFormatter={(v) => v.slice(5)} />
                    <YAxis stroke="#52525b" fontSize={10} domain={["dataMin", "dataMax"]} tickFormatter={(v) => Math.round(v / 1000) + "k"} />
                    <Tooltip
                      contentStyle={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 0, fontFamily: "JetBrains Mono" }}
                      formatter={(v) => `₹${fmt(v, 0)}`}
                    />
                    <Area type="monotone" dataKey="equity" stroke="#3b82f6" strokeWidth={1.5} fill="url(#eq)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <TradeLogTable trades={result.trades} />
              <AiRiskReviewPanel risk={risk} />
            </div>

            <StressTestPanel stress={stress} />
          </>
        )}
      </div>
    </AppShell>
  );
}
