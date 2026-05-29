import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Layers, Plus, Trash2, Loader2, Wand2 } from "lucide-react";
import { toast } from "sonner";

const PRESETS = [
  { id: "long-straddle", name: "Long Straddle", legs: (atm, step) => [
    { side: "BUY", option_kind: "CE", strikeDelta: 0 },
    { side: "BUY", option_kind: "PE", strikeDelta: 0 },
  ]},
  { id: "short-straddle", name: "Short Straddle", legs: () => [
    { side: "SELL", option_kind: "CE", strikeDelta: 0 },
    { side: "SELL", option_kind: "PE", strikeDelta: 0 },
  ]},
  { id: "long-strangle", name: "Long Strangle", legs: () => [
    { side: "BUY", option_kind: "CE", strikeDelta: 2 },
    { side: "BUY", option_kind: "PE", strikeDelta: -2 },
  ]},
  { id: "iron-condor", name: "Iron Condor", legs: () => [
    { side: "SELL", option_kind: "CE", strikeDelta: 2 },
    { side: "BUY",  option_kind: "CE", strikeDelta: 4 },
    { side: "SELL", option_kind: "PE", strikeDelta: -2 },
    { side: "BUY",  option_kind: "PE", strikeDelta: -4 },
  ]},
  { id: "bull-call-spread", name: "Bull Call Spread", legs: () => [
    { side: "BUY",  option_kind: "CE", strikeDelta: 0 },
    { side: "SELL", option_kind: "CE", strikeDelta: 2 },
  ]},
  { id: "bear-put-spread", name: "Bear Put Spread", legs: () => [
    { side: "BUY",  option_kind: "PE", strikeDelta: 0 },
    { side: "SELL", option_kind: "PE", strikeDelta: -2 },
  ]},
];

export default function MultiLegBuilder({ symbols, onPlaced, disabled }) {
  const [symbol, setSymbol] = useState("NIFTY");
  const [qty, setQty] = useState(50);
  const [chain, setChain] = useState(null);
  const [legs, setLegs] = useState([]);
  const [name, setName] = useState("Long Straddle");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!symbol) return;
    api.get("/market/options-chain", { params: { symbol } }).then(({ data }) => setChain(data));
  }, [symbol]);

  const applyPreset = (preset) => {
    if (!chain) return;
    const built = preset.legs(chain.atm, chain.step).map((l) => ({
      side: l.side,
      instrument_type: "OPT",
      symbol,
      qty: Number(qty),
      option_kind: l.option_kind,
      option_strike: chain.atm + l.strikeDelta * chain.step,
    }));
    setLegs(built);
    setName(preset.name);
  };

  const addCustomLeg = () => {
    if (!chain) return;
    setLegs((prev) => [
      ...prev,
      {
        side: "BUY",
        instrument_type: "OPT",
        symbol,
        qty: Number(qty),
        option_kind: "CE",
        option_strike: chain.atm,
      },
    ]);
  };

  const updateLeg = (i, patch) => {
    setLegs((prev) => prev.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  };

  const removeLeg = (i) => {
    setLegs((prev) => prev.filter((_, idx) => idx !== i));
  };

  const place = async () => {
    if (legs.length === 0) {
      toast.error("Add at least one leg");
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.post("/paper/order/multi-leg", { name, legs });
      toast.success(`${name}: ${data.orders.length} legs filled`);
      setLegs([]);
      onPlaced?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Multi-leg order rejected");
    } finally {
      setBusy(false);
    }
  };

  const strikeOptions = chain?.rows?.map((r) => r.strike) || [];

  return (
    <div className="panel p-5">
      <div className="flex items-center gap-2 mb-4">
        <Layers className="w-4 h-4 txt-muted" />
        <div className="overline">Multi-leg options builder</div>
      </div>

      {/* Setup */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <div>
          <Label className="overline">Symbol</Label>
          <Select value={symbol} onValueChange={setSymbol}>
            <SelectTrigger data-testid="ml-symbol" className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="rounded-none bg-[var(--bg-surface)] border-[var(--border)]">
              {symbols.map((s) => <SelectItem key={s.symbol} value={s.symbol}>{s.symbol}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="overline">Lots × qty</Label>
          <Input data-testid="ml-qty" type="number" value={qty} onChange={(e) => setQty(e.target.value)} className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
        </div>
        <div>
          <Label className="overline">Basket name</Label>
          <Input data-testid="ml-name" value={name} onChange={(e) => setName(e.target.value)} className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
        </div>
        <div className="font-mono-data text-xs txt-muted flex items-end pb-2">
          {chain ? <>Spot {chain.spot} · ATM <span className="text-white">{chain.atm}</span> · step {chain.step}</> : "loading chain…"}
        </div>
      </div>

      {/* Presets */}
      <div className="mb-4">
        <div className="overline mb-2">Presets</div>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              data-testid={`ml-preset-${p.id}`}
              onClick={() => applyPreset(p)}
              disabled={!chain}
              className="text-xs px-3 py-1.5 border border-[var(--border)] hover:border-white hover:text-white txt-secondary transition-colors font-section tracking-wider disabled:opacity-40"
            >
              <Wand2 className="w-3 h-3 mr-1.5 inline" /> {p.name}
            </button>
          ))}
        </div>
      </div>

      {/* Legs */}
      <div className="space-y-2">
        {legs.length === 0 && (
          <div className="text-sm txt-muted py-6 text-center border border-dashed border-[var(--border)]">
            No legs yet. Pick a preset or add a custom leg.
          </div>
        )}
        {legs.map((leg, i) => (
          <div key={i} data-testid={`ml-leg-${i}`} className="grid grid-cols-6 gap-2 items-end border border-[var(--border)] p-3">
            <div className="col-span-1">
              <Label className="overline">Side</Label>
              <Select value={leg.side} onValueChange={(v) => updateLeg(i, { side: v })}>
                <SelectTrigger data-testid={`ml-leg-${i}-side`} className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="rounded-none bg-[var(--bg-surface)] border-[var(--border)]">
                  <SelectItem value="BUY">BUY</SelectItem>
                  <SelectItem value="SELL">SELL</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="col-span-1">
              <Label className="overline">Type</Label>
              <Select value={leg.option_kind} onValueChange={(v) => updateLeg(i, { option_kind: v })}>
                <SelectTrigger data-testid={`ml-leg-${i}-kind`} className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="rounded-none bg-[var(--bg-surface)] border-[var(--border)]">
                  <SelectItem value="CE">CE</SelectItem>
                  <SelectItem value="PE">PE</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="col-span-2">
              <Label className="overline">Strike</Label>
              <Select value={String(leg.option_strike)} onValueChange={(v) => updateLeg(i, { option_strike: Number(v) })}>
                <SelectTrigger data-testid={`ml-leg-${i}-strike`} className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="rounded-none bg-[var(--bg-surface)] border-[var(--border)] max-h-56">
                  {strikeOptions.map((s) => <SelectItem key={s} value={String(s)}>{s}{s === chain?.atm ? " (ATM)" : ""}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="col-span-1">
              <Label className="overline">Qty</Label>
              <Input data-testid={`ml-leg-${i}-qty`} type="number" value={leg.qty} onChange={(e) => updateLeg(i, { qty: Number(e.target.value) })} className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
            </div>
            <div className="col-span-1 flex justify-end pb-1">
              <Button data-testid={`ml-leg-${i}-remove`} variant="ghost" size="sm" onClick={() => removeLeg(i)} className="rounded-none text-zinc-400 hover:text-red-400">
                <Trash2 className="w-3.5 h-3.5" />
              </Button>
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between gap-3 mt-4">
        <Button data-testid="ml-add-leg" onClick={addCustomLeg} variant="outline" size="sm" className="rounded-none border-[var(--border)] hover:border-white">
          <Plus className="w-3.5 h-3.5 mr-1" /> Add custom leg
        </Button>
        <Button
          data-testid="ml-place-btn"
          onClick={place}
          disabled={busy || legs.length === 0 || disabled}
          className="rounded-none bg-white text-black hover:bg-zinc-200 font-section tracking-wider h-10"
        >
          {busy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Layers className="w-4 h-4 mr-2" />}
          PLACE BASKET ({legs.length} legs)
        </Button>
      </div>
    </div>
  );
}
