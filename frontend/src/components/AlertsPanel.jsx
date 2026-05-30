import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { Bell, Send, Mail, RefreshCw } from "lucide-react";

const ALL_EVENT_TYPES = [
  "KILL_SWITCH",
  "BROKER_DISCONNECT",
  "BASKET_ROLLBACK",
  "RISK_POLICY_CHANGE",
  "OVERRIDE",
];

export default function AlertsPanel() {
  const [prefs, setPrefs] = useState(null);
  const [transports, setTransports] = useState({});
  const [log, setLog] = useState([]);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      const [p, l] = await Promise.all([
        api.get("/alerts/prefs"),
        api.get("/alerts/log", { params: { limit: 25 } }),
      ]);
      setPrefs(p.data.prefs);
      setTransports(p.data.transports || {});
      setLog(l.data.items || []);
    } catch {
      toast.error("Could not load alert settings");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    if (!prefs) return;
    setBusy(true);
    try {
      await api.put("/alerts/prefs", prefs);
      toast.success("Alert preferences saved");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const sendTest = async (channel) => {
    setBusy(true);
    try {
      await api.put("/alerts/prefs", prefs); // save first so server has latest dest
      await api.post("/alerts/test", { channel });
      toast.success(`Test ${channel} alert dispatched`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || `${channel} test failed`);
    } finally {
      setBusy(false);
    }
  };

  const toggleEventType = (et) => {
    const cur = new Set(prefs.event_types || []);
    if (cur.has(et)) cur.delete(et);
    else cur.add(et);
    setPrefs({ ...prefs, event_types: Array.from(cur) });
  };

  if (!prefs) return null;

  const tgConfigured = transports.telegram === "configured";
  const emConfigured = transports.email === "configured";

  return (
    <div className="space-y-6" data-testid="alerts-panel">
      <div className="panel p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Bell className="w-4 h-4 txt-warn" />
            <div className="overline">Alert routing</div>
          </div>
          <Button
            data-testid="alerts-refresh"
            size="sm"
            variant="ghost"
            onClick={load}
            disabled={busy}
            className="rounded-none"
          >
            <RefreshCw className={`w-3.5 h-3.5 mr-2 ${busy ? "animate-spin" : ""}`} /> RELOAD
          </Button>
        </div>
        <p className="txt-secondary text-sm mb-4">
          HIGH-severity events (kill-switch, basket rollback, risk policy change, override, broker disconnect) are
          pushed in real time. Transports are platform-configured via env; you supply your own destination.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Telegram */}
          <div className="border border-[var(--border)] p-4 bg-[var(--bg-page)]">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Send className="w-4 h-4 txt-muted" />
                <div className="font-section text-sm tracking-wider">TELEGRAM</div>
                <span className={`text-xs font-mono-data ${tgConfigured ? "txt-profit" : "txt-loss"}`}>
                  {tgConfigured ? "● BOT READY" : "● NO BOT TOKEN"}
                </span>
              </div>
              <Switch
                data-testid="alerts-telegram-enabled"
                checked={!!prefs.telegram_enabled}
                onCheckedChange={(v) => setPrefs({ ...prefs, telegram_enabled: v })}
              />
            </div>
            <Label className="overline">Your chat_id</Label>
            <Input
              data-testid="alerts-telegram-chat-id"
              value={prefs.telegram_chat_id || ""}
              onChange={(e) => setPrefs({ ...prefs, telegram_chat_id: e.target.value })}
              placeholder="e.g. 1234567890"
              className="mt-2 rounded-none bg-[var(--bg-surface)] border-[var(--border)] font-mono-data"
            />
            <p className="text-xs txt-muted mt-2">
              DM the platform bot and send <code className="font-mono-data">/start</code> to get your chat id.
            </p>
            <Button
              data-testid="alerts-telegram-test"
              size="sm"
              variant="ghost"
              onClick={() => sendTest("telegram")}
              disabled={busy || !tgConfigured || !prefs.telegram_chat_id}
              className="mt-3 rounded-none border border-[var(--border)] font-section tracking-wider"
            >
              SEND TEST
            </Button>
          </div>

          {/* Email */}
          <div className="border border-[var(--border)] p-4 bg-[var(--bg-page)]">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Mail className="w-4 h-4 txt-muted" />
                <div className="font-section text-sm tracking-wider">EMAIL</div>
                <span className={`text-xs font-mono-data ${emConfigured ? "txt-profit" : "txt-loss"}`}>
                  {emConfigured ? "● SMTP READY" : "● NO SMTP"}
                </span>
              </div>
              <Switch
                data-testid="alerts-email-enabled"
                checked={!!prefs.email_enabled}
                onCheckedChange={(v) => setPrefs({ ...prefs, email_enabled: v })}
              />
            </div>
            <Label className="overline">Your email</Label>
            <Input
              data-testid="alerts-email-address"
              value={prefs.email_address || ""}
              onChange={(e) => setPrefs({ ...prefs, email_address: e.target.value })}
              placeholder="trader@example.com"
              className="mt-2 rounded-none bg-[var(--bg-surface)] border-[var(--border)] font-mono-data"
            />
            <p className="text-xs txt-muted mt-2">
              Plain-text emails sent via the platform SMTP relay. Configure SMTP_* env to enable.
            </p>
            <Button
              data-testid="alerts-email-test"
              size="sm"
              variant="ghost"
              onClick={() => sendTest("email")}
              disabled={busy || !emConfigured || !prefs.email_address}
              className="mt-3 rounded-none border border-[var(--border)] font-section tracking-wider"
            >
              SEND TEST
            </Button>
          </div>
        </div>

        {/* Event types */}
        <div className="mt-6">
          <Label className="overline">Event types to alert on</Label>
          <div className="flex flex-wrap gap-2 mt-3">
            {ALL_EVENT_TYPES.map((et) => {
              const active = (prefs.event_types || []).includes(et);
              return (
                <button
                  key={et}
                  data-testid={`alerts-evt-${et}`}
                  onClick={() => toggleEventType(et)}
                  className={`px-3 py-1.5 text-xs font-section tracking-wider border ${
                    active
                      ? "bg-white text-black border-white"
                      : "bg-transparent text-zinc-400 border-[var(--border)] hover:text-white"
                  }`}
                >
                  {et}
                </button>
              );
            })}
          </div>
        </div>

        <Button
          data-testid="alerts-save"
          onClick={save}
          disabled={busy}
          className="mt-6 rounded-none bg-white text-black hover:bg-zinc-200 font-section tracking-wider"
        >
          {busy ? "SAVING…" : "SAVE ALERT PREFERENCES"}
        </Button>
      </div>

      {/* Log */}
      <div className="panel p-6">
        <div className="overline mb-3">Recent alert deliveries</div>
        {log.length === 0 && <div className="txt-muted text-sm">No alerts dispatched yet.</div>}
        <div className="space-y-2">
          {log.map((row, i) => (
            <div
              key={`${row.ts}-${i}`}
              data-testid={`alerts-log-row-${i}`}
              className="flex items-center justify-between text-xs font-mono-data border-b border-[var(--border)] pb-2"
            >
              <span className="txt-secondary">{row.ts?.slice(11, 19)}</span>
              <span className="font-section tracking-wider">{row.channel?.toUpperCase()}</span>
              <span className="txt-muted truncate max-w-[200px]">{row.destination}</span>
              <span className="font-section">{row.event_type}</span>
              <span className={row.ok ? "txt-profit" : "txt-loss"}>{row.ok ? "OK" : "FAIL"}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
