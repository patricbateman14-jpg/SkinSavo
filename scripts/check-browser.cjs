const { chromium } = require("playwright");
const fs = require("fs");
(async () => {
  const browser = await chromium.launch({
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    headless: true,
  });
  const page = await browser.newPage();
  await page.route("https://telegram.org/**", (route) =>
    route.fulfill({ body: "" }),
  );
  await page.route("https://fonts.googleapis.com/**", (route) => route.abort());
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  fs.mkdirSync("test-results", { recursive: true });
  for (const width of [1440, 1280, 1024, 768, 390, 360]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("http://127.0.0.1:8000", { waitUntil: "domcontentloaded" });
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
  await page.waitForSelector("dialog[open]");
  await page.keyboard.press("Escape");
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
  await page.locator('[data-action="inventory"]').first().click();
  await page.waitForSelector("dialog[open]");
  if (
    !(await page.locator("#modalContent").innerText()).includes(
      "Telegram orqali kiring",
    )
  )
    throw Error("Guest auth failed");
  if (errors.length) throw Error(errors.join("\n"));
  console.log(
    "PASS: responsive, images, search, combined category, reset, sorting, detail, theme persistence, mobile drawer and guest authentication.",
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
