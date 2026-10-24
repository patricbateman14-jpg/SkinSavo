const { chromium } = require("playwright");
const crypto = require("crypto");
const base = "http://127.0.0.1:8000";
function signed(token = "123456789:browser-test-secret-only") {
  const data = {
    auth_date: String(Math.floor(Date.now() / 1000)),
    user: JSON.stringify({
      id: 999002,
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
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    // Network access to external SDK is intentionally blocked. Real local SDK
    // still has to parse Telegram's launch fragment in the normal scenario.
    await page.route("https://telegram.org/**", (r) => r.abort());
    await page.route("https://fonts.googleapis.com/**", (r) => r.abort());
    if (options.blockSdk)
      await page.route("**/static/telegram-web-app.js*", (r) => r.abort());
    if (options.late) {
      await page.addInitScript((data) => {
        setTimeout(() => {
          window.Telegram = {
            WebApp: {
              initData: data,
              platform: "android",
              ready() {},
              expand() {},
            },
          };
        }, 750);
      }, signed());
    }
    if (options.slow)
      await page.route("**/api/session", async (r) => {
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
    const pendingStart = await page.evaluate(() => performance.now());
    if (await page.locator("header").isVisible())
      throw Error(label + ": early app exposure");
    await page.waitForTimeout(1500);
    if (!(await page.locator("#authLoading").isVisible()))
      throw Error(label + ": splash shorter than 3 seconds");
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
    if (errors.length) throw Error(label + ": " + errors.join("\n"));
    console.log("PASS", label, Math.round(elapsed) + "ms");
    await context.close();
  }
  await scenario("official local SDK / signed Android launch fragment", {
    hash: true,
  });
  await scenario("delayed Telegram bridge", { late: true });
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
