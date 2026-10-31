(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const money = (n) => new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 0, maximumFractionDigits: 2,
  }).format(Number(n)).replace(/,/g, " ").replace(".", ",") + " so‘m";
  const paths = {
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1"/>',
    user: '<circle cx="12" cy="8" r="3.5"/><path d="M5 21c0-8 14-8 14 0"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    arrow: '<path d="M4 12h15m-6-6 6 6-6 6"/>',
    search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
    shield:
      '<path d="m12 3 8 4v5c0 5-8 9-8 9s-8-4-8-9V7z"/><path d="m8 12 3 3 5-6"/>',
    bolt: '<path d="m13 2-9 12h7l-1 8 10-13h-8z"/>',
    headphones:
      '<path d="M4 14v-3a8 8 0 0 1 16 0v3M4 12h3v8H4zM17 12h3v8h-3z"/>',
    filter: '<path d="M4 6h16M7 12h10M10 18h4"/>',
    reset: '<path d="M4 10a8 8 0 1 1 0 6M4 3v7h7"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    weapon: '<path d="m3 9 15-3 3 3-3 2-6 1-2 7H7l1-7-5 1zM13 12l2 4h3"/>',
    knife: '<path d="M4 20 20 4c1 9-4 12-10 11l-4 7z"/>',
    trade: '<path d="M3 7h17l-5-5M21 17H4l5 5M20 7l-5 5M4 17l5-5"/>',
  };
  const icon = (name) =>
    `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.weapon}</svg>`;
  function icons(root = document) {
    root
      .querySelectorAll("[data-icon]")
      .forEach((el) => (el.innerHTML = icon(el.dataset.icon)));
  }
  icons();
  const auth = window.SkinSavoAuth;
  if (!auth) {
    setTimeout(
      () => {
        document.body.dataset.auth = "blocked";
        $("gateTitle").textContent = "Ulanishni yangilang";
        $("gateMessage").textContent =
          "Kirish moduli yuklanmadi. Qayta urinib ko‘ring.";
        $("authRetry").hidden = false;
        $("authRetry").onclick = () => location.reload();
      },
      Math.max(0, 3000 - performance.now()),
    );
    return;
  }
  let tg = window.Telegram?.WebApp;
  let launchHash = "";
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  function readTelegramInitData() {
    tg = window.Telegram?.WebApp || tg;
    return auth.readData();
  }
  try {
    tg?.ready();
    tg?.expand();
  } catch {}
  const state = {
    category: "",
    rarity: [],
    condition: [],
    q: "",
    sort: "featured",
    offset: 0,
    items: [],
    session: null,
    balance: null,
    manifest: {},
  };
  const categories = [
    "",
    "Rifles",
    "Snipers",
    "SMGs",
    "Shotguns",
    "Pistols",
    "Knives",
    "Gloves",
  ];
  const rarities = [
    "Consumer Grade",
    "Industrial Grade",
    "Mil-Spec",
    "Restricted",
    "Classified",
    "Covert",
    "Exceedingly Rare",
    "Contraband",
  ];
  const conditions = [
    "Factory New",
    "Minimal Wear",
    "Field-Tested",
    "Well-Worn",
    "Battle-Scarred",
  ];
  $("categorySelect").innerHTML = categories
    .map((c) => `<option value="${c}">${c || "Barcha kategoriyalar"}</option>`)
    .join("");
  function renderCategories(counts = {}, total) {
    $("categoryList").innerHTML = categories
      .map(
        (c) =>
          `<button class="category ${state.category === c ? "active" : ""}" data-category="${c}" aria-pressed="${state.category === c}">${icon(!c ? "grid" : c === "Knives" ? "knife" : "weapon")}<span>${c || "Barchasi"}</span><span class="count">${c ? (counts[c] ?? "—") : (total ?? "—")}</span></button>`,
      )
      .join("");
  }
  renderCategories();
  for (const [key, values] of [
    ["rarity", rarities],
    ["condition", conditions],
  ]) {
    $(key + "List").innerHTML = values
      .map(
        (value) =>
          `<label><input type="checkbox" value="${value}" data-filter="${key}">${value}</label>`,
      )
      .join("");
  }
  let toastTimer;
  function toast(message) {
    $("toast").textContent = message;
    $("toast").classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $("toast").classList.remove("show"), 3500);
  }
  async function api(path, options = {}) {
    try {
      return await auth.request(path, options);
    } catch (error) {
      if (error.status === 401) {
        state.session = null;
        if (!authenticating)
          showGate(
            "Sessiya tugadi",
            "Botdagi SkinSavo tugmasidan qayta oching.",
          );
      }
      throw error;
    }
  }
  function imageUrl(item) {
    const value = String(item.image || "");
    return /^(https?:\/\/|\/static\/|\/media\/skins\/)/.test(value) &&
      !value.includes("placehold.co")
      ? value
      : state.manifest[item.name] || "/static/assets/art-unavailable.svg";
  }
  const rarityKeys = {"Consumer Grade":"consumer", "Industrial Grade":"industrial", "Mil-Spec":"milspec", "Restricted":"restricted", "Classified":"classified", "Covert":"covert", "Exceedingly Rare":"rare", "Contraband":"contraband"};
  const wearCodes = {"Factory New":"FN", "Minimal Wear":"MW", "Field-Tested":"FT", "Well-Worn":"WW", "Battle-Scarred":"BS"};
  function rarityKey(rarity) {
    const name = rarities.find(value => value.toLowerCase() === String(rarity).toLowerCase());
    return rarityKeys[name] || (String(rarity).toLowerCase() === "classifid" ? "classified" : "consumer");
  }
  function skinCard(item, preview = false) {
    const tag = preview ? "article" : "a";
    const source = preview && String(item.image).startsWith("blob:") ? item.image : imageUrl(item);
    const finish = item.skin || String(item.name || "").split(" | ").pop();
    const wear = wearCodes[item.condition] || String(item.condition || "").toUpperCase();
    const glyph = rarityKey(item.rarity) === "covert"
      ? '<path d="M13 2c1 5-4 5-2 9 2-1 3-3 3-5 6 5 7 10 4 14-4 4-12 2-12-4 0-4 3-5 4-8-1 5 1 5 1 5 0-4 3-6 2-11Z"/>'
      : '<path d="m12 3 8 9-8 9-8-9 8-9Zm0 5-4 4 4 4 4-4-4-4Z"/>';
    return `<${tag} class="skin-card market-card rarity-${rarityKey(item.rarity)}${Number(item.stock) < 1 ? " sold-out" : ""}" ${preview ? "" : `href="/skins/${item.id}" data-route aria-label="${esc(item.name)} · ${esc(item.condition)} · ${esc(money(item.price))}"`}><div class="card-top"><span class="card-stock">${Number(item.stock) > 0 ? `Jami: ${Number(item.stock).toLocaleString("en-US")} dona` : "Tugagan"}</span><span class="card-rarity" title="${esc(item.rarity)}" aria-label="${esc(item.rarity)}"><svg viewBox="0 0 24 24" aria-hidden="true">${glyph}</svg></span></div><div class="skin-image"><img src="${esc(source)}" alt="${esc(item.name || finish)}" loading="${preview ? "eager" : "lazy"}" width="256" height="112"></div><div class="card-meta"><span>${esc(item.weapon)}</span><abbr title="${esc(item.condition)}">${esc(wear)}</abbr></div><div class="card-title-row"><h3 title="${esc(finish)}">${esc(finish)}</h3><strong class="card-price">${money(item.price)}</strong></div></${tag}>`;
  }
  function imageFallbacks(root = document) {
    root.querySelectorAll("img").forEach((img) => {
      img.addEventListener(
        "error",
        () => {
          if (img.parentElement?.classList.contains("profile-avatar")) {
            img.parentElement.textContent = Array.from(
              state.session?.user?.first_name || "S",
            )[0].toUpperCase();
            return;
          }
          if (img.closest(".loading-emblem, .navbar-brand")) {
            const fallback = document.createElement("span");
            fallback.className = "brand-lettermark";
            fallback.textContent = "CS2 SKIN SAVDO";
            img.replaceWith(fallback);
            return;
          }
          img.src = "/static/assets/art-unavailable.svg";
          img.alt = "Rasm vaqtincha mavjud emas";
        },
        { once: true },
      );
    });
  }
  let requestId = 0,
    controller;
  async function loadSkins(append = false) {
    const id = ++requestId;
    controller?.abort();
    controller = new AbortController();
    if (!append) {
      state.offset = 0;
      state.items = [];
      $("skinGrid").innerHTML = '<p class="empty">Katalog yuklanmoqda…</p>';
    }
    $("skinGrid").setAttribute("aria-busy", "true");
    $("loadMore").disabled = true;
    const params = new URLSearchParams({
      q: state.q,
      category: state.category,
      rarity: state.rarity.join(","),
      condition: state.condition.join(","),
      sort: state.sort,
      limit: normalizedPath() === "/" ? "10" : "100",
      offset: String(state.offset),
    });
    try {
      const data = await api("/api/skins?" + params, {
        signal: controller.signal,
      });
      if (id !== requestId) return;
      state.items = append ? [...state.items, ...data.items] : data.items;
      state.catalogCounts = data.categories;
      state.catalogTotal = data.catalog_total;
      renderCategories(data.categories, data.catalog_total);
      $("skinCount").textContent = `(${data.total})`;
      $("availableStat").textContent = data.catalog_total;
      $("footerCatalogCount").hidden = false;
      $("activeFilters").textContent = [
        state.q && `Qidiruv: ${state.q}`,
        state.category,
        ...state.rarity,
        ...state.condition,
      ]
        .filter(Boolean)
        .join(" · ");
      $("skinGrid").innerHTML = state.items.length
        ? state.items
            .map(s => skinCard(s))
            .join("")
        : '<div class="empty"><strong>Skinlar topilmadi</strong>Filtrlarni o‘zgartiring yoki keyinroq qayting.<br><button class="secondary" data-action="reset">Filtrlarni tozalash</button></div>';
      $("loadMore").hidden =
        normalizedPath() === "/" || state.items.length >= data.total;
      imageFallbacks($("skinGrid"));
    } catch (error) {
      if (error.name !== "AbortError" && id === requestId) {
        $("skinGrid").innerHTML =
          '<div class="empty"><strong>Katalogni yuklab bo‘lmadi</strong><button class="secondary" data-action="retry">Qayta urinish</button></div>';
        toast(error.message);
      }
    } finally {
      if (id === requestId) {
        $("skinGrid").setAttribute("aria-busy", "false");
        $("loadMore").disabled = false;
      }
    }
  }
  let routeVersion = 0;
  let lastCatalogUrl = "/skins";
  function renderPage(title, content, backHref = "/skins", label = "SKINSAVO") {
    $("pageView").innerHTML =
      `<div class="page-header"><div><span class="eyebrow">${esc(label)}</span><h1 id="pageTitle">${esc(title)}</h1></div><a class="secondary" href="${esc(backHref)}" data-route>${icon("arrow")} Orqaga</a></div><div class="page-panel"><div id="pageContent">${content}</div></div>`;
    document.title = title + " — SkinSavo";
    icons($("pageView"));
    imageFallbacks($("pageView"));
  }
  function pageError(error, version) {
    if (version !== routeVersion || !state.session) return;
    renderPage(
      error.status === 404 ? "Skin topilmadi" : "Yuklab bo‘lmadi",
      `<p>${esc(error.message)}</p><button class="secondary" data-action="retryPage">Qayta urinish</button>`,
      lastCatalogUrl,
    );
  }
  function requireSession() {
    if (state.session?.authenticated) return true;
    showGate(
      "Bu sayt faqat Telegramda ishlaydi",
      "Botdagi SkinSavo tugmasidan oching.",
    );
    return false;
  }
  function renderAccount(user) {
    state.balance = user.balance;
    state.session.user = user;
    $("balanceValue").textContent = money(user.balance);
    const button = document.querySelector(
      '.header-actions [data-action="profile"]',
    );
    const name =
      [user.first_name, user.last_name].filter(Boolean).join(" ") ||
      user.username ||
      "Profil";
    button.title = name;
    button.setAttribute("aria-label", name + " — profil");
    button.innerHTML = user.photo_url
      ? `<img class="header-avatar" src="${esc(user.photo_url)}" alt="" referrerpolicy="no-referrer">`
      : `<span>${esc(Array.from(name)[0].toUpperCase())}</span>`;
    button.querySelector("img")?.addEventListener(
      "error",
      () => {
        button.innerHTML = `<span>${esc(Array.from(name)[0].toUpperCase())}</span>`;
      },
      { once: true },
    );
  }
  async function loadUser() {
    if (!state.session?.authenticated) return;
    const user = await api(
      "/api/users/" + encodeURIComponent(state.session.telegram_id),
    );
    renderAccount(user);
  }
  async function detail(id, version = routeVersion) {
    try {
      const item = await api("/api/skins/" + id);
      if (version !== routeVersion) return;
      renderPage(
        item.name,
        `<div class="detail-layout"><div class="detail-art"><img class="modal-image" src="${esc(imageUrl(item))}" alt="${esc(item.name)}"></div><div class="detail-copy"><span class="eyebrow">${esc(item.rarity)}</span><h2>${esc(item.skin)}</h2><div class="history-row"><span>Holati</span><strong>${esc(item.condition)}</strong></div><div class="history-row"><span>Qoldiq</span><strong>${esc(item.stock)} dona</strong></div>${item.description ? `<p>${esc(item.description)}</p>` : ""}<div class="modal-price">${money(item.price)}</div><p>Demo xarid. Haqiqiy to‘lov va Steam transferi yo‘q.</p><button class="full-btn" data-purchase="${item.id}" ${item.stock < 1 ? "disabled" : ""}>${item.stock > 0 ? "Demo xarid qilish" : "Qoldiq tugagan"}</button><div class="page-links"><a class="secondary" href="/balance/topup" data-route>Balans qo‘shish</a><a class="secondary" href="/inventory" data-route>Inventar</a></div></div></div>`,
        lastCatalogUrl,
        "SKIN TAFSILOTI",
      );
    } catch (error) {
      pageError(error, version);
    }
  }
  function topup() {
    renderPage(
      "Balans to‘ldirish",
      '<p>Faqat sinov mablag‘i. Haqiqiy pul olinmaydi.</p><form id="topupForm"><label class="field-label" for="amount">Miqdor (so‘m)</label><input class="modal-input" id="amount" type="number" min="1" max="10000000" step="1" value="50000" required><button class="full-btn" type="submit">Demo balans qo‘shish</button></form>',
      "/balance",
      "DEMO HAMYON",
    );
  }
  function profile() {
    const user = state.session.user;
    const name =
      [user.first_name, user.last_name].filter(Boolean).join(" ") ||
      user.username ||
      "Foydalanuvchi";
    renderPage(
      "Profil",
      `<div class="profile-summary"><div class="profile-avatar">${user.photo_url ? `<img src="${esc(user.photo_url)}" alt="Telegram profil rasmi" referrerpolicy="no-referrer">` : esc(Array.from(name)[0].toUpperCase())}</div><div><h2>${esc(name)}</h2>${user.username ? `<p>@${esc(user.username)}</p>` : ""}<p>Telegram ID: ${esc(user.telegram_id)}</p></div></div><div class="history-row"><span>Demo balans</span><strong>${money(state.balance)}</strong></div><div class="page-links"><a class="secondary" href="/balance" data-route>Balans</a><a class="secondary" href="/inventory" data-route>Inventar</a><a class="secondary" href="/history" data-route>Tarix</a>${state.session.is_admin ? '<a class="secondary" href="/admin" data-route>Administrator</a>' : ""}</div>`,
      "/",
      "TELEGRAM HISOBI",
    );
  }
  async function balance(version = routeVersion) {
    try {
      await loadUser();
      if (version !== routeVersion) return;
      renderPage(
        "Balans",
        `<div class="wallet-summary"><span class="eyebrow">DEMO BALANS</span><strong class="wallet-amount">${money(state.balance)}</strong><p>Sinov mablag‘i. Haqiqiy pul emas.</p></div><div class="page-links"><a class="primary" href="/balance/topup" data-route>Balans to‘ldirish ${icon("plus")}</a><a class="secondary" href="/history" data-route>Balans tarixi</a></div>`,
        "/profile",
        "HAMYON",
      );
    } catch (error) {
      pageError(error, version);
    }
  }
  async function inventory(version = routeVersion) {
    try {
      const data = await api("/api/inventory");
      if (version !== routeVersion) return;
      renderPage(
        "Inventar",
        `<p>Demo skinlaringiz.</p>${data.items.length ? data.items.map((item) => `<div class="inventory-row"><img src="${esc(imageUrl(item))}" alt="${esc(item.name)}"><div><a href="/skins/${item.skin_id}" data-route><strong>${esc(item.name)}</strong></a><p>${esc(item.condition)} · ${money(item.price)}</p></div>${item.status === "owned" ? `<button class="secondary" data-sell="${item.id}">Demo sotish</button>` : "<small>Sotilgan</small>"}</div>`).join("") : '<div class="empty"><strong>Inventar bo‘sh</strong><a class="primary" href="/skins" data-route>Skin tanlash</a></div>'}`,
        "/profile",
        "SIZNING SKINLARINGIZ",
      );
    } catch (error) {
      pageError(error, version);
    }
  }
  async function history(version = routeVersion) {
    try {
      const data = await api(
        "/api/users/" + state.session.telegram_id + "/history",
      );
      if (version !== routeVersion) return;
      renderPage(
        "Balans tarixi",
        data.items.length
          ? data.items
              .map(
                (item) =>
                  `<div class="history-row"><div>${esc(item.note || item.event_type)}<small>${esc(item.created_at)}</small></div><strong>${money(item.amount)}</strong></div>`,
              )
              .join("")
          : "<p>Hozircha tarix bo‘sh.</p>",
        "/balance",
        "DEMO AMALLAR",
      );
    } catch (error) {
      pageError(error, version);
    }
  }
  function admin() {
    if (!state.session.is_admin) {
      renderPage(
        "Kirish cheklangan",
        "<p>Bu sahifa faqat administrator uchun.</p>",
        "/profile",
      );
      return;
    }
    window.SkinSavoAdmin.render({api, renderPage, card:skinCard, esc, rarities, conditions, toast, money});
  }
  function normalizedPath() {
    return location.pathname.replace(/\/+$/, "") || "/";
  }
  function syncFilterControls() {
    $("searchInput").value = state.q;
    $("categorySelect").value = state.category;
    $("sortSelect").value = state.sort;
    document
      .querySelectorAll("[data-filter]")
      .forEach(
        (el) => (el.checked = state[el.dataset.filter].includes(el.value)),
      );
    renderCategories(state.catalogCounts || {}, state.catalogTotal);
  }
  function readCatalogFilters() {
    const params =
      normalizedPath() === "/skins"
        ? new URLSearchParams(location.search)
        : new URLSearchParams();
    state.q = (params.get("q") || "").slice(0, 100);
    state.category = categories.includes(params.get("category"))
      ? params.get("category")
      : "";
    state.sort = [
      "featured",
      "price_asc",
      "price_desc",
      "name",
      "name_desc",
      "stock",
    ].includes(params.get("sort"))
      ? params.get("sort")
      : "featured";
    state.rarity = [...new Set((params.get("rarity") || "").split(","))].filter(
      (value) => rarities.includes(value),
    );
    state.condition = [
      ...new Set((params.get("condition") || "").split(",")),
    ].filter((value) => conditions.includes(value));
    syncFilterControls();
  }
  function catalogUrl() {
    const params = new URLSearchParams();
    if (state.q) params.set("q", state.q);
    if (state.category) params.set("category", state.category);
    if (state.sort !== "featured") params.set("sort", state.sort);
    if (state.rarity.length) params.set("rarity", state.rarity.join(","));
    if (state.condition.length)
      params.set("condition", state.condition.join(","));
    return "/skins" + (params.size ? "?" + params : "");
  }
  function catalogChanged() {
    clearTimeout(searchTimer);
    const url = catalogUrl();
    if (normalizedPath() !== "/skins") {
      navigate(url);
      return;
    }
    window.history.replaceState(window.history.state, "", url + launchHash);
    lastCatalogUrl = url;
    loadSkins();
  }
  function navigate(href, { replace = false } = {}) {
    if (!requireSession()) return;
    const target = new URL(href, location.origin);
    if (target.origin !== location.origin) return;
    const next = target.pathname + target.search;
    if (next !== location.pathname + location.search) {
      const depth = (window.history.state?.depth || 0) + (replace ? 0 : 1);
      window.history[replace ? "replaceState" : "pushState"](
        { skinsavo: true, depth },
        "",
        next + launchHash,
      );
    }
    renderRoute();
  }
  async function renderRoute({ focus = true } = {}) {
    window.SkinSavoAdmin?.close();
    if (!state.session?.authenticated) return;
    clearTimeout(searchTimer);
    const version = ++routeVersion;
    const path = normalizedPath();
    const home = path === "/",
      catalog = path === "/skins",
      market = home || catalog;
    document.body.dataset.page = home ? "home" : catalog ? "skins" : "account";
    $("filters").classList.remove("open");
    $("filters").removeAttribute("role");
    $("filters").removeAttribute("aria-modal");
    $("filters").hidden = !market;
    document.querySelector(".layout").classList.toggle("page-layout", !market);
    document
      .querySelectorAll("[data-home]")
      .forEach((el) => (el.hidden = !home));
    $("catalog").hidden = !market;
    $("filterForm").hidden = !catalog;
    $("faq").hidden = path !== "/faq";
    $("pageView").hidden = market || path === "/faq";
    document.querySelectorAll("header nav a[data-route]").forEach((link) => {
      const active =
        link.getAttribute("href") === path ||
        (link.getAttribute("href") === "/skins" && path.startsWith("/skins/"));
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.title =
      (home
        ? "Bosh sahifa"
        : catalog
          ? "Skinlar"
          : path === "/faq"
            ? "FAQ"
            : "SkinSavo") + " — SkinSavo";
    try {
      if (path === "/") tg?.BackButton?.hide();
      else tg?.BackButton?.show();
    } catch {}
    if (focus) {
      window.scrollTo(0, 0);
      $("mainContent").focus({ preventScroll: true });
    }
    if (market) {
      readCatalogFilters();
      $("catalogTitle").textContent = home ? "Mashhur Skins" : "Skinlar";
      $("viewAll").hidden = !home;
      if (catalog) lastCatalogUrl = catalogUrl();
      await loadSkins();
      return;
    }
    if (path === "/faq") return;
    renderPage("Yuklanmoqda…", '<p role="status">Ma’lumotlar yuklanmoqda…</p>');
    if (/^\/skins\/[1-9]\d*$/.test(path))
      await detail(path.split("/")[2], version);
    else if (path === "/profile") profile();
    else if (path === "/inventory") await inventory(version);
    else if (path === "/balance") await balance(version);
    else if (path === "/balance/topup") topup();
    else if (path === "/history") await history(version);
    else if (path === "/admin") admin();
    else
      renderPage(
        "Sahifa topilmadi",
        '<p>Bu manzil mavjud emas.</p><a href="/" class="primary" data-route>Bosh sahifa</a>',
        "/",
      );
  }
  window.addEventListener("popstate", () => renderRoute());
  let telegramBackBound;
  function bindTelegramBack() {
    if (!tg?.BackButton || telegramBackBound === tg.BackButton) return;
    tg.BackButton.onClick(() => {
      if (window.history.state?.skinsavo && window.history.state.depth > 0)
        window.history.back();
      else navigate("/");
    });
    telegramBackBound = tg.BackButton;
  }
  window.addEventListener("skinsavo:telegram-ready", () => {
    tg = window.Telegram?.WebApp || tg;
    try {
      tg?.ready();
      tg?.expand();
      if (state.session?.authenticated) {
        bindTelegramBack();
        if (normalizedPath() === "/") tg?.BackButton?.hide();
        else tg?.BackButton?.show();
      }
    } catch {}
  });
  function reset() {
    clearTimeout(searchTimer);
    Object.assign(state, {
      q: "",
      category: "",
      rarity: [],
      condition: [],
      sort: "featured",
    });
    $("searchInput").value = "";
    $("categorySelect").value = "";
    $("sortSelect").value = "featured";
    document
      .querySelectorAll("[data-filter]")
      .forEach((el) => (el.checked = false));
    catalogChanged();
  }
  const actions = {
    inventory: () => navigate("/inventory"),
    profile: () => navigate("/profile"),
    topup: () => navigate("/balance/topup"),
    history: () => navigate("/history"),
    admin: () => navigate("/admin"),
    reset,
    retry: () => loadSkins(),
    retryPage: () => renderRoute(),
  };
  document.addEventListener("click", async (event) => {
    const link = event.target.closest("a[data-route]");
    if (
      link &&
      event.button === 0 &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.shiftKey &&
      !event.altKey
    ) {
      if (link.target === "_blank" || link.hasAttribute("download")) return;
      event.preventDefault();
      navigate(link.href);
      return;
    }
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.action) {
      actions[button.dataset.action]?.();
      return;
    }
    if (button.dataset.category !== undefined) {
      state.category = button.dataset.category;
      $("categorySelect").value = state.category;
      catalogChanged();
      return;
    }
    if (button.dataset.detail) {
      navigate("/skins/" + button.dataset.detail);
      return;
    }
    if (button.dataset.purchase) {
      if (!requireSession()) return;
      button.disabled = true;
      try {
        await api("/api/demo/purchase", {
          method: "POST",
          body: JSON.stringify({ skin_id: Number(button.dataset.purchase) }),
        });
        await loadUser();
        toast("Demo xarid saqlandi.");
        navigate("/inventory");
      } catch (e) {
        toast(e.message);
        button.disabled = false;
      }
      return;
    }
    if (button.dataset.sell) {
      button.disabled = true;
      try {
        await api("/api/demo/inventory/" + button.dataset.sell + "/sell", {
          method: "POST",
        });
        await loadUser();
        if (normalizedPath() === "/inventory")
          await renderRoute({ focus: false });
        toast("Demo sotuv saqlandi");
      } catch (e) {
        toast(e.message);
        button.disabled = false;
      }
    }
  });
  document.addEventListener("submit", async (event) => {
    if (event.target.id !== "topupForm") return;
    event.preventDefault();
    const button = event.target.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      await api("/api/demo/topup", {
        method: "POST",
        body: JSON.stringify({
          telegram_id: state.session.telegram_id,
          amount: Number($("amount").value),
        }),
      });
      await loadUser();
      toast("Demo balans yangilandi.");
      navigate("/balance");
    } catch (e) {
      toast(e.message);
      button.disabled = false;
    }
  });
  $("filterForm").onsubmit = (e) => e.preventDefault();
  let searchTimer;
  $("searchInput").oninput = () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.q = $("searchInput").value.trim();
      catalogChanged();
    }, 250);
  };
  $("categorySelect").onchange = () => {
    state.category = $("categorySelect").value;
    catalogChanged();
  };
  $("sortSelect").onchange = () => {
    state.sort = $("sortSelect").value;
    catalogChanged();
  };
  document.querySelectorAll("[data-filter]").forEach(
    (el) =>
      (el.onchange = () => {
        const key = el.dataset.filter;
        state[key] = [
          ...document.querySelectorAll(`[data-filter="${key}"]:checked`),
        ].map((i) => i.value);
        catalogChanged();
      }),
  );
  $("resetBtn").onclick = reset;
  $("viewAll").onclick = () => navigate("/skins");
  $("loadMore").onclick = () => {
    state.offset = state.items.length;
    loadSkins(true);
  };
  $("openFilters").onclick = () => {
    $("filters").classList.add("open");
    $("filters").setAttribute("role", "dialog");
    $("filters").setAttribute("aria-modal", "true");
    $("filters").setAttribute("aria-label", "Katalog filtrlari");
    $("closeFilters").focus();
  };
  function closeFilters() {
    $("filters").classList.remove("open");
    $("filters").removeAttribute("role");
    $("filters").removeAttribute("aria-modal");
    $("openFilters").focus();
  }
  $("closeFilters").onclick = closeFilters;
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && $("filters").classList.contains("open"))
      closeFilters();
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (normalizedPath() !== "/skins") navigate("/skins");
      $("searchInput").focus();
    }
    if (e.key === "Tab" && $("filters").classList.contains("open")) {
      const els = [...$("filters").querySelectorAll("button,input")];
      if (e.shiftKey && document.activeElement === els[0]) {
        e.preventDefault();
        els.at(-1).focus();
      } else if (!e.shiftKey && document.activeElement === els.at(-1)) {
        e.preventDefault();
        els[0].focus();
      }
    }
  });
  try {
    if (localStorage.getItem("skinsavo_theme") === "light")
      document.documentElement.dataset.theme = "light";
  } catch {}
  $("themeBtn").onclick = () => {
    const theme =
      document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("skinsavo_theme", theme);
      tg?.setHeaderColor(theme === "light" ? "#f5f5f5" : "#090909");
    } catch {}
  };
  $("year").textContent = new Date().getFullYear();
  imageFallbacks();
  function showGate(title, message, retry = false) {
    document.body.dataset.auth = "blocked";
    $("gateTitle").textContent = title;
    $("gateMessage").textContent = message;
    $("authRetry").hidden = !retry;
  }
  async function loadBotLink() {
    try {
      const config = await api("/api/app-config", {
        timeoutMs: 8000,
      });
      const entryUrl = config.mini_app_url || config.bot_url;
      if (
        /^https:\/\/t\.me\/[A-Za-z0-9_]+(?:\?(?:startapp|start=app))?$/.test(
          entryUrl || "",
        )
      ) {
        $("telegramOpen").href = entryUrl;
        $("telegramOpen").hidden = false;
      }
    } catch {}
  }
  let authenticating = false;
  let initialSession = auth.initialSession;
  let lastAuthError = null;
  // Start nonessential artwork mapping while identity is being verified.
  api("/static/assets/manifest.json", { timeoutMs: 3000 })
    .then((manifest) => {
      state.manifest = manifest;
    })
    .catch(() => {});
  async function authenticate() {
    if (authenticating) return;
    authenticating = true;
    const finishSplash = () =>
      sleep(Math.max(0, 3000 - (performance.now() - auth.startedAt)));
    document.body.dataset.auth = "pending";
    $("authRetry").hidden = true;
    try {
      const pending = initialSession || auth.signIn();
      initialSession = null;
      const session = await pending;
      readTelegramInitData();
      try {
        tg?.ready();
        tg?.expand();
      } catch {}
      state.session = session;
      renderAccount(session.user);
      launchHash = auth.persistLaunch();
      const clean = new URLSearchParams(location.search);
      for (const key of [...clean.keys()])
        if (key.startsWith("tgWebApp")) clean.delete(key);
      window.history.replaceState(
        { skinsavo: true, depth: 0 },
        "",
        location.pathname + (clean.size ? "?" + clean : "") + launchHash,
      );
      bindTelegramBack();
      // Profile is already verified. Catalog/artwork cannot hold login hostage.
      renderRoute({ focus: false }).catch((error) => toast(error.message));
      await finishSplash();
      if (!state.session?.authenticated) {
        const error = new Error("Sessiya tugadi");
        error.status = 401;
        throw error;
      }
      lastAuthError = null;
      document.body.dataset.auth = "ready";
    } catch (e) {
      state.session = null;
      lastAuthError = e;
      await finishSplash();
      if (e.code === "NO_INIT_DATA") {
        showGate(
          auth.insideTelegram()
            ? "Bot menyusidan qayta oching"
            : "Bu sayt faqat Telegramda ishlaydi",
          "Botdagi pastki SkinSavo menyu tugmasini bosing. Profil avtomatik ochiladi.",
          true,
        );
      } else {
        showGate(
          e.status === 401 ? "Telegramdan qayta oching" : "Ulanish tiklanmadi",
          e.status === 401
            ? "Botdagi SkinSavo menyusidan qayta kiring."
            : "Internetni tekshiring. Qayta urinish profilingizni o‘zgartirmaydi.",
          true,
        );
      }
    } finally {
      authenticating = false;
    }
  }
  function recoverLogin() {
    if (authenticating || document.body.dataset.auth !== "blocked") return;
    const raw = readTelegramInitData();
    if (raw && raw !== auth.lastAttemptData) authenticate();
  }
  // A late native bridge must recover automatically, even after the initial gate.
  const lateBridge = setInterval(recoverLogin, 200);
  setTimeout(() => clearInterval(lateBridge), 30000);
  window.addEventListener("hashchange", recoverLogin);
  window.addEventListener("pageshow", recoverLogin);
  window.addEventListener("focus", recoverLogin);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) recoverLogin();
  });
  window.addEventListener("online", () => {
    if (
      !authenticating &&
      document.body.dataset.auth === "blocked" &&
      readTelegramInitData() &&
      lastAuthError?.status !== 401
    )
      authenticate();
  });
  $("telegramOpen").onclick = (event) => {
    if (auth.insideTelegram() && tg?.openTelegramLink) {
      event.preventDefault();
      try {
        tg.openTelegramLink($("telegramOpen").href);
      } catch {
        location.href = $("telegramOpen").href;
      }
    }
  };
  $("authRetry").onclick = authenticate;
  loadBotLink();
  authenticate();
})();
