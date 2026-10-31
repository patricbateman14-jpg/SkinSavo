/* Catalog editor: local PNG preview, authenticated upload and listing management. */
(() => {
  "use strict";
  let dispose = () => {};
  window.SkinSavoAdmin = {
    close() { dispose(); dispose = () => {}; },
    render({ api, renderPage, card, esc, rarities, conditions, toast, money }) {
      this.close();
      const $ = (id) => document.getElementById(id);
      let file = null, previewUrl = "", uploadedUrl = "", editing = null, editingActive = true;
      let busy = false, alive = true, rows = [], offset = 0, listRequest = 0;
      let searchTimer;
      const weapons = ["AK-47", "M4A4", "M4A1-S", "AWP", "SSG 08", "Desert Eagle", "USP-S", "Glock-18", "P250", "Five-SeveN", "Tec-9", "CZ75-Auto", "Dual Berettas", "P2000", "R8 Revolver", "FAMAS", "Galil AR", "AUG", "SG 553", "SCAR-20", "G3SG1", "MP9", "MAC-10", "MP7", "MP5-SD", "UMP-45", "P90", "PP-Bizon", "Nova", "XM1014", "MAG-7", "Sawed-Off", "M249", "Negev", "Karambit", "Bayonet", "Butterfly Knife", "Knife", "Gloves"];
      const select = (name, label, values) => `<label class="admin-field">${label}<select name="${name}" id="admin-${name}" class="modal-input" required>${values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("")}</select></label>`;
      renderPage("Skinlarni boshqarish", `
        <div class="admin-workspace">
          <form id="skinEditor" class="skin-editor">
            <div class="admin-section-title"><span class="admin-step">01</span><h2 id="editorTitle">Yangi skin</h2><button type="button" class="secondary" id="newSkin" hidden>Yangi skin</button></div>
            <div class="admin-image-zone" id="imageDrop">
              <label class="admin-upload" for="skinPng"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5"/></svg><strong>PNG rasm tanlash</strong><span>Faylni shu yerga tashlash ham mumkin</span></label>
              <input id="skinPng" type="file" accept="image/png,.png" class="admin-file">
              <p id="imageStatus" role="status">Shaffof fonli PNG · 8 MB gacha</p>
            </div>
            <details class="admin-url"><summary>Rasm havolasidan foydalanish</summary><label class="admin-field">HTTPS rasm havolasi<input id="admin-image-url" class="modal-input" type="url" placeholder="https://…/skin.png"></label></details>
            <div class="admin-section-title"><span class="admin-step">02</span><h2>Skin ma’lumotlari</h2></div>
            <div class="admin-field-grid">
              <label class="admin-field">Qurol<input name="weapon" id="admin-weapon" class="modal-input" list="weaponOptions" placeholder="AK-47" maxlength="60" required autocomplete="off"><datalist id="weaponOptions">${weapons.map(v => `<option value="${esc(v)}">`).join("")}</datalist></label>
              <label class="admin-field">Skin nomi<input name="skin" id="admin-skin" class="modal-input" placeholder="Aphrodite" maxlength="90" required></label>
              ${select("rarity", "Noyoblik darajasi", rarities)}
              ${select("condition", "Qurol holati", conditions)}
              <label class="admin-field">Narx (so‘m)<input name="price" id="admin-price" class="modal-input" type="number" min="0" max="100000000" step="0.01" placeholder="136885" required></label>
              <label class="admin-field">Jami soni<input name="stock" id="admin-stock" class="modal-input" type="number" min="0" max="1000000" step="1" value="1" required></label>
            </div>
            <label class="admin-field">Tavsif <span class="optional">ixtiyoriy</span><textarea name="description" id="admin-description" class="modal-input" rows="3" maxlength="2000" placeholder="Skin haqida qisqa ma’lumot"></textarea></label>
            <div class="admin-error" id="editorError" role="alert" hidden></div>
            <div class="admin-submit"><button class="full-btn" type="submit" id="saveSkin">Skinni joylash</button><button class="secondary" type="button" id="resetSkin">Tozalash</button></div>
            <div id="editorSuccess" role="status" hidden></div>
          </form>
          <div class="admin-preview-panel"><span class="eyebrow">KARTANING KO‘RINISHI</span><div id="skinPreview"></div><div class="admin-rarity-label" id="rarityPreview"></div><p>Tanlangan noyoblik karta rangini belgilaydi.</p></div>
        </div>
        <section class="admin-list-section"><div class="admin-list-heading"><h2>Joylangan skinlar <span id="adminCount"></span></h2><label class="admin-search"><span class="sr-only">Skin qidirish</span><input id="adminSearch" class="modal-input" type="search" placeholder="Skinni qidirish…" maxlength="100"></label></div><div id="adminListings" aria-live="polite"></div><div class="admin-pagination"><button type="button" class="secondary" id="adminPrevious">← Oldingi</button><span id="adminRange"></span><button type="button" class="secondary" id="adminNext">Keyingi →</button></div></section>`, "/profile", "ADMINISTRATOR");
      const form = $("skinEditor");
      dispose = () => { alive = false; clearTimeout(searchTimer); if (previewUrl) URL.revokeObjectURL(previewUrl); };
      function message(text) { $("editorError").textContent = text; $("editorError").hidden = !text; }
      function data() {
        const value = Object.fromEntries(new FormData(form));
        value.weapon = value.weapon.trim(); value.skin = value.skin.trim();
        value.name = `${value.weapon} | ${value.skin}`;
        value.price = Number(value.price); value.stock = Number(value.stock);
        value.image = previewUrl || uploadedUrl || $("admin-image-url").value.trim();
        return value;
      }
      function preview() {
        const item = data();
        $("skinPreview").innerHTML = card({...item, weapon: item.weapon || "Qurol", skin: item.skin || "Skin nomi"}, true);
        $("rarityPreview").textContent = item.rarity;
        const img = $("skinPreview").querySelector("img");
        if (img) img.onerror = () => { img.onerror = null; img.src = "/static/assets/art-unavailable.svg"; };
      }
      function clearImage() {
        if (previewUrl) URL.revokeObjectURL(previewUrl);
        previewUrl = ""; file = null; uploadedUrl = ""; $("skinPng").value = "";
      }
      function chooseFile(candidate) {
        if (busy || !candidate) return;
        if (!/\.png$/i.test(candidate.name) || (candidate.type && candidate.type !== "image/png")) return message("Faqat PNG rasm tanlang.");
        if (candidate.size > 8 * 1024 * 1024) return message("PNG hajmi 8 MB dan oshmasin.");
        clearImage(); file = candidate; previewUrl = URL.createObjectURL(file);
        $("admin-image-url").value = "";
        $("imageStatus").textContent = `${file.name} · ${(file.size / 1024).toFixed(0)} KB`;
        message(""); preview();
      }
      $("skinPng").onchange = e => chooseFile(e.target.files[0]);
      $("admin-image-url").oninput = () => { clearImage(); $("imageStatus").textContent = "Rasm havolasi tanlandi"; preview(); };
      const drop = $("imageDrop");
      drop.ondragover = e => { e.preventDefault(); if (!busy) drop.classList.add("dragging"); };
      drop.ondragleave = () => drop.classList.remove("dragging");
      drop.ondrop = e => { e.preventDefault(); drop.classList.remove("dragging"); chooseFile(e.dataTransfer.files[0]); };
      form.addEventListener("input", preview);
      form.addEventListener("change", preview);
      function reset() {
        if (busy) return;
        form.reset(); clearImage(); editing = null; editingActive = true;
        $("admin-rarity").value = "Covert";
        $("editorTitle").textContent = "Yangi skin"; $("saveSkin").textContent = "Skinni joylash";
        $("newSkin").hidden = true; $("editorSuccess").hidden = true;
        $("imageStatus").textContent = "Shaffof fonli PNG · 8 MB gacha";
        message(""); preview();
      }
      $("resetSkin").onclick = reset; $("newSkin").onclick = reset;
      function edit(item) {
        if (busy) return;
        reset(); editing = item.id; editingActive = Boolean(item.active); uploadedUrl = item.image;
        for (const key of ["weapon", "skin", "rarity", "condition", "price", "stock", "description"]) $("admin-" + key).value = item[key];
        $("editorTitle").textContent = `Skinni tahrirlash · #${item.id}`;
        $("newSkin").hidden = false; $("saveSkin").textContent = "O‘zgarishlarni saqlash";
        $("imageStatus").textContent = "Saqlangan rasm · almashtirish uchun yangi PNG tanlang";
        preview(); form.scrollIntoView({behavior:"smooth", block:"start"});
      }
      async function list() {
        const request = ++listRequest;
        $("adminListings").setAttribute("aria-busy", "true");
        try {
          const result = await api(`/api/admin/skins?${new URLSearchParams({q: $("adminSearch").value, offset: String(offset)})}`);
          if (!alive || request !== listRequest) return;
          rows = result.items;
          $("adminCount").textContent = `(${result.total})`;
          $("adminListings").innerHTML = rows.length ? rows.map(item => `<div class="admin-list-row"><img src="${esc(item.image)}" alt="" loading="lazy"><div class="admin-item-copy"><strong>${esc(item.name)}</strong><small>${esc(item.rarity)} · ${esc(item.condition)} · ${item.stock} dona</small><span>${money(item.price)} · ${item.active ? "Faol" : "Arxivda"}</span></div><div class="admin-item-actions"><button type="button" class="secondary" data-edit="${item.id}">Tahrirlash</button><button type="button" class="admin-archive" data-archive="${item.id}">${item.active ? "Arxivlash" : "Qaytarish"}</button></div></div>`).join("") : '<p class="empty">Skinlar topilmadi.</p>';
          $("adminListings").querySelectorAll("img").forEach(img => img.onerror = () => { img.onerror = null; img.src = "/static/assets/art-unavailable.svg"; });
          $("adminPrevious").disabled = offset === 0;
          $("adminNext").disabled = offset + rows.length >= result.total;
          $("adminRange").textContent = result.total ? `${offset + 1}–${offset + rows.length} / ${result.total}` : "0";
        } catch (error) {
          if (alive && request === listRequest) $("adminListings").innerHTML = `<p role="alert">${esc(error.message)}</p><button type="button" class="secondary" id="adminListRetry">Qayta urinish</button>`;
          if ($("adminListRetry")) $("adminListRetry").onclick = list;
        } finally { if (alive && request === listRequest) $("adminListings").removeAttribute("aria-busy"); }
      }
      $("adminSearch").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { offset = 0; list(); }, 250); };
      $("adminPrevious").onclick = () => { offset = Math.max(0, offset - 30); list(); };
      $("adminNext").onclick = () => { offset += 30; list(); };
      $("adminListings").onclick = async event => {
        const button = event.target.closest("button");
        if (!button || busy) return;
        const item = rows.find(row => row.id === Number(button.dataset.edit || button.dataset.archive));
        if (!item) return;
        if (button.dataset.edit) return edit(item);
        if (!window.confirm(item.active ? `«${item.name}» katalogdan yashirilsinmi?` : `«${item.name}» katalogga qaytarilsinmi?`)) return;
        button.disabled = true;
        try {
          await api(`/api/admin/skins/${item.id}`, item.active ? {method:"DELETE"} : {method:"PUT", body:JSON.stringify({...item, active:true})});
          if (!alive) return;
          toast(item.active ? "Skin arxivlandi" : "Skin katalogga qaytarildi"); await list();
        } catch (error) { if (alive) { toast(error.message); button.disabled = false; } }
      };
      form.onsubmit = async event => {
        event.preventDefault(); if (busy) return;
        message(""); $("editorSuccess").hidden = true;
        const payload = data();
        if (!payload.weapon || !payload.skin) return message("Qurol va skin nomini kiriting.");
        if (!payload.image) return message("Avval PNG rasm tanlang yoki HTTPS havola kiriting.");
        payload.active = editingActive;
        busy = true;
        const controls = [...form.querySelectorAll("input, select, textarea, button")];
        controls.forEach(control => control.disabled = true);
        try {
          if (file && !uploadedUrl) {
            $("saveSkin").textContent = "PNG yuklanmoqda…";
            const uploaded = await api("/api/admin/images", {method:"POST", headers:{"Content-Type":"image/png"}, body:file, timeoutMs:60000});
            uploadedUrl = uploaded.url;
            if (!alive) return;
            if (!uploaded.transparent) $("imageStatus").textContent = "PNG yuklandi. Shaffof fonli rasm kartada yaxshiroq ko‘rinadi.";
          }
          payload.image = uploadedUrl || $("admin-image-url").value.trim();
          $("saveSkin").textContent = "Saqlanmoqda…";
          const result = await api(editing ? `/api/admin/skins/${editing}` : "/api/admin/skins", {method: editing ? "PUT" : "POST", body:JSON.stringify(payload)});
          if (!alive) return;
          editing = result.item.id;
          $("editorTitle").textContent = `Skinni tahrirlash · #${editing}`; $("newSkin").hidden = false;
          $("editorSuccess").innerHTML = `Skin saqlandi. <a href="/skins/${editing}" data-route>Katalogda ko‘rish ↗</a>`;
          $("editorSuccess").hidden = false;
          toast("Skin saqlandi"); await list();
        } catch (error) { if (alive) message(error.message); }
        finally { busy = false; if (alive) { controls.forEach(control => control.disabled = false); $("saveSkin").textContent = editing ? "O‘zgarishlarni saqlash" : "Skinni joylash"; } }
      };
      reset(); list();
    },
  };
})();
