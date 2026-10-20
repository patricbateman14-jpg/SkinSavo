(() => {
  "use strict";

  const tg = window.Telegram?.WebApp;
  tg?.ready();
  tg?.expand();
  try {
    tg?.setHeaderColor("#050505");
    tg?.setBackgroundColor("#050505");
  } catch (_) {}

  const $ = (id) => document.getElementById(id);

  const state = {
    query: "",
    sort: "featured",
    userId: "",
    username: "",
    balance: 250,
    skins: [],
    sortIndex: 0,
    selectedAmount: 25,
    loading: false,
  };

  const SORT_OPTIONS = [
    { key: "featured", label: "Tavsiya" },
    { key: "price_asc", label: "Arzon" },
    { key: "price_desc", label: "Qimmat" },
    { key: "name", label: "Nom" },
    { key: "stock", label: "Qoldiq" },
  ];

  const RARITY_CLASS = {
    Covert: "rarity-covert",
    Classified: "rarity-classified",
    Restricted: "rarity-restricted",
    "Mil-Spec": "rarity-milspec",
    Industrial: "rarity-industrial",
    Consumer: "rarity-consumer",
    Extraordinary: "rarity-extraordinary",
  };

  // ---------- Utils ----------
  const params = new URLSearchParams(location.search);
  const demoId =
    params.get("user_id") ||
    tg?.initDataUnsafe?.user?.id ||
    localStorage.getItem("skinsavo_demo_user") ||
    "demo-guest";

  state.userId = String(demoId);
  state.username =
    tg?.initDataUnsafe?.user?.username ||
    tg?.initDataUnsafe?.user?.first_name ||
    "Guest";

  localStorage.setItem("skinsavo_demo_user", state.userId);

  const money = (n) =>
    Number(n || 0).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });

  const escapeHtml = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c]
    );

  let toastTimer;
  function toast(message) {
    const el = $("toast");
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2800);
  }

  async function api(path, options = {}) {
    const r = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!r.ok) {
      const data = await r.json().catch(() => ({}));
      throw new Error(data.detail || "Server bilan aloqa xatosi");
    }
    return r.json();
  }

  // ---------- Theme ----------
  function initTheme() {
    const saved = localStorage.getItem("skinsavo_theme");
    if (saved === "light") {
      document.documentElement.setAttribute("data-theme", "light");
      $("themeBtn").textContent = "☀";
    }
  }

  $("themeBtn").addEventListener("click", () => {
    const isLight = document.documentElement.getAttribute("data-theme") === "light";
    if (isLight) {
      document.documentElement.removeAttribute("data-theme");
      localStorage.setItem("skinsavo_theme", "dark");
      $("themeBtn").textContent = "☾";
      try {
        tg?.setHeaderColor("#050505");
        tg?.setBackgroundColor("#050505");
      } catch (_) {}
    } else {
      document.documentElement.setAttribute("data-theme", "light");
      localStorage.setItem("skinsavo_theme", "light");
      $("themeBtn").textContent = "☀";
      try {
        tg?.setHeaderColor("#f5f6f8");
        tg?.setBackgroundColor("#f5f6f8");
      } catch (_) {}
    }
  });

  // ---------- User & Balance ----------
  async function loadUser() {
    try {
      const u = await api(
        `/api/users/${encodeURIComponent(state.userId)}?username=${encodeURIComponent(state.username)}`
      );
      state.balance = u.balance;
    } catch (_) {
      state.balance = 250;
    }
    renderBalance();
  }

  function renderBalance() {
    $("balanceValue").innerHTML = `${money(state.balance)} <small>USD</small>`;
  }

  // ---------- Header skin gallery ----------
  const FEATURED_BRAND_SKINS = [
    { match: "AWP | Gungnir", label: "AWP Gungnir" },
    { match: "AWP | Dragon Lore", label: "AWP Dragon Lore" },
    { match: "M4A4 | Howl", label: "M4A4 Howl" },
    { match: "AK-47 | Wild Lotus", label: "AK-47 Wild Lotus" },
  ];

  function renderBrandSkinGallery(items) {
    const strip = $("brandSkinStrip");
    if (!strip || !Array.isArray(items)) return;
    const chosen = FEATURED_BRAND_SKINS.map((featured) => {
      const found = items.find((item) =>
        String(item.name || "").toLowerCase().includes(featured.match.toLowerCase()) && item.image
      );
      return found ? { ...featured, image: found.image } : null;
    }).filter(Boolean);
    if (!chosen.length) return;
    strip.replaceChildren();
    chosen.forEach((skin) => {
      const link = document.createElement("a");
      link.className = "brand-skin-thumb";
      link.href = "https://steamcommunity.com/market/search?appid=730&q=" + encodeURIComponent(skin.match);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.title = skin.label;
      link.setAttribute("aria-label", skin.label + " — Steam Market");
      const img = document.createElement("img");
      img.src = skin.image;
      img.alt = skin.label;
      img.loading = "eager";
      img.onerror = () => link.remove();
      link.appendChild(img);
      strip.appendChild(link);
    });
  }

  async function loadBrandSkinGallery() {
    try {
      const response = await fetch("https://bymykel.github.io/CSGO-API/api/en/skins.json", { cache: "force-cache" });
      if (!response.ok) throw new Error("Skin images unavailable");
      const items = await response.json();
      renderBrandSkinGallery(items);
    } catch (_) {
      // Fall back to matching skins already loaded from the site's own catalogue.
      renderBrandSkinGallery(state.skins);
    }
  }

  // ---------- Skins ----------
  function showSkeleton() {
    $("skinGrid").innerHTML = `
      <div class="skeleton-grid">
        <div class="skeleton-card"></div>
        <div class="skeleton-card"></div>
        <div class="skeleton-card"></div>
        <div class="skeleton-card"></div>
      </div>`;
  }

  async function loadSkins() {
    if (state.loading) return;
    state.loading = true;
    showSkeleton();

    try {
      const data = await api(
        `/api/skins?q=${encodeURIComponent(state.query)}&sort=${state.sort}&limit=100`
      );
      state.skins = data.items || [];
      $("skinCount").textContent = data.total ?? state.skins.length;
      renderSkins();
      if ($("brandSkinStrip")?.querySelector(".brand-skin-loading")) renderBrandSkinGallery(state.skins);
    } catch (e) {
      $("skinGrid").innerHTML = `
        <div class="empty">
          Katalogni yuklab bo‘lmadi.<br>
          <span style="font-size:12px;opacity:.7">${escapeHtml(e.message)}</span>
        </div>`;
      $("skinCount").textContent = "0";
    } finally {
      state.loading = false;
    }
  }

  function renderSkins() {
    const grid = $("skinGrid");
    if (!state.skins.length) {
      grid.innerHTML = `
        <div class="empty">
          Hech narsa topilmadi.<br>
          <span style="font-size:12px;opacity:.7">Boshqa so‘z bilan qidirib ko‘ring.</span>
        </div>`;
      return;
    }

    grid.innerHTML = state.skins
      .map((s, i) => {
        const rarityCls = RARITY_CLASS[s.rarity] || "";
        const stockCls = s.stock > 0 ? "" : "out";
        const stockText = s.stock > 0 ? `● ${s.stock} ta` : "Tugagan";
        return `
        <article class="skin-card" style="animation-delay:${Math.min(i * 40, 320)}ms">
          <div class="skin-image">
            <img
              src="${escapeHtml(s.image)}"
              alt="${escapeHtml(s.name)}"
              loading="lazy"
              onerror="this.src='https://placehold.co/640x420/080808/ffffff?text=CS2+SKIN'"
            >
            <span class="skin-badge ${rarityCls}">${escapeHtml(s.rarity)}</span>
            <span class="stock-badge ${stockCls}">${stockText}</span>
          </div>
          <div class="skin-info">
            <h3 title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</h3>
            <div class="skin-meta">${escapeHtml(s.condition)} · ${escapeHtml(s.weapon)}</div>
            <div class="skin-bottom">
              <div class="price">$${money(s.price)}</div>
              <button class="view-btn" data-skin="${s.id}">Ko‘rish ↗</button>
            </div>
          </div>
        </article>`;
      })
      .join("");

    grid.querySelectorAll("[data-skin]").forEach((btn) => {
      btn.addEventListener("click", () => openSkin(Number(btn.dataset.skin)));
    });
  }

  // ---------- Modal ----------
  function openModal(html) {
    $("modalContent").innerHTML = html;
    $("modalBackdrop").classList.remove("hidden");
    document.body.style.overflow = "hidden";
  }

  function closeModal() {
    $("modalBackdrop").classList.add("hidden");
    document.body.style.overflow = "";
  }

  async function openSkin(id) {
    let s = state.skins.find((x) => x.id === id);
    if (!s) {
      try {
        s = await api(`/api/skins/${id}`);
      } catch {
        return toast("Skin topilmadi");
      }
    }
    if (!s) return toast("Skin topilmadi");

    const rarityCls = RARITY_CLASS[s.rarity] || "";

    openModal(`
      <span class="eyebrow ${rarityCls}">${escapeHtml(s.rarity)} · CS2 SKIN</span>
      <h2 id="modalTitle">${escapeHtml(s.name)}</h2>
      <img class="modal-skin-image" src="${escapeHtml(s.image)}" alt="${escapeHtml(s.name)}"
           onerror="this.src='https://placehold.co/640x420/080808/ffffff?text=CS2+SKIN'">
      <p>${escapeHtml(s.description || "Demo skin tavsifi.")}</p>
      <div class="history-row"><span>Holati</span><strong>${escapeHtml(s.condition)}</strong></div>
      <div class="history-row"><span>Qurol</span><strong>${escapeHtml(s.weapon)}</strong></div>
      <div class="history-row"><span>Qoldiq</span><strong>${s.stock > 0 ? s.stock + " ta" : "Tugagan"}</strong></div>
      <div class="modal-price">$${money(s.price)} <span style="font-size:13px;color:var(--muted);font-weight:600">USD</span></div>
      <button class="full-btn" id="buyDemoBtn" ${s.stock <= 0 ? "disabled" : ""}>
        ${s.stock <= 0 ? "Tugagan" : "Demo xarid"}
      </button>
      <p style="font-size:11px;margin-top:12px;margin-bottom:0;color:var(--muted)">
        Demo rejim: haqiqiy xarid yoki skin transferi amalga oshmaydi.
      </p>
    `);

    $("buyDemoBtn")?.addEventListener("click", () => {
      if (s.stock <= 0) return;
      toast("Demo rejimda xarid vaqtincha o‘chirilgan.");
    });
  }

  function openTopup() {
    state.selectedAmount = 25;
    openModal(`
      <span class="eyebrow">DEMO HAMYON</span>
      <h2 id="modalTitle">Balansni to‘ldirish</h2>
      <p>Sinov uchun demo mablag‘ qo‘shing. Bu haqiqiy to‘lov emas.</p>
      <div class="amount-row">
        ${[10, 25, 50, 100]
          .map(
            (n) =>
              `<button class="amount-option ${n === 25 ? "selected" : ""}" data-amount="${n}">$${n}</button>`
          )
          .join("")}
      </div>
      <label class="field-label" for="customAmount">Boshqa miqdor (USD)</label>
      <input class="modal-input" id="customAmount" type="number" min="1" max="10000" step="1" value="25" inputmode="decimal">
      <button class="full-btn" id="confirmTopup">+ Demo balans qo‘shish</button>
    `);

    document.querySelectorAll("[data-amount]").forEach((b) => {
      b.addEventListener("click", () => {
        state.selectedAmount = Number(b.dataset.amount);
        $("customAmount").value = state.selectedAmount;
        document.querySelectorAll("[data-amount]").forEach((x) =>
          x.classList.toggle("selected", x === b)
        );
      });
    });

    $("customAmount").addEventListener("input", () => {
      state.selectedAmount = Number($("customAmount").value);
      document.querySelectorAll("[data-amount]").forEach((x) =>
        x.classList.toggle(
          "selected",
          Number(x.dataset.amount) === state.selectedAmount
        )
      );
    });

    $("confirmTopup").addEventListener("click", async () => {
      const amount = Number($("customAmount").value);
      if (!Number.isFinite(amount) || amount <= 0 || amount > 10000) {
        return toast("1 dan 10 000 USD gacha kiriting");
      }
      const btn = $("confirmTopup");
      btn.disabled = true;
      btn.textContent = "Kutilmoqda…";
      try {
        const u = await api("/api/demo/topup", {
          method: "POST",
          body: JSON.stringify({ telegram_id: state.userId, amount }),
        });
        state.balance = u.balance;
        renderBalance();
        closeModal();
        toast("Demo balans muvaffaqiyatli qo‘shildi ✓");
        try {
          tg?.HapticFeedback?.notificationOccurred("success");
        } catch (_) {}
      } catch (e) {
        toast(e.message);
        btn.disabled = false;
        btn.textContent = "+ Demo balans qo‘shish";
      }
    });
  }

  async function openHistory() {
    try {
      const data = await api(
        `/api/users/${encodeURIComponent(state.userId)}/history`
      );
      const items = data.items || [];
      openModal(`
        <span class="eyebrow">HISOB HARAKATLARI</span>
        <h2 id="modalTitle">Balans tarixi</h2>
        ${
          items.length
            ? items
                .map(
                  (x) => `
            <div class="history-row">
              <div>
                ${escapeHtml(x.note || x.event_type)}
                <small>${escapeHtml(x.created_at || "")}</small>
              </div>
              <strong class="positive">+$${money(x.amount)}</strong>
            </div>`
                )
                .join("")
            : `<p>Hozircha tarix bo‘sh. Demo balans to‘ldirishni sinab ko‘ring.</p>`
        }
      `);
    } catch (e) {
      toast(e.message);
    }
  }

  function openProfile() {
    openModal(`
      <span class="eyebrow">SKINSAVO HISOBI</span>
      <h2 id="modalTitle">Salom, ${escapeHtml(state.username)}!</h2>
      <p>Telegram ID: <strong>${escapeHtml(state.userId)}</strong></p>
      <div class="history-row"><span>Demo balans</span><strong>$${money(state.balance)}</strong></div>
      <div class="history-row"><span>Hisob turi</span><strong>Demo</strong></div>
      <p style="font-size:12px;color:var(--muted)">Haqiqiy pul, to‘lovlar yoki skinlar savdosi ulangan emas.</p>
      <button class="full-btn" id="profileTopup">Balansni to‘ldirish</button>
    `);
    $("profileTopup").addEventListener("click", openTopup);
  }

  // ---------- Events ----------
  $("modalClose").addEventListener("click", closeModal);
  $("modalBackdrop").addEventListener("click", (e) => {
    if (e.target === $("modalBackdrop")) closeModal();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      $("searchInput").focus();
    }
  });

  $("topupBtn").addEventListener("click", openTopup);
  $("profileBtn").addEventListener("click", openProfile);
  $("accountBtn").addEventListener("click", () => {
    setActiveNav("account");
    openProfile();
  });
  $("historyBtn").addEventListener("click", () => {
    setActiveNav("history");
    openHistory();
  });
  $("inventoryBtn").addEventListener("click", () => {
    setActiveNav("inventory");
    toast("Inventar demo versiyada mavjud emas.");
  });
  $("navHome").addEventListener("click", () => {
    setActiveNav("home");
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  $("browseBtn").addEventListener("click", () => {
    $("catalog").scrollIntoView({ behavior: "smooth" });
  });

  function setActiveNav(page) {
    document.querySelectorAll(".nav-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.page === page || el.id === `nav${page.charAt(0).toUpperCase() + page.slice(1)}`);
    });
    // simpler approach
    document.querySelectorAll(".nav-item").forEach((el) => el.classList.remove("active"));
    if (page === "home") $("navHome").classList.add("active");
    else if (page === "history") $("historyBtn").classList.add("active");
    else if (page === "inventory") $("inventoryBtn").classList.add("active");
    else if (page === "account") $("accountBtn").classList.add("active");
  }

  // Search with debounce
  let searchTimer;
  $("searchInput").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.query = e.target.value.trim();
      // clear chip active if typing
      $("chips").querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
      if (!state.query) {
        $("chips").querySelector('[data-query=""]')?.classList.add("active");
      }
      loadSkins();
    }, 280);
  });

  $("chips").querySelectorAll("[data-query]").forEach((b) => {
    b.addEventListener("click", () => {
      state.query = b.dataset.query;
      $("searchInput").value = state.query;
      $("chips").querySelectorAll(".chip").forEach((x) =>
        x.classList.toggle("active", x === b)
      );
      loadSkins();
    });
  });

  $("sortBtn").addEventListener("click", () => {
    state.sortIndex = (state.sortIndex + 1) % SORT_OPTIONS.length;
    const opt = SORT_OPTIONS[state.sortIndex];
    state.sort = opt.key;
    $("sortLabel").textContent = opt.label;
    loadSkins();
  });

  // ---------- Init ----------
  initTheme();
  loadUser();
  loadBrandSkinGallery();
  loadSkins();
})();
