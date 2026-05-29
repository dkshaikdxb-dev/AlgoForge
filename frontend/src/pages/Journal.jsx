import { useEffect, useState } from "react";
import api from "@/lib/api";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from "@/components/ui/dialog";
import { Plus, Loader2, BookOpen } from "lucide-react";
import { toast } from "sonner";

const fmt = (n, d = 2) =>
  (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

export default function Journal() {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    symbol: "NIFTY", side: "BUY", qty: 50,
    entry_price: 0, exit_price: 0, pnl: 0, rationale: "",
  });

  const load = async () => {
    const { data } = await api.get("/journal");
    setItems(data.items);
  };

  useEffect(() => { load(); }, []);

  const submit = async () => {
    setSaving(true);
    try {
      await api.post("/journal", { ...form, qty: Number(form.qty), entry_price: Number(form.entry_price), exit_price: Number(form.exit_price), pnl: Number(form.pnl), request_ai: true });
      toast.success("Entry saved · AI commentary generated");
      setOpen(false);
      setForm({ symbol: "NIFTY", side: "BUY", qty: 50, entry_price: 0, exit_price: 0, pnl: 0, rationale: "" });
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppShell>
      <PageHeader
        overline="Analytics"
        title="Trade Journal"
        description="Log your rationale and outcome. Claude Sonnet 4.5 tags the behaviour and coaches you on each trade."
        actions={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button data-testid="journal-new-btn" className="rounded-none bg-white text-black hover:bg-zinc-200 font-section tracking-wider">
                <Plus className="w-4 h-4 mr-2" /> NEW ENTRY
              </Button>
            </DialogTrigger>
            <DialogContent className="rounded-none bg-[var(--bg-surface)] border-[var(--border)] text-white max-w-lg">
              <DialogHeader>
                <DialogTitle className="font-display text-2xl">New journal entry</DialogTitle>
              </DialogHeader>
              <div className="space-y-3" data-testid="journal-form">
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <Label className="overline">Symbol</Label>
                    <Input data-testid="journal-symbol" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value.toUpperCase() })} className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
                  </div>
                  <div>
                    <Label className="overline">Side</Label>
                    <Input data-testid="journal-side" value={form.side} onChange={(e) => setForm({ ...form, side: e.target.value.toUpperCase() })} className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
                  </div>
                  <div>
                    <Label className="overline">Qty</Label>
                    <Input data-testid="journal-qty" type="number" value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })} className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <Label className="overline">Entry</Label>
                    <Input data-testid="journal-entry" type="number" value={form.entry_price} onChange={(e) => setForm({ ...form, entry_price: e.target.value })} className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
                  </div>
                  <div>
                    <Label className="overline">Exit</Label>
                    <Input data-testid="journal-exit" type="number" value={form.exit_price} onChange={(e) => setForm({ ...form, exit_price: e.target.value })} className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
                  </div>
                  <div>
                    <Label className="overline">P&L ₹</Label>
                    <Input data-testid="journal-pnl" type="number" value={form.pnl} onChange={(e) => setForm({ ...form, pnl: e.target.value })} className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
                  </div>
                </div>
                <div>
                  <Label className="overline">Rationale</Label>
                  <Textarea data-testid="journal-rationale" value={form.rationale} onChange={(e) => setForm({ ...form, rationale: e.target.value })} className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] min-h-[100px]" placeholder="Why did you take this trade?" />
                </div>
              </div>
              <DialogFooter>
                <Button data-testid="journal-save-btn" onClick={submit} disabled={saving} className="rounded-none bg-white text-black hover:bg-zinc-200 font-section tracking-wider">
                  {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
                  {saving ? "SAVING…" : "SAVE + GET AI FEEDBACK"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        }
      />

      <div className="p-8 space-y-4">
        {items.length === 0 && (
          <div className="panel p-10 text-center">
            <BookOpen className="w-8 h-8 mx-auto txt-muted mb-3" />
            <div className="font-display text-2xl mb-1">No entries yet</div>
            <p className="txt-muted text-sm">Log your first trade to get AI commentary from Claude Sonnet 4.5.</p>
          </div>
        )}
        {items.map((e) => (
          <div key={e.id} className="panel panel-hover p-5" data-testid={`journal-item-${e.id}`}>
            <div className="flex items-start justify-between gap-6">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="font-display text-2xl">{e.symbol}</span>
                  <span className={`overline ${e.side === "BUY" ? "txt-profit" : "txt-loss"}`}>{e.side} {e.qty}</span>
                  <span className="overline">@ ₹{fmt(e.entry_price)} → ₹{fmt(e.exit_price)}</span>
                  <span className={`font-mono-data text-sm ${e.pnl > 0 ? "txt-profit" : e.pnl < 0 ? "txt-loss" : "txt-muted"}`}>
                    P&L ₹{fmt(e.pnl)}
                  </span>
                </div>
                {e.rationale && <p className="text-sm mt-3 txt-secondary">{e.rationale}</p>}
                {e.ai_commentary && (
                  <div className="mt-4 border-l-2 border-blue-500 pl-4 py-1">
                    <div className="overline mb-1">AI coach (Claude)</div>
                    <p className="text-sm">{e.ai_commentary}</p>
                  </div>
                )}
                {e.ai_tags?.length > 0 && (
                  <div className="flex gap-2 mt-3 flex-wrap">
                    {e.ai_tags.map((t, i) => (
                      <span key={i} className="text-xs border border-[var(--border)] px-2 py-0.5 font-mono-data txt-secondary">{t}</span>
                    ))}
                  </div>
                )}
              </div>
              <div className="overline shrink-0">{e.created_at?.slice(0, 10)}</div>
            </div>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
