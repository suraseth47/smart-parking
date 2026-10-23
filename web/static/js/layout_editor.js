// Layout Editor: วาด/แก้/ลบ/คัดลอก/ทำซ้ำช่องจอดด้วย Konva.js (FR-24), preview (FR-25), publish (FR-26)

const TYPE_LABELS = {
  normal: "ปกติ",
  disabled: "คนพิการ",
  ev: "EV",
  reserved: "สงวน",
};

const STATE_COLORS = { free: "#16a34a", occupied: "#dc2626" };
const DEFAULT_STROKE = "#38bdf8";
const SELECTED_STROKE = "#f97316";
// กรอบที่ AI เห็นใน Preview: เขียว = AI ทายว่าเป็นรถ, เหลืองอำพัน = วัตถุใหญ่ที่นับเป็นรถ
const DETECTION_COLORS = { vehicle: "#22c55e", large: "#f59e0b" };
const ROI_COLOR = "#0ea5e9";

class LayoutEditor {
  constructor(cameraId) {
    this.cameraId = cameraId;
    this.zones = [];
    this.slots = [];
    this.selected = null;
    this.drawMode = false;
    this.drawPoints = [];
    this.stage = null;
    this.layer = null;
    this.detLayer = null;
    this.previewDetections = [];
    this.previewRoi = null;
    this.showDetections = true;
    this.imgWidth = 0;
    this.imgHeight = 0;
  }

  async init() {
    const camera = await apiJson(`/api/admin/cameras/${this.cameraId}`);
    document.getElementById("camera-name").textContent = `กล้อง: ${camera.name}`;

    this.zones = await apiJson("/api/admin/zones");
    this._fillZoneSelect(document.getElementById("default-zone"));
    this._fillZoneSelect(document.getElementById("sel-zone"));

    await this._loadSnapshotAndSetupStage();
    await this._loadSlots();
    this._wireButtons();
  }

  _fillZoneSelect(selectEl) {
    selectEl.innerHTML = "";
    for (const z of this.zones) {
      const opt = document.createElement("option");
      opt.value = z.id;
      opt.textContent = `${z.code} - ${z.name_th}`;
      selectEl.appendChild(opt);
    }
  }

  async _loadSnapshotAndSetupStage() {
    // ใช้ความกว้างจริงของ container (ไม่ใช่ window.innerWidth) ไม่งั้น CSS จะย่อ canvas
    // ให้เล็กกว่าที่ Konva คิดไว้ ทำให้พิกัดคลิกกับพิกัดภายใน Konva ไม่ตรงกัน
    const wrapEl = document.querySelector(".editor-canvas-wrap");
    const maxWidth = Math.min(900, wrapEl.clientWidth - 2);
    const snapshotUrl = `/api/admin/cameras/${this.cameraId}/snapshot?t=${Date.now()}`;

    const img = new Image();
    const loaded = await new Promise((resolve) => {
      img.onload = () => resolve(true);
      img.onerror = () => resolve(false);
      img.src = snapshotUrl;
    });

    if (loaded) {
      document.getElementById("no-snapshot-msg").style.display = "none";
      const scale = Math.min(1, maxWidth / img.naturalWidth);
      this.imgWidth = Math.round(img.naturalWidth * scale);
      this.imgHeight = Math.round(img.naturalHeight * scale);
    } else {
      document.getElementById("no-snapshot-msg").style.display = "block";
      this.imgWidth = maxWidth;
      this.imgHeight = Math.round(maxWidth * 0.5625);
    }

    document.getElementById("stage-container").innerHTML = "";
    this.stage = new Konva.Stage({
      container: "stage-container",
      width: this.imgWidth,
      height: this.imgHeight,
    });

    const bgLayer = new Konva.Layer();
    if (loaded) {
      bgLayer.add(new Konva.Image({ image: img, width: this.imgWidth, height: this.imgHeight }));
    }
    this.stage.add(bgLayer);

    // ชั้นกรอบที่ AI เห็น (อยู่ใต้ช่องจอด และไม่รับคลิก จะได้ไม่บังการวาด/เลือกช่อง)
    this.detLayer = new Konva.Layer({ listening: false });
    this.stage.add(this.detLayer);

    this.layer = new Konva.Layer();
    this.stage.add(this.layer);

    this.stage.on("click tap", (e) => this._onStageClick(e));
  }

  async _loadSlots() {
    const data = await apiJson(`/api/admin/cameras/${this.cameraId}/slots`);
    this.slots = data.map((s) => this._toSlotState(s));
    this.selected = null;
    this._renderAll();
  }

  _toSlotState(apiSlot) {
    return {
      id: apiSlot.id,
      code: apiSlot.code,
      zone_id: apiSlot.zone_id,
      type: apiSlot.type,
      polygon: apiSlot.polygon.map((p) => [...p]),
      threshold: apiSlot.threshold,
      is_active: apiSlot.is_active,
      group: null,
      previewState: null,
    };
  }

  // ---------- วาดช่องใหม่ ----------

  _onStageClick(e) {
    if (!this.drawMode) return;
    const pos = this.stage.getPointerPosition();
    this.drawPoints.push([pos.x / this.imgWidth, pos.y / this.imgHeight]);
    if (this.drawPoints.length === 4) {
      this._finishDrawing(this.drawPoints);
      this.drawPoints = [];
    }
  }

  toggleDrawMode() {
    this.drawMode = !this.drawMode;
    this.drawPoints = [];
    document.getElementById("btn-draw").textContent = this.drawMode
      ? "กำลังวาด... (คลิก 4 จุด, กดอีกทีเพื่อหยุด)"
      : "+ วาดช่องใหม่";
    this.stage.container().style.cursor = this.drawMode ? "crosshair" : "default";
  }

  _finishDrawing(points) {
    const zoneId = Number(document.getElementById("default-zone").value);
    const type = document.getElementById("default-type").value;
    const prefix = document.getElementById("code-prefix").value || "A-";

    const slot = {
      id: null,
      code: this._nextCode(prefix),
      zone_id: zoneId,
      type,
      polygon: points,
      threshold: 0.3,
      is_active: true,
      group: null,
      previewState: null,
    };
    this.slots.push(slot);
    this.select(slot);
    this._markUnpublished();
  }

  _nextCode(prefix) {
    let max = 0;
    for (const s of this.slots) {
      if (s.code.startsWith(prefix)) {
        const n = parseInt(s.code.slice(prefix.length), 10);
        if (!isNaN(n) && n > max) max = n;
      }
    }
    return prefix + String(max + 1).padStart(2, "0");
  }

  // ---------- render ----------

  _renderAll() {
    this.layer.destroyChildren();
    for (const slot of this.slots) this._renderSlot(slot);
    this.layer.draw();
    this._renderSlotList();
    document.getElementById("slot-count").textContent = this.slots.length;
  }

  _renderSlot(slot) {
    const group = new Konva.Group();
    const isSelected = this.selected === slot;

    let stroke = DEFAULT_STROKE;
    if (slot.previewState) stroke = STATE_COLORS[slot.previewState] || DEFAULT_STROKE;
    if (isSelected) stroke = SELECTED_STROKE;

    const points = slot.polygon.flatMap(([x, y]) => [x * this.imgWidth, y * this.imgHeight]);
    const line = new Konva.Line({
      points,
      closed: true,
      stroke,
      strokeWidth: isSelected ? 3 : 2,
      fill: stroke,
      opacity: slot.previewState ? 0.35 : 0.15,
    });
    group.add(line);

    const centroid = this._centroid(slot.polygon);
    const label = new Konva.Text({
      x: centroid[0] * this.imgWidth - 15,
      y: centroid[1] * this.imgHeight - 7,
      text: slot.previewScore != null ? `${slot.code} · ${slot.previewScore.toFixed(2)}` : slot.code,
      shadowColor: "#000",
      shadowBlur: 3,
      shadowOpacity: 0.9,
      fontSize: 13,
      fill: "#fff",
      fontStyle: "bold",
      listening: false, // ไม่ให้ป้ายชื่อบังคลิกที่เส้นขอบด้านล่าง
    });
    group.add(label);

    line.on("click tap", (evt) => {
      if (this.drawMode) return;
      evt.cancelBubble = true;
      this.select(slot);
    });

    if (isSelected && !this.drawMode) {
      slot.polygon.forEach((pt, idx) => {
        const handle = new Konva.Circle({
          x: pt[0] * this.imgWidth,
          y: pt[1] * this.imgHeight,
          radius: 6,
          fill: "#fff",
          stroke: SELECTED_STROKE,
          strokeWidth: 2,
          draggable: true,
        });
        handle.on("dragmove", () => {
          slot.polygon[idx] = [handle.x() / this.imgWidth, handle.y() / this.imgHeight];
          line.points(slot.polygon.flatMap(([x, y]) => [x * this.imgWidth, y * this.imgHeight]));
          const c = this._centroid(slot.polygon);
          label.x(c[0] * this.imgWidth - 15);
          label.y(c[1] * this.imgHeight - 7);
          this.layer.batchDraw();
        });
        group.add(handle);
      });
    }

    slot.group = group;
    this.layer.add(group);
  }

  _centroid(polygon) {
    const n = polygon.length;
    const sx = polygon.reduce((a, p) => a + p[0], 0);
    const sy = polygon.reduce((a, p) => a + p[1], 0);
    return [sx / n, sy / n];
  }

  _renderSlotList() {
    const ul = document.getElementById("slot-list");
    ul.innerHTML = "";
    for (const slot of this.slots) {
      const li = document.createElement("li");
      if (slot === this.selected) li.classList.add("selected");
      const zone = this.zones.find((z) => z.id === slot.zone_id);
      let badge = "";
      if (slot.previewState) {
        const scoreText = slot.previewScore != null
          ? `<span class="muted" style="font-size:0.8rem;" title="คะแนน / Threshold">${slot.previewScore.toFixed(2)} / ${slot.threshold}</span> `
          : "";
        badge = `<span>${scoreText}<span class="badge badge-${slot.previewState}">${slot.previewState}</span></span>`;
      }
      li.innerHTML = `<span>${slot.code} <span class="muted">(${zone ? zone.code : "?"}, ${TYPE_LABELS[slot.type] || slot.type})</span></span>${badge}`;
      li.style.cursor = "pointer";
      li.addEventListener("click", () => this.select(slot));
      ul.appendChild(li);
    }
  }

  // ---------- เลือก/แก้ไขช่อง ----------

  select(slot) {
    this.selected = slot;
    this._renderAll();
    document.getElementById("delete-confirm").style.display = "none";
    const card = document.getElementById("selected-slot-card");
    if (!slot) {
      card.style.display = "none";
      return;
    }
    card.style.display = "block";
    document.getElementById("sel-code").value = slot.code;
    document.getElementById("sel-zone").value = slot.zone_id;
    document.getElementById("sel-type").value = slot.type;
    document.getElementById("sel-threshold").value = slot.threshold;
  }

  applySelectedEdits() {
    if (!this.selected) return;
    this.selected.code = document.getElementById("sel-code").value;
    this.selected.zone_id = Number(document.getElementById("sel-zone").value);
    this.selected.type = document.getElementById("sel-type").value;
    this.selected.threshold = Number(document.getElementById("sel-threshold").value);
    this._renderAll();
  }

  async saveSelectedEdits() {
    if (!this.selected) return;
    const threshold = Number(document.getElementById("sel-threshold").value);
    if (isNaN(threshold) || threshold < 0.1 || threshold > 0.9) {
      this._setStatus("Threshold ต้องอยู่ระหว่าง 0.1-0.9", true);
      return;
    }
    this.applySelectedEdits();
    await this.saveDraft();
    this._setStatus("บันทึกแล้ว");
  }

  requestDeleteSelected() {
    if (!this.selected) return;
    document.getElementById("delete-confirm-text").textContent = `ต้องการลบช่อง ${this.selected.code} ใช่ไหม`;
    document.getElementById("delete-confirm").style.display = "block";
  }

  cancelDeleteSelected() {
    document.getElementById("delete-confirm").style.display = "none";
  }

  deleteSelected() {
    if (!this.selected) return;
    this.slots = this.slots.filter((s) => s !== this.selected);
    this.selected = null;
    document.getElementById("delete-confirm").style.display = "none";
    document.getElementById("selected-slot-card").style.display = "none";
    this._renderAll();
    this._markUnpublished();
  }

  requestClearAll() {
    document.getElementById("clear-all-text").textContent =
      `ต้องการลบช่องทั้งหมด ${this.slots.length} ช่องของกล้องนี้ใช่ไหม (ใช้เมื่อย้ายกล้องแล้วจะวาดใหม่ทั้งหมด)`;
    document.getElementById("clear-all-confirm").style.display = "block";
  }

  cancelClearAll() {
    document.getElementById("clear-all-confirm").style.display = "none";
  }

  async clearAll() {
    document.getElementById("clear-all-confirm").style.display = "none";
    const removed = this.slots.length;
    this.slots = [];
    this.selected = null;
    document.getElementById("selected-slot-card").style.display = "none";
    this._renderAll();
    if (await this.saveDraft()) {
      this._setStatus(`ลบช่องเดิมแล้ว ${removed} ช่อง · กด "ดึงภาพล่าสุด" แล้ววาดช่องใหม่ เสร็จแล้วกด Publish`);
    }
  }

  copySelected() {
    if (!this.selected) return;
    const prefix = document.getElementById("code-prefix").value || "A-";
    const offset = 0.03;
    const copy = {
      id: null,
      code: this._nextCode(prefix),
      zone_id: this.selected.zone_id,
      type: this.selected.type,
      polygon: this.selected.polygon.map(([x, y]) => [x + offset, y + offset]),
      threshold: this.selected.threshold,
      is_active: true,
      group: null,
      previewState: null,
    };
    this.slots.push(copy);
    this.select(copy);
    this._markUnpublished();
  }

  repeatSelected(count, direction) {
    if (!this.selected) return;
    const prefix = document.getElementById("code-prefix").value || "A-";
    const xs = this.selected.polygon.map((p) => p[0]);
    const ys = this.selected.polygon.map((p) => p[1]);
    const width = Math.max(...xs) - Math.min(...xs);
    const height = Math.max(...ys) - Math.min(...ys);
    const dx = direction === "right" ? width : 0;
    const dy = direction === "down" ? height : 0;

    const base = this.selected;
    for (let i = 1; i <= count; i++) {
      this.slots.push({
        id: null,
        code: this._nextCode(prefix),
        zone_id: base.zone_id,
        type: base.type,
        polygon: base.polygon.map(([x, y]) => [x + dx * i, y + dy * i]),
        threshold: base.threshold,
        is_active: true,
        group: null,
        previewState: null,
      });
    }
    this._renderAll();
    this._markUnpublished();
  }

  // ---------- save / preview / publish ----------

  async saveDraft() {
    this._setStatus("กำลังบันทึก...");
    const payload = {
      slots: this.slots.map((s) => ({
        id: s.id,
        code: s.code,
        zone_id: s.zone_id,
        type: s.type,
        polygon: s.polygon,
        threshold: s.threshold,
        is_active: s.is_active,
      })),
    };
    try {
      const saved = await apiJson(`/api/admin/cameras/${this.cameraId}/slots`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      this.slots = saved.map((s) => this._toSlotState(s));
      this.selected = null;
      document.getElementById("selected-slot-card").style.display = "none";
      this._renderAll();
      this._setStatus(`บันทึก draft สำเร็จ (${saved.length} ช่อง)`);
      this._markUnpublished();
      return true;
    } catch (e) {
      this._setStatus("บันทึกไม่สำเร็จ: " + e.message, true);
      return false;
    }
  }

  async preview() {
    this._setStatus("กำลังตรวจจับ...");
    const payload = { slots: this.slots.map((s) => ({ code: s.code, polygon: s.polygon, threshold: s.threshold })) };
    try {
      const result = await apiJson(`/api/admin/cameras/${this.cameraId}/slots/preview`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const byCode = {};
      for (const r of result.results) byCode[r.code] = r;
      for (const slot of this.slots) {
        const r = byCode[slot.code];
        slot.previewState = r ? r.state : null;
        slot.previewScore = r ? r.score : null;
      }
      this.previewDetections = result.detections || [];
      this.previewRoi = result.roi || null;

      await this._refreshBackgroundImage();
      this._renderAll();
      this._renderDetections();
      this._renderPreviewSummary(result.detected_vehicle_count);
      this._setStatus("preview สำเร็จ");
    } catch (e) {
      this._setStatus("preview ไม่สำเร็จ: " + e.message, true);
    }
  }

  _renderPreviewSummary(total) {
    const large = this.previewDetections.filter((d) => d.kind === "large").length;
    const vehicles = this.previewDetections.length - large;
    let text = `ตรวจพบรถ ${total} คัน`;
    if (this.previewDetections.length) {
      text += ` (AI ทายว่าเป็นรถ ${vehicles}`;
      if (large) text += ` · วัตถุขนาดใหญ่ที่นับเป็นรถ ${large}`;
      text += ")";
    }
    if (this.previewRoi) text += " · ตรวจเฉพาะในกรอบ ROI";
    document.getElementById("preview-summary").textContent = text;
    document.getElementById("preview-legend").style.display =
      this.previewDetections.length || this.previewRoi ? "" : "none";
  }

  _clearPreview() {
    this.previewDetections = [];
    this.previewRoi = null;
    for (const slot of this.slots) {
      slot.previewState = null;
      slot.previewScore = null;
    }
    if (this.detLayer) this.detLayer.destroyChildren();
    document.getElementById("preview-summary").textContent = "";
    document.getElementById("preview-legend").style.display = "none";
  }

  // วาดกรอบที่ระบบนับเป็นรถ + แถบส่วนที่ใช้คำนวณคะแนนจริง (ครึ่งล่างของกรอบ)
  _renderDetections() {
    if (!this.detLayer) return;
    this.detLayer.destroyChildren();
    if (this.showDetections) {
      const w = this.imgWidth;
      const h = this.imgHeight;
      if (this.previewRoi) {
        const [rx1, ry1, rx2, ry2] = this.previewRoi;
        this.detLayer.add(new Konva.Rect({
          x: rx1 * w, y: ry1 * h, width: (rx2 - rx1) * w, height: (ry2 - ry1) * h,
          stroke: ROI_COLOR, strokeWidth: 2, dash: [10, 6],
        }));
        const roiTag = new Konva.Label({ x: rx1 * w + 2, y: ry1 * h + 2 });
        roiTag.add(new Konva.Tag({ fill: ROI_COLOR, opacity: 0.9 }));
        roiTag.add(new Konva.Text({ text: "ROI (AI ตรวจเฉพาะในกรอบนี้)", fontSize: 12, padding: 3, fill: "#fff" }));
        this.detLayer.add(roiTag);
      }
      for (const d of this.previewDetections) {
        const color = DETECTION_COLORS[d.kind] || DETECTION_COLORS.vehicle;
        const [x1, y1, x2, y2] = d.box;
        const [fx1, fy1, fx2, fy2] = d.footprint;
        this.detLayer.add(new Konva.Rect({
          x: fx1 * w, y: fy1 * h, width: (fx2 - fx1) * w, height: (fy2 - fy1) * h,
          fill: color, opacity: 0.18,
        }));
        this.detLayer.add(new Konva.Rect({
          x: x1 * w, y: y1 * h, width: (x2 - x1) * w, height: (y2 - y1) * h,
          stroke: color, strokeWidth: 2, dash: d.kind === "large" ? [8, 5] : undefined,
        }));
        const tag = new Konva.Label({ x: x1 * w, y: Math.max(0, y1 * h) });
        tag.add(new Konva.Tag({ fill: color, opacity: 0.9 }));
        const name = d.kind === "large" ? `${d.class_name}→รถ` : d.class_name;
        tag.add(new Konva.Text({ text: `${name} ${d.score.toFixed(2)}`, fontSize: 12, padding: 3, fill: "#111" }));
        this.detLayer.add(tag);
      }
    }
    this.detLayer.draw();
  }

  async _refreshBackgroundImage() {
    const bgLayer = this.stage.getLayers()[0];
    const img = new Image();
    await new Promise((resolve) => {
      img.onload = resolve;
      img.onerror = resolve;
      img.src = `/api/admin/cameras/${this.cameraId}/snapshot?t=${Date.now()}`;
    });
    bgLayer.destroyChildren();
    bgLayer.add(new Konva.Image({ image: img, width: this.imgWidth, height: this.imgHeight }));
    bgLayer.draw();
  }

  async publish() {
    if (!confirm("ยืนยัน publish layout นี้? ช่องทั้งหมดของกล้องนี้จะถูกใช้งานจริงทันที")) return;
    // บันทึกสิ่งที่แก้ในหน้าจอก่อนเสมอ (รวมช่องที่ลบ) ไม่งั้น publish จะใช้ชุดเก่าในฐานข้อมูล
    if (!(await this.saveDraft())) return;
    this._setStatus("กำลัง publish...");
    try {
      const result = await apiJson(`/api/admin/cameras/${this.cameraId}/slots/publish`, { method: "POST" });
      this._setStatus(`Publish สำเร็จ (${result.published_count} ช่อง)`);
      this._clearUnpublished();
      await this._loadSlots();
    } catch (e) {
      this._setStatus("publish ไม่สำเร็จ: " + e.message, true);
    }
  }

  _markUnpublished() {
    document.getElementById("unpublished-banner").style.display = "block";
  }

  _clearUnpublished() {
    document.getElementById("unpublished-banner").style.display = "none";
  }

  async fetchFreshSnapshot() {
    this._setStatus("กำลังดึงภาพจากกล้อง...");
    try {
      await apiJson(`/api/admin/cameras/${this.cameraId}/test`, { method: "POST" });
      await this._loadSnapshotAndSetupStage();
      this._clearPreview();  // ภาพเปลี่ยนแล้ว ผล Preview เดิมไม่ตรงกับภาพใหม่
      this._renderAll();
      this._setStatus("ดึงภาพสำเร็จ");
    } catch (e) {
      this._setStatus("ดึงภาพไม่สำเร็จ: " + e.message, true);
    }
  }

  _setStatus(text, isError = false) {
    const el = document.getElementById("status-text");
    el.textContent = text;
    el.style.color = isError ? "var(--color-danger)" : "var(--color-muted)";
  }

  _wireButtons() {
    document.getElementById("btn-draw").addEventListener("click", () => this.toggleDrawMode());
    document.getElementById("btn-save").addEventListener("click", () => this.saveDraft());
    document.getElementById("btn-preview").addEventListener("click", () => this.preview());
    document.getElementById("btn-publish").addEventListener("click", () => this.publish());
    document.getElementById("btn-fetch-snapshot").addEventListener("click", () => this.fetchFreshSnapshot());
    document.getElementById("btn-save-selected").addEventListener("click", () => this.saveSelectedEdits());
    document.getElementById("btn-delete").addEventListener("click", () => this.requestDeleteSelected());
    document.getElementById("btn-delete-confirm").addEventListener("click", () => this.deleteSelected());
    document.getElementById("btn-delete-cancel").addEventListener("click", () => this.cancelDeleteSelected());
    document.getElementById("btn-copy").addEventListener("click", () => this.copySelected());
    document.getElementById("btn-clear-all").addEventListener("click", () => this.requestClearAll());
    document.getElementById("btn-clear-all-confirm").addEventListener("click", () => this.clearAll());
    document.getElementById("btn-clear-all-cancel").addEventListener("click", () => this.cancelClearAll());
    document.getElementById("show-detections").addEventListener("change", (e) => {
      this.showDetections = e.target.checked;
      this._renderDetections();
    });
    document.getElementById("btn-repeat").addEventListener("click", () => {
      const count = Number(document.getElementById("repeat-count").value) || 1;
      const direction = document.getElementById("repeat-direction").value;
      this.repeatSelected(count, direction);
    });
    for (const id of ["sel-code", "sel-zone", "sel-type", "sel-threshold"]) {
      document.getElementById(id).addEventListener("change", () => this.applySelectedEdits());
    }
    for (const id of ["sel-code", "sel-threshold"]) {
      document.getElementById(id).addEventListener("input", () => this.applySelectedEdits());
    }
  }
}

(async function bootstrap() {
  const params = new URLSearchParams(window.location.search);
  const cameraId = params.get("camera_id");

  const user = await requireAuth();
  if (!user) return;

  if (!cameraId) {
    document.getElementById("no-camera").style.display = "block";
    return;
  }

  document.getElementById("editor-root").style.display = "block";
  const editor = new LayoutEditor(Number(cameraId));
  await editor.init();
})();
