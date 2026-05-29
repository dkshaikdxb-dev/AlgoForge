import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Zap } from "lucide-react";

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await register(email, name, password);
      toast.success("Account created");
      navigate("/");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Registration failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg-page)] text-white p-8 grid-bg">
      <form onSubmit={submit} className="w-full max-w-md panel p-8" data-testid="register-form">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-8 h-8 bg-white text-black flex items-center justify-center">
            <Zap className="w-4 h-4" strokeWidth={2.5} />
          </div>
          <div className="font-display text-xl tracking-tight">ALGOFORGE</div>
        </div>
        <div className="overline mb-1">Create account</div>
        <h2 className="font-display text-4xl mb-6">Forge your edge</h2>

        <div className="space-y-4">
          <div>
            <Label className="overline">Full name</Label>
            <Input
              data-testid="register-name-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-2 rounded-none bg-[var(--bg-surface)] border-[var(--border)]"
              required
            />
          </div>
          <div>
            <Label className="overline">Email</Label>
            <Input
              type="email"
              data-testid="register-email-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-2 rounded-none bg-[var(--bg-surface)] border-[var(--border)] font-mono-data"
              required
            />
          </div>
          <div>
            <Label className="overline">Password</Label>
            <Input
              type="password"
              data-testid="register-password-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={6}
              className="mt-2 rounded-none bg-[var(--bg-surface)] border-[var(--border)] font-mono-data"
              required
            />
          </div>
          <Button
            type="submit"
            data-testid="register-submit-btn"
            disabled={loading}
            className="w-full rounded-none bg-white text-black hover:bg-zinc-200 h-11 font-section tracking-wider"
          >
            {loading ? "CREATING…" : "CREATE ACCOUNT"}
          </Button>
        </div>
        <div className="mt-6 text-sm txt-secondary">
          Already have an account?{" "}
          <Link data-testid="register-login-link" to="/login" className="text-white underline underline-offset-4">
            Sign in
          </Link>
        </div>
      </form>
    </div>
  );
}
