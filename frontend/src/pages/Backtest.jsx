import { useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import StatCard from "@/components/StatCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Loader2, Play, ShieldCheck, Activity } from "lucide-react";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid, BarChart, Bar, LineChart, Line, ReferenceLine } from "recharts";
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
              {/* Trades */}
              <div className="panel p-5 lg:col-span-2">
                <div className="overline mb-3">Trade log · {result.trades.length}</div>
                <div className="max-h-96 overflow-auto border border-[var(--border)]">
                  <Table>
                    <TableHeader>
                      <TableRow className="border-[var(--border)]">
                        <TableHead className="overline">Date</TableHead>
                        <TableHead className="overline">Side</TableHead>
                        <TableHead className="overline text-right">Qty</TableHead>
                        <TableHead className="overline text-right">Price</TableHead>
                        <TableHead className="overline text-right">P&L</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {result.trades.map((t, i) => (
                        <TableRow key={`${t.date}-${t.side}-${i}`} className="border-[var(--border)]">
                          <TableCell className="font-mono-data text-xs">{t.date}</TableCell>
                          <TableCell className={`font-section text-xs ${t.side === "BUY" ? "txt-profit" : "txt-loss"}`}>{t.side}</TableCell>
                          <TableCell className="font-mono-data text-right">{t.qty}</TableCell>
                          <TableCell className="font-mono-data text-right">{fmt(t.price)}</TableCell>
                          <TableCell className={`font-mono-data text-right ${t.pnl > 0 ? "txt-profit" : t.pnl < 0 ? "txt-loss" : "txt-muted"}`}>
                            {t.pnl === null ? "—" : fmt(t.pnl)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </div>

              {/* Risk panel */}
              <div className="panel p-5">
                <div className="overline mb-3">AI risk review · Claude Sonnet 4.5</div>
                {!risk && (
                  <div className="txt-muted text-sm">Click "AI risk review" to get Claude's structured analysis.</div>
                )}
                {risk && (
                  <div data-testid="risk-review-output" className="space-y-4">
                    <div className="flex items-center gap-3">
                      <div className={`kpi-num text-5xl ${risk.verdict === "HIGH" ? "txt-loss" : risk.verdict === "MEDIUM" ? "txt-warn" : "txt-profit"}`}>
                        {risk.risk_score}
                      </div>
                      <div>
                        <div className="overline">Risk score</div>
                        <div className={`font-section text-lg ${risk.verdict === "HIGH" ? "txt-loss" : risk.verdict === "MEDIUM" ? "txt-warn" : "txt-profit"}`}>
                          {risk.verdict}
                        </div>
                      </div>
                    </div>
                    <p className="text-sm txt-secondary">{risk.summary}</p>
                    {risk.strengths?.length > 0 && (
                      <div>
                        <div className="overline mb-1.5">Strengths</div>
                        <ul className="text-sm space-y-1">
                          {risk.strengths.map((x) => <li key={`s-${x}`} className="flex gap-2"><span className="txt-profit">+</span>{x}</li>)}
                        </ul>
                      </div>
                    )}
                    {risk.concerns?.length > 0 && (
                      <div>
                        <div className="overline mb-1.5">Concerns</div>
                        <ul className="text-sm space-y-1">
                          {risk.concerns.map((x) => <li key={`c-${x}`} className="flex gap-2"><span className="txt-loss">−</span>{x}</li>)}
                        </ul>
                      </div>
                    )}
                    {risk.suggestions?.length > 0 && (
                      <div>
                        <div className="overline mb-1.5">Suggestions</div>
                        <ul className="text-sm space-y-1">
                          {risk.suggestions.map((x) => <li key={`g-${x}`} className="flex gap-2"><span className="txt-warn">→</span>{x}</li>)}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Monte Carlo stress test */}
            {stress && (
              <div className="panel p-5 space-y-6" data-testid="stress-results">
                <div className="flex items-center justify-between flex-wrap gap-3">
                  <div>
                    <div className="overline">Monte Carlo Stress Test</div>
                    <div className="font-display text-3xl mt-1">
                      Blow-up rate{" "}
                      <span className={stress.blowup_rate_pct > 5 ? "txt-loss" : stress.blowup_rate_pct > 1 ? "txt-warn" : "txt-profit"}>
                        {stress.blowup_rate_pct}%
                      </span>
                    </div>
                    <div className="text-xs txt-muted font-mono-data mt-1">
                      {stress.iterations} paths · block_size {stress.block_size} · slippage jitter ±{stress.slippage_jitter_bps}bps · {stress.bars_per_path} bars/path · DD &lt; {stress.blowup_threshold_pct}% counts as blow-up
                    </div>
                  </div>
                </div>

                {/* Percentile cards */}
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                  {[
                    { k: "total_return_pct", label: "Return %", suffix: "%" },
                    { k: "max_drawdown_pct", label: "Max DD %", suffix: "%", tone: "loss" },
                    { k: "sharpe", label: "Sharpe", suffix: "" },
                    { k: "sortino", label: "Sortino", suffix: "" },
                    { k: "final_equity", label: "Final ₹", suffix: "", fmtFn: (v) => fmt(v, 0) },
                  ].map(({ k, label, suffix, tone, fmtFn }) => {
                    const m = stress.metrics[k];
                    const fv = fmtFn || ((v) => fmt(v));
                    return (
                      <div key={k} className="panel panel-hover p-4">
                        <div className="overline">{label}</div>
                        <div className="font-mono-data text-xs mt-3 space-y-1">
                          <div className="flex justify-between"><span className="txt-muted">P5</span><span className={tone === "loss" ? "txt-loss" : ""}>{fv(m.p5)}{suffix}</span></div>
                          <div className="flex justify-between"><span className="txt-muted">P50</span><span className="text-white">{fv(m.p50)}{suffix}</span></div>
                          <div className="flex justify-between"><span className="txt-muted">P95</span><span>{fv(m.p95)}{suffix}</span></div>
                          <div className="flex justify-between border-t border-[var(--border)] pt-1 mt-1">
                            <span className="txt-muted">μ ± σ</span>
                            <span>{fv(m.mean)}±{fv(m.std)}</span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Distributions */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {[
                    { k: "max_drawdown_pct", title: "Drawdown distribution", color: "#ef4444" },
                    { k: "total_return_pct", title: "Return distribution", color: "#10b981" },
                  ].map(({ k, title, color }) => (
                    <div key={k} className="border border-[var(--border)] p-3">
                      <div className="overline mb-2">{title}</div>
                      <div className="h-44">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={stress.histograms[k]}>
                            <CartesianGrid stroke="#27272a" strokeDasharray="2 4" vertical={false} />
                            <XAxis dataKey="mid" stroke="#52525b" fontSize={10} tickFormatter={(v) => fmt(v, 1)} />
                            <YAxis stroke="#52525b" fontSize={10} />
                            <Tooltip
                              contentStyle={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 0, fontFamily: "JetBrains Mono" }}
                              formatter={(v) => v + " paths"}
                              labelFormatter={(v) => `≈ ${fmt(v, 2)}`}
                            />
                            <Bar dataKey="count" fill={color} />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Worst path */}
                <div className="border border-[var(--border)] p-3">
                  <div className="flex items-center justify-between mb-2">
                    <div className="overline">Worst path (max DD {stress.worst_path.max_drawdown_pct}%)</div>
                    <div className="font-mono-data text-xs txt-muted">{stress.worst_path.equity_curve.length} bars</div>
                  </div>
                  <div className="h-48">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={stress.worst_path.equity_curve}>
                        <CartesianGrid stroke="#27272a" strokeDasharray="2 4" vertical={false} />
                        <XAxis dataKey="step" stroke="#52525b" fontSize={10} />
                        <YAxis stroke="#52525b" fontSize={10} tickFormatter={(v) => Math.round(v / 1000) + "k"} />
                        <Tooltip
                          contentStyle={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 0, fontFamily: "JetBrains Mono" }}
                          formatter={(v) => `₹${fmt(v, 0)}`}
                        />
                        <ReferenceLine y={stress.capital} stroke="#52525b" strokeDasharray="2 4" />
                        <Line type="monotone" dataKey="equity" stroke="#ef4444" strokeWidth={1.5} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
