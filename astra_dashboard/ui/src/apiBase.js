export const API_BASE_STORAGE_KEY = "astra_api_base_url";
export const DEFAULT_API_BASE = "http://127.0.0.1:8000";
export const API_TOKEN_STORAGE_KEY = "astra_remote_access_token";
export const API_BASE_CHANGED_EVENT = "astra:api-base-changed";
export const DEFAULT_FETCH_TIMEOUT_MS = 9000;
export const DEFAULT_STALE_PAYLOAD_TTL_MS = 180000;

const LAST_GOOD_RESPONSE_CACHE = new Map();

function defaultApiBaseFromWindow() {
  try {
    if (typeof window === "undefined" || !window.location) return DEFAULT_API_BASE;
    const proto = String(window.location.protocol || "http:");
    const host = String(window.location.hostname || "127.0.0.1");
    if (!host || host === "localhost" || host === "127.0.0.1") return DEFAULT_API_BASE;
    return `${proto}//${host}:8000`;
  } catch (_e) {
    return DEFAULT_API_BASE;
  }
}

function normalizeApiBase(raw) {
  const v = String(raw || "").trim();
  if (!v) return "";
  try {
    const u = new URL(v);
    // Normalize localhost and 127.0.0.1 to a single canonical local host.
    const host = u.hostname === "localhost" ? "127.0.0.1" : u.hostname;
    const port = u.port ? `:${u.port}` : "";
    return `${u.protocol}//${host}${port}`.replace(/\/$/, "");
  } catch (_e) {
    return v.replace("://localhost:", "://127.0.0.1:").replace(/\/$/, "");
  }
}

function isLoopbackHostname(hostname) {
  const h = String(hostname || "").trim().toLowerCase();
  return h === "localhost" || h === "127.0.0.1" || h === "::1";
}

function isLoopbackBase(base) {
  try {
    const u = new URL(normalizeApiBase(base));
    return isLoopbackHostname(u.hostname);
  } catch (_e) {
    const b = String(base || "").toLowerCase();
    return b.includes("://localhost:") || b.includes("://127.0.0.1:") || b.includes("://[::1]:");
  }
}

function currentWindowHostIsRemote() {
  try {
    if (typeof window === "undefined" || !window.location) return false;
    return !isLoopbackHostname(window.location.hostname || "");
  } catch (_e) {
    return false;
  }
}

export function resolveApiBase() {
  const envBase = normalizeApiBase(import.meta.env.VITE_API_BASE_URL || "");
  return envBase || defaultApiBaseFromWindow();
}

export function getInitialApiBase() {
  const resolved = resolveApiBase();
  if (resolved) return resolved;
  try {
    const stored = normalizeApiBase(window.localStorage.getItem(API_BASE_STORAGE_KEY) || "");
    if (stored) return stored;
  } catch (_e) {}
  return DEFAULT_API_BASE;
}

export function persistApiBase(base) {
  try {
    const normalized = normalizeApiBase(base);
    window.localStorage.setItem(API_BASE_STORAGE_KEY, normalized);
    window.dispatchEvent(new CustomEvent(API_BASE_CHANGED_EVENT, { detail: { base: normalized } }));
  } catch (_e) {}
}

export function buildApiUrl(base, path) {
  const b = normalizeApiBase(base) || defaultApiBaseFromWindow();
  return `${b}${path}`;
}

function alternateHost(base) {
  const normalized = normalizeApiBase(base);
  if (!normalized) return "";
  if (normalized.includes("://localhost:")) return normalized.replace("://localhost:", "://127.0.0.1:");
  if (normalized.includes("://127.0.0.1:")) return normalized.replace("://127.0.0.1:", "://localhost:");
  return "";
}

export function getApiBaseCandidates(preferredBase = "") {
  const candidates = [];
  const push = (v) => {
    const n = normalizeApiBase(v);
    if (!n) return;
    if (!candidates.includes(n)) candidates.push(n);
  };

  push(preferredBase);
  push(getInitialApiBase());
  push(resolveApiBase());
  push(DEFAULT_API_BASE);
  push(alternateHost(preferredBase));
  push(alternateHost(getInitialApiBase()));
  push(alternateHost(resolveApiBase()));
  push(alternateHost(DEFAULT_API_BASE));
  if (currentWindowHostIsRemote()) {
    const remoteFirst = candidates.filter((v) => !isLoopbackBase(v));
    const loopbackTail = candidates.filter((v) => isLoopbackBase(v));
    return [...remoteFirst, ...loopbackTail];
  }
  return candidates;
}

export async function fetchJsonWithFallback(path, options = {}) {
  const {
    preferredBase = "",
    fallbackValue = null,
    init = undefined,
    timeoutMs = undefined,
    staleTtlMs = DEFAULT_STALE_PAYLOAD_TTL_MS,
  } = options;

  const attempts = [];
  const candidates = getApiBaseCandidates(preferredBase);
  const envToken = String(import.meta.env.VITE_REMOTE_ACCESS_TOKEN || "").trim();
  const envTimeout = Number(import.meta.env.VITE_API_TIMEOUT_MS || 0);
  const perAttemptTimeoutMs = Math.max(
    1200,
    Number.isFinite(Number(timeoutMs)) && Number(timeoutMs) > 0
      ? Number(timeoutMs)
      : (Number.isFinite(envTimeout) && envTimeout > 0 ? envTimeout : DEFAULT_FETCH_TIMEOUT_MS)
  );
  const method = String((init && init.method) || "GET").toUpperCase();
  const responseCacheKey = `${method} ${String(path || "")}`;

  const isTransientError = (errorText) => {
    const text = String(errorText || "").toLowerCase();
    if (!text) return false;
    return (
      text.includes("timeout_after_")
      || text.includes("failed to fetch")
      || text.includes("networkerror")
      || text.includes("couldn't connect")
      || text.includes("econn")
      || text.includes("socket")
      || text.includes("fetch failed")
    );
  };

  for (const base of candidates) {
    const url = buildApiUrl(base, path);
    try {
      const initHeaders = (init && init.headers) ? init.headers : {};
      const headers = { ...initHeaders, "x-astra-access-token": envToken };
      const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
      const timeoutId = controller
        ? setTimeout(() => {
            try { controller.abort(); } catch (_e) {}
          }, perAttemptTimeoutMs)
        : null;
      let res;
      try {
        res = await fetch(url, { ...(init || {}), headers, signal: controller ? controller.signal : undefined });
      } finally {
        if (timeoutId) clearTimeout(timeoutId);
      }
      if (!res.ok) {
        const body = await res.text();
        attempts.push({
          base,
          url,
          httpStatus: res.status,
          error: `${res.status} ${res.statusText}${body ? ` :: ${body.slice(0, 180)}` : ""}`,
        });
        continue;
      }
      const parsed = await res.json();
      LAST_GOOD_RESPONSE_CACHE.set(responseCacheKey, {
        ts: Date.now(),
        parsed,
        httpStatus: res.status,
        baseUsed: base,
        url,
      });
      persistApiBase(base);
      return { ok: true, baseUsed: base, url, httpStatus: res.status, parsed, attempts };
    } catch (err) {
      const timeoutLike = err && (String(err.name || "").toLowerCase() === "aborterror" || String(err.message || "").toLowerCase().includes("aborted"));
      attempts.push({
        base,
        url,
        httpStatus: null,
        error: timeoutLike ? `timeout_after_${perAttemptTimeoutMs}ms` : (err instanceof Error ? err.message : String(err)),
      });
    }
  }

  const last = attempts[attempts.length - 1] || {
    error: "No API base candidates were available",
    httpStatus: null,
  };
  const staleCached = LAST_GOOD_RESPONSE_CACHE.get(responseCacheKey);
  const staleAgeMs = staleCached ? Math.max(0, Date.now() - Number(staleCached.ts || 0)) : null;
  const staleAllowed = Number.isFinite(Number(staleTtlMs)) ? Number(staleTtlMs) > 0 : true;
  if (
    staleCached
    && staleAllowed
    && staleAgeMs !== null
    && staleAgeMs <= Number(staleTtlMs || DEFAULT_STALE_PAYLOAD_TTL_MS)
    && isTransientError(last.error)
  ) {
    return {
      ok: true,
      staleCache: true,
      staleCacheAgeMs: staleAgeMs,
      staleCacheReason: String(last.error || "transient_fetch_error"),
      baseUsed: staleCached.baseUsed || normalizeApiBase(preferredBase) || "",
      url: staleCached.url || buildApiUrl(preferredBase || DEFAULT_API_BASE, path),
      httpStatus: staleCached.httpStatus || 200,
      parsed: staleCached.parsed,
      attempts,
    };
  }
  return {
    ok: false,
    baseUsed: normalizeApiBase(preferredBase) || "",
    url: last.url || buildApiUrl(preferredBase || DEFAULT_API_BASE, path),
    httpStatus: last.httpStatus ?? null,
    parsed: fallbackValue,
    error: last.error,
    attempts,
  };
}
