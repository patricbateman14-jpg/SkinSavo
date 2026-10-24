const { chromium } = require("playwright");
const crypto = require("crypto");
const base = process.env.SKINSAVO_TEST_URL || "http://127.0.0.1:8000";
function signed(
  token = "123456789:browser-test-secret-only",
  age = 0,
  id = 999002,
) {
  const data = {
    auth_date: String(Math.floor(Date.now() / 1000) - age),
    user: JSON.stringify({
      id,
      first_name: "Telegram",
      last_name: "User",
    }),
  };
  const secret = crypto
    .createHmac("sha256", "WebAppData")
    .update(token)
    .digest();
  data.hash = crypto
    .createHmac("sha256", secret)
    .update(
      Object.keys(data)
        .sort()
        .map((k) => `${k}=${data[k]}`)
        .join("\n"),
    )
    .digest("hex");
  return new URLSearchParams(data).toString();
}
(async () => {
  const browser = await chromium.launch({
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    headless: true,
  });
  async function scenario(label, options = {}) {
    if (
      process.env.SKINSAVO_TEST_SCENARIO &&
      !label.includes(process.env.SKINSAVO_TEST_SCENARIO)
    )
      return;
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    const releases = [];
    let sessionRequests = 0;
    let firstSessionAt;
    page.on("pageerror", (e) => errors.push(e.message));
    // Network access to external SDK is intentionally blocked. Real local SDK
    // still has to parse Telegram's launch fragment in the normal scenario.
    await page.route("https://telegram.org/**", (r) => r.abort());
    await page.route("https://fonts.googleapis.com/**", (r) => r.abort());
    if (options.noTimeoutApi)
      await page.addInitScript(() => {
        AbortSignal.timeout = undefined;
      });
    if (options.noStorage)
      await page.addInitScript(() => {
        Storage.prototype.getItem = Storage.prototype.setItem = () => {
          throw new DOMException("Storage disabled", "SecurityError");
        };
      });
    if (options.staleSdk)
      await page.addInitScript(
        (data) => {
          sessionStorage.setItem(
            "__telegram__initParams",
            JSON.stringify({ tgWebAppData: data }),
          );
        },
        signed(undefined, 90000),
      );
    for (const pattern of options.stalled
      ? [
          "https://fonts.googleapis.com/**",
          "**/static/telegram-web-app.js*",
          "**/static/assets/manifest.json",
          "**/api/skins?*",
        ]
      : []) {
      await page.route(pattern, async (r) => {
        await new Promise((resolve) => releases.push(resolve));
        await r.abort().catch(() => {});
      });
    }
    if (options.blockSdk)
      await page.route("**/static/telegram-web-app.js*", (r) => r.abort());
    if (options.late) {
      await page.addInitScript(
        ({ data, delay, hint }) => {
          if (hint) window.TelegramWebviewProxy = { postEvent() {} };
          setTimeout(() => {
            window.Telegram = {
              WebApp: {
                initData: data,
                platform: "android",
                ready() {},
                expand() {},
              },
            };
          }, delay);
        },
        {
          data: signed(),
          delay: options.late === true ? 750 : options.late,
          hint: options.hint,
        },
      );
    }
    await page.route("**/api/session", async (r) => {
      sessionRequests++;
      firstSessionAt ??= Date.now();
      if (options.switchIdentity && sessionRequests === 1) {
        await page.evaluate(
          (data) =>
            history.replaceState(
              null,
              "",
              location.pathname +
                "#" +
                new URLSearchParams({ tgWebAppData: data }),
            ),
          signed(undefined, 0, 999003),
        );
      }
      if (options.timeout && sessionRequests === 1) {
        await new Promise((resolve) => releases.push(resolve));
        return r.abort().catch(() => {});
      }
      if (options.manual && sessionRequests <= 3)
        return r.fulfill({ status: 503, body: "Temporary failure" });
      if (options.transient && sessionRequests === 1) {
        if (options.transient === "network") return r.abort();
        return r.fulfill({
          status: options.transient === "html" ? 200 : 503,
          contentType: "text/html",
          body: "Temporarily unavailable",
        });
      }
      if (options.slow)
        await new Promise((resolve) => setTimeout(resolve, 4000));
      await r.continue();
    });
    let url = base;
    if (options.hash)
      url +=
        "#" +
        new URLSearchParams({
          tgWebAppData: options.invalid ? signed("invalid-key") : signed(),
          tgWebAppPlatform: "android",
          tgWebAppVersion: "8.0",
        });
    if (options.query)
      url += "?" + new URLSearchParams({ tgWebAppData: signed() });
    const started = Date.now();
    await page.goto(url, { waitUntil: "domcontentloaded" });
    const pendingStart = await page.evaluate(
      () => window.SkinSavoAuth.startedAt,
    );
    if (await page.locator("header").isVisible())
      throw Error(label + ": early app exposure");
    await page.waitForTimeout(1500);
    if (!(await page.locator("#authLoading").isVisible()))
      throw Error(label + ": splash shorter than 3 seconds");
    if (options.late > 3000 && !options.hint) {
      await page.waitForFunction(
        () => document.body.dataset.auth === "blocked",
      );
      if (await page.locator("header").isVisible())
        throw Error("Late bridge bypassed signature");
    }
    const target = options.blocked ? "blocked" : "ready";
    await page.waitForFunction(
      (state) => document.body.dataset.auth === state,
      target,
    );
    const elapsed = await page.evaluate(
      (start) => performance.now() - start,
      pendingStart,
    );
    if (elapsed < 2800) throw Error(label + ": splash too short " + elapsed);
    if (!options.blocked && !(await page.locator("header").isVisible()))
      throw Error(label + ": valid Telegram entry blocked");
    if (options.blocked && (await page.locator("header").isVisible()))
      throw Error(label + ": invalid entry accepted");
    if (options.slow && Date.now() - started < 3900)
      throw Error(label + ": app opened before profile");
    if (options.stalled && Date.now() - started > 4500)
      throw Error("Nonessential requests delayed login");
    if (options.transient && sessionRequests !== 2)
      throw Error("Transient error not retried exactly once");
    if (
      options.timeout &&
      (sessionRequests !== 2 || Date.now() - started > 7500)
    )
      throw Error("Timed-out profile did not recover within bounds");
    if (options.manual) {
      if (sessionRequests !== 3) throw Error("Retry budget was not bounded");
      await page.locator("#authRetry").click();
      await page.waitForFunction(() => document.body.dataset.auth === "ready");
      if (sessionRequests !== 4) throw Error("Manual retry did not recover");
    }
    if (options.invalid && sessionRequests !== 1)
      throw Error("Forged credentials repeatedly retried");
    if (options.switchIdentity) {
      if (sessionRequests !== 2)
        throw Error("Superseded login result accepted");
      await page.locator('header [href="/profile"]').click();
      await page.waitForFunction(() =>
        document.querySelector("#pageContent")?.textContent.includes("999003"),
      );
    }
    if (options.noStorage) {
      await page.locator('header [href="/profile"]').click();
      await page.waitForFunction(
        () => document.querySelector("#pageTitle")?.textContent === "Profil",
      );
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.waitForFunction(() => document.body.dataset.auth === "ready");
      if ((await page.locator("#pageTitle").innerText()) !== "Profil")
        throw Error("Storage-free refresh lost route");
    }
    if (options.fast && firstSessionAt - started > 1200)
      throw Error("Session verification started too late");
    if (errors.length) throw Error(label + ": " + errors.join("\n"));
    console.log(
      "PASS",
      label,
      Math.round(elapsed) + "ms",
      "session requests:",
      sessionRequests,
      firstSessionAt
        ? "first request at " + (firstSessionAt - started) + "ms"
        : "",
    );
    releases.forEach((resolve) => resolve());
    await context.close();
  }
  await scenario("official local SDK / signed Android launch fragment", {
    hash: true,
    fast: true,
  });
  await scenario("delayed Telegram bridge", { late: true });
  await scenario(
    "new launch supersedes in-flight identity without showing old account",
    { hash: true, switchIdentity: true },
  );
  await scenario("bridge arriving after three seconds", {
    late: 4500,
    hint: true,
  });
  await scenario(
    "bridge arriving after the browser gate recovers automatically",
    { late: 4500 },
  );
  await scenario("older WebView without AbortSignal.timeout", {
    hash: true,
    noTimeoutApi: true,
  });
  await scenario(
    "fresh query replaces expired SDK/sessionStorage credentials",
    { query: true, staleSdk: true },
  );
  await scenario(
    "storage disabled: navigation and deep refresh preserve login",
    { hash: true, noStorage: true },
  );
  await scenario("transient server 503 retries automatically", {
    hash: true,
    transient: "http",
  });
  await scenario("transient network disconnect retries automatically", {
    hash: true,
    transient: "network",
  });
  await scenario("invalid proxy HTML response retries automatically", {
    hash: true,
    transient: "html",
  });
  await scenario(
    "stalled fonts, artwork and catalog do not block verified login",
    { hash: true, stalled: true },
  );
  await scenario("timed-out profile request retries within bounded time", {
    hash: true,
    timeout: true,
  });
  await scenario(
    "exhausted retry budget shows recovery button; retry logs in",
    { hash: true, manual: true, blocked: true },
  );
  await scenario("SDK unavailable / signed fragment recovery", {
    hash: true,
    blockSdk: true,
  });
  await scenario("signed query launch recovery", { query: true });
  await scenario("slow profile stays behind loading", {
    hash: true,
    slow: true,
  });
  await scenario("plain browser remains blocked after splash", {
    blocked: true,
  });
  await scenario("forged launch is rejected after splash", {
    hash: true,
    invalid: true,
    blocked: true,
  });
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
