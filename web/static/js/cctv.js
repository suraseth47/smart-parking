// หน้ากล้องวงจรปิด: แบ่งจอ 1 / 4 / 8 กล้อง ภาพนิ่งอัปเดตทุก ~1 วินาที (หลังบ้านเท่านั้น)

const CCTV_REFRESH_MS = 1000;
const CCTV_STALE_SECONDS = 10;
const CCTV_LAYOUTS = [1, 4, 8];

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

class CctvTile {
  constructor(camera) {
    this.camera = camera;
    this.active = false;
    this.objectUrl = null;
    this.el = document.createElement("button");
    this.el.type = "button";
    this.el.className = "tile" + (camera ? "" : " empty");
    if (!camera) {
      this.el.disabled = true;
      this.el.innerHTML = '<div class="tile-msg">ไม่มีกล้อง</div>';
      return;
    }
    this.el.setAttribute("aria-label", `ขยายดูกล้อง ${camera.name}`);
    this.img = document.createElement("img");
    this.img.alt = `ภาพจากกล้อง ${camera.name}`;
    this.msg = document.createElement("div");
    this.msg.className = "tile-msg";
    this.msg.textContent = "กำลังเชื่อมต่อกล้อง...";
    const label = document.createElement("div");
    label.className = "tile-label";
    this.dot = document.createElement("span");
    this.dot.className = "dot";
    const name = document.createElement("span");
    name.appendChild(this.dot);
    name.appendChild(document.createTextNode(camera.name));
    this.timeEl = document.createElement("span");
    this.timeEl.className = "tile-time";
    label.appendChild(name);
    label.appendChild(this.timeEl);
    this.el.appendChild(this.img);
    this.el.appendChild(this.msg);
    this.el.appendChild(label);
  }

  start() {
    if (!this.camera || this.active) return;
    this.active = true;
    this._loop();
  }

  stop() {
    this.active = false;
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
    this.objectUrl = null;
  }

  async _loop() {
    while (this.active) {
      if (document.hidden) {
        await sleep(1000);
        continue;
      }
      const started = Date.now();
      await this._fetchOnce();
      await sleep(Math.max(0, CCTV_REFRESH_MS - (Date.now() - started)));
    }
  }

  async _fetchOnce() {
    try {
      const resp = await apiFetch(`/api/admin/cctv/${this.camera.id}/frame?t=${Date.now()}`);
      if (!this.active) return;
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        this._showError(data.detail || `โหลดภาพไม่สำเร็จ (${resp.status})`);
        return;
      }
      const blob = await resp.blob();
      if (!this.active) return;
      const url = URL.createObjectURL(blob);
      this.img.src = url;
      if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = url;
      this.msg.style.display = "none";
      this._showTime(resp.headers.get("X-Frame-Time"), resp.headers.get("X-Frame-Source"));
    } catch (e) {
      this._showError("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้");
    }
  }

  _showTime(frameTimeIso, source) {
    if (source !== "live" || !frameTimeIso) {
      this.dot.className = "dot stale";
      this.timeEl.textContent = "ภาพล่าสุดที่บันทึกไว้ (ไม่ใช่ภาพสด)";
      return;
    }
    const frameTime = new Date(frameTimeIso + "Z");
    const ageSeconds = (Date.now() - frameTime.getTime()) / 1000;
    this.dot.className = ageSeconds > CCTV_STALE_SECONDS ? "dot stale" : "dot";
    this.timeEl.textContent = frameTime.toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  _showError(text) {
    this.dot.className = "dot err";
    if (!this.objectUrl) {
      this.msg.style.display = "flex";
      this.msg.textContent = text;
    }
    this.timeEl.textContent = text;
  }
}

class CctvPage {
  constructor() {
    this.cameras = [];
    this.tiles = [];
    this.layout = Number(localStorageGet("cctv-layout")) || 4;
    if (!CCTV_LAYOUTS.includes(this.layout)) this.layout = 4;
    this.singleCameraId = null;
    this.grid = document.getElementById("cctv-grid");
    this.select = document.getElementById("single-camera");
  }

  async init() {
    try {
      this.cameras = await apiJson("/api/admin/cctv/cameras");
    } catch (e) {
      document.getElementById("cctv-status").textContent = "โหลดรายชื่อกล้องไม่สำเร็จ: " + e.message;
      return;
    }
    if (this.cameras.length === 0) {
      document.getElementById("cctv-status").textContent = "ยังไม่มีกล้องที่เปิดใช้งานในระบบ";
      return;
    }
    this.singleCameraId = this.cameras[0].id;
    this.select.innerHTML = "";
    for (const c of this.cameras) {
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = c.name;
      this.select.appendChild(opt);
    }
    this.select.addEventListener("change", () => {
      this.singleCameraId = Number(this.select.value);
      this.render();
    });
    document.querySelectorAll("[data-layout]").forEach((btn) => {
      btn.addEventListener("click", () => this.setLayout(Number(btn.dataset.layout)));
    });
    document.getElementById("btn-fullscreen").addEventListener("click", () => {
      if (this.grid.requestFullscreen) this.grid.requestFullscreen();
    });
    window.addEventListener("pagehide", () => this.stopAll());
    this.render();
  }

  setLayout(layout, cameraId) {
    this.layout = layout;
    if (cameraId) this.singleCameraId = cameraId;
    localStorageSet("cctv-layout", String(layout));
    this.render();
  }

  stopAll() {
    for (const t of this.tiles) t.stop();
    this.tiles = [];
  }

  render() {
    this.stopAll();
    document.querySelectorAll("[data-layout]").forEach((btn) => {
      const isActive = Number(btn.dataset.layout) === this.layout;
      btn.classList.toggle("active", isActive);
      btn.setAttribute("aria-pressed", String(isActive));
    });
    const single = this.layout === 1;
    this.select.style.display = single ? "" : "none";
    document.getElementById("single-camera-label").style.display = single ? "" : "none";
    this.select.value = String(this.singleCameraId);

    this.grid.className = `cctv-grid g${this.layout}`;
    this.grid.innerHTML = "";
    const cams = single
      ? [this.cameras.find((c) => c.id === this.singleCameraId) || this.cameras[0]]
      : Array.from({ length: this.layout }, (_, i) => this.cameras[i] || null);

    for (const cam of cams) {
      const tile = new CctvTile(cam);
      if (cam && !single) tile.el.addEventListener("click", () => this.setLayout(1, cam.id));
      this.grid.appendChild(tile.el);
      this.tiles.push(tile);
      tile.start();
    }
    const shown = cams.filter(Boolean).length;
    document.getElementById("cctv-status").textContent =
      this.cameras.length > shown ? `แสดง ${shown} จาก ${this.cameras.length} กล้อง` : "";
  }
}

function localStorageGet(key) {
  try {
    return window.localStorage.getItem(key);
  } catch (e) {
    return null;
  }
}

function localStorageSet(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch (e) {
    // เบราว์เซอร์ไม่ให้เก็บค่า ไม่เป็นไร ใช้ค่าเริ่มต้นแทน
  }
}

(async function bootstrap() {
  const user = await requireAuth();
  if (!user) return;
  const page = new CctvPage();
  await page.init();
})();
