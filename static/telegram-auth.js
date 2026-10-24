/* Start Telegram verification before fonts, artwork and the page application. */
(() => {
  "use strict";
  const startedAt = performance.now();
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  let verifiedData = "";
  let inFlight = null;

  function launchParams(source) {
    const query = source.indexOf("?");
    return new URLSearchParams(query >= 0 ? source.slice(query + 1) : source);
  }
  function readData() {
    // An explicit new launch takes precedence over SDK/sessionStorage leftovers.
    for (const source of [location.hash.slice(1), location.search.slice(1)]) {
      const raw = launchParams(source).get("tgWebAppData");
      if (raw && raw.trim()) return raw;
    }
    const sdk = window.Telegram;
    const raw = sdk?.WebApp?.initData || sdk?.WebView?.initParams?.tgWebAppData;
    if (typeof raw === "string" && raw.trim()) return raw;
    if (verifiedData) return verifiedData;
    try {
      const stored = JSON.parse(
        sessionStorage.getItem("__telegram__initParams") || "{}",
      );
      if (typeof stored.tgWebAppData === "string") return stored.tgWebAppData;
    } catch {}
    return "";
  }
  function insideTelegram() {
    const platform = window.Telegram?.WebApp?.platform;
    return Boolean(
      (platform && platform !== "unknown") ||
      window.TelegramWebviewProxy ||
      window.external?.notify ||
      launchParams(location.hash.slice(1)).has("tgWebAppPlatform") ||
      launchParams(location.search.slice(1)).has("tgWebAppPlatform"),
    );
  }
  async function request(path, options = {}) {
    const { timeoutMs = 12000, signal, ...fetchOptions } = options;
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
    const timer = setTimeout(abort, timeoutMs);
    try {
      const response = await fetch(path, {
        ...fetchOptions,
        cache: "no-store",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          "X-Telegram-Init-Data": verifiedData || readData(),
          ...fetchOptions.headers,
        },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || data === null) {
        const error = new Error(
          typeof data?.detail === "string"
            ? data.detail
            : "Ulanish vaqtincha uzildi. Qayta urinib ko‘ring.",
        );
        error.status = response.ok ? 502 : response.status;
        throw error;
      }
      return data;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }
  async function verify() {
    const waitingSince = performance.now();
    let raw;
    while (!(raw = readData())) {
      // A real bridge gets extra time; ordinary browsers still reach the gate at 3s.
      const waitMs = insideTelegram() ? 10000 : 3000;
      if (performance.now() - waitingSince >= waitMs) {
        const error = new Error("Telegram kirish ma’lumoti kelmadi");
        error.code = "NO_INIT_DATA";
        throw error;
      }
      await sleep(50);
    }
    for (let attempt = 0; attempt < 3; attempt++) {
      raw = readData() || raw;
      auth.lastAttemptData = raw;
      try {
        const session = await request("/api/session", {
          timeoutMs: 4500,
          headers: { "X-Telegram-Init-Data": raw },
        });
        if (!session.authenticated || !session.user) {
          const error = new Error("Kirish tasdiqlanmadi");
          error.status = 502;
          throw error;
        }
        if (readData() && readData() !== raw) {
          const error = new Error("Telegram kirish ma’lumoti yangilandi");
          error.status = 401;
          throw error;
        }
        verifiedData = raw;
        return session;
      } catch (error) {
        const changed = readData() && readData() !== raw;
        const transient =
          !error.status ||
          error.status === 408 ||
          error.status === 429 ||
          error.status >= 500;
        if (attempt === 2 || (!transient && !(error.status === 401 && changed)))
          throw error;
        await sleep(attempt === 0 ? 150 : 450);
      }
    }
  }
  function signIn() {
    if (inFlight) return inFlight;
    inFlight = verify().finally(() => {
      inFlight = null;
    });
    return inFlight;
  }
  function persistLaunch() {
    try {
      const params = JSON.parse(
        sessionStorage.getItem("__telegram__initParams") || "{}",
      );
      params.tgWebAppData = verifiedData;
      sessionStorage.setItem("__telegram__initParams", JSON.stringify(params));
      if (
        JSON.parse(sessionStorage.getItem("__telegram__initParams"))
          ?.tgWebAppData === verifiedData
      )
        return "";
    } catch {}
    // Keep signed launch data across deep-page refresh if WebView storage is disabled.
    return "#" + new URLSearchParams({ tgWebAppData: verifiedData });
  }
  const auth = {
    startedAt,
    readData,
    insideTelegram,
    request,
    signIn,
    persistLaunch,
    lastAttemptData: "",
  };
  window.SkinSavoAuth = auth;
  auth.initialSession = signIn();
  // The page application attaches its handler after parsing the document.
  auth.initialSession.catch(() => {});
})();
