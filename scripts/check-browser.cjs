const { chromium } = require("playwright");
const fs = require("fs");
const crypto = require("crypto");
(async () => {
  const browser = await chromium.launch({
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    headless: true,
  });
  const page = await browser.newPage();
  const user = {
    id: 999001,
    first_name: "Aziz",
    last_name: "Aliyev",
    username: "aziz",
    language_code: "uz",
  };
  function initData(token = "123456789:browser-test-secret-only") {
    const fields = {
      auth_date: String(Math.floor(Date.now() / 1000)),
      user: JSON.stringify(user),
    };
    const secret = crypto
      .createHmac("sha256", "WebAppData")
      .update(token)
      .digest();
    fields.hash = crypto
      .createHmac("sha256", secret)
      .update(
        Object.keys(fields)
          .sort()
          .map((k) => `${k}=${fields[k]}`)
          .join("\n"),
      )
      .digest("hex");
    return new URLSearchParams(fields).toString();
  }
  let telegramData = "";
  await page.route("**/static/telegram-web-app.js*", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: `window.Telegram={WebApp:{initData:${JSON.stringify(telegramData)},ready(){},expand(){},setHeaderColor(){}}};`,
    }),
  );
  await page.route("https://fonts.googleapis.com/**", (route) => route.abort());
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  fs.mkdirSync("test-results", { recursive: true });
  await page.goto("http://127.0.0.1:8000", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.body.dataset.auth === "blocked");
  if (await page.locator("header").isVisible())
    throw Error("Guest can see app");
  if (
    !(await page.locator("#gateTitle").innerText()).includes("faqat Telegramda")
  )
    throw Error("Missing Telegram gate");
  const blocked = await page.request.get("http://127.0.0.1:8000/api/skins");
  if (blocked.status() !== 401) throw Error("Unsigned catalog API allowed");
  telegramData = initData("wrong-secret");
  await page.reload();
  await page.waitForFunction(
    () =>
      document.body.dataset.auth === "blocked" &&
      document.querySelector("#gateTitle").textContent.includes("qayta"),
  );
  if (await page.locator("header").isVisible())
    throw Error("Forged session can see app");
  telegramData = initData();
  for (const width of [1440, 1280, 1024, 768, 390, 360]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("http://127.0.0.1:8000/skins", {
      waitUntil: "domcontentloaded",
    });
    await page.waitForSelector(".skin-card");
    await page.evaluate(() => document.fonts.ready);
    await page
      .locator(".skin-card img")
      .evaluateAll((images) => images.forEach((i) => (i.loading = "eager")));
    await page.waitForFunction(() =>
      [...document.images].every((i) => i.complete && i.naturalWidth > 0),
    );
    const result = await page.evaluate(() => ({
      width: innerWidth,
      scroll: document.documentElement.scrollWidth,
      broken: [...document.images]
        .filter((i) => !i.complete || i.naturalWidth === 0)
        .map((i) => i.src),
      cards: document.querySelectorAll(".skin-card").length,
    }));
    if (result.scroll > width)
      throw Error("Overflow: " + JSON.stringify(result));
    await page.locator(".skin-card img").last().scrollIntoViewIfNeeded();
    await page.waitForFunction(() =>
      [...document.querySelectorAll(".skin-card img")].every(
        (i) => i.complete && i.naturalWidth > 0,
      ),
    );
    await page.screenshot({
      path: `test-results/desktop-${width}.png`,
      fullPage: true,
    });
    console.log(JSON.stringify(result));
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator("#searchInput").fill("Redline");
  await page.waitForFunction(
    () => document.querySelectorAll(".skin-card").length === 1,
  );
  await page.locator("#categorySelect").selectOption("Snipers");
  await page.waitForSelector(".empty");
  await page.locator("#resetBtn").click();
  await page.waitForFunction(
    () => document.querySelectorAll(".skin-card").length === 20,
  );
  await page.locator("#sortSelect").selectOption("price_desc");
  await page.waitForFunction(() =>
    document
      .querySelector(".skin-card h3")
      ?.textContent.includes("Dragon Lore"),
  );
  await page.locator(".view-btn").first().click();
  await page.waitForURL(/\/skins\/\d+$/);
  await page.waitForSelector("#pageTitle");
  await page.goBack();
  await page.waitForSelector("#skinGrid .skin-card");
  await page.locator("#themeBtn").click();
  if ((await page.locator("html").getAttribute("data-theme")) !== "light")
    throw Error("Theme failed");
  await page.reload();
  if ((await page.locator("html").getAttribute("data-theme")) !== "light")
    throw Error("Theme persistence failed");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("#openFilters").click();
  await page.locator('input[value="Factory New"]').check();
  await page.keyboard.press("Escape");
  await page.waitForFunction(
    () =>
      document.querySelectorAll(".skin-meta").length > 0 &&
      [...document.querySelectorAll(".skin-meta")].every(
        (i) => i.textContent === "Factory New",
      ),
  );
  await page.locator('[data-action="profile"]').first().click();
  await page.waitForURL("**/profile");
  await page.waitForSelector("#pageContent");
  if (!(await page.locator("#pageContent").innerText()).includes("Aziz Aliyev"))
    throw Error("Automatic Telegram profile failed");
  if (!(await page.locator("#pageContent").innerText()).includes("@aziz"))
    throw Error("Username missing");
  await page.locator('header nav [href="/inventory"]').click();
  await page.waitForURL("**/inventory");
  await page.waitForFunction(
    () => document.querySelector("#pageTitle")?.textContent === "Inventar",
  );
  if (!(await page.locator("#pageTitle").innerText()).includes("Inventar"))
    throw Error("Inventory unavailable");
  if (errors.length) throw Error(errors.join("\n"));
  console.log(
    "PASS: blocked browser and forged session, real server HMAC auto-login/profile, responsive catalog, filters, images, theme and inventory.",
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
