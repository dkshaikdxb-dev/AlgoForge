import { useEffect, useState } from "react";
import api from "@/lib/api";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import StatCard from "@/components/StatCard";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Loader2, Sparkles, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

const fmt = (n, d = 0) =>
  (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

const heatClass = (score) => {
  if (score >= 0.8) return "heat-4";
  if (score >= 0.6) return "heat-3";
  if (score >= 0.4) return "heat-2";
  if (score >= 0.2) return "heat-1";
  return "heat-0";
};

export default function TrapDetection() {
  const [symbols, setSymbols] = useState([]);
  const [symbol, setSymbol] = useState("NIFTY");
  const [expiryDays, setExpiryDays] = useState(7);
  const [scan, setScan] = useState(null);
  const [loading, setLoading] = useState(false);
  const [explain, setExplain] = useState(null);
  const [explainLoading, setExplainLoading] = useState(false);

  useEffect(() => {
    api.get("/market/symbols").then((r) => setSymbols(r.data.symbols));
  }, []);

  const runScan = async () => {
    setLoading(true);
    setExplain(null);
    try {
      const { data } = await api.get("/trap/scan", { params: { symbol, expiry_days: expiryDays } });
      setScan(data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Scan failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    runScan();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, expiryDays]);

  const askClaude = async () => {
    if (!scan) return;
    setExplainLoading(true);
    try {
      const { data } = await api.post("/trap/explain", { scan });
      setExplain(data);
    } catch {
      toast.error("Claude explanation failed");
    } finally {
      setExplainLoading(false);
    }
  };

  const score = scan?.overall_trap_score ?? 0;
  const scoreTone = score > 0.7 ? "loss" : score > 0.4 ? "warn" : "profit";

  return (
    <AppShell>
      <PageHeader
        overline="AI / Quant Engine"
        title="Option Writers' Trap Detection"
        description="Spot strikes where heavy OI buildup may force option writers into a squeeze. Get hedging plays from Claude Sonnet 4.5."
        actions={
          <Button
            data-testid="trap-explain-btn"
            onClick={askClaude}
            disabled={!scan || explainLoading}
            className="rounded-none bg-white text-black hover:bg-zinc-200 font-section tracking-wider"
          >
            {explainLoading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Sparkles className="w-4 h-4 mr-2" />}
            EXPLAIN WITH AI
          </Button>
        }
      />

      <div className="p-8 space-y-6">
        {/* Controls */}
        <div className="panel p-5">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 items-end">
            <div>
              <Label className="overline">Symbol</Label>
              <Select value={symbol} onValueChange={setSymbol}>
                <SelectTrigger data-testid="trap-symbol-select" className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="rounded-none bg-[var(--bg-surface)] border-[var(--border)]">
                  {symbols.map((s) => <SelectItem key={s.symbol} value={s.symbol}>{s.symbol} · {s.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="overline">Expiry (days)</Label>
              <Select value={String(expiryDays)} onValueChange={(v) => setExpiryDays(Number(v))}>
                <SelectTrigger data-testid="trap-expiry-select" className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="rounded-none bg-[var(--bg-surface)] border-[var(--border)]">
                  {[3, 7, 14, 30].map((d) => <SelectItem key={d} value={String(d)}>{d}D</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <Button
              data-testid="trap-rescan-btn"
              onClick={runScan}
              disabled={loading}
              variant="outline"
              className="rounded-none border-white text-white hover:bg-white hover:text-black h-10"
            >
              {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <AlertTriangle className="w-4 h-4 mr-2" />}
              RE-SCAN
            </Button>
          </div>
        </div>

        {scan && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <StatCard testid="trap-kpi-score" label="Overall trap score" value={`${(score * 100).toFixed(0)}%`} tone={scoreTone} />
              <StatCard testid="trap-kpi-spot" label="Spot" value={fmt(scan.spot, 2)} sub={`ATM ${fmt(scan.atm)}`} />
              <StatCard testid="trap-kpi-range" label="20D Range" value={`${fmt(scan.range_20d.low)} – ${fmt(scan.range_20d.high)}`} sub={`ATR ${scan.range_20d.atr}`} />
              <StatCard testid="trap-kpi-expiry" label="Expiry" value={scan.expiry} sub={`${expiryDays} days out`} />
            </div>

            {/* Suggestions */}
            {scan.suggestions?.length > 0 && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {scan.suggestions.map((s, i) => (
                  <div key={`${s.side}-${s.strike}`} data-testid={`trap-suggestion-${i}`} className={`panel p-5 border-l-4 ${s.level === "HIGH" ? "border-l-red-500" : "border-l-amber-500"}`}>
                    <div className="flex items-center justify-between">
                      <div className={`overline ${s.level === "HIGH" ? "txt-loss" : "txt-warn"}`}>
                        {s.level} · {s.side === "CE" ? "Call writers" : "Put writers"}
                      </div>
                      <div className="font-mono-data font-semibold">{s.strike}</div>
                    </div>
                    <div className="font-section text-lg mt-2">{s.headline}</div>
                    <p className="text-sm txt-secondary mt-2">{s.action}</p>
                  </div>
                ))}
              </div>
            )}

            {/* AI explanation */}
            {explain && (
              <div data-testid="trap-ai-explanation" className="panel p-6 border-l-4 border-l-blue-500">
                <div className="overline mb-2">Claude Sonnet 4.5 commentary</div>
                <div className="font-display text-2xl mb-2">{explain.headline}</div>
                <p className="txt-secondary text-sm leading-relaxed">{explain.explanation}</p>
                {explain.hedging_playbook?.length > 0 && (
                  <div className="mt-4">
                    <div className="overline mb-1.5">Hedging playbook</div>
                    <ul className="text-sm space-y-1">
                      {explain.hedging_playbook.map((x) => <li key={`pb-${x.slice(0, 30)}`} className="flex gap-2"><span className="txt-warn">→</span>{x}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {/* Heatmap table */}
            <div className="panel p-5">
              <div className="overline mb-3">Strike-level trap heatmap</div>
              <div className="overflow-auto border border-[var(--border)]">
                <Table>
                  <TableHeader>
                    <TableRow className="border-[var(--border)]">
                      <TableHead className="overline">PE Trap</TableHead>
                      <TableHead className="overline text-right">PE OI</TableHead>
                      <TableHead className="overline text-right">PE Δ OI</TableHead>
                      <TableHead className="overline text-right">PE IV</TableHead>
                      <TableHead className="overline text-center">Strike</TableHead>
                      <TableHead className="overline text-right">CE IV</TableHead>
                      <TableHead className="overline text-right">CE Δ OI</TableHead>
                      <TableHead className="overline text-right">CE OI</TableHead>
                      <TableHead className="overline">CE Trap</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {scan.rows.map((r) => {
                      const isAtm = r.strike === scan.atm;
                      return (
                        <TableRow key={r.strike} className={`border-[var(--border)] ${isAtm ? "bg-[var(--bg-surface-2)]" : ""}`} data-testid={`trap-row-${r.strike}`}>
                          <TableCell className={`${heatClass(r.pe_trap)} font-mono-data text-xs w-20`}>{(r.pe_trap * 100).toFixed(0)}%</TableCell>
                          <TableCell className="font-mono-data text-right text-xs">{fmt(r.pe_oi)}</TableCell>
                          <TableCell className={`font-mono-data text-right text-xs ${r.pe_oi_change > 0 ? "txt-profit" : "txt-loss"}`}>{r.pe_oi_change > 0 ? "+" : ""}{fmt(r.pe_oi_change)}</TableCell>
                          <TableCell className="font-mono-data text-right text-xs txt-secondary">{r.pe_iv}%</TableCell>
                          <TableCell className={`font-display text-center text-lg ${isAtm ? "text-white" : ""}`}>{r.strike}</TableCell>
                          <TableCell className="font-mono-data text-right text-xs txt-secondary">{r.ce_iv}%</TableCell>
                          <TableCell className={`font-mono-data text-right text-xs ${r.ce_oi_change > 0 ? "txt-profit" : "txt-loss"}`}>{r.ce_oi_change > 0 ? "+" : ""}{fmt(r.ce_oi_change)}</TableCell>
                          <TableCell className="font-mono-data text-right text-xs">{fmt(r.ce_oi)}</TableCell>
                          <TableCell className={`${heatClass(r.ce_trap)} font-mono-data text-xs w-20`}>{(r.ce_trap * 100).toFixed(0)}%</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
              <div className="flex items-center gap-3 mt-3 text-xs txt-muted">
                <span>Trap heat scale:</span>
                <span className="px-2 py-0.5 heat-0 border border-[var(--border)]">0%</span>
                <span className="px-2 py-0.5 heat-1">20%</span>
                <span className="px-2 py-0.5 heat-2">40%</span>
                <span className="px-2 py-0.5 heat-3">60%</span>
                <span className="px-2 py-0.5 heat-4">80%+</span>
              </div>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
