import { useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { AlertTriangle, Loader2, ShieldCheck, Zap } from "lucide-react";
import { toast } from "sonner";

const fmt = (n, d = 2) =>
  (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

const initialForm = {
  broker: "zerodha", symbol: "IDEA", side: "BUY", qty: 1,
  order_type: "LIMIT", product: "CNC", price: "",
};

export default function LiveOrderTicket({ liveBrokers, killSwitch, onPlaced }) {
  const [form, setForm] = useState(initialForm);
  const [preview, setPreview] = useState(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setPreview(null);
    setTyped("");
  };

  const runPreview = async () => {
    setBusy(true);
    try {
      const payload = {
        broker: form.broker,
        symbol: form.symbol.toUpperCase(),
        side: form.side,
        qty: Number(form.qty),
        order_type: form.order_type,
        product: form.product,
      };
      if (form.order_type === "LIMIT") payload.price = Number(form.price);
      const { data } = await api.post("/orders/live/preview", payload);
      setPreview(data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Preview failed");
    } finally {
      setBusy(false);
    }
  };

  const execute = async () => {
    if (typed !== "LIVE") {
      toast.error('Type "LIVE" in caps to confirm');
      return;
    }
    setBusy(true);
    try {
      const payload = {
        broker: form.broker, symbol: form.symbol.toUpperCase(),
        side: form.side, qty: Number(form.qty),
        order_type: form.order_type, product: form.product,
        confirm_token: preview.confirm_token, typed_confirm: "LIVE",
      };
      if (form.order_type === "LIMIT") payload.price = Number(form.price);
      const { data } = await api.post("/orders/live/execute", payload);
      toast.success(`LIVE ${form.side} ${form.qty} ${form.symbol} → ${data.broker_order_id}`);
      reset();
      setForm(initialForm);
      onPlaced?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Execute failed");
    } finally {
      setBusy(false);
    }
  };

  const hasLiveBroker = liveBrokers.length > 0;

  return (
    <div className="panel p-5 border-red-500/40" data-testid="live-order-ticket">
      <div className="flex items-center gap-2 mb-3">
        <Zap className="w-4 h-4 txt-loss" />
        <div className="overline">Live order · real money</div>
        <span className="ml-auto text-xs font-mono-data txt-loss border border-red-500/40 px-2 py-0.5">REAL</span>
      </div>
      {!hasLiveBroker && (
        <div className="border border-amber-500/40 bg-amber-500/5 p-3 text-xs txt-warn mb-3">
          No live broker connections. Use the wizard at /brokers to link Zerodha or Upstox.
        </div>
      )}
      {killSwitch && (
        <div className="border border-red-500/40 bg-red-500/5 p-3 text-xs txt-loss mb-3">
          KILL SWITCH ACTIVE — live orders disabled. Toggle off in Settings.
        </div>
      )}
      <div className="border border-zinc-700 bg-zinc-900/40 p-3 text-xs txt-secondary mb-3">
        <strong className="text-white">Tip:</strong> for symbols outside the mock universe (e.g. IDEA, YESBANK),
        use <strong className="font-section">LIMIT</strong> orders with your own price so the notional
        check doesn't depend on Kite's paid market-data add-on.
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div>
          <Label className="overline">Broker</Label>
          <Select value={form.broker} onValueChange={(v) => setForm({ ...form, broker: v })}>
            <SelectTrigger data-testid="live-broker-select" className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {liveBrokers.map((b) => <SelectItem key={b} value={b}>{b.toUpperCase()}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="overline">Symbol</Label>
          <Input data-testid="live-symbol-input" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
        </div>
        <div>
          <Label className="overline">Side</Label>
          <Select value={form.side} onValueChange={(v) => setForm({ ...form, side: v })}>
            <SelectTrigger data-testid="live-side-select" className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="BUY">BUY</SelectItem>
              <SelectItem value="SELL">SELL</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="overline">Qty</Label>
          <Input data-testid="live-qty-input" type="number" value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })} className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
        </div>
        <div>
          <Label className="overline">Type</Label>
          <Select value={form.order_type} onValueChange={(v) => setForm({ ...form, order_type: v })}>
            <SelectTrigger data-testid="live-type-select" className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="MARKET">MARKET</SelectItem>
              <SelectItem value="LIMIT">LIMIT</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="overline">Product</Label>
          <Select value={form.product} onValueChange={(v) => setForm({ ...form, product: v })}>
            <SelectTrigger data-testid="live-product-select" className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="CNC">CNC (delivery)</SelectItem>
              <SelectItem value="MIS">MIS (intraday)</SelectItem>
              <SelectItem value="NRML">NRML (carry)</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {form.order_type === "LIMIT" && (
          <div className="col-span-2 md:col-span-2">
            <Label className="overline">Limit price ₹</Label>
            <Input data-testid="live-price-input" type="number" step="0.05" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
          </div>
        )}
      </div>
      <Button
        data-testid="live-review-btn"
        disabled={busy || killSwitch || !hasLiveBroker}
        onClick={runPreview}
        className="mt-4 w-full h-11 rounded-none bg-red-500 hover:bg-red-600 text-white font-section tracking-wider"
      >
        {busy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Zap className="w-4 h-4 mr-2" />}
        REVIEW LIVE ORDER
      </Button>

      <Dialog open={!!preview} onOpenChange={(v) => !v && reset()}>
        <DialogContent data-testid="live-confirm-dialog" className="rounded-none bg-[var(--bg-surface)] border-red-500 text-white max-w-md">
          <DialogHeader>
            <DialogTitle className="font-display text-2xl flex items-center gap-2 txt-loss">
              <AlertTriangle className="w-5 h-5" /> Confirm LIVE order
            </DialogTitle>
          </DialogHeader>
          {preview && (
            <div className="space-y-3 text-sm font-mono-data">
              <div className="flex justify-between border-b border-[var(--border)] pb-2"><span className="txt-muted">Broker</span><span className="font-section">{preview.broker.toUpperCase()}</span></div>
              <div className="flex justify-between border-b border-[var(--border)] pb-2"><span className="txt-muted">Side / Qty</span><span className={preview.side === "BUY" ? "txt-profit" : "txt-loss"}>{preview.side} × {preview.qty}</span></div>
              <div className="flex justify-between border-b border-[var(--border)] pb-2"><span className="txt-muted">Symbol</span><span>{preview.symbol}</span></div>
              <div className="flex justify-between border-b border-[var(--border)] pb-2"><span className="txt-muted">Est. price</span><span>₹{fmt(preview.estimated_price)}</span></div>
              <div className="flex justify-between border-b border-[var(--border)] pb-2"><span className="txt-muted">Notional</span><span>₹{fmt(preview.notional, 0)}</span></div>
              <div className="flex justify-between text-xs"><span className="txt-muted">Cap / day used</span><span>₹{fmt(preview.notional_cap, 0)} / {preview.daily_count}+1 of {preview.daily_limit}</span></div>
              <div className="border border-red-500/40 bg-red-500/5 p-3 mt-3">
                <div className="flex items-center gap-2 mb-2 txt-loss">
                  <ShieldCheck className="w-4 h-4" />
                  <span className="font-section text-xs tracking-wider">Type "LIVE" in caps to confirm</span>
                </div>
                <Input
                  data-testid="live-typed-confirm"
                  autoFocus
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  placeholder="LIVE"
                  className="rounded-none bg-[var(--bg-page)] border-red-500/60 font-mono-data text-center"
                />
                <div className="text-xs txt-muted mt-2">
                  Token expires in {preview.expires_in}s. Real money will move when you click EXECUTE.
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button data-testid="live-cancel-btn" variant="ghost" onClick={reset} disabled={busy} className="rounded-none">
              CANCEL
            </Button>
            <Button
              data-testid="live-execute-btn"
              onClick={execute}
              disabled={busy || typed !== "LIVE"}
              className="rounded-none bg-red-500 hover:bg-red-600 text-white font-section tracking-wider"
            >
              {busy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Zap className="w-4 h-4 mr-2" />}
              EXECUTE LIVE ORDER
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
