// เมนู "แสดงกล้องและช่องจอดจริง": ภาพกล้องสด (ซ้าย) คู่กับหน้าจอที่ประชาชนเห็น (ขวา)
// - ภาพกล้องอัปเดตทุก ~1 วินาที (หยุดเองเมื่อสลับแท็บ) · ข้อมูลช่องจอดอัปเดตทุก 10 วินาที
// - ปุ่มเต็มจอ: ใช้ Fullscreen API ถ้าเบราว์เซอร์รองรับ ไม่รองรับ (iPhone) = ขยายเต็มหน้าต่างแทน
// - มือถือ/แท็บเล็ตตะแคงจอ = เต็มจออัตโนมัติ (กดปุ่มเพื่อออกได้ หมุนกลับแนวตั้งก็ออกเอง)

const SC_FRAME_MS = 1000;
const SC_DATA_MS = 10000;
const SC_STALE_SECONDS = 10;
const SC_KEY = "showcase-camera";

const scSleep = (ms) => new Promise((r) => setTimeout(r, ms));
const scStore = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } },
};
const SVG_NS = "http://www.w3.org/2000/svg";
const STATE_COLOR = { free: "#16a34a", occupied: "#dc2626", unknown: "#94a3b8", locked: "#64748b" };

class Showcase {
  constructor() {
    this.$ = (id) => document.getElementById(id);
    this.stage = this.$("sc-stage");
    this.img = this.$("sc-img");
    this.svg = this.$("sc-svg");
    this.box = this.$("sc-cam-box");
    this.body = this.$("sc-cam-body");
    this.cameraId = null;
    this.data = null;
    this.selected = null;
    this.objectUrl = null;
    this.loopToken = 0;
    this.userExitedAuto = false;
    this.landscapeMq = window.matchMedia("(orientation: landscape) and (pointer: coarse)");
  }

  async init() {
    const cameras = await apiJson("/api/admin/cctv/cameras");
    const select = this.$("sc-camera");
    if (!cameras.length) {
      this.$("sc-cam-msg").textContent = "ยังไม่มีกล้องในระบบ";
      return;
    }
    select.innerHTML = "";
    for (const c of cameras) select.add(new Option(c.name, c.id));
    const wanted = Number(new URLSearchParams(location.search).get("camera_id") || scStore.get(SC_KEY));
    this.cameraId = cameras.some((c) => c.id === wanted) ? wanted : cameras[0].id;
    select.value = this.cameraId;
    select.addEventListener("change", () => this.switchCamera(Number(select.value)));

    this.$("sc-overlay").addEventListener("change", (e) => this.stage.classList.toggle("no-overlay", !e.target.checked));
    this.$("sc-fs").addEventListener("click", () => this.toggleFullscreen());
    document.addEventListener("fullscreenchange", () => this._syncFs());
    document.addEventListener("webkitfullscreenchange", () => this._syncFs());
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && this.stage.classList.contains("pseudo-fs")) this._setPseudo(false); });
    const onRotate = () => { this.userExitedAuto = false; this._applyAuto(); };
    if (this.landscapeMq.addEventListener) this.landscapeMq.addEventListener("change", onRotate);
    else this.landscapeMq.addListener(onRotate);
    this._applyAuto();

    new ResizeObserver(() => this._fitBox()).observe(this.body);
    // ความสูงแถบบน → ภาพกล้องติดต่อจากแถบบนพอดีตอนเลื่อนดู (มือถือแนวตั้ง)
    const bar = this.stage.querySelector(".sc-bar");
    new ResizeObserver(() => this.stage.style.setProperty("--sc-bar-h", bar.offsetHeight + "px")).observe(bar);
    this.img.addEventListener("load", () => this._fitBox());
    this._tickClock();
    setInterval(() => this._tickClock(), 1000);

    this.switchCamera(this.cameraId);
    setInterval(() => this.loadData(), SC_DATA_MS);
  }

  switchCamera(id) {
    this.cameraId = id;
    scStore.set(SC_KEY, String(id));
    this.selected = null;
    this.data = null;
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
    this.objectUrl = null;
    this.img.removeAttribute("src");
    this.svg.innerHTML = "";
    this._camMsg("กำลังเชื่อมต่อกล้อง...");
    this.loadData();
    this._frameLoop(++this.loopToken);
  }

  // ---------- ภาพกล้องสด ----------
  async _frameLoop(token) {
    while (token === this.loopToken) {
      if (document.hidden) { await scSleep(1000); continue; }
      const started = Date.now();
      await this._fetchFrame(token);
      await scSleep(Math.max(0, SC_FRAME_MS - (Date.now() - started)));
    }
  }

  async _fetchFrame(token) {
    try {
      const resp = await apiFetch(`/api/admin/cctv/${this.cameraId}/frame?t=${Date.now()}`);
      if (token !== this.loopToken) return;
      if (!resp.ok) {
        const d = await resp.json().catch(() => ({}));
        this._camError(d.detail || `โหลดภาพไม่สำเร็จ (${resp.status})`);
        return;
      }
      const blob = await resp.blob();
      if (token !== this.loopToken) return;
      const url = URL.createObjectURL(blob);
      this.img.src = url;
      if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = url;
      this._camMsg("");
      this._camTime(resp.headers.get("X-Frame-Time"), resp.headers.get("X-Frame-Source"));
    } catch (e) {
      this._camError("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้");
    }
  }

  _camTime(iso, source) {
    const dot = this.$("sc-dot");
    const el = this.$("sc-cam-time");
    if (source !== "live" || !iso) {
      dot.className = "sc-dot stale";
      el.textContent = "ภาพล่าสุดที่บันทึกไว้ (ไม่ใช่ภาพสด)";
      return;
    }
    const t = new Date(iso + "Z");
    dot.className = (Date.now() - t.getTime()) / 1000 > SC_STALE_SECONDS ? "sc-dot stale" : "sc-dot";
    el.textContent = "LIVE " + t.toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  _camError(text) {
    this.$("sc-dot").className = "sc-dot err";
    this.$("sc-cam-time").textContent = text;
    if (!this.objectUrl) this._camMsg(text);
  }

  _camMsg(text) {
    const m = this.$("sc-cam-msg");
    m.textContent = text;
    m.hidden = !text;
  }

  // กรอบภาพให้พอดีช่องแสดงผล โดยคงสัดส่วนภาพ (กรอบช่องจอดจะซ้อนตรงตำแหน่งเสมอ)
  _fitBox() {
    const w = this.img.naturalWidth || 16, h = this.img.naturalHeight || 9;
    const bw = this.body.clientWidth, bh = this.body.clientHeight;
    if (!bw || !bh) return;
    const scale = Math.min(bw / w, bh / h);
    this.box.style.width = `${Math.floor(w * scale)}px`;
    this.box.style.height = `${Math.floor(h * scale)}px`;
    const vb = `0 0 ${w} ${h}`;
    if (this.svg.getAttribute("viewBox") !== vb) {
      this.svg.setAttribute("viewBox", vb);
      this._drawOverlay();
    }
  }

  _drawOverlay() {
    this.svg.innerHTML = "";
    if (!this.data || !this.img.naturalWidth) return;
    const w = this.img.naturalWidth, h = this.img.naturalHeight;
    const fs = Math.max(12, Math.round(w / 55));
    for (const s of this.data.slots) {
      const g = document.createElementNS(SVG_NS, "g");
      g.setAttribute("class", "slot s-" + s.state + (s.code === this.selected ? " sel" : ""));
      const poly = document.createElementNS(SVG_NS, "polygon");
      poly.setAttribute("points", s.polygon.map(([x, y]) => `${x * w},${y * h}`).join(" "));
      poly.style.setProperty("--c", STATE_COLOR[s.state] || STATE_COLOR.unknown);
      const cx = s.polygon.reduce((a, p) => a + p[0], 0) / s.polygon.length * w;
      const cy = s.polygon.reduce((a, p) => a + p[1], 0) / s.polygon.length * h;
      const text = document.createElementNS(SVG_NS, "text");
      text.setAttribute("x", cx);
      text.setAttribute("y", cy);
      text.setAttribute("font-size", fs);
      text.textContent = s.code;
      g.append(poly, text);
      g.addEventListener("click", () => this.select(s.code));
      this.svg.appendChild(g);
    }
  }

  // ---------- ข้อมูลช่องจอด / หน้าจอประชาชน ----------
  async loadData() {
    const id = this.cameraId;
    try {
      const data = await apiJson(`/api/admin/showcase/${id}`);
      if (id !== this.cameraId) return;
      this.data = data;
      this.$("sc-cam-name").textContent = data.camera.name;
      this._drawOverlay();
      this._renderPublic();
    } catch (e) {
      this.$("sc-pub-upd").textContent = "โหลดข้อมูลไม่สำเร็จ";
    }
  }

  _renderPublic() {
    const pub = this.data.public || {};
    const $ = this.$;
    const ring = this.data.style === "ring";
    this.stage.classList.toggle("style-ring", ring);
    $("sc-ring").hidden = !ring;
    $("sc-gridview").hidden = ring;
    $("sc-site").textContent = pub.site_name || "ยังไม่ได้ผูกกับสถานที่";
    const note = $("sc-note");
    note.textContent = pub.note || "";
    note.hidden = !pub.note;

    // สถานที่ไม่แสดงต่อสาธารณะ → แสดงช่องของกล้องนี้แทน (บอกไว้ในหมายเหตุ)
    let zones = pub.shown ? pub.zones || [] : [];
    let free = pub.free, cap = pub.capacity, status = pub.status;
    if (!pub.shown) {
      const slots = this.data.slots.map((s) => ({ code: s.code, state: s.type === "reserved" ? "locked" : s.state, type: s.type }));
      zones = [{ code: "", name: "ช่องของกล้องนี้ (ไม่แสดงต่อสาธารณะ)", status: "ok", slots,
                 free: slots.filter((s) => s.state === "free").length, capacity: slots.filter((s) => s.state !== "locked").length }];
      free = zones[0].free; cap = zones[0].capacity; status = "preview";
    }
    const unknownNum = status === "stale" || status === "no_data";
    $("sc-free").textContent = unknownNum ? "–" : free;
    $("sc-cap").textContent = cap ?? "–";
    const pill = { ok: ["มีที่ว่าง", "ok"], full: ["เต็ม", "full"], stale: ["ข้อมูลไม่เป็นปัจจุบัน", "warn"], closed: ["ปิดให้บริการ", "off"],
                   no_data: ["ยังไม่มีข้อมูล", "off"], preview: ["ตัวอย่าง", "off"] }[status] || ["–", "off"];
    $("sc-pill").textContent = pill[0];
    $("sc-pill").className = "sc-pill " + pill[1];
    $("sc-total").className = "sc-total t-" + (status || "off");
    const upd = pub.site_updated_at ? new Date(pub.site_updated_at + "Z") : null;
    $("sc-pub-upd").textContent = upd ? "อัปเดต " + upd.toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";

    if (ring) { this._renderRing(pub, zones, free, cap, status, upd); return; }

    const wrap = $("sc-zones");
    wrap.innerHTML = "";
    const many = zones.length > 1 || !pub.shown;
    for (const z of zones) {
      const sec = document.createElement("section");
      sec.className = "sc-zone";
      if (many || zones.length === 1) {
        const head = document.createElement("div");
        head.className = "sc-zone-head";
        const name = document.createElement("span");
        name.textContent = z.name;
        const val = document.createElement("b");
        val.textContent = z.status === "closed" ? "ปิดให้บริการ" : `ว่าง ${z.free}/${z.capacity}`;
        val.className = z.status === "closed" ? "off" : z.free ? "" : "full";
        head.append(name, val);
        sec.appendChild(head);
      }
      const grid = document.createElement("div");
      grid.className = "sc-grid";
      for (const s of z.slots || []) {
        const b = document.createElement("button");
        b.type = "button";
        const kind = s.state === "locked" ? "locked" : s.state === "free" ? "free" : s.state === "occupied" ? "taken" : "unknown";
        b.className = `sc-slot ${kind}` + (s.code === this.selected ? " sel" : "");
        b.dataset.code = s.code;
        b.title = `${s.code} · ${{ free: "ว่าง", taken: "มีรถ", unknown: "ไม่ทราบสถานะ", locked: "ช่องสงวน" }[kind]}`;
        b.innerHTML = `<span class="code"></span>${kind === "taken" ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 16V11l2-5h10l2 5v5"/><path d="M3 16h18v3H3z"/><circle cx="7.5" cy="13" r="1"/><circle cx="16.5" cy="13" r="1"/></svg>' : ""}`;
        b.querySelector(".code").textContent = s.code;
        b.addEventListener("click", () => this.select(s.code));
        grid.appendChild(b);
      }
      if (z.status === "closed") grid.innerHTML = '<p class="sc-empty">โซนนี้ปิดให้บริการ</p>';
      sec.appendChild(grid);
      wrap.appendChild(sec);
    }
  }

  // แบบหน้าประชาชน: วงแหวนช่องว่าง + ตัวเลขแยกสถานะ + การ์ดโซน (หน้าตาเดียวกับหน้าสาธารณะบนมือถือ)
  _renderRing(pub, zones, free, cap, status, upd) {
    const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    const counts = pub.counts || zones.reduce((acc, z) => {
      for (const s of z.slots || []) acc[s.state in acc ? s.state : "unknown"] += 1;
      return acc;
    }, { free: 0, occupied: 0, locked: 0, unknown: 0 });
    const noNum = status === "stale" || status === "no_data";
    const ratio = cap && !noNum ? Math.max(0, Math.min(1, free / cap)) : 0;
    const C = 2 * Math.PI * 52;
    const live = { ok: "ออนไลน์", full: "ออนไลน์ · เต็ม", stale: "ข้อมูลไม่เป็นปัจจุบัน", closed: "ปิดให้บริการ", no_data: "ยังไม่มีข้อมูล", preview: "ตัวอย่าง (ไม่แสดงต่อสาธารณะ)" }[status] || "";
    const t = upd ? upd.toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" }) + " น." : "";
    const tone = noNum ? "off" : free === 0 ? "full" : "ok";
    let html = `
      <div class="rg-head">
        <small>ที่จอดรถว่างแบบเรียลไทม์</small>
        <b>${esc(pub.site_name || "ช่องของกล้องนี้")}</b>
        <span class="rg-live ${tone}"><i></i>${esc(live)}${t ? " · อัปเดต " + t : ""}</span>
      </div>
      ${pub.note ? `<p class="rg-note">${esc(pub.note)}</p>` : ""}
      <section class="rg-card">
        <div class="rg-ring ${tone}">
          <svg viewBox="0 0 120 120" aria-hidden="true"><circle class="bg" cx="60" cy="60" r="52"/>
            <circle class="fg" cx="60" cy="60" r="52" stroke-dasharray="${(C * ratio).toFixed(1)} ${C.toFixed(1)}"/></svg>
          <div class="rg-center"><b>${noNum ? "–" : free}</b><span>ช่องว่าง จาก ${cap ?? 0}</span></div>
        </div>
        <div class="rg-stats">
          <div><b class="c-free">${counts.free}</b><span>ว่าง</span></div>
          <div><b class="c-taken">${counts.occupied}</b><span>มีรถจอด</span></div>
          <div><b class="c-locked">${counts.locked}</b><span>สงวน/ล็อก</span></div>
          <div><b class="c-unknown">${counts.unknown}</b><span>ไม่ทราบ</span></div>
        </div>
        <div class="rg-extra"><span>♿ คนพิการ ว่าง ${pub.free_disabled || 0}</span><span>⚡ EV ว่าง ${pub.free_ev || 0}</span></div>
      </section>`;
    for (const z of zones) {
      const slots = z.slots || [];
      const freeCodes = slots.filter((s) => s.state === "free").map((s) => s.code);
      html += `
      <section class="rg-zone">
        <div class="rg-zone-head"><b>${esc(z.name)}</b><span><b class="${z.free ? "c-free" : "c-taken"}">${z.status === "closed" ? "ปิด" : z.free}</b> / ${z.capacity}</span></div>
        <div class="rg-strip" style="grid-template-columns: repeat(${Math.max(1, slots.length)}, minmax(0, 1fr))">
          ${slots.map((s) => `<button type="button" class="rg-bar ${s.state === "occupied" ? "taken" : esc(s.state)}${s.code === this.selected ? " sel" : ""}" data-code="${esc(s.code)}" title="${esc(s.code)}"></button>`).join("")}
        </div>
        ${z.status === "closed" ? '<p class="rg-free-title">โซนนี้ปิดให้บริการ</p>'
          : freeCodes.length ? `<p class="rg-free-title">มีช่องจอดว่างตำแหน่ง</p><p class="rg-free">${freeCodes.map((c) => `<button type="button" class="rg-code${c === this.selected ? " sel" : ""}" data-code="${esc(c)}">${esc(c)}</button>`).join(", ")}</p>`
          : '<p class="rg-free-title">ไม่มีช่องว่างในโซนนี้</p>'}
      </section>`;
    }
    const box = this.$("sc-ring");
    box.innerHTML = html;
    box.querySelectorAll("[data-code]").forEach((b) => b.addEventListener("click", () => this.select(b.dataset.code)));
  }

  // แตะช่องฝั่งใดฝั่งหนึ่ง → ไฮไลต์ทั้งบนภาพกล้องและในหน้าจอประชาชน (แตะซ้ำ = ยกเลิก)
  select(code) {
    this.selected = this.selected === code ? null : code;
    this.svg.querySelectorAll(".slot").forEach((g, i) => g.classList.toggle("sel", this.data && this.data.slots[i].code === this.selected));
    document.querySelectorAll(".sc-slot, .rg-bar, .rg-code").forEach((b) => b.classList.toggle("sel", b.dataset.code === this.selected));
  }

  // ---------- เต็มจอ ----------
  toggleFullscreen() {
    const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
    if (fsEl) { (document.exitFullscreen || document.webkitExitFullscreen).call(document); return; }
    if (this.stage.classList.contains("pseudo-fs")) {
      if (this.landscapeMq.matches) this.userExitedAuto = true;
      this._setPseudo(false);
      return;
    }
    const req = this.stage.requestFullscreen || this.stage.webkitRequestFullscreen;
    if (req) {
      Promise.resolve(req.call(this.stage)).catch(() => this._setPseudo(true));
    } else {
      this._setPseudo(true);  // iPhone: ไม่มี Fullscreen API → ขยายเต็มหน้าต่างแทน
    }
  }

  _setPseudo(on) {
    this.stage.classList.toggle("pseudo-fs", on);
    document.documentElement.classList.toggle("sc-lock", on);
    this._syncFs();
  }

  _applyAuto() {
    const auto = this.landscapeMq.matches && !this.userExitedAuto;
    if (auto !== this.stage.classList.contains("pseudo-fs")) this._setPseudo(auto);
  }

  _syncFs() {
    const on = !!(document.fullscreenElement || document.webkitFullscreenElement) || this.stage.classList.contains("pseudo-fs");
    this.stage.classList.toggle("is-fs", on);
    const btn = this.$("sc-fs");
    btn.title = on ? "ออกจากเต็มจอ" : "แสดงเต็มจอ";
    btn.setAttribute("aria-label", btn.title);
    btn.querySelector(".sc-fs-text").textContent = on ? "ออก" : "เต็มจอ";
    this._wakeLock(on);
    requestAnimationFrame(() => this._fitBox());
  }

  // นำเสนอบนจอใหญ่: กันหน้าจอดับระหว่างเต็มจอ (ถ้าเบราว์เซอร์รองรับ)
  async _wakeLock(on) {
    try {
      if (on && !this.lock && navigator.wakeLock) this.lock = await navigator.wakeLock.request("screen");
      if (!on && this.lock) { await this.lock.release(); this.lock = null; }
    } catch (e) { this.lock = null; }
  }

  _tickClock() {
    this.$("sc-clock").textContent = new Date().toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) + " น.";
  }
}

(async function bootstrap() {
  const user = await requireAuth();
  if (!user) return;
  await new Showcase().init();
})();
