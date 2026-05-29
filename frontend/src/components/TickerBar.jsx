import useTickStream from "@/lib/useTickStream";

const fmt = (n, d = 2) =>
  (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

export default function TickerBar({ symbols = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "HDFCBANK", "INFY"] }) {
  const { ticks, connected } = useTickStream(symbols);

  return (
    <div className="border-b border-[var(--border)] bg-[var(--bg-surface)] flex items-stretch text-xs">
      <div className="px-4 py-2 border-r border-[var(--border)] flex items-center gap-2">
        <span className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-emerald-500" : "bg-zinc-600"}`} />
        <span className="overline">{connected ? "LIVE" : "OFFLINE"}</span>
      </div>
      <div className="flex-1 flex items-stretch overflow-x-auto" data-testid="ticker-bar">
        {symbols.map((s) => {
          const t = ticks[s];
          const up = (t?.change ?? 0) >= 0;
          return (
            <div key={s} className="px-4 py-2 border-r border-[var(--border)] flex items-center gap-3 whitespace-nowrap" data-testid={`ticker-${s}`}>
              <span className="font-section text-[11px] tracking-wider">{s}</span>
              <span className="font-mono-data">{t ? fmt(t.ltp) : "—"}</span>
              {t && (
                <span className={`font-mono-data text-[11px] ${up ? "txt-profit" : "txt-loss"}`}>
                  {up ? "▲" : "▼"} {fmt(Math.abs(t.change))} ({up ? "+" : ""}{fmt(t.change_pct, 2)}%)
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
