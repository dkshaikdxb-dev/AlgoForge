import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { X } from "lucide-react";

const fmt = (n, d = 2) =>
  (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

const pnlClass = (v) => (v > 0 ? "txt-profit" : v < 0 ? "txt-loss" : "txt-muted");

export default function PositionsTable({ positions, onFlatten }) {
  return (
    <div className="panel p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="overline">Open positions</div>
        {positions.length > 0 && (
          <Button data-testid="paper-flatten-btn" variant="ghost" size="sm" onClick={onFlatten} className="rounded-none text-zinc-400 hover:text-red-400">
            <X className="w-4 h-4 mr-1" /> FLATTEN ALL
          </Button>
        )}
      </div>
      <Table>
        <TableHeader>
          <TableRow className="border-[var(--border)]">
            <TableHead className="overline">Symbol</TableHead>
            <TableHead className="overline">Type</TableHead>
            <TableHead className="overline text-right">Qty</TableHead>
            <TableHead className="overline text-right">Avg</TableHead>
            <TableHead className="overline text-right">LTP</TableHead>
            <TableHead className="overline text-right">P&L</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {positions.length === 0 && (
            <TableRow className="border-[var(--border)]">
              <TableCell colSpan={6} className="text-center txt-muted py-6">No open positions.</TableCell>
            </TableRow>
          )}
          {positions.map((p) => (
            <TableRow key={p.id} className="border-[var(--border)]" data-testid={`position-${p.id}`}>
              <TableCell className="font-section">{p.symbol}</TableCell>
              <TableCell className="font-mono-data text-xs txt-secondary">
                {p.instrument_type === "OPT" ? `${p.option_strike} ${p.option_kind}` : "EQ"}
              </TableCell>
              <TableCell className={`font-mono-data text-right ${p.qty > 0 ? "txt-profit" : "txt-loss"}`}>{p.qty}</TableCell>
              <TableCell className="font-mono-data text-right">{fmt(p.avg_price)}</TableCell>
              <TableCell className="font-mono-data text-right">{fmt(p.ltp)}</TableCell>
              <TableCell className={`font-mono-data text-right ${pnlClass(p.pnl)}`}>{fmt(p.pnl)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
