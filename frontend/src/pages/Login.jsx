import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Zap } from "lucide-react";

const BG_URL =
  "https://static.prod-images.emergentagent.com/jobs/5f5c09e7-cff3-4175-97eb-bbb4082159db/images/fc241036c09b649a1bdc45cfa57ef0079f7caa53d30e8c1770628d4c602ee158.png";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("demo@algoforge.io");
  const [password, setPassword] = useState("Demo@123");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(email, password);
      toast.success("Welcome back");
      navigate("/");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex bg-[var(--bg-page)] text-white">
      <div
        className="hidden lg:flex flex-1 relative grid-bg"
        style={{
          backgroundImage: `linear-gradient(rgba(9,9,11,0.82), rgba(9,9,11,0.92)), url(${BG_URL})`,
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      >
        <div className="absolute inset-0 flex flex-col justify-between p-12">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-white text-black flex items-center justify-center">
              <Zap className="w-5 h-5" strokeWidth={2.5} />
            </div>
            <div className="font-display text-2xl tracking-tight">ALGOFORGE</div>
          </div>
          <div className="max-w-md">
            <div className="overline mb-3">AI-First Algo Trading</div>
            <h1 className="font-display text-5xl leading-[0.95] mb-4">
              Build, backtest &amp; defend against option-writer traps.
            </h1>
            <p className="txt-secondary text-sm">
              Natural-language strategy generation with GPT-5.2. Risk analysis &amp; squeeze
              detection by Claude Sonnet 4.5. Tick-replay backtests, paper execution and an
              always-on cockpit for Indian equity &amp; options desks.
            </p>
            <div className="grid grid-cols-3 gap-4 mt-10">
              <div className="border border-[var(--border)] p-4">
                <div className="kpi-num text-3xl">6</div>
                <div className="overline mt-1">Symbols seeded</div>
              </div>
              <div className="border border-[var(--border)] p-4">
                <div className="kpi-num text-3xl txt-profit">AI</div>
                <div className="overline mt-1">GPT-5.2 + Claude</div>
              </div>
              <div className="border border-[var(--border)] p-4">
                <div className="kpi-num text-3xl txt-warn">Trap</div>
                <div className="overline mt-1">Detection live</div>
              </div>
            </div>
          </div>
          <div className="overline">SEBI-compliance ready · Audit-trailed · Sandbox first</div>
        </div>
      </div>

      <div className="flex-1 flex items-center justify-center p-8">
        <form onSubmit={submit} className="w-full max-w-sm" data-testid="login-form">
          <div className="overline mb-2">Sign in</div>
          <h2 className="font-display text-4xl mb-1">Access cockpit</h2>
          <p className="txt-muted text-sm mb-8">Use your trader credentials.</p>

          <div className="space-y-4">
            <div>
              <Label htmlFor="email" className="overline">Email</Label>
              <Input
                id="email"
                type="email"
                data-testid="login-email-input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-2 rounded-none bg-[var(--bg-surface)] border-[var(--border)] font-mono-data"
                required
              />
            </div>
            <div>
              <Label htmlFor="password" className="overline">Password</Label>
              <Input
                id="password"
                type="password"
                data-testid="login-password-input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-2 rounded-none bg-[var(--bg-surface)] border-[var(--border)] font-mono-data"
                required
              />
            </div>
            <Button
              type="submit"
              data-testid="login-submit-btn"
              disabled={loading}
              className="w-full rounded-none bg-white text-black hover:bg-zinc-200 h-11 font-section tracking-wider"
            >
              {loading ? "AUTHENTICATING…" : "ENTER COCKPIT →"}
            </Button>
          </div>

          <div className="mt-6 text-sm txt-secondary">
            No account?{" "}
            <Link data-testid="login-register-link" to="/register" className="text-white underline underline-offset-4">
              Create one
            </Link>
          </div>
          <div className="mt-10 overline">Demo · demo@algoforge.io / Demo@123</div>
        </form>
      </div>
    </div>
  );
}
