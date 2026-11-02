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

    // เปิดจากลิงก์ในหน้าแจ้งเตือน (?camera_id=) → เลือกกล้องนั้นเลย
    const wanted = Number(new URLSearchParams(location.search).get("camera_id"));
    this.cameraId = cameras.some((c) => c.id === wanted) ? wanted : cameras[0].id;
    this.cameras = cameras;
    ExportKit.bindTools(document.getElementById("tools"), {
      refresh: () => this.loadAndRender(),
      lineText: () => this._lineText(),
      spec: () => this._spec(),
      image: () => (this.stage ? this.stage.toDataURL({ pixelRatio: 2 }) : null),  // ภาพกล้องพร้อมกรอบช่อง
      card: () => this._card(),  // ภาพสรุปสำหรับส่ง LINE / บันทึกรูป
    });
    select.value = this.cameraId;
    await this.loadAndRender();
    this.refreshTimer = setInterval(() => this.loadAndRender(), LIVE_REFRESH_MS);
  }

  async loadAndRender() {
    this._setStatus("กำลังโหลด...");
    try {
      const data = await apiJson(`/api/admin/live/${this.cameraId}`);
      this.data = data;
      document.getElementById("camera-status").textContent = `สถานะกล้อง: ${data.camera.status}`;
      await this._setupStage();
      this._renderNoParking(data.no_parking);
      this._renderSlots(data.slots);
      const now = new Date().toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      this._setStatus("");
      ExportKit.markUpdated(document.getElementById("tools"));
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

    this.npzLayer = new Konva.Layer({ listening: false });
    this.stage.add(this.npzLayer);
    this.layer = new Konva.Layer();
    this.stage.add(this.layer);
  }

  // เขตห้ามจอด: เส้นประแดง + จำนวนรถที่จอดนิ่งในเขต
  _renderNoParking(np) {
    const card = document.getElementById("npz-card");
    if (!np || !np.zones.length) {
      card.style.display = "none";
      return;
    }
    card.style.display = "";
    for (const zone of np.zones) {
      const points = zone.polygon.flatMap(([x, y]) => [x * this.imgWidth, y * this.imgHeight]);
      const hit = zone.count > 0;
      this.npzLayer.add(new Konva.Line({
        points, closed: true, stroke: "#dc2626", strokeWidth: hit ? 3 : 2, dash: [10, 6],
        fill: hit ? "rgba(220,38,38,0.30)" : "rgba(220,38,38,0.10)",
      }));
      const c = zone.polygon.reduce((acc, [x, y]) => [acc[0] + x, acc[1] + y], [0, 0]).map((v) => v / zone.polygon.length);
      const tag = new Konva.Label({ x: c[0] * this.imgWidth, y: c[1] * this.imgHeight });
      tag.add(new Konva.Tag({ fill: "#dc2626", opacity: 0.9, cornerRadius: 3 }));
      tag.add(new Konva.Text({ text: hit ? `⛔ ${zone.name} · จอด ${zone.count} คัน` : `⛔ ${zone.name}`, fontSize: 12, padding: 3, fill: "#fff", fontStyle: "bold" }));
      tag.offsetX(tag.width() / 2);
      this.npzLayer.add(tag);
    }
    this.npzLayer.draw();

    const summary = document.getElementById("npz-summary");
    summary.textContent = np.total ? `พบรถจอดในเขตห้ามจอด ${np.total} คัน` : "ไม่มีรถจอดในเขตห้ามจอด";
    summary.className = "npz-badge" + (np.total ? "" : " ok");
    document.getElementById("npz-dwell-text").textContent = np.dwell_min;
    const ul = document.getElementById("npz-list");
    ul.innerHTML = "";
    for (const zone of np.zones) {
      const li = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = zone.name;
      const badge = document.createElement("span");
      badge.className = "npz-badge" + (zone.count ? "" : " ok");
      badge.textContent = zone.count ? `${zone.count} คัน · ${zone.longest_min} นาที` : "ว่าง";
      li.append(name, badge);
      ul.appendChild(li);
    }
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
          text: `${slot.code} ${scoreText}${slot.held ? " จำ" : ""}`,
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
      // "จำ" = AI ไม่เห็นรถรอบนี้ แต่ภาพช่องยังเหมือนตอนที่เห็นรถ ระบบจึงคงสถานะมีรถไว้ (ช่องจำรถ)
      const heldText = slot.held ? " · จำ" : "";
      li.innerHTML = `<span>${slot.code}</span><span class="badge badge-${slot.state}" title="${slot.held ? "ช่องจำรถ: AI ไม่เห็นรถรอบนี้ แต่ภาพช่องยังเหมือนตอนที่มีรถ" : ""}">${slot.state} (${scoreText})${heldText}</span>`;
      ul.appendChild(li);
    }
  }

  _counts() {
    const c = { free: 0, occupied: 0, unknown: 0 };
    for (const s of this.data.slots) c[s.state] = (c[s.state] || 0) + 1;
    return c;
  }

  // ข้อความสรุปวางใน LINE: ยอดช่องของกล้องนี้ + ช่องว่าง + เขตห้ามจอด
  _lineText() {
    if (!this.data) return "";
    const d = this.data;
    const c = this._counts();
    const lines = [`📷 ${d.camera.name} — ${ExportKit.thaiNow()}`,
      `ว่าง ${c.free} · มีรถ ${c.occupied}${c.unknown ? ` · ไม่ทราบ ${c.unknown}` : ""} (รวม ${d.slots.length} ช่อง)`];
    const free = d.slots.filter((s) => s.state === "free").map((s) => s.code);
    if (free.length) lines.push(`ช่องว่าง: ${free.join(", ")}`);
    if (d.no_parking) {
      lines.push(d.no_parking.total
        ? `⛔ รถจอดในเขตห้ามจอด ${d.no_parking.total} คัน: ` + d.no_parking.zones.filter((z) => z.count).map((z) => `${z.name} ${z.count} คัน (${z.longest_min} นาที)`).join(", ")
        : "⛔ เขตห้ามจอด: ไม่มีรถจอด");
    }
    if (d.camera.status !== "online") lines.push(`⚠️ สถานะกล้อง: ${d.camera.status}`);
    return lines.join("\n");
  }

  // ภาพสรุปสถานะ (ปุ่ม คัดลอก (วางใน LINE) / บันทึกรูป): ภาพกล้องพร้อมกรอบ + ยอดช่อง + เขตห้ามจอด
  _card() {
    if (!this.data) throw new Error("ยังโหลดข้อมูลไม่เสร็จ");
    const d = this.data;
    const c = this._counts();
    const total = d.slots.length;
    const pct = total ? Math.round((c.free * 100) / total) : 0;
    const camText = { online: "ออนไลน์", offline: "ขาดการเชื่อมต่อ", moved: "อาจถูกขยับ", disabled: "ปิดใช้งาน" }[d.camera.status] || d.camera.status;
    let panel;
    if (d.no_parking) {
      panel = {
        title: "⛔ เขตห้ามจอด / จอดซ้อนคัน",
        rows: d.no_parking.zones.filter((z) => z.count).map((z) => ({ left: z.name, right: `${z.count} คัน · ${z.longest_min} นาที`, tone: "red" })),
        empty: "ไม่มีรถจอดในเขตห้ามจอด",
      };
    } else {
      const free = d.slots.filter((s) => s.state === "free").map((s) => s.code);
      const rows = [];
      for (let i = 0; i < Math.min(free.length, 24); i += 6) rows.push({ left: free.slice(i, i + 6).join(", "), right: "", tone: "green" });
      panel = { title: "ช่องที่ว่าง", rows, empty: "ไม่มีช่องว่าง" };
    }
    return {
      filename: `live-camera-${d.camera.id}`,
      subtitle: `สถานะช่องจอดสด · ${d.camera.name}`,
      picture: this.stage ? this.stage.toDataURL({ pixelRatio: 2 }) : null,
      hero: { label: "ช่องจอดทั้งหมด", value: total, unit: "ช่อง", ratio: total ? c.free / total : 0,
              ratioText: c.free ? `ว่าง ${pct}%` : "เต็มแล้ว", tone: "blue", barColor: c.free ? "#16a34a" : "#dc2626" },
      pair: [{ label: "ว่าง", value: c.free, unit: "ช่อง", tone: "green" }, { label: "มีรถจอด", value: c.occupied, unit: "ช่อง", tone: "red" }],
      legend: [{ color: "#16a34a", text: "ว่าง" }, { color: "#dc2626", text: "มีรถจอด" }, { color: "#64748b", text: "ไม่ทราบสถานะ" },
               { color: "#dc2626", text: "เขตห้ามจอด", dash: true }],
      info: `สถานะกล้อง: ${camText}` + (c.unknown ? ` · ไม่ทราบสถานะ ${c.unknown} ช่อง` : ""),
      panel,
    };
  }

  _spec() {
    const d = this.data || { camera: { name: "" }, slots: [] };
    const label = { free: "ว่าง", occupied: "มีรถ", unknown: "ไม่ทราบ" };
    const c = this.data ? this._counts() : { free: 0, occupied: 0, unknown: 0 };
    const meta = [`ว่าง ${c.free} · มีรถ ${c.occupied} · ไม่ทราบ ${c.unknown} (รวม ${d.slots.length} ช่อง)`];
    if (d.no_parking) meta.push(`เขตห้ามจอด: ${d.no_parking.total ? "มีรถจอด " + d.no_parking.total + " คัน" : "ไม่มีรถจอด"}`);
    return {
      title: `สถานะช่องจอดสด — ${d.camera.name}`,
      filename: `live-camera-${this.cameraId}`,
      columns: ["ช่อง", "ประเภท", "สถานะ", "คะแนน", "หมายเหตุ"],
      rows: d.slots.map((s) => [s.code, s.type, label[s.state] || s.state, s.score != null ? s.score.toFixed(2) : "-", s.held ? "จำ (ช่องจำรถ)" : ""]),
      meta,
    };
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
