// Live view: เลือกกล้อง ดูภาพล่าสุด + กรอบสีตามสถานะ + score (FR-33)

const LIVE_STATE_COLORS = { free: "#16a34a", occupied: "#dc2626", unknown: "#64748b" };
const LIVE_REFRESH_MS = 30000;

class LiveView {
  constructor() {
    this.cameraId = null;
    this.stage = null;
    this.layer = null;
    this.imgWidth = 0;
    this.imgHeight = 0;
    this.refreshTimer = null;
  }

  async init() {
    const cameras = await apiJson("/api/admin/live/cameras");
    if (cameras.length === 0) {
      document.getElementById("no-camera-msg").style.display = "block";
      return;
    }

    const select = document.getElementById("camera-select");
    select.innerHTML = cameras
      .map((c) => `<option value="${c.id}">${c.name}</option>`)
      .join("");
    select.addEventListener("change", () => {
      this.cameraId = Number(select.value);
      this.loadAndRender();
    });

    this.cameraId = cameras[0].id;
    await this.loadAndRender();
    this.refreshTimer = setInterval(() => this.loadAndRender(), LIVE_REFRESH_MS);
  }

  async loadAndRender() {
    this._setStatus("กำลังโหลด...");
    try {
      const data = await apiJson(`/api/admin/live/${this.cameraId}`);
      document.getElementById("camera-status").textContent = `สถานะกล้อง: ${data.camera.status}`;
      await this._setupStage();
      this._renderSlots(data.slots);
      const now = new Date().toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      this._setStatus(`รีเฟรชล่าสุด ${now}`);
    } catch (e) {
      this._setStatus("โหลดไม่สำเร็จ: " + e.message, true);
    }
  }

  async _setupStage() {
    const maxWidth = Math.min(900, window.innerWidth - 40);
    const snapshotUrl = `/api/admin/cameras/${this.cameraId}/snapshot?t=${Date.now()}`;

    const img = new Image();
    const loaded = await new Promise((resolve) => {
      img.onload = () => resolve(true);
      img.onerror = () => resolve(false);
      img.src = snapshotUrl;
    });

    document.getElementById("no-snapshot-msg").style.display = loaded ? "none" : "block";
    if (loaded) {
      const scale = Math.min(1, maxWidth / img.naturalWidth);
      this.imgWidth = Math.round(img.naturalWidth * scale);
      this.imgHeight = Math.round(img.naturalHeight * scale);
    } else {
      this.imgWidth = maxWidth;
      this.imgHeight = Math.round(maxWidth * 0.5625);
    }

    document.getElementById("stage-container").innerHTML = "";
    this.stage = new Konva.Stage({ container: "stage-container", width: this.imgWidth, height: this.imgHeight });

    const bgLayer = new Konva.Layer();
    if (loaded) {
      bgLayer.add(new Konva.Image({ image: img, width: this.imgWidth, height: this.imgHeight }));
    }
    this.stage.add(bgLayer);

    this.layer = new Konva.Layer();
    this.stage.add(this.layer);
  }

  _renderSlots(slots) {
    this.layer.destroyChildren();
    for (const slot of slots) {
      const color = LIVE_STATE_COLORS[slot.state] || LIVE_STATE_COLORS.unknown;
      const points = slot.polygon.flatMap(([x, y]) => [x * this.imgWidth, y * this.imgHeight]);
      this.layer.add(new Konva.Line({ points, closed: true, stroke: color, strokeWidth: 2, fill: color, opacity: 0.35 }));

      const centroid = slot.polygon.reduce((acc, [x, y]) => [acc[0] + x, acc[1] + y], [0, 0]).map((v) => v / slot.polygon.length);
      const scoreText = slot.score !== null && slot.score !== undefined ? slot.score.toFixed(2) : "-";
      this.layer.add(
        new Konva.Text({
          x: centroid[0] * this.imgWidth - 20,
          y: centroid[1] * this.imgHeight - 7,
          text: `${slot.code} ${scoreText}`,
          fontSize: 12,
          fill: "#fff",
          fontStyle: "bold",
        })
      );
    }
    this.layer.draw();

    document.getElementById("slot-count").textContent = slots.length;
    const ul = document.getElementById("slot-list");
    ul.innerHTML = "";
    for (const slot of slots) {
      const li = document.createElement("li");
      const scoreText = slot.score !== null && slot.score !== undefined ? slot.score.toFixed(2) : "-";
      li.innerHTML = `<span>${slot.code}</span><span class="badge badge-${slot.state}">${slot.state} (${scoreText})</span>`;
      ul.appendChild(li);
    }
  }

  _setStatus(text, isError = false) {
    const el = document.getElementById("status-text");
    el.textContent = text;
    el.style.color = isError ? "var(--color-danger)" : "var(--color-muted)";
  }
}

(async function bootstrap() {
  const user = await requireAuth();
  if (!user) return;

  const view = new LiveView();
  await view.init();
})();
