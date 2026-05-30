import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API_BASE = `${BACKEND_URL}/api`;

// Cookies auth: send credentials on every request; CSRF token added below.
export const api = axios.create({ baseURL: API_BASE, withCredentials: true });

const _uuid = () =>
  (crypto?.randomUUID?.() ||
    `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`);

function getCookie(name) {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

const UNSAFE = new Set(["post", "put", "patch", "delete"]);

api.interceptors.request.use((config) => {
  // Idempotency for paper orders (per-click UUID, keeps replay-safe semantics).
  const url = config.url || "";
  if (
    config.method?.toLowerCase() === "post" &&
    (url.startsWith("/paper/order") || url.includes("/paper/order/multi-leg")) &&
    !config.headers["Idempotency-Key"]
  ) {
    config.headers["Idempotency-Key"] = _uuid();
  }

  // Double-submit CSRF: echo the algoforge_csrf cookie on every state-changing
  // request. Backend skips the check on Bearer-only clients; only browsers
  // with the cookie actually trigger the middleware.
  const method = (config.method || "get").toLowerCase();
  if (UNSAFE.has(method)) {
    const csrf = getCookie("algoforge_csrf");
    if (csrf) config.headers["X-CSRF-Token"] = csrf;
  }

  // Legacy bridge: any localStorage token still present from earlier sessions
  // is sent as Bearer too (it's accepted by get_current_user). Removed by
  // auth.jsx's bootstrap migration on the first /auth/me call.
  const legacy = typeof localStorage !== "undefined" && localStorage.getItem("af_token");
  if (legacy && !config.headers.Authorization) {
    config.headers.Authorization = `Bearer ${legacy}`;
  }
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) {
      try { localStorage.removeItem("af_token"); } catch { /* ignore storage errors */ }
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
    }
    return Promise.reject(err);
  },
);

export default api;
