import { useEffect, useRef, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Copy, ExternalLink, Loader2, ShieldCheck, Wand2, Check } from "lucide-react";
import { toast } from "sonner";

const POLL_INTERVAL_MS = 2500;
const POLL_TIMEOUT_MS = 5 * 60 * 1000;

export default function BrokerOAuthWizard({ broker, onClose, onLinked }) {
  const [step, setStep] = useState(1); // 1 urls, 2 keys, 3 awaiting, 4 done
  const [urls, setUrls] = useState({ redirect_url: "", postback_url: "", oauth_supported: false });
  const [creds, setCreds] = useState({ api_key: "", api_secret: "" });
  const [busy, setBusy] = useState(false);
  const [authWindow, setAuthWindow] = useState(null);
  const [linkStatus, setLinkStatus] = useState(null);
  const pollRef = useRef(null);
  const startedAt = useRef(0);

  useEffect(() => {
    // Reset all wizard state when the broker prop changes — prevents step/state
    // leakage across consecutive wizard sessions on different brokers.
    setStep(1);
    setCreds({ api_key: "", api_secret: "" });
    setLinkStatus(null);
    setAuthWindow(null);
    setUrls({ redirect_url: "", postback_url: "", oauth_supported: false });
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (!broker) return;
    (async () => {
      try {
        const { data } = await api.get(`/brokers/${broker.name}/oauth/urls`);
        setUrls(data);
      } catch {
        toast.error("Could not load OAuth URLs");
      }
    })();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [broker]);

  const copy = async (text, label) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(`${label} copied`);
    } catch {
      toast.error("Copy failed");
    }
  };

  const launchLogin = async () => {
    if (!creds.api_key || !creds.api_secret) {
      toast.error("Enter API key & secret first");
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.post(`/brokers/${broker.name}/oauth/start`, creds);
      const w = window.open(data.login_url, "_blank", "noopener,noreferrer,width=540,height=720");
      setAuthWindow(w);
      setStep(3);
      startedAt.current = Date.now();
      pollRef.current = setInterval(checkStatus, POLL_INTERVAL_MS);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "OAuth start failed");
    } finally {
      setBusy(false);
    }
  };

  const checkStatus = async () => {
    if (Date.now() - startedAt.current > POLL_TIMEOUT_MS) {
      clearInterval(pollRef.current);
      toast.error("Wizard timed out — try again");
      onClose?.();
      return;
    }
    try {
      const { data } = await api.get("/brokers");
      const me = data.items.find((b) => b.name === broker.name);
      if (me?.connected && (me.status === "live" || me.status === "error")) {
        clearInterval(pollRef.current);
        setLinkStatus(me.status);
        setStep(4);
        if (me.status === "live") {
          toast.success(`${broker.label} connected`);
          onLinked?.();
        } else {
          toast.error(`${broker.label} link failed: ${me.last_message || ""}`);
        }
      }
    } catch {
      /* keep polling */
    }
  };

  if (!broker) return null;

  return (
    <Dialog open={!!broker} onOpenChange={(v) => !v && onClose?.()}>
      <DialogContent
        data-testid="oauth-wizard-dialog"
        className="rounded-none bg-[var(--bg-surface)] border-[var(--border)] text-white max-w-2xl"
      >
        <DialogHeader>
          <DialogTitle className="font-display text-2xl flex items-center gap-2">
            <Wand2 className="w-5 h-5 txt-warn" /> {broker.label} · OAuth wizard
          </DialogTitle>
        </DialogHeader>

        {/* Step rail */}
        <div className="flex gap-1 mt-1 mb-4">
          {[1, 2, 3, 4].map((n) => (
            <div
              key={n}
              className={`h-0.5 flex-1 ${step >= n ? "bg-white" : "bg-zinc-700"}`}
            />
          ))}
        </div>

        {step === 1 && (
          <div className="space-y-4" data-testid="wizard-step-1">
            <div className="overline">Step 1 · paste these into your broker developer console</div>
            <p className="text-xs txt-secondary">
              Open the {broker.label} developer console and create / edit an app. Paste the redirect URL
              (mandatory) and, if your plan supports it, the postback URL (optional, used for real-time
              order push notifications).
            </p>

            <div>
              <Label className="overline">Redirect URL · MANDATORY</Label>
              <div className="flex mt-1">
                <Input
                  data-testid="wizard-redirect-url"
                  readOnly
                  value={urls.redirect_url}
                  className="rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data text-xs"
                />
                <Button
                  data-testid="wizard-copy-redirect"
                  type="button"
                  onClick={() => copy(urls.redirect_url, "Redirect URL")}
                  className="rounded-none bg-white text-black hover:bg-zinc-200 px-3"
                >
                  <Copy className="w-3.5 h-3.5" />
                </Button>
              </div>
            </div>

            <div>
              <Label className="overline">Postback URL · OPTIONAL</Label>
              <div className="flex mt-1">
                <Input
                  data-testid="wizard-postback-url"
                  readOnly
                  value={urls.postback_url}
                  className="rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data text-xs"
                />
                <Button
                  data-testid="wizard-copy-postback"
                  type="button"
                  onClick={() => copy(urls.postback_url, "Postback URL")}
                  className="rounded-none bg-white text-black hover:bg-zinc-200 px-3"
                >
                  <Copy className="w-3.5 h-3.5" />
                </Button>
              </div>
              <p className="text-[11px] txt-muted mt-1">
                A per-connection token will be appended to this URL after the first successful link.
              </p>
            </div>

            {!urls.oauth_supported && (
              <div className="border border-amber-500/40 bg-amber-500/5 p-3 txt-warn text-xs">
                <strong>Heads up:</strong> {broker.label} doesn't expose a standard OAuth dialog. Copy the
                URLs above into their developer console, then go back to the broker card and use the manual
                CONNECT flow with whatever credentials they issue.
              </div>
            )}
          </div>
        )}

        {step === 2 && urls.oauth_supported && (
          <div className="space-y-4" data-testid="wizard-step-2">
            <div className="overline">Step 2 · API key + secret</div>
            <p className="text-xs txt-secondary">
              From the same developer console, copy your app credentials and paste them here. Stored
              encrypted at rest. The access token is generated automatically in the next step.
            </p>
            <div>
              <Label className="overline">API Key</Label>
              <Input
                data-testid="wizard-api-key"
                value={creds.api_key}
                onChange={(e) => setCreds({ ...creds, api_key: e.target.value })}
                className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data"
              />
            </div>
            <div>
              <Label className="overline">API Secret</Label>
              <Input
                data-testid="wizard-api-secret"
                type="password"
                value={creds.api_secret}
                onChange={(e) => setCreds({ ...creds, api_secret: e.target.value })}
                className="mt-1 rounded-none bg-[var(--bg-page)] border-[var(--border)] font-mono-data"
              />
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4 text-center py-6" data-testid="wizard-step-3">
            <Loader2 className="w-8 h-8 animate-spin mx-auto txt-warn" />
            <div className="font-section tracking-wider">WAITING FOR {broker.label.toUpperCase()} LOGIN</div>
            <p className="text-xs txt-secondary max-w-md mx-auto">
              A new tab has opened with the {broker.label} login page. Sign in there; we'll capture the
              access token automatically and close that tab. Don't refresh this page.
            </p>
            {authWindow && (
              <button
                data-testid="wizard-reopen-login"
                onClick={() => authWindow.focus()}
                className="text-xs txt-muted underline hover:text-white inline-flex items-center gap-1"
              >
                Re-open broker login <ExternalLink className="w-3 h-3" />
              </button>
            )}
          </div>
        )}

        {step === 4 && (
          <div className="space-y-3 text-center py-6" data-testid="wizard-step-4">
            {linkStatus === "live" ? (
              <>
                <div className="mx-auto w-12 h-12 bg-emerald-500/10 flex items-center justify-center">
                  <Check className="w-6 h-6 txt-profit" />
                </div>
                <div className="font-display text-xl">CONNECTED</div>
                <p className="txt-secondary text-sm">
                  {broker.label} is live. Live orders will route through this account. Reconciler will pick
                  it up on the next tick.
                </p>
              </>
            ) : (
              <>
                <div className="mx-auto w-12 h-12 bg-red-500/10 flex items-center justify-center">
                  <ShieldCheck className="w-6 h-6 txt-loss" />
                </div>
                <div className="font-display text-xl">LINK FAILED</div>
                <p className="txt-secondary text-sm">
                  Token exchange completed but the live test failed. Check the Brokers page for the last
                  error message and retry.
                </p>
              </>
            )}
          </div>
        )}

        <DialogFooter className="gap-2">
          {step === 1 && (
            <Button
              data-testid="wizard-next-1"
              disabled={!urls.redirect_url}
              onClick={() => urls.oauth_supported ? setStep(2) : onClose?.()}
              className="rounded-none bg-white text-black hover:bg-zinc-200 font-section tracking-wider"
            >
              {urls.oauth_supported ? "NEXT · ENTER KEYS" : "DONE"}
            </Button>
          )}
          {step === 2 && (
            <>
              <Button
                data-testid="wizard-back-2"
                variant="ghost"
                onClick={() => setStep(1)}
                className="rounded-none"
              >
                BACK
              </Button>
              <Button
                data-testid="wizard-launch-login"
                disabled={busy || !creds.api_key || !creds.api_secret}
                onClick={launchLogin}
                className="rounded-none bg-white text-black hover:bg-zinc-200 font-section tracking-wider"
              >
                {busy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <ExternalLink className="w-4 h-4 mr-2" />}
                LAUNCH BROKER LOGIN
              </Button>
            </>
          )}
          {step === 3 && (
            <Button
              data-testid="wizard-cancel-3"
              variant="ghost"
              onClick={() => {
                if (pollRef.current) clearInterval(pollRef.current);
                onClose?.();
              }}
              className="rounded-none"
            >
              CANCEL
            </Button>
          )}
          {step === 4 && (
            <Button
              data-testid="wizard-close-4"
              onClick={onClose}
              className="rounded-none bg-white text-black hover:bg-zinc-200 font-section tracking-wider"
            >
              CLOSE
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
