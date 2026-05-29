import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  Sparkles,
  LineChart,
  Activity,
  AlertTriangle,
  BookOpen,
  Settings,
  LogOut,
  Zap,
  Plug,
  ScrollText,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import TickerBar from "@/components/TickerBar";

const NAV = [
  { to: "/", label: "Cockpit", icon: LayoutDashboard, end: true, testid: "nav-cockpit" },
  { to: "/strategies", label: "Strategy Builder", icon: Sparkles, testid: "nav-strategies" },
  { to: "/backtest", label: "Backtest", icon: LineChart, testid: "nav-backtest" },
  { to: "/paper", label: "Paper Execution", icon: Activity, testid: "nav-paper" },
  { to: "/trap", label: "Trap Detection", icon: AlertTriangle, testid: "nav-trap" },
  { to: "/journal", label: "Journal", icon: BookOpen, testid: "nav-journal" },
  { to: "/audit", label: "Audit Log", icon: ScrollText, testid: "nav-audit" },
  { to: "/brokers", label: "Brokers", icon: Plug, testid: "nav-brokers" },
  { to: "/settings", label: "Settings", icon: Settings, testid: "nav-settings" },
];

export default function AppShell({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen flex bg-[var(--bg-page)] text-white">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 border-r border-[var(--border)] flex flex-col">
        <button
          data-testid="sidebar-logo"
          onClick={() => navigate("/")}
          className="px-5 py-5 flex items-center gap-2 border-b border-[var(--border)] text-left"
        >
          <div className="w-7 h-7 bg-white text-black flex items-center justify-center">
            <Zap className="w-4 h-4" strokeWidth={2.5} />
          </div>
          <div>
            <div className="font-display text-xl tracking-tight leading-none">ALGOFORGE</div>
            <div className="overline mt-0.5">AI Trading Cockpit</div>
          </div>
        </button>

        <nav className="flex-1 py-4 px-2 space-y-1">
          {NAV.map(({ to, label, icon: Icon, end, testid }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              data-testid={testid}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 text-sm font-section transition-colors ${
                  isActive
                    ? "bg-[var(--bg-surface)] text-white border-l-2 border-white"
                    : "text-zinc-400 hover:text-white hover:bg-[var(--bg-surface)] border-l-2 border-transparent"
                }`
              }
            >
              <Icon className="w-4 h-4" strokeWidth={2} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-[var(--border)] p-3">
          <div className="px-2 py-2">
            <div className="overline">Signed in</div>
            <div data-testid="sidebar-user-email" className="text-sm font-mono-data truncate">{user?.email}</div>
          </div>
          <Button
            data-testid="sidebar-logout-btn"
            variant="ghost"
            size="sm"
            onClick={logout}
            className="w-full justify-start rounded-none text-zinc-400 hover:text-white"
          >
            <LogOut className="w-4 h-4 mr-2" /> Logout
          </Button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 min-w-0 overflow-x-hidden flex flex-col">
        <TickerBar />
        <div className="flex-1">{children}</div>
      </main>
    </div>
  );
}
