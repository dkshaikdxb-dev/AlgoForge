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
  const symbolsKey = symbols.join(",");

  useEffect(() => {
    const backend = process.env.REACT_APP_BACKEND_URL || "";
    const wsBase = backend.replace(/^http/, "ws");
    const url = `${wsBase}/api/ws/ticks?symbols=${encodeURIComponent(symbolsKey)}`;
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
        ws.onerror = (err) => {
          console.warn("[useTickStream] websocket error", err);
          try {
            ws.close();
          } catch (closeErr) {
            console.warn("[useTickStream] close after error failed", closeErr);
          }
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
          } catch (parseErr) {
            console.warn("[useTickStream] failed to parse tick payload", parseErr);
          }
        };
      } catch (connectErr) {
        console.warn("[useTickStream] failed to open WebSocket; retrying", connectErr);
        if (!stopped) retry = setTimeout(open, 1500);
      }
    };
    open();

    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      try {
        wsRef.current?.close();
      } catch (cleanupErr) {
        console.warn("[useTickStream] cleanup close failed", cleanupErr);
      }
    };
  }, [symbolsKey]);

  return { ticks, connected };
}
