import { useEffect, useState } from "react";
import api from "@/lib/api";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import AlertsPanel from "@/components/AlertsPanel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useAuth } from "@/lib/auth";
import { toast } from "sonner";
import { KeyRound, Save, ShieldCheck, Bell } from "lucide-react";

export default function Settings() {
  const { user } = useAuth();
  const [risk, setRisk] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get("/risk/limits").then((r) => setRisk(r.data));
  }, []);

  const save = async () => {
    if (!risk) return;
    setSaving(true);
    try {
      await api.put("/risk/limits", {
        max_drawdown_pct: Number(risk.max_drawdown_pct),
        daily_loss_cap: Number(risk.daily_loss_cap),
        position_limit: Number(risk.position_limit),
        kill_switch: !!risk.kill_switch,
      });
      toast.success("Risk policy updated");
    } catch {
      toast.error("Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppShell>
      <PageHeader
        overline="Settings"
        title="Account · risk · alerts"
        description="Tune daily caps, drawdown limits, broker keys and where critical alerts are delivered."
      />

      <div className="p-8">
        <Tabs defaultValue="risk" className="w-full">
          <TabsList className="rounded-none bg-[var(--bg-surface)] border border-[var(--border)] h-auto p-0 mb-6">
            <TabsTrigger value="risk" data-testid="settings-tab-risk" className="rounded-none data-[state=active]:bg-[var(--bg-surface-2)] data-[state=active]:text-white font-section tracking-wider px-6 py-3"><ShieldCheck className="w-4 h-4 mr-2" /> RISK & PROFILE</TabsTrigger>
            <TabsTrigger value="alerts" data-testid="settings-tab-alerts" className="rounded-none data-[state=active]:bg-[var(--bg-surface-2)] data-[state=active]:text-white font-section tracking-wider px-6 py-3"><Bell className="w-4 h-4 mr-2" /> ALERTS</TabsTrigger>
          </TabsList>

          <TabsContent value="risk">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="panel p-6">
                <div className="overline mb-3">Profile</div>
                <div className="space-y-3">
                  <div>
                    <Label className="overline">Email</Label>
                    <div className="font-mono-data text-sm mt-1">{user?.email}</div>
                  </div>
                  <div>
                    <Label className="overline">Name</Label>
                    <div className="font-section text-sm mt-1">{user?.name}</div>
                  </div>
                  <div>
                    <Label className="overline">Role</Label>
                    <div className="font-section text-sm mt-1 txt-warn uppercase">{user?.role}</div>
                  </div>
                </div>
              </div>

              <div className="panel p-6">
                <div className="overline mb-3">Risk policy</div>
                {risk && (
                  <div className="space-y-4">
                    <div>
                      <Label className="overline">Max drawdown (%)</Label>
                      <Input data-testid="risk-max-dd" type="number" value={risk.max_drawdown_pct} onChange={(e) => setRisk({ ...risk, max_drawdown_pct: e.target.value })} className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
                    </div>
                    <div>
                      <Label className="overline">Daily loss cap (₹)</Label>
                      <Input data-testid="risk-daily-cap" type="number" value={risk.daily_loss_cap} onChange={(e) => setRisk({ ...risk, daily_loss_cap: e.target.value })} className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
                    </div>
                    <div>
                      <Label className="overline">Position limit</Label>
                      <Input data-testid="risk-pos-limit" type="number" value={risk.position_limit} onChange={(e) => setRisk({ ...risk, position_limit: e.target.value })} className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data" />
                    </div>
                    <div className="flex items-center justify-between border-t border-[var(--border)] pt-4">
                      <div>
                        <div className="overline">Kill switch</div>
                        <div className="text-xs txt-muted mt-1">Blocks all new orders when ON.</div>
                      </div>
                      <Switch data-testid="settings-kill-switch" checked={!!risk.kill_switch} onCheckedChange={(v) => setRisk({ ...risk, kill_switch: v })} />
                    </div>
                    <Button data-testid="risk-save-btn" onClick={save} disabled={saving} className="rounded-none bg-white text-black hover:bg-zinc-200 font-section tracking-wider w-full h-10">
                      <Save className="w-4 h-4 mr-2" /> {saving ? "SAVING…" : "SAVE POLICY"}
                    </Button>
                  </div>
                )}
              </div>

              <div className="panel p-6 lg:col-span-2">
                <div className="flex items-center gap-2 mb-3">
                  <KeyRound className="w-4 h-4 txt-muted" />
                  <div className="overline">Broker connections</div>
                </div>
                <p className="txt-secondary text-sm">
                  Real-money execution requires broker API credentials (KYC + 2FA). Manage your encrypted vault from the
                  <a href="/brokers" className="text-white underline underline-offset-4 ml-1">Brokers</a> page. Supported:
                  <span className="font-section text-white"> Zerodha</span>, <span className="font-section text-white">Upstox</span>, Dhan, ICICI Direct and Rmoney.
                </p>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="alerts">
            <AlertsPanel />
          </TabsContent>
        </Tabs>
      </div>
    </AppShell>
  );
}
