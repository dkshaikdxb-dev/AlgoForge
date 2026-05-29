import { useEffect, useState, useCallback } from "react";
import api, { API_BASE } from "@/lib/api";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Loader2, Download, Filter, ScrollText } from "lucide-react";
import { toast } from "sonner";

const TYPE_LABELS = {
  SIGNAL: "Signal",
  DECISION: "Decision",
  REQUEST: "Request",
  RESPONSE: "Response",
  FILL: "Fill",
  OVERRIDE: "Override",
  AUTH_LOGIN: "Login",
  AUTH_REGISTER: "Register",
  KILL_SWITCH: "Kill switch",
  RISK_POLICY_CHANGE: "Risk policy",
  BROKER_CONNECT: "Broker connect",
  BROKER_DISCONNECT: "Broker disconnect",
  BROKER_TEST: "Broker test",
  RECONCILE: "Reconcile",
  STRATEGY_SAVED: "Strategy saved",
  BACKTEST_RUN: "Backtest",
  DUPLICATE_BLOCKED: "Duplicate blocked",
  BASKET_ROLLBACK: "Basket rollback",
};

const SEVERITY_CLASSES = {
  INFO: "txt-secondary",
  WARN: "txt-warn",
  HIGH: "txt-loss",
};

export default function AuditLog() {
  const [types, setTypes] = useState({ all: [], sebi_trace: [], severities: [] });
  const [selectedTypes, setSelectedTypes] = useState([]);
  const [q, setQ] = useState("");
  const [fromTs, setFromTs] = useState("");
  const [toTs, setToTs] = useState("");
  const [events, setEvents] = useState([]);
  const [hasMore, setHasMore] = useState(false);
  const [cursor, setCursor] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sebiOnly, setSebiOnly] = useState(false);

  useEffect(() => {
    api.get("/audit/types").then((r) => setTypes(r.data));
  }, []);

  const buildParams = useCallback((withCursor = false) => {
    const params = { limit: 100 };
    const eff = sebiOnly ? types.sebi_trace : selectedTypes;
    if (eff?.length) params.event_types = eff.join(",");
    if (q) params.q = q;
    if (fromTs) params.from_ts = fromTs;
    if (toTs) params.to_ts = toTs;
    if (withCursor && cursor) params.cursor = cursor;
    return params;
  }, [sebiOnly, selectedTypes, q, fromTs, toTs, types.sebi_trace, cursor]);

  const load = useCallback(async (more = false) => {
    setLoading(true);
    try {
      const { data } = await api.get("/audit/events", { params: buildParams(more) });
      setEvents(more ? (prev) => [...prev, ...data.items] : data.items);
      setHasMore(data.has_more);
      setCursor(data.next_cursor);
    } catch {
      toast.error("Could not load audit events");
    } finally {
      setLoading(false);
    }
  }, [buildParams]);

  useEffect(() => {
    load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sebiOnly, selectedTypes, q, fromTs, toTs]);

  const toggleType = (t) => {
    setSelectedTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));
  };

  const exportCsv = () => {
    const token = localStorage.getItem("af_token");
    const params = new URLSearchParams();
    const eff = sebiOnly ? types.sebi_trace : selectedTypes;
    if (eff?.length) params.set("event_types", eff.join(","));
    if (q) params.set("q", q);
    if (fromTs) params.set("from_ts", fromTs);
    if (toTs) params.set("to_ts", toTs);
    // Use fetch + blob so we can attach the bearer header.
    fetch(`${API_BASE}/audit/export?${params.toString()}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.blob())
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `algoforge-audit-${Date.now()}.csv`;
        a.click();
        URL.revokeObjectURL(url);
        toast.success("Audit log exported");
      })
      .catch(() => toast.error("Export failed"));
  };

  return (
    <AppShell>
      <PageHeader
        overline="Compliance"
        title="Audit log"
        description="Immutable, append-only event stream. Reconstruct any trade across the full SEBI 6-step trace: signal → decision → request → response → fill → override."
        actions={
          <Button data-testid="audit-export-btn" onClick={exportCsv} className="rounded-none bg-white text-black hover:bg-zinc-200 font-section tracking-wider">
            <Download className="w-4 h-4 mr-2" /> EXPORT CSV
          </Button>
        }
      />

      <div className="p-8 space-y-6">
        {/* Filters */}
        <div className="panel p-5 space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 txt-muted" />
              <div className="overline">Filter</div>
            </div>
            <button
              data-testid="audit-sebi-only-toggle"
              onClick={() => setSebiOnly((v) => !v)}
              className={`text-xs px-3 py-1.5 border transition-colors font-section tracking-wider ${
                sebiOnly ? "border-white text-white bg-[var(--bg-surface-2)]" : "border-[var(--border)] txt-secondary hover:border-white"
              }`}
            >
              {sebiOnly ? "SEBI TRACE ✓" : "SEBI 6-STEP ONLY"}
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div>
              <Label className="overline">Search</Label>
              <Input
                data-testid="audit-search-input"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="symbol, strategy, broker…"
                className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data"
              />
            </div>
            <div>
              <Label className="overline">From (ISO)</Label>
              <Input
                data-testid="audit-from-input"
                value={fromTs}
                onChange={(e) => setFromTs(e.target.value)}
                placeholder="2026-02-29T00:00:00Z"
                className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data text-xs"
              />
            </div>
            <div>
              <Label className="overline">To (ISO)</Label>
              <Input
                data-testid="audit-to-input"
                value={toTs}
                onChange={(e) => setToTs(e.target.value)}
                placeholder="2026-02-29T23:59:59Z"
                className="mt-2 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data text-xs"
              />
            </div>
            <div className="font-mono-data text-xs txt-muted flex items-end pb-2">
              {events.length} {hasMore ? "+" : ""} events
            </div>
          </div>

          <div className="flex flex-wrap gap-1.5">
            {types.all.map((t) => {
              const active = (sebiOnly ? types.sebi_trace : selectedTypes).includes(t);
              return (
                <button
                  key={t}
                  data-testid={`audit-type-${t}`}
                  disabled={sebiOnly}
                  onClick={() => toggleType(t)}
                  className={`text-[10px] uppercase tracking-wider px-2 py-1 border font-section transition-colors disabled:opacity-40 ${
                    active
                      ? "border-white bg-[var(--bg-surface-2)] text-white"
                      : "border-[var(--border)] txt-secondary hover:border-white hover:text-white"
                  }`}
                >
                  {TYPE_LABELS[t] || t}
                </button>
              );
            })}
          </div>
        </div>

        {/* Events table */}
        <div className="panel">
          <div className="overflow-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-[var(--border)]">
                  <TableHead className="overline w-32">Timestamp</TableHead>
                  <TableHead className="overline w-32">Type</TableHead>
                  <TableHead className="overline w-20">Severity</TableHead>
                  <TableHead className="overline w-20">Actor</TableHead>
                  <TableHead className="overline">Summary</TableHead>
                  <TableHead className="overline w-28">Correlation</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {events.length === 0 && !loading && (
                  <TableRow className="border-[var(--border)]">
                    <TableCell colSpan={6} className="text-center txt-muted py-10">
                      <ScrollText className="w-6 h-6 mx-auto mb-2 txt-muted" />
                      No events match the current filters.
                    </TableCell>
                  </TableRow>
                )}
                {events.map((e) => (
                  <TableRow key={e.id} className="border-[var(--border)]" data-testid={`audit-row-${e.id}`}>
                    <TableCell className="font-mono-data text-xs txt-secondary">
                      <div>{e.ts.slice(0, 10)}</div>
                      <div className="txt-muted">{e.ts.slice(11, 19)}</div>
                    </TableCell>
                    <TableCell className="font-section text-xs">{TYPE_LABELS[e.event_type] || e.event_type}</TableCell>
                    <TableCell className={`font-section text-xs ${SEVERITY_CLASSES[e.severity]}`}>{e.severity}</TableCell>
                    <TableCell className="font-mono-data text-xs txt-muted">{e.actor}</TableCell>
                    <TableCell className="text-sm">{e.summary}</TableCell>
                    <TableCell className="font-mono-data text-[10px] txt-muted">
                      {e.correlation_id ? e.correlation_id.slice(0, 8) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {hasMore && (
            <div className="border-t border-[var(--border)] p-3 flex justify-center">
              <Button
                data-testid="audit-load-more"
                variant="outline"
                size="sm"
                onClick={() => load(true)}
                disabled={loading}
                className="rounded-none border-[var(--border)] hover:border-white"
              >
                {loading ? <Loader2 className="w-3.5 h-3.5 mr-2 animate-spin" /> : null}
                Load more
              </Button>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
