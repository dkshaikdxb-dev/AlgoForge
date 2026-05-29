import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API_BASE = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API_BASE });

// Generate a per-click UUID for paper-order endpoints so legitimate retries
// (user clicks BUY twice on purpose) aren't silently replayed by the server's
// 24h idempotency cache. Backend matches against this header.
const _uuid = () =>
  (crypto?.randomUUID?.() ||
    `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`);

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("af_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  const url = config.url || "";
  if (
    config.method?.toLowerCase() === "post" &&
    (url.startsWith("/paper/order") || url.includes("/paper/order/multi-leg")) &&
    !config.headers["Idempotency-Key"]
  ) {
    config.headers["Idempotency-Key"] = _uuid();
  }
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) {
      localStorage.removeItem("af_token");
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
    }
    return Promise.reject(err);
  },
);

export default api;
