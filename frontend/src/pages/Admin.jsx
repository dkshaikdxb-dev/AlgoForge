import { useEffect, useState } from "react";
import api from "@/lib/api";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import StatCard from "@/components/StatCard";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/lib/auth";
import { Navigate } from "react-router-dom";
import { ShieldAlert, Activity, Users, Plug, ScrollText, RefreshCw } from "lucide-react";
import { toast } from "sonner";

const fmt = (n, d = 2) =>
  (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

export default function Admin() {
  const { user } = useAuth();
  const [health, setHealth] = useState(null);
  const [users, setUsers] = useState([]);
  const [brokerMap, setBrokerMap] = useState({ connections: [], by_broker: {} });
  const [events, setEvents] = useState([]);
  const [adminEvents, setAdminEvents] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [h, u, b, e, ae] = await Promise.all([
        api.get("/admin/health"),
        api.get("/admin/risk/users"),
        api.get("/admin/brokers/map"),
        api.get("/admin/audit", { params: { limit: 50 } }),
        api.get("/admin/events", { params: { limit: 50 } }),
      ]);
      setHealth(h.data);
      setUsers(u.data.items);
      setBrokerMap(b.data);
      setEvents(e.data.items);
      setAdminEvents(ae.data.items);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Admin load failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user?.role === "admin") load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.role]);

  if (user && user.role !== "admin") return <Navigate to="/" replace />;

  const forceKill = async (uid, email, killOn) => {
    const reason = window.prompt(`${killOn ? "Force-kill" : "Release kill on"} ${email}? Reason:`);
    if (reason === null) return;
    try {
      await api.post("/admin/risk/kill", { user_id: uid, kill_switch: killOn, reason });
      toast.success(`${killOn ? "Killed" : "Released"} ${email}`);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Action failed");
    }
  };

  return (
    <AppShell>
      <PageHeader
        overline="Platform"
        title="Admin console"
        description="Super-admin view across all users. Every action here is recorded in the admin audit trail."
        actions={
          <Button data-testid="admin-refresh" onClick={load} disabled={loading} className="rounded-none bg-white text-black hover:bg-zinc-200 font-section tracking-wider">
            <RefreshCw className={`w-4 h-4 mr-2 ${loading ? "animate-spin" : ""}`} /> REFRESH
          </Button>
        }
      />

      <div className="p-8 space-y-6">
        {/* Health stats */}
        {health && (
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
            <StatCard testid="admin-health-mongo" label="Mongo" value={health.mongo === "ok" ? "OK" : "ERR"} tone={health.mongo === "ok" ? "profit" : "loss"} />
            <StatCard testid="admin-health-reconciler" label="Reconciler" value={health.reconciler} tone="profit" />
            <StatCard testid="admin-health-llm" label="LLM Key" value={health.emergent_llm_key === "configured" ? "OK" : "MISSING"} tone={health.emergent_llm_key === "configured" ? "profit" : "warn"} />
            <StatCard testid="admin-health-users" label="Users" value={health.users} />
            <StatCard testid="admin-health-orders" label="Paper orders" value={health.paper_orders} />
            <StatCard testid="admin-health-live" label="Live brokers" value={health.live_brokers} tone={health.live_brokers > 0 ? "profit" : "neutral"} />
          </div>
        )}

        <Tabs defaultValue="risk" className="w-full">
          <TabsList className="rounded-none bg-[var(--bg-surface)] border border-[var(--border)] h-auto p-0">
            <TabsTrigger value="risk" data-testid="admin-tab-risk" className="rounded-none data-[state=active]:bg-[var(--bg-surface-2)] data-[state=active]:text-white font-section tracking-wider px-6 py-3"><Users className="w-4 h-4 mr-2" /> RISK / USERS</TabsTrigger>
            <TabsTrigger value="brokers" data-testid="admin-tab-brokers" className="rounded-none data-[state=active]:bg-[var(--bg-surface-2)] data-[state=active]:text-white font-section tracking-wider px-6 py-3"><Plug className="w-4 h-4 mr-2" /> BROKER MAP</TabsTrigger>
            <TabsTrigger value="audit" data-testid="admin-tab-audit" className="rounded-none data-[state=active]:bg-[var(--bg-surface-2)] data-[state=active]:text-white font-section tracking-wider px-6 py-3"><ScrollText className="w-4 h-4 mr-2" /> GLOBAL AUDIT</TabsTrigger>
            <TabsTrigger value="events" data-testid="admin-tab-events" className="rounded-none data-[state=active]:bg-[var(--bg-surface-2)] data-[state=active]:text-white font-section tracking-wider px-6 py-3"><ShieldAlert className="w-4 h-4 mr-2" /> ADMIN TRAIL</TabsTrigger>
          </TabsList>

          {/* Risk / Users */}
          <TabsContent value="risk" className="mt-4">
            <div className="panel">
              <Table>
                <TableHeader>
                  <TableRow className="border-[var(--border)]">
                    <TableHead className="overline">Email</TableHead>
                    <TableHead className="overline">Role</TableHead>
                    <TableHead className="overline text-right">Pos</TableHead>
                    <TableHead className="overline text-right">P&L</TableHead>
                    <TableHead className="overline text-right">Exposure</TableHead>
                    <TableHead className="overline">Kill</TableHead>
                    <TableHead className="overline">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((u) => (
                    <TableRow key={u.id} className="border-[var(--border)]" data-testid={`admin-user-${u.id}`}>
                      <TableCell className="font-mono-data text-xs">{u.email}</TableCell>
                      <TableCell className={`font-section text-xs ${u.role === "admin" ? "txt-warn" : "txt-secondary"}`}>{u.role.toUpperCase()}</TableCell>
                      <TableCell className="font-mono-data text-right">{u.open_positions}</TableCell>
                      <TableCell className={`font-mono-data text-right ${u.total_pnl > 0 ? "txt-profit" : u.total_pnl < 0 ? "txt-loss" : "txt-muted"}`}>₹{fmt(u.total_pnl)}</TableCell>
                      <TableCell className="font-mono-data text-right">₹{fmt(u.exposure, 0)}</TableCell>
                      <TableCell className={`font-section text-xs ${u.kill_switch ? "txt-loss" : "txt-muted"}`}>{u.kill_switch ? "ARMED" : "—"}</TableCell>
                      <TableCell>
                        <Button
                          data-testid={`admin-kill-${u.id}`}
                          size="sm"
                          variant="ghost"
                          onClick={() => forceKill(u.id, u.email, !u.kill_switch)}
                          className={`rounded-none ${u.kill_switch ? "text-emerald-400 hover:bg-emerald-500 hover:text-black" : "text-red-400 hover:bg-red-500 hover:text-white"}`}
                        >
                          <ShieldAlert className="w-3.5 h-3.5 mr-1" /> {u.kill_switch ? "RELEASE" : "FORCE KILL"}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </TabsContent>

          {/* Broker map */}
          <TabsContent value="brokers" className="mt-4 space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              {Object.entries(brokerMap.by_broker).map(([b, s]) => (
                <div key={b} className="panel p-4" data-testid={`admin-broker-stat-${b}`}>
                  <div className="overline">{b}</div>
                  <div className="kpi-num text-3xl mt-2">{s.total}</div>
                  <div className="text-xs font-mono-data mt-2 space-x-3">
                    <span className="txt-profit">{s.live || 0} live</span>
                    <span className="txt-warn">{s.saved || 0} saved</span>
                    <span className="txt-loss">{s.error || 0} err</span>
                  </div>
                </div>
              ))}
              {Object.keys(brokerMap.by_broker).length === 0 && (
                <div className="panel p-6 col-span-full txt-muted text-sm text-center">No broker connections across users.</div>
              )}
            </div>
            <div className="panel">
              <Table>
                <TableHeader>
                  <TableRow className="border-[var(--border)]">
                    <TableHead className="overline">User</TableHead>
                    <TableHead className="overline">Broker</TableHead>
                    <TableHead className="overline">Status</TableHead>
                    <TableHead className="overline">Last test</TableHead>
                    <TableHead className="overline">Message</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {brokerMap.connections.map((c) => (
                    <TableRow key={`${c.user_id}-${c.broker}`} className="border-[var(--border)]">
                      <TableCell className="font-mono-data text-xs">{c.user_email}</TableCell>
                      <TableCell className="font-section">{c.broker}</TableCell>
                      <TableCell className={`font-section text-xs ${c.status === "live" ? "txt-profit" : c.status === "error" ? "txt-loss" : "txt-warn"}`}>{(c.status || "saved").toUpperCase()}</TableCell>
                      <TableCell className="font-mono-data text-xs txt-secondary">{c.last_test?.slice(11, 19) || "—"}</TableCell>
                      <TableCell className="text-xs txt-secondary truncate max-w-md">{c.last_message || "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </TabsContent>

          {/* Global audit feed */}
          <TabsContent value="audit" className="mt-4">
            <div className="panel">
              <Table>
                <TableHeader>
                  <TableRow className="border-[var(--border)]">
                    <TableHead className="overline">Timestamp</TableHead>
                    <TableHead className="overline">User</TableHead>
                    <TableHead className="overline">Type</TableHead>
                    <TableHead className="overline">Severity</TableHead>
                    <TableHead className="overline">Summary</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {events.map((e) => (
                    <TableRow key={e.id} className="border-[var(--border)]">
                      <TableCell className="font-mono-data text-xs txt-secondary">{e.ts?.slice(0, 19)}</TableCell>
                      <TableCell className="font-mono-data text-xs txt-muted">{(e.user_id || "—").slice(0, 8)}</TableCell>
                      <TableCell className="font-section text-xs">{e.event_type}</TableCell>
                      <TableCell className={`font-section text-xs ${e.severity === "HIGH" ? "txt-loss" : e.severity === "WARN" ? "txt-warn" : "txt-secondary"}`}>{e.severity}</TableCell>
                      <TableCell className="text-sm">{e.summary}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </TabsContent>

          {/* Admin trail */}
          <TabsContent value="events" className="mt-4">
            <div className="panel">
              <Table>
                <TableHeader>
                  <TableRow className="border-[var(--border)]">
                    <TableHead className="overline">Timestamp</TableHead>
                    <TableHead className="overline">Admin</TableHead>
                    <TableHead className="overline">Action</TableHead>
                    <TableHead className="overline">Target</TableHead>
                    <TableHead className="overline">Summary</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {adminEvents.length === 0 && (
                    <TableRow className="border-[var(--border)]"><TableCell colSpan={5} className="txt-muted text-center py-6">No admin actions yet.</TableCell></TableRow>
                  )}
                  {adminEvents.map((e) => (
                    <TableRow key={e.id} className="border-[var(--border)]">
                      <TableCell className="font-mono-data text-xs txt-secondary">{e.ts?.slice(0, 19)}</TableCell>
                      <TableCell className="font-mono-data text-xs">{e.admin_id?.slice(0, 8)}</TableCell>
                      <TableCell className="font-section text-xs txt-warn">{e.action}</TableCell>
                      <TableCell className="font-mono-data text-xs">{(e.target_user_id || e.target_broker || "—").slice(0, 12)}</TableCell>
                      <TableCell className="text-sm">{e.summary}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </AppShell>
  );
}
