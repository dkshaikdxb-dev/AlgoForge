import { useEffect, useState } from "react";
import api from "@/lib/api";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from "@/components/ui/dialog";
import { Plug, Loader2, ShieldCheck, ExternalLink, Trash2, KeyRound } from "lucide-react";
import { toast } from "sonner";

export default function Brokers() {
  const [items, setItems] = useState([]);
  const [active, setActive] = useState(null); // broker being edited
  const [form, setForm] = useState({});
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const { data } = await api.get("/brokers");
      setItems(data.items);
    } catch {
      toast.error("Could not load brokers");
    }
  };

  useEffect(() => { load(); }, []);

  const openConnect = (broker) => {
    setActive(broker);
    setForm(Object.fromEntries(broker.fields.map((f) => [f.key, ""])));
  };

  const saveConnect = async () => {
    if (!active) return;
    setBusy(true);
    try {
      await api.post(`/brokers/${active.name}/connect`, { credentials: form });
      toast.success(`${active.label} credentials saved (encrypted)`);
      const { data } = await api.post(`/brokers/${active.name}/test`);
      if (data.status === "live") toast.success(`${active.label} live: ${data.message}`);
      else toast.warning(`${active.label} saved but test failed: ${data.message}`);
      setActive(null);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const testNow = async (name) => {
    setBusy(true);
    try {
      const { data } = await api.post(`/brokers/${name}/test`);
      if (data.status === "live") toast.success(`Connected: ${data.message}`);
      else toast.warning(`Test failed: ${data.message}`);
      load();
    } catch {
      toast.error("Test failed");
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async (name) => {
    try {
      await api.delete(`/brokers/${name}`);
      toast.success("Disconnected");
      load();
    } catch {
      toast.error("Disconnect failed");
    }
  };

  const statusLabel = (it) => {
    if (!it.connected) return { label: "DISCONNECTED", color: "text-zinc-500", dot: "bg-zinc-600" };
    if (it.status === "live") return { label: "LIVE", color: "txt-profit", dot: "bg-emerald-500" };
    if (it.status === "error") return { label: "ERROR", color: "txt-loss", dot: "bg-red-500" };
    return { label: "SAVED · NOT TESTED", color: "txt-warn", dot: "bg-amber-500" };
  };

  return (
    <AppShell>
      <PageHeader
        overline="Connectivity"
        title="Broker connections"
        description="Wire your live trading account. Credentials are encrypted at rest. Until tested live, all orders stay in the paper engine."
      />

      <div className="p-8">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {items.map((b) => {
            const st = statusLabel(b);
            return (
              <div key={b.name} className="panel p-5 flex flex-col gap-4" data-testid={`broker-card-${b.name}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-display text-2xl">{b.label}</div>
                    <p className="text-sm txt-secondary mt-1">{b.description}</p>
                    <div className="flex items-center gap-2 mt-3">
                      <span className={`w-1.5 h-1.5 rounded-full ${st.dot}`} />
                      <span className={`overline ${st.color}`}>{st.label}</span>
                      {b.last_test && <span className="overline txt-muted">last test {b.last_test.slice(11, 19)}</span>}
                    </div>
                  </div>
                  <KeyRound className="w-5 h-5 txt-muted shrink-0" />
                </div>
                <div className="flex items-center gap-2 mt-auto">
                  <Button
                    data-testid={`broker-connect-${b.name}`}
                    onClick={() => openConnect(b)}
                    size="sm"
                    className="rounded-none bg-white text-black hover:bg-zinc-200 font-section tracking-wider"
                  >
                    <Plug className="w-3.5 h-3.5 mr-2" /> {b.connected ? "UPDATE" : "CONNECT"}
                  </Button>
                  {b.connected && (
                    <>
                      <Button
                        data-testid={`broker-test-${b.name}`}
                        onClick={() => testNow(b.name)}
                        disabled={busy}
                        size="sm"
                        variant="outline"
                        className="rounded-none border-white text-white hover:bg-white hover:text-black"
                      >
                        <ShieldCheck className="w-3.5 h-3.5 mr-2" /> TEST
                      </Button>
                      <Button
                        data-testid={`broker-disconnect-${b.name}`}
                        onClick={() => disconnect(b.name)}
                        size="sm"
                        variant="ghost"
                        className="rounded-none text-zinc-400 hover:text-red-400"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    </>
                  )}
                  <a
                    href={b.docs_url}
                    target="_blank"
                    rel="noreferrer"
                    className="ml-auto text-xs txt-muted hover:text-white inline-flex items-center gap-1"
                    data-testid={`broker-docs-${b.name}`}
                  >
                    Docs <ExternalLink className="w-3 h-3" />
                  </a>
                </div>
                {b.sdk_package && (
                  <div className="text-[11px] txt-muted font-mono-data border-t border-[var(--border)] pt-2">
                    SDK: {b.sdk_package}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <Dialog open={!!active} onOpenChange={(v) => !v && setActive(null)}>
        <DialogContent className="rounded-none bg-[var(--bg-surface)] border-[var(--border)] text-white max-w-md" data-testid="broker-connect-dialog">
          <DialogHeader>
            <DialogTitle className="font-display text-2xl">{active?.label}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {active?.fields.map((f) => (
              <div key={f.key}>
                <Label className="overline">{f.label}</Label>
                <Input
                  data-testid={`broker-field-${f.key}`}
                  type={f.secret ? "password" : "text"}
                  value={form[f.key] || ""}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                  className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data"
                />
              </div>
            ))}
            <p className="text-xs txt-muted pt-2">
              Stored encrypted (Fernet) in your account vault. Only used server-side when you place a live order.
            </p>
          </div>
          <DialogFooter>
            <Button
              data-testid="broker-save-btn"
              onClick={saveConnect}
              disabled={busy}
              className="rounded-none bg-white text-black hover:bg-zinc-200 font-section tracking-wider"
            >
              {busy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Plug className="w-4 h-4 mr-2" />}
              {busy ? "SAVING…" : "SAVE + TEST"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
