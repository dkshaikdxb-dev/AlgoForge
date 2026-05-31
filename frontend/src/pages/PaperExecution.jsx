import { useEffect, useState } from "react";
import api from "@/lib/api";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import StatCard from "@/components/StatCard";
import OrdersTable from "@/components/paper/OrdersTable";
import PositionsTable from "@/components/paper/PositionsTable";
import LiveOrderTicket from "@/components/paper/LiveOrderTicket";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { ShieldAlert, ArrowDownUp } from "lucide-react";
import { toast } from "sonner";
import MultiLegBuilder from "@/components/MultiLegBuilder";

const fmt = (n, d = 2) =>
  (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

export default function PaperExecution() {
  const [symbols, setSymbols] = useState([]);
  const [positions, setPositions] = useState([]);
  const [orders, setOrders] = useState([]);
  const [liveOrders, setLiveOrders] = useState([]);
  const [liveBrokers, setLiveBrokers] = useState([]);
  const [totals, setTotals] = useState({ total_pnl: 0, exposure: 0 });
  const [risk, setRisk] = useState({ kill_switch: false });

  // form
  const [symbol, setSymbol] = useState("NIFTY");
  const [side, setSide] = useState("BUY");
  const [qty, setQty] = useState(50);
  const [instrumentType, setInstrumentType] = useState("EQ");
  const [optStrike, setOptStrike] = useState("");
  const [optKind, setOptKind] = useState("CE");

  const load = async () => {
    const [s, p, o, r, lb, lo] = await Promise.all([
      api.get("/market/symbols"),
      api.get("/paper/positions"),
      api.get("/paper/orders"),
      api.get("/risk/limits"),
      api.get("/brokers"),
      api.get("/orders/live/orders").catch(() => ({ data: { orders: [] } })),
    ]);
    setSymbols(s.data.symbols);
    setPositions(p.data.positions);
    setTotals({ total_pnl: p.data.total_pnl, exposure: p.data.exposure });
    setOrders(o.data.orders);
    setRisk(r.data);
    setLiveBrokers(lb.data.items.filter((b) => b.connected && b.status === "live").map((b) => b.name));
    setLiveOrders(lo.data.orders || []);
  };

  useEffect(() => {
    load();
  }, []);

  const placeOrder = async () => {
    try {
      const payload = {
        symbol,
        side,
        qty: Number(qty),
        order_type: "MARKET",
        instrument_type: instrumentType,
      };
      if (instrumentType === "OPT") {
        payload.option_strike = Number(optStrike);
        payload.option_kind = optKind;
      }
      const { data } = await api.post("/paper/order", payload);
      if (data.idempotent_replay) {
        toast.info(`${side} ${qty} ${symbol} — replay (already filled within 24h)`);
      } else {
        toast.success(`${side} ${qty} ${symbol} filled (paper)`);
      }
      load();
    } catch (e) {
      const status = e?.response?.status;
      const detail = e?.response?.data?.detail || "Order rejected";
      if (status === 409) {
        toast.warning(detail, {
          action: {
            label: "Force",
            onClick: async () => {
              try {
                await api.post("/paper/order?force=true", {
                  symbol,
                  side,
                  qty: Number(qty),
                  order_type: "MARKET",
                  instrument_type: instrumentType,
                  ...(instrumentType === "OPT"
                    ? { option_strike: Number(optStrike), option_kind: optKind }
                    : {}),
                });
                toast.success("Forced order placed");
                load();
              } catch {
                toast.error("Force order failed");
              }
            },
          },
        });
      } else {
        toast.error(detail);
      }
    }
  };

  const flatten = async () => {
    try {
      const { data } = await api.post("/paper/flatten");
      toast.success(`Flattened ${data.closed} positions`);
      load();
    } catch {
      toast.error("Flatten failed");
    }
  };

  const toggleKill = async (val) => {
    try {
      await api.put("/risk/limits", { ...risk, kill_switch: val });
      toast[val ? "warning" : "success"](val ? "Kill switch ACTIVE — orders blocked" : "Kill switch released");
      load();
    } catch {
      toast.error("Could not toggle kill switch");
    }
  };

  const pnlTone = totals.total_pnl > 0 ? "profit" : totals.total_pnl < 0 ? "loss" : "neutral";

  return (
    <AppShell>
      <PageHeader
        overline="Execution"
        title="Paper Trading Console"
        description="Simulate orders on live mock data. Multi-leg options supported. Kill switch halts new orders instantly."
        actions={
          <div className="flex items-center gap-3 panel px-3 py-2">
            <ShieldAlert className={`w-4 h-4 ${risk.kill_switch ? "txt-loss" : "txt-muted"}`} />
            <div className="overline">Kill switch</div>
            <Switch data-testid="paper-kill-switch" checked={!!risk.kill_switch} onCheckedChange={toggleKill} />
          </div>
        }
      />

      <div className="p-8 space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard testid="paper-kpi-pnl" label="Open P&L" value={`₹${fmt(totals.total_pnl)}`} tone={pnlTone} />
          <StatCard testid="paper-kpi-exposure" label="Exposure" value={`₹${fmt(totals.exposure, 0)}`} />
          <StatCard testid="paper-kpi-positions" label="Open positions" value={positions.length} />
          <StatCard testid="paper-kpi-mode" label="Mode" value="PAPER" sub="live trading: pending broker keys" />
        </div>

        {/* Order ticket */}
        <div className="panel p-5">
          <div className="overline mb-3">Order ticket</div>
          <div className="grid grid-cols-2 md:grid-cols-6 gap-4 items-end">
            <div>
              <Label className="overline">Symbol</Label>
              <Select value={symbol} onValueChange={setSymbol}>
                <SelectTrigger data-testid="order-symbol-select" className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="rounded-none bg-[var(--bg-surface)] border-[var(--border)]">
                  {symbols.map((s) => <SelectItem key={s.symbol} value={s.symbol}>{s.symbol}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="overline">Side</Label>
              <Select value={side} onValueChange={setSide}>
                <SelectTrigger data-testid="order-side-select" className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="rounded-none bg-[var(--bg-surface)] border-[var(--border)]">
                  <SelectItem value="BUY">BUY</SelectItem>
                  <SelectItem value="SELL">SELL</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="overline">Type</Label>
              <Select value={instrumentType} onValueChange={setInstrumentType}>
                <SelectTrigger data-testid="order-type-select" className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="rounded-none bg-[var(--bg-surface)] border-[var(--border)]">
                  <SelectItem value="EQ">Equity</SelectItem>
                  <SelectItem value="OPT">Option</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="overline">Qty</Label>
              <Input data-testid="order-qty-input" type="number" value={qty} onChange={(e) => setQty(e.target.value)} className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
            </div>
            {instrumentType === "OPT" && (
              <>
                <div>
                  <Label className="overline">Strike</Label>
                  <Input data-testid="order-strike-input" type="number" value={optStrike} onChange={(e) => setOptStrike(e.target.value)} className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
                </div>
                <div>
                  <Label className="overline">CE/PE</Label>
                  <Select value={optKind} onValueChange={setOptKind}>
                    <SelectTrigger data-testid="order-kind-select" className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="rounded-none bg-[var(--bg-surface)] border-[var(--border)]">
                      <SelectItem value="CE">CE (Call)</SelectItem>
                      <SelectItem value="PE">PE (Put)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}
            <Button
              data-testid="order-place-btn"
              onClick={placeOrder}
              disabled={risk.kill_switch}
              className={`rounded-none h-10 font-section tracking-wider ${side === "BUY" ? "bg-emerald-500 hover:bg-emerald-400 text-black" : "bg-red-500 hover:bg-red-400 text-white"}`}
            >
              <ArrowDownUp className="w-4 h-4 mr-2" /> PLACE {side}
            </Button>
          </div>
          {risk.kill_switch && (
            <div className="mt-3 text-xs txt-loss">Kill switch active — new orders blocked.</div>
          )}
        </div>

        {/* Multi-leg builder */}
        <MultiLegBuilder symbols={symbols} disabled={risk.kill_switch} onPlaced={load} />

        {/* LIVE order ticket — only renders properly once a live broker exists */}
        <LiveOrderTicket
          liveBrokers={liveBrokers}
          killSwitch={risk.kill_switch}
          onPlaced={load}
        />

        <PositionsTable positions={positions} onFlatten={flatten} />

        <OrdersTable orders={orders} />

        {liveOrders.length > 0 && (
          <div className="panel p-5 border-red-500/40" data-testid="live-orders-section">
            <div className="overline mb-3 txt-loss">Live orders · {liveOrders.length}</div>
            <div className="space-y-2 max-h-72 overflow-auto text-xs font-mono-data">
              {liveOrders.map((o) => (
                <div key={o.broker_order_id || o.id} data-testid={`live-order-row`} className="flex items-center justify-between border-b border-[var(--border)] pb-2">
                  <span className="txt-secondary">{o.created_at?.slice(11, 19)}</span>
                  <span className="font-section">{o.broker?.toUpperCase()}</span>
                  <span className={o.side === "BUY" ? "txt-profit" : "txt-loss"}>{o.side} {o.qty} {o.symbol}</span>
                  <span className="txt-muted">{o.broker_order_id}</span>
                  <span className="font-section">{o.status}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
