const { chromium } = require("playwright");
const crypto = require("crypto");
const fs = require("fs");
const base = "http://127.0.0.1:8000";
const user = {
  id: 999010,
  first_name: "Aziz",
  last_name: "Aliyev",
  username: "pages_test",
  language_code: "uz",
};
function launchData() {
  const fields = {
    auth_date: String(Math.floor(Date.now() / 1000)),
    user: JSON.stringify(user),
  };
  const key = crypto
    .createHmac("sha256", "WebAppData")
    .update("123456789:browser-test-secret-only")
    .digest();
  fields.hash = crypto
    .createHmac("sha256", key)
    .update(
      Object.keys(fields)
        .sort()
        .map((k) => `${k}=${fields[k]}`)
        .join("\n"),
    )
    .digest("hex");
  return new URLSearchParams({
    tgWebAppData: new URLSearchParams(fields).toString(),
    tgWebAppPlatform: "android",
    tgWebAppVersion: "8.0",
  }).toString();
}
(async () => {
  const browser = await chromium.launch({
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    headless: true,
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route("https://fonts.googleapis.com/**", (r) => r.abort());
  await page.goto(base + "/profile#" + launchData(), {
    waitUntil: "domcontentloaded",
  });
  await page.waitForFunction(() => document.body.dataset.auth === "ready");
  if ((await page.locator("#pageTitle").innerText()) !== "Profil")
    throw Error("Deep profile route failed");
  if (!(await page.locator("#pageContent").innerText()).includes("Aziz Aliyev"))
    throw Error("Profile data missing");
  if (await page.locator(".hero").isVisible())
    throw Error("Home visible on profile");
  await page.reload();
  await page.waitForFunction(() => document.body.dataset.auth === "ready");
  if ((await page.locator("#pageTitle").innerText()) !== "Profil")
    throw Error("Profile refresh lost route/login");
  console.log("PASS direct page refresh and Telegram session preservation");
  await page.locator('header nav [href="/skins"]').click();
  await page.waitForSelector("#skinGrid .skin-card");
  await page.locator("#searchInput").fill("Redline");
  await page.waitForFunction(
    () => document.querySelectorAll("#skinGrid .skin-card").length === 1,
  );
  await page.locator("#categorySelect").selectOption("Rifles");
  await page.waitForURL(/category=Rifles/);
  const filteredUrl = page.url();
  await page.locator(".view-btn").first().click();
  await page.waitForURL("**/skins/1");
  await page.waitForFunction(
    () =>
      document.querySelector("#pageTitle")?.textContent === "AK-47 | Redline",
  );
  if (await page.locator("#catalog").isVisible())
    throw Error("Catalog visible on detail page");
  await page.goBack();
  await page.waitForSelector("#skinGrid .skin-card");
  if (
    page.url() !== filteredUrl ||
    (await page.locator("#searchInput").inputValue()) !== "Redline" ||
    (await page.locator("#categorySelect").inputValue()) !== "Rifles"
  )
    throw Error("Back lost catalog filters");
  await page.goForward();
  await page.waitForFunction(
    () =>
      document.querySelector("#pageTitle")?.textContent === "AK-47 | Redline",
  );
  await page.reload();
  await page.waitForFunction(() => document.body.dataset.auth === "ready");
  if ((await page.locator("#pageTitle").innerText()) !== "AK-47 | Redline")
    throw Error("Detail refresh failed");
  console.log("PASS skin detail URL, catalog filters and back/forward");
  await page.locator("header .balance").click();
  await page.waitForFunction(
    () => document.querySelector("#pageTitle")?.textContent === "Balans",
  );
  await page.locator('#pageContent [href="/balance/topup"]').click();
  await page.waitForURL("**/balance/topup");
  await page.locator("#amount").fill("100");
  await page.locator('#topupForm [type="submit"]').click();
  await page.waitForFunction(
    () => document.querySelector(".wallet-amount")?.textContent === "$100.00",
  );
  await page.locator('header nav [href="/skins"]').click();
  await page.waitForSelector("#skinGrid .skin-card");
  await page.locator('.view-btn[href="/skins/1"]').click();
  await page.waitForSelector('[data-purchase="1"]');
  await page.locator('[data-purchase="1"]').click();
  await page.waitForURL("**/inventory");
  await page.waitForSelector("[data-sell]");
  if (
    !(await page.locator("#pageContent").innerText()).includes(
      "AK-47 | Redline",
    )
  )
    throw Error("Purchased item not in inventory");
  await page.locator("[data-sell]").first().click();
  await page.waitForFunction(() => !document.querySelector("[data-sell]"));
  await page.locator("header .balance").click();
  await page.waitForFunction(
    () => document.querySelector(".wallet-amount")?.textContent === "$100.00",
  );
  await page.locator('#pageContent [href="/history"]').click();
  await page.waitForURL("**/history");
  await page.waitForFunction(
    () => document.querySelectorAll("#pageContent .history-row").length >= 3,
  );
  console.log(
    "PASS routed top-up, purchase, inventory sale, balance and history persistence",
  );
  async function route(path) {
    await page.evaluate((target) => {
      window.history.pushState({ skinsavo: true, depth: 1 }, "", target);
      window.dispatchEvent(new PopStateEvent("popstate"));
    }, path);
    if (path === "/" || path === "/skins")
      await page.waitForFunction(
        () =>
          document.querySelector("#skinGrid").getAttribute("aria-busy") ===
          "false",
      );
    else if (path === "/faq") await page.waitForSelector("#faq:visible");
    else
      await page.waitForFunction(
        () =>
          document.querySelector("#pageTitle")?.textContent !== "Yuklanmoqda…",
      );
  }
  await route("/skins/999999");
  await page.waitForFunction(
    () =>
      document.querySelector("#pageTitle")?.textContent === "Skin topilmadi",
  );
  await route("/admin");
  if ((await page.locator("#pageTitle").innerText()) !== "Kirish cheklangan")
    throw Error("Admin page not guarded");
  for (const path of [
    "/",
    "/skins",
    "/skins/1",
    "/profile",
    "/inventory",
    "/balance",
    "/balance/topup",
    "/history",
    "/faq",
  ]) {
    await route(path);
    for (const width of [1440, 1280, 1024, 768, 390, 360]) {
      await page.setViewportSize({ width, height: 900 });
      if (
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        )
      )
        throw Error(`Overflow ${path} at ${width}`);
    }
    await page.screenshot({
      path:
        "test-results/page-" +
        (path === "/" ? "home" : path.slice(1).replaceAll("/", "-")) +
        ".png",
      fullPage: true,
    });
  }
  if (errors.length) throw Error(errors.join("\n"));
  console.log(
    "PASS all page layouts at six viewport widths, missing skin, admin guard and no JavaScript errors",
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
