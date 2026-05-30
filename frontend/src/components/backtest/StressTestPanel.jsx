import {
  ResponsiveContainer, BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine,
} from "recharts";

const fmt = (n, d = 2) =>
  (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

const TOOLTIP_STYLE = {
  background: "#18181b", border: "1px solid #27272a", borderRadius: 0, fontFamily: "JetBrains Mono",
};

const PERCENTILE_DEFS = [
  { k: "total_return_pct", label: "Return %", suffix: "%" },
  { k: "max_drawdown_pct", label: "Max DD %", suffix: "%", tone: "loss" },
  { k: "sharpe", label: "Sharpe", suffix: "" },
  { k: "sortino", label: "Sortino", suffix: "" },
  { k: "final_equity", label: "Final ₹", suffix: "", fmtFn: (v) => fmt(v, 0) },
];

const HISTOGRAM_DEFS = [
  { k: "max_drawdown_pct", title: "Drawdown distribution", color: "#ef4444" },
  { k: "total_return_pct", title: "Return distribution", color: "#10b981" },
];

function blowupTone(rate) {
  if (rate > 5) return "txt-loss";
  if (rate > 1) return "txt-warn";
  return "txt-profit";
}

function PercentileCard({ k, label, suffix, tone, fmtFn, metrics }) {
  const m = metrics[k];
  const fv = fmtFn || ((v) => fmt(v));
  return (
    <div className="panel panel-hover p-4">
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
}

function HistogramChart({ title, color, data }) {
  return (
    <div className="border border-[var(--border)] p-3">
      <div className="overline mb-2">{title}</div>
      <div className="h-44">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <CartesianGrid stroke="#27272a" strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="mid" stroke="#52525b" fontSize={10} tickFormatter={(v) => fmt(v, 1)} />
            <YAxis stroke="#52525b" fontSize={10} />
            <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => v + " paths"} labelFormatter={(v) => `≈ ${fmt(v, 2)}`} />
            <Bar dataKey="count" fill={color} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function WorstPathChart({ worstPath, capital }) {
  return (
    <div className="border border-[var(--border)] p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="overline">Worst path (max DD {worstPath.max_drawdown_pct}%)</div>
        <div className="font-mono-data text-xs txt-muted">{worstPath.equity_curve.length} bars</div>
      </div>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={worstPath.equity_curve}>
            <CartesianGrid stroke="#27272a" strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="step" stroke="#52525b" fontSize={10} />
            <YAxis stroke="#52525b" fontSize={10} tickFormatter={(v) => Math.round(v / 1000) + "k"} />
            <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => `₹${fmt(v, 0)}`} />
            <ReferenceLine y={capital} stroke="#52525b" strokeDasharray="2 4" />
            <Line type="monotone" dataKey="equity" stroke="#ef4444" strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default function StressTestPanel({ stress }) {
  if (!stress) return null;
  return (
    <div className="panel p-5 space-y-6" data-testid="stress-results">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="overline">Monte Carlo Stress Test</div>
          <div className="font-display text-3xl mt-1">
            Blow-up rate{" "}
            <span className={blowupTone(stress.blowup_rate_pct)}>{stress.blowup_rate_pct}%</span>
          </div>
          <div className="text-xs txt-muted font-mono-data mt-1">
            {stress.iterations} paths · block_size {stress.block_size} · slippage jitter ±{stress.slippage_jitter_bps}bps · {stress.bars_per_path} bars/path · DD &lt; {stress.blowup_threshold_pct}% counts as blow-up
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {PERCENTILE_DEFS.map((d) => (
          <PercentileCard key={d.k} {...d} metrics={stress.metrics} />
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {HISTOGRAM_DEFS.map((h) => (
          <HistogramChart key={h.k} title={h.title} color={h.color} data={stress.histograms[h.k]} />
        ))}
      </div>

      <WorstPathChart worstPath={stress.worst_path} capital={stress.capital} />
    </div>
  );
}
