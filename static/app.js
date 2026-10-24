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
  const money = (n) =>
    new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
    }).format(Number(n));
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
  const tg = window.Telegram?.WebApp;
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
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": tg?.initData || "",
        ...options.headers,
      },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok)
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : "So‘rov bajarilmadi. Qayta urinib ko‘ring.",
      );
    return data;
  }
  function imageUrl(item) {
    const local = state.manifest[item.name];
    if (local) return local;
    const value = String(item.image || "");
    return /^(https?:\/\/|\/static\/)/.test(value) &&
      !value.includes("placehold.co")
      ? value
      : "/static/assets/art-unavailable.svg";
  }
  function imageFallbacks(root = document) {
    root.querySelectorAll("img").forEach((img) => {
      img.addEventListener(
        "error",
        () => {
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
      limit: "100",
      offset: String(state.offset),
    });
    try {
      const data = await api("/api/skins?" + params, {
        signal: controller.signal,
      });
      if (id !== requestId) return;
      state.items = append ? [...state.items, ...data.items] : data.items;
      renderCategories(data.categories, data.catalog_total);
      $("skinCount").textContent = `(${data.total})`;
      $("availableStat").textContent = data.catalog_total;
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
            .map(
              (s) =>
                `<article class="skin-card"><div class="skin-image"><span class="skin-badge">${esc(s.rarity)}</span><span class="stock-badge">${s.stock > 0 ? esc(s.stock) + " dona" : "Tugagan"}</span><img src="${esc(imageUrl(s))}" alt="${esc(s.name)}" loading="lazy" width="240" height="160"></div><div class="skin-info"><h3>${esc(s.name)}</h3><p class="skin-meta">${esc(s.condition)}</p><div class="skin-bottom"><strong class="price">${money(s.price)}</strong><button class="view-btn" data-detail="${s.id}" aria-label="${esc(s.name)} — ko‘rish">Ko‘rish ↗</button></div></div></article>`,
            )
            .join("")
        : '<div class="empty"><strong>Skinlar topilmadi</strong>Filtrlarni o‘zgartiring yoki keyinroq qayting.<br><button class="secondary" data-action="reset">Filtrlarni tozalash</button></div>';
      $("loadMore").hidden = state.items.length >= data.total;
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
  let previousFocus;
  function modal(html) {
    if (!$("modal").open) previousFocus = document.activeElement;
    $("modalContent").innerHTML = html;
    icons($("modalContent"));
    imageFallbacks($("modalContent"));
    if (!$("modal").open) $("modal").showModal();
    $("modalClose").focus();
  }
  $("modalClose").onclick = () => $("modal").close();
  $("modal").addEventListener("close", () => previousFocus?.focus());
  $("modal").addEventListener("click", (event) => {
    if (event.target === $("modal")) {
      const r = $("modal").getBoundingClientRect();
      if (
        event.clientX < r.left ||
        event.clientX > r.right ||
        event.clientY < r.top ||
        event.clientY > r.bottom
      )
        $("modal").close();
    }
  });
  function requireSession() {
    if (state.session?.authenticated) return true;
    modal(
      '<span class="eyebrow">TELEGRAM SIGN IN</span><h2 id="modalTitle">Telegram orqali kiring</h2><p>Shaxsiy balans, demo xarid va inventardan foydalanish uchun SkinSavo’ni Telegram botidagi Mini App tugmasi orqali oching. Katalogni hisob ochmasdan ko‘rish mumkin.</p>',
    );
    return false;
  }
  async function loadUser() {
    if (!state.session?.authenticated) return;
    const user = await api(
      "/api/users/" + encodeURIComponent(state.session.telegram_id),
    );
    state.balance = user.balance;
    $("balanceValue").textContent = money(user.balance);
  }
  async function detail(id) {
    try {
      const s = await api("/api/skins/" + id);
      modal(
        `<span class="eyebrow">${esc(s.rarity)} · DEMO LISTING</span><h2 id="modalTitle">${esc(s.name)}</h2><img class="modal-image" src="${esc(imageUrl(s))}" alt="${esc(s.name)}"><p>${esc(s.condition)} · ${esc(s.stock)} dona</p><p>${esc(s.description)}</p><div class="modal-price">${money(s.price)}</div><p>Faqat demo mablag‘. Haqiqiy to‘lov va Steam transferi mavjud emas.</p><button class="full-btn" data-purchase="${s.id}" ${s.stock < 1 ? "disabled" : ""}>${s.stock > 0 ? "Demo xarid qilish" : "Qoldiq tugagan"}</button>`,
      );
    } catch (e) {
      toast(e.message);
    }
  }
  function topup() {
    if (!requireSession()) return;
    modal(
      '<span class="eyebrow">DEMO HAMYON</span><h2 id="modalTitle">Demo balans qo‘shish</h2><p>Bu sinov mablag‘i. Haqiqiy pul olinmaydi va yechib bo‘lmaydi.</p><form id="topupForm"><label class="field-label" for="amount">Miqdor (USD)</label><input class="modal-input" id="amount" type="number" min="0.01" max="10000" step="0.01" value="25" required><button class="full-btn" type="submit">Demo balans qo‘shish</button></form>',
    );
  }
  function profile() {
    if (!requireSession()) return;
    modal(
      `<span class="eyebrow">SKINSAVO HISOBI</span><h2 id="modalTitle">Salom, ${esc(state.session.username || "foydalanuvchi")}!</h2><p>Telegram ID: ${esc(state.session.telegram_id)}</p><div class="history-row"><span>Demo balans</span><strong>${money(state.balance)}</strong></div><p>Haqiqiy to‘lovlar yoki skin transferi ulanmagan.</p><button class="full-btn" data-action="topup">Demo balans qo‘shish</button><button class="full-btn" data-action="history">Balans tarixi</button>${state.session.is_admin ? '<button class="full-btn" data-action="admin">Administrator paneli</button>' : ""}`,
    );
  }
  async function inventory() {
    if (!requireSession()) return;
    try {
      const data = await api("/api/inventory");
      modal(
        `<span class="eyebrow">DEMO INVENTAR</span><h2 id="modalTitle">Sizning skinlaringiz</h2><p>Demo xaridlar bazada saqlanadi. Sotish demo balansni qaytaradi, haqiqiy skin jo‘natilmaydi.</p>${data.items.length ? data.items.map((i) => `<div class="inventory-row"><img src="${esc(imageUrl(i))}" alt="${esc(i.name)}"><div><strong>${esc(i.name)}</strong><p>${esc(i.condition)} · ${money(i.price)}</p></div>${i.status === "owned" ? `<button class="secondary" data-sell="${i.id}">Demo sotish</button>` : "<small>Sotilgan</small>"}</div>`).join("") : "<p>Inventar bo‘sh. Katalogdan birinchi demo skinni tanlang.</p>"}`,
      );
    } catch (e) {
      toast(e.message);
    }
  }
  async function history() {
    if (!requireSession()) return;
    try {
      const data = await api(
        "/api/users/" + state.session.telegram_id + "/history",
      );
      modal(
        `<span class="eyebrow">DEMO HISOB</span><h2 id="modalTitle">Balans tarixi</h2>${data.items.length ? data.items.map((i) => `<div class="history-row"><div>${esc(i.note || i.event_type)}<small>${esc(i.created_at)}</small></div><strong>${money(i.amount)}</strong></div>`).join("") : "<p>Hozircha tarix bo‘sh.</p>"}`,
      );
    } catch (e) {
      toast(e.message);
    }
  }
  function admin() {
    if (!state.session?.is_admin) return;
    const fields = [
      ["name", "Skin nomi", "text"],
      ["weapon", "Qurol", "text"],
      ["skin", "Finish nomi", "text"],
      ["rarity", "Rarity", "text"],
      ["condition", "Holati", "text"],
      ["price", "Narx (USD)", "number"],
      ["stock", "Soni", "number"],
      ["image", "HTTPS rasm URL", "url"],
      ["description", "Tavsif", "text"],
    ];
    modal(
      '<span class="eyebrow">ADMINISTRATOR</span><h2 id="modalTitle">Yangi skin joylash</h2><form id="adminForm">' +
        fields
          .map(
            ([name, label, type]) =>
              `<label class="field-label" for="admin-${name}">${label}</label><input class="modal-input" id="admin-${name}" name="${name}" type="${type}" ${type === "number" ? 'min="0" step="' + (name === "stock" ? "1" : "0.01") + '"' : ""} ${name === "description" ? "" : "required"}>`,
          )
          .join("") +
        '<button class="full-btn" type="submit">Skinni joylash</button></form>',
    );
  }
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
    loadSkins();
  }
  const actions = {
    inventory,
    profile,
    topup,
    history,
    admin,
    reset,
    retry: () => loadSkins(),
  };
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.action) {
      actions[button.dataset.action]?.();
      return;
    }
    if (button.dataset.category !== undefined) {
      state.category = button.dataset.category;
      $("categorySelect").value = state.category;
      loadSkins();
      return;
    }
    if (button.dataset.detail) {
      detail(button.dataset.detail);
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
        $("modal").close();
        toast("Demo xarid saqlandi. Haqiqiy skin transferi amalga oshmadi.");
        loadSkins();
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
        await inventory();
        loadSkins();
        toast("Demo sotuv saqlandi");
      } catch (e) {
        toast(e.message);
        button.disabled = false;
      }
    }
  });
  document.addEventListener("submit", async (event) => {
    if (!["topupForm", "adminForm"].includes(event.target.id)) return;
    event.preventDefault();
    const button = event.target.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      if (event.target.id === "topupForm") {
        await api("/api/demo/topup", {
          method: "POST",
          body: JSON.stringify({
            telegram_id: state.session.telegram_id,
            amount: Number($("amount").value),
          }),
        });
        await loadUser();
        toast("Demo balans yangilandi. Haqiqiy to‘lov bo‘lmadi.");
      } else {
        const payload = Object.fromEntries(new FormData(event.target));
        payload.price = Number(payload.price);
        payload.stock = Number(payload.stock);
        await api("/api/admin/skins", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        loadSkins();
        toast("Skin saqlandi");
      }
      $("modal").close();
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
      loadSkins();
    }, 250);
  };
  $("categorySelect").onchange = () => {
    state.category = $("categorySelect").value;
    loadSkins();
  };
  $("sortSelect").onchange = () => {
    state.sort = $("sortSelect").value;
    loadSkins();
  };
  document.querySelectorAll("[data-filter]").forEach(
    (el) =>
      (el.onchange = () => {
        const key = el.dataset.filter;
        state[key] = [
          ...document.querySelectorAll(`[data-filter="${key}"]:checked`),
        ].map((i) => i.value);
        loadSkins();
      }),
  );
  $("resetBtn").onclick = reset;
  $("viewAll").onclick = reset;
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
  (async () => {
    try {
      state.manifest = await api("/static/assets/manifest.json");
    } catch {}
    await loadSkins();
  })();
  (async () => {
    try {
      state.session = await api("/api/session");
      await loadUser();
      if (!state.session.authenticated)
        $("balanceValue").textContent = "Kirish";
    } catch (e) {
      $("balanceValue").textContent = "Mavjud emas";
      toast(e.message);
    }
  })();
})();
