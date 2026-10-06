// หน้ากึ่งออโต้: สร้าง job สังเกตรถจอดจริง, ดู proposal, แก้มุม/อนุมัติ/ปฏิเสธ (FR-28, FR-29)

const PROPOSAL_STATUS_COLORS = { pending: "#f59e0b", accepted: "#16a34a", rejected: "#dc2626" };
const SELECTED_STROKE = "#2563eb";

class CalibrationPage {
  constructor() {
    this.cameras = [];
    this.zones = [];
    this.jobs = [];
    this.selectedJob = null;
    this.proposals = [];
    this.selectedProposal = null;
    this.stage = null;
    this.layer = null;
    this.imgWidth = 0;
    this.imgHeight = 0;
  }

  async init() {
    const user = await requireAuth();
    if (!user) return;
    if (user.role !== "admin") {
      document.querySelector(".page").innerHTML =
        '<div class="card"><p>หน้านี้ (กึ่งออโต้) สำหรับ Admin เท่านั้น</p></div>';
      return;
    }
    this.cameras = await apiJson("/api/admin/cameras");
    this.zones = await apiJson("/api/admin/zones");
    this._fillSelect("camera-select", this.cameras, (c) => c.id, (c) => c.name);
    this._fillSelect("lines-camera-select", this.cameras, (c) => c.id, (c) => c.name);
    this._fillSelect("bulk-zone-select", this.zones, (z) => z.id, (z) => `${z.code} ${z.name_th}`);
    this._fillSelect("prop-zone", this.zones, (z) => z.id, (z) => `${z.code} ${z.name_th}`);
    await this.loadJobs();
    this._wireButtons();
  }

  _fillSelect(elementId, items, valueFn, labelFn) {
    const select = document.getElementById(elementId);
    select.innerHTML = items.map((item) => `<option value="${valueFn(item)}">${labelFn(item)}</option>`).join("");
  }

  async loadJobs() {
    this.jobs = await apiJson("/api/admin/calib/jobs");
    const ul = document.getElementById("job-list");
    ul.innerHTML = "";
    for (const job of this.jobs) {
      const camera = this.cameras.find((c) => c.id === job.camera_id);
      const li = document.createElement("li");
      li.style.cursor = "pointer";
      if (this.selectedJob && this.selectedJob.id === job.id) li.classList.add("selected");
      const pct = Math.round((job.progress || 0) * 100);
      li.innerHTML = `<span>Job #${job.id}<br><span class="muted">${camera ? camera.name : "?"} · ${job.status} · ${pct}% · proposal ${job.proposal_count}</span></span>`;
      li.addEventListener("click", () => this.selectJob(job.id));
      ul.appendChild(li);
    }
  }

  async startJob() {
    const cameraId = Number(document.getElementById("camera-select").value);
    const durationHours = Number(document.getElementById("duration-hours").value) || 48;
    const intervalMinutes = Number(document.getElementById("interval-minutes").value) || 5;
    const hourStart = Number(document.getElementById("hour-start").value) || 0;
    const hourEnd = Number(document.getElementById("hour-end").value) || 24;
    const btn = document.getElementById("btn-start-job");
    const statusEl = document.getElementById("start-status");

    btn.disabled = true;
    statusEl.textContent = "กำลังสร้าง job...";
    try {
      const job = await apiJson("/api/admin/calib/jobs", {
        method: "POST",
        body: JSON.stringify({
          camera_id: cameraId,
          duration_hours: durationHours,
          interval_minutes: intervalMinutes,
          hour_start: hourStart,
          hour_end: hourEnd,
        }),
      });
      statusEl.textContent = `สร้าง job #${job.id} สำเร็จ กำลังเก็บข้อมูลเบื้องหลัง (ใช้เวลาตามระยะเวลาที่ตั้งไว้)`;
      await this.loadJobs();
      await this.selectJob(job.id);
    } catch (e) {
      statusEl.textContent = "ผิดพลาด: " + e.message;
    } finally {
      btn.disabled = false;
    }
  }

  toggleMethodForm() {
    const isLines = document.getElementById("method-lines").checked;
    document.getElementById("observation-form").style.display = isLines ? "none" : "block";
    document.getElementById("lines-form").style.display = isLines ? "block" : "none";
  }

  async previewLines() {
    const cameraId = Number(document.getElementById("lines-camera-select").value);
    const params = this._readLinesParams();
    const statusEl = document.getElementById("lines-status");
    statusEl.textContent = "กำลังดึงภาพ+ประมวลผล...";
    try {
      const result = await apiJson("/api/admin/calib/lines/preview", {
        method: "POST",
        body: JSON.stringify({ camera_id: cameraId, ...params }),
      });
      statusEl.textContent = `พบกรอบที่เป็นไปได้ ${result.polygons.length} กรอบ (ปรับพารามิเตอร์แล้วกด Preview ซ้ำได้)`;
      await this._renderLinesPreview(result.snapshot_url, result.polygons);
    } catch (e) {
      statusEl.textContent = "ผิดพลาด: " + e.message;
    }
  }

  async _renderLinesPreview(snapshotUrl, polygons) {
    const container = document.getElementById("lines-preview-container");
    const wrapEl = document.querySelector(".card");
    const maxWidth = Math.min(900, wrapEl.clientWidth - 2);
    const img = new Image();
    const loaded = await new Promise((resolve) => {
      img.onload = () => resolve(true);
      img.onerror = () => resolve(false);
      img.src = snapshotUrl + `?t=${Date.now()}`;
    });
    if (!loaded) {
      container.innerHTML = '<p class="muted">โหลดภาพไม่สำเร็จ</p>';
      return;
    }
    const scale = Math.min(1, maxWidth / img.naturalWidth);
    const w = Math.round(img.naturalWidth * scale);
    const h = Math.round(img.naturalHeight * scale);

    container.innerHTML = "";
    const stage = new Konva.Stage({ container: "lines-preview-container", width: w, height: h });
    const bgLayer = new Konva.Layer();
    bgLayer.add(new Konva.Image({ image: img, width: w, height: h }));
    stage.add(bgLayer);
    const overlay = new Konva.Layer();
    stage.add(overlay);
    for (const polygon of polygons) {
      overlay.add(
        new Konva.Line({
          points: polygon.flatMap(([x, y]) => [x * w, y * h]),
          closed: true,
          stroke: "#f59e0b",
          strokeWidth: 2,
          fill: "#f59e0b",
          opacity: 0.3,
          listening: false,
        })
      );
    }
    overlay.draw();
  }

  _readLinesParams() {
    return {
      slot_width_min: Number(document.getElementById("slot-width-min").value) || 50,
      slot_width_max: Number(document.getElementById("slot-width-max").value) || 150,
      min_line_length: Number(document.getElementById("min-line-length").value) || 40,
      hough_threshold: Number(document.getElementById("hough-threshold").value) || 40,
    };
  }

  async createLinesJob() {
    const cameraId = Number(document.getElementById("lines-camera-select").value);
    const params = this._readLinesParams();
    const statusEl = document.getElementById("lines-status");
    const btn = document.getElementById("btn-create-lines-job");
    btn.disabled = true;
    statusEl.textContent = "กำลังสร้าง proposals...";
    try {
      const job = await apiJson("/api/admin/calib/jobs", {
        method: "POST",
        body: JSON.stringify({ camera_id: cameraId, method: "lines", ...params }),
      });
      statusEl.textContent = `สร้าง job #${job.id} สำเร็จ (${job.proposal_count} proposal) ดูและอนุมัติได้ในรายการ job ด้านซ้าย`;
      await this.loadJobs();
      await this.selectJob(job.id);
    } catch (e) {
      statusEl.textContent = "ผิดพลาด: " + e.message;
    } finally {
      btn.disabled = false;
    }
  }

  async cancelJob() {
    if (!this.selectedJob) return;
    if (!confirm(`ยกเลิก job #${this.selectedJob.id}?`)) return;
    try {
      await apiJson(`/api/admin/calib/jobs/${this.selectedJob.id}/cancel`, { method: "POST" });
      await this.loadJobs();
      await this.selectJob(this.selectedJob.id);
    } catch (e) {
      alert("ยกเลิกไม่สำเร็จ: " + e.message);
    }
  }

  async selectJob(jobId) {
    this.selectedJob = await apiJson(`/api/admin/calib/jobs/${jobId}`);
    this.selectedProposal = null;
    document.getElementById("no-job-msg").style.display = "none";
    document.getElementById("job-detail").style.display = "block";
    document.getElementById("proposal-card").style.display = "none";
    document.getElementById("job-status-text").textContent =
      `${this.selectedJob.status} (${Math.round(this.selectedJob.progress * 100)}%)`;
    document.getElementById("btn-cancel-job").style.display =
      this.selectedJob.status === "running" ? "inline-block" : "none";

    this.proposals = await apiJson(`/api/admin/calib/jobs/${jobId}/proposals`);
    await this._renderStage();
    await this.loadJobs();
  }

  async _renderStage() {
    const noBg = document.getElementById("no-background-msg");
    const noProposals = document.getElementById("no-proposals-msg");
    noProposals.style.display = this.proposals.length === 0 ? "block" : "none";

    if (!this.selectedJob.background_image_url) {
      noBg.style.display = "block";
      document.getElementById("stage-container").innerHTML = "";
      this.stage = null;
      return;
    }
    noBg.style.display = "none";

    const wrapEl = document.querySelector(".editor-canvas-wrap");
    const maxWidth = Math.min(900, wrapEl.clientWidth - 2);
    const img = new Image();
    const loaded = await new Promise((resolve) => {
      img.onload = () => resolve(true);
      img.onerror = () => resolve(false);
      img.src = this.selectedJob.background_image_url + `?t=${Date.now()}`;
    });
    if (!loaded) {
      noBg.style.display = "block";
      return;
    }
    const scale = Math.min(1, maxWidth / img.naturalWidth);
    this.imgWidth = Math.round(img.naturalWidth * scale);
    this.imgHeight = Math.round(img.naturalHeight * scale);

    document.getElementById("stage-container").innerHTML = "";
    this.stage = new Konva.Stage({ container: "stage-container", width: this.imgWidth, height: this.imgHeight });
    const bgLayer = new Konva.Layer();
    bgLayer.add(new Konva.Image({ image: img, width: this.imgWidth, height: this.imgHeight }));
    this.stage.add(bgLayer);
    this.layer = new Konva.Layer();
    this.stage.add(this.layer);

    this._renderProposals();
  }

  _renderProposals() {
    this.layer.destroyChildren();
    for (const proposal of this.proposals) {
      const isSelected = this.selectedProposal && this.selectedProposal.id === proposal.id;
      const baseColor = PROPOSAL_STATUS_COLORS[proposal.status] || PROPOSAL_STATUS_COLORS.pending;
      const points = proposal.polygon.flatMap(([x, y]) => [x * this.imgWidth, y * this.imgHeight]);
      const line = new Konva.Line({
        points,
        closed: true,
        stroke: isSelected ? SELECTED_STROKE : baseColor,
        strokeWidth: isSelected ? 3 : 2,
        fill: baseColor,
        opacity: 0.3,
      });
      line.on("click tap", (evt) => {
        evt.cancelBubble = true;
        this._selectProposal(proposal);
      });
      this.layer.add(line);

      const centroid = proposal.polygon
        .reduce((acc, [x, y]) => [acc[0] + x, acc[1] + y], [0, 0])
        .map((v) => v / proposal.polygon.length);
      this.layer.add(
        new Konva.Text({
          x: centroid[0] * this.imgWidth - 25,
          y: centroid[1] * this.imgHeight - 7,
          text: `${Math.round(proposal.confidence * 100)}%`,
          fontSize: 12,
          fill: "#fff",
          fontStyle: "bold",
          listening: false,
        })
      );

      if (isSelected && proposal.status === "pending") {
        proposal.polygon.forEach((pt, idx) => {
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
            proposal.polygon[idx] = [handle.x() / this.imgWidth, handle.y() / this.imgHeight];
            line.points(proposal.polygon.flatMap(([x, y]) => [x * this.imgWidth, y * this.imgHeight]));
            this.layer.batchDraw();
          });
          this.layer.add(handle);
        });
      }
    }
    this.layer.draw();
  }

  _selectProposal(proposal) {
    this.selectedProposal = proposal;
    document.getElementById("proposal-card").style.display = "block";
    document.getElementById("prop-confidence").textContent = `${Math.round(proposal.confidence * 100)}%`;
    document.getElementById("prop-status").textContent = proposal.status;
    const decided = proposal.status !== "pending";
    document.getElementById("prop-decide-form").style.display = decided ? "none" : "block";
    document.getElementById("prop-decided-note").style.display = decided ? "block" : "none";
    this._renderProposals();
  }

  async saveCorners() {
    if (!this.selectedProposal) return;
    try {
      const updated = await apiJson(`/api/admin/calib/proposals/${this.selectedProposal.id}`, {
        method: "PATCH",
        body: JSON.stringify({ polygon: this.selectedProposal.polygon }),
      });
      Object.assign(this.selectedProposal, updated);
      alert("บันทึกมุมที่แก้แล้ว");
    } catch (e) {
      alert("บันทึกไม่สำเร็จ: " + e.message);
    }
  }

  async acceptSelectedProposal() {
    if (!this.selectedProposal) return;
    const code = document.getElementById("prop-code").value.trim();
    if (!code) {
      alert("กรุณากรอกรหัสช่อง");
      return;
    }
    const zoneId = Number(document.getElementById("prop-zone").value);
    const type = document.getElementById("prop-type").value;
    const threshold = Number(document.getElementById("prop-threshold").value) || 0.3;
    try {
      const updated = await apiJson(`/api/admin/calib/proposals/${this.selectedProposal.id}/accept`, {
        method: "POST",
        body: JSON.stringify({ code, zone_id: zoneId, type, threshold }),
      });
      Object.assign(this.selectedProposal, updated);
      this._selectProposal(this.selectedProposal);
      await this.loadJobs();
    } catch (e) {
      alert("Accept ไม่สำเร็จ: " + e.message);
    }
  }

  async rejectSelectedProposal() {
    if (!this.selectedProposal) return;
    try {
      const updated = await apiJson(`/api/admin/calib/proposals/${this.selectedProposal.id}/reject`, {
        method: "POST",
      });
      Object.assign(this.selectedProposal, updated);
      this._selectProposal(this.selectedProposal);
      await this.loadJobs();
    } catch (e) {
      alert("Reject ไม่สำเร็จ: " + e.message);
    }
  }

  async bulkAccept() {
    const minConfidence = Number(document.getElementById("bulk-min-confidence").value) || 0;
    const zoneId = Number(document.getElementById("bulk-zone-select").value);
    const prefix = document.getElementById("bulk-code-prefix").value.trim() || "AUTO-";
    const targets = this.proposals.filter((p) => p.status === "pending" && p.confidence >= minConfidence);
    if (targets.length === 0) {
      alert("ไม่มี proposal ที่ตรงเงื่อนไข");
      return;
    }
    if (!confirm(`Accept ทั้งหมด ${targets.length} proposal เข้าโซนที่เลือก?`)) return;

    let seq = 1;
    for (const proposal of targets) {
      const code = `${prefix}${String(seq).padStart(2, "0")}`;
      seq += 1;
      try {
        await apiJson(`/api/admin/calib/proposals/${proposal.id}/accept`, {
          method: "POST",
          body: JSON.stringify({ code, zone_id: zoneId }),
        });
      } catch (e) {
        alert(`Accept proposal #${proposal.id} ไม่สำเร็จ: ${e.message} (หยุดที่ตัวนี้)`);
        break;
      }
    }
    await this.selectJob(this.selectedJob.id);
  }

  _wireButtons() {
    document.getElementById("method-observation").addEventListener("change", () => this.toggleMethodForm());
    document.getElementById("method-lines").addEventListener("change", () => this.toggleMethodForm());
    document.getElementById("btn-preview-lines").addEventListener("click", () => this.previewLines());
    document.getElementById("btn-create-lines-job").addEventListener("click", () => this.createLinesJob());
    document.getElementById("btn-start-job").addEventListener("click", () => this.startJob());
    document.getElementById("btn-cancel-job").addEventListener("click", () => this.cancelJob());
    document.getElementById("btn-save-corners").addEventListener("click", () => this.saveCorners());
    document.getElementById("btn-accept-proposal").addEventListener("click", () => this.acceptSelectedProposal());
    document.getElementById("btn-reject-proposal").addEventListener("click", () => this.rejectSelectedProposal());
    document.getElementById("btn-bulk-accept").addEventListener("click", () => this.bulkAccept());
  }
}

(async function bootstrap() {
  const page = new CalibrationPage();
  await page.init();
})();
