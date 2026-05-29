import { useEffect, useRef, useState } from "react";

/**
 * Subscribes to the backend mock tick feed.
 * symbols: e.g. ["NIFTY","BANKNIFTY"]
 * returns { ticks: {SYMBOL: {ltp, change, change_pct, ts}}, connected: bool }
 */
export default function useTickStream(symbols = ["NIFTY", "BANKNIFTY"]) {
  const [ticks, setTicks] = useState({});
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  useEffect(() => {
    const backend = process.env.REACT_APP_BACKEND_URL || "";
    const wsBase = backend.replace(/^http/, "ws");
    const url = `${wsBase}/api/ws/ticks?symbols=${encodeURIComponent(symbols.join(","))}`;
    let stopped = false;
    let retry = null;

    const open = () => {
      try {
        const ws = new WebSocket(url);
        wsRef.current = ws;
        ws.onopen = () => setConnected(true);
        ws.onclose = () => {
          setConnected(false);
          if (!stopped) retry = setTimeout(open, 1500);
        };
        ws.onerror = () => {
          try { ws.close(); } catch {}
        };
        ws.onmessage = (e) => {
          try {
            const msg = JSON.parse(e.data);
            if (Array.isArray(msg.ticks)) {
              setTicks((prev) => {
                const next = { ...prev };
                for (const t of msg.ticks) next[t.symbol] = t;
                return next;
              });
            }
          } catch {}
        };
      } catch {
        if (!stopped) retry = setTimeout(open, 1500);
      }
    };
    open();

    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      try { wsRef.current?.close(); } catch {}
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbols.join(",")]);

  return { ticks, connected };
}
