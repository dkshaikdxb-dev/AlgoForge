import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const fmt = (n, d = 2) =>
  (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

export default function TradeLogTable({ trades }) {
  return (
    <div className="panel p-5 lg:col-span-2" data-testid="bt-trade-log">
      <div className="overline mb-3">Trade log · {trades.length}</div>
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
            {trades.map((t, i) => (
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
  );
}
