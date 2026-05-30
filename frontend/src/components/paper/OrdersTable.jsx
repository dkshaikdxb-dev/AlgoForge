import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const fmt = (n, d = 2) =>
  (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

export default function OrdersTable({ orders }) {
  return (
    <div className="panel p-5">
      <div className="overline mb-3">Recent orders</div>
      <div className="max-h-72 overflow-auto">
        <Table>
          <TableHeader>
            <TableRow className="border-[var(--border)]">
              <TableHead className="overline">Time</TableHead>
              <TableHead className="overline">Symbol</TableHead>
              <TableHead className="overline">Side</TableHead>
              <TableHead className="overline text-right">Qty</TableHead>
              <TableHead className="overline text-right">Price</TableHead>
              <TableHead className="overline">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {orders.length === 0 && (
              <TableRow className="border-[var(--border)]">
                <TableCell colSpan={6} className="text-center txt-muted py-6">No orders yet.</TableCell>
              </TableRow>
            )}
            {orders.map((o) => (
              <TableRow key={o.id} className="border-[var(--border)]">
                <TableCell className="font-mono-data text-xs">{o.created_at?.slice(11, 19)}</TableCell>
                <TableCell className="font-section">{o.symbol}</TableCell>
                <TableCell className={`font-section text-xs ${o.side === "BUY" ? "txt-profit" : "txt-loss"}`}>{o.side}</TableCell>
                <TableCell className="font-mono-data text-right">{o.qty}</TableCell>
                <TableCell className="font-mono-data text-right">{fmt(o.price)}</TableCell>
                <TableCell className="font-mono-data text-xs txt-profit">{o.status}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
