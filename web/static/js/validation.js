// Validation tool: เริ่ม job, ดูภาพทีละใบ, ยืนยันสถานะจริง, ดู % ความแม่นยำ (NFR-4)

const VALIDATION_STATE_COLORS = { free: "#16a34a", occupied: "#dc2626", unknown: "#64748b" };

class ValidationPage {
  constructor() {
    this.cameras = [];
    this.jobs = [];
    this.selectedJob = null;
    this.sampleIndex = 0;
    this.selectedSlotId = null;
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
        '<div class="card"><p>หน้านี้ (Validation tool) สำหรับ Admin เท่านั้น</p></div>';
      return;
    }
    this.cameras = await apiJson("/api/admin/cameras");
    const select = document.getElementById("camera-select");
    select.innerHTML = this.cameras.map((c) => `<option value="${c.id}">${c.name}</option>`).join("");
    await this.loadJobs();
    this._wireButtons();
  }

  async loadJobs() {
    this.jobs = await apiJson("/api/admin/validation/jobs");
    const ul = document.getElementById("job-list");
    ul.innerHTML = "";
    for (const job of this.jobs) {
      const camera = this.cameras.find((c) => c.id === job.camera_id);
      const li = document.createElement("li");
      li.style.cursor = "pointer";
      if (this.selectedJob && this.selectedJob.id === job.id) li.classList.add("selected");
      li.innerHTML = `<span>Job #${job.id}<br><span class="muted">${camera ? camera.name : "?"} · ${job.samples.length} ภาพ · ${job.status}</span></span>`;
      li.addEventListener("click", () => this.selectJob(job.id));
      ul.appendChild(li);
    }
  }

  async startJob() {
    const cameraId = Number(document.getElementById("camera-select").value);
    const sampleCount = Number(document.getElementById("sample-count").value) || 20;
    const btn = document.getElementById("btn-start-job");
    const statusEl = document.getElementById("start-status");

    btn.disabled = true;
    statusEl.textContent = `กำลังถ่ายภาพ+ตรวจจับ ${sampleCount} ภาพ (ใช้เวลาประมาณ ${sampleCount} วินาที กรุณารอ)...`;
    try {
      const job = await apiJson("/api/admin/validation/jobs", {
        method: "POST",
        body: JSON.stringify({ camera_id: cameraId, sample_count: sampleCount }),
      });
      statusEl.textContent = `สร้าง job #${job.id} สำเร็จ (${job.samples.length} ภาพ)`;
      await this.loadJobs();
      await this.selectJob(job.id);
    } catch (e) {
      statusEl.textContent = "ผิดพลาด: " + e.message;
    } finally {
      btn.disabled = false;
    }
  }

  async selectJob(jobId) {
    this.selectedJob = await apiJson(`/api/admin/validation/jobs/${jobId}`);
    this.sampleIndex = 0;
    this.selectedSlotId = null;
    document.getElementById("no-job-msg").style.display = "none";
    document.getElementById("job-detail").style.display = "block";
    document.getElementById("confirm-card").style.display = "none";
    await this._renderSample();
    await this._renderAccuracy();
    await this.loadJobs();
  }

  async prevSample() {
    if (!this.selectedJob || this.sampleIndex <= 0) return;
    this.sampleIndex -= 1;
    this.selectedSlotId = null;
    document.getElementById("confirm-card").style.display = "none";
    await this._renderSample();
  }

  async nextSample() {
    if (!this.selectedJob || this.sampleIndex >= this.selectedJob.samples.length - 1) return;
    this.sampleIndex += 1;
    this.selectedSlotId = null;
    document.getElementById("confirm-card").style.display = "none";
    await this._renderSample();
  }

  async _renderSample() {
    const sample = this.selectedJob.samples[this.sampleIndex];
    document.getElementById("sample-index").textContent = this.sampleIndex + 1;
    document.getElementById("sample-total").textContent = this.selectedJob.samples.length;

    // ใช้ความกว้างจริงของ container (ไม่ใช่ window.innerWidth) ไม่งั้น CSS จะย่อ canvas
    // ให้เล็กกว่าที่ Konva คิดไว้ ทำให้พิกัดคลิกกับพิกัดภายใน Konva ไม่ตรงกัน
    const wrapEl = document.querySelector(".editor-canvas-wrap");
    const maxWidth = Math.min(900, wrapEl.clientWidth - 2);
    const img = new Image();
    const loaded = await new Promise((resolve) => {
      img.onload = () => resolve(true);
      img.onerror = () => resolve(false);
      img.src = sample.image_url + `?t=${Date.now()}`;
    });

    document.getElementById("no-image-msg").style.display = loaded ? "none" : "block";
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
    if (loaded) bgLayer.add(new Konva.Image({ image: img, width: this.imgWidth, height: this.imgHeight }));
    this.stage.add(bgLayer);
    this.layer = new Konva.Layer();
    this.stage.add(this.layer);

    this._renderSlots(sample.slot_results);
  }

  _renderSlots(slotResults) {
    this.layer.destroyChildren();
    for (const item of slotResults) {
      const baseColor = VALIDATION_STATE_COLORS[item.detected_state] || VALIDATION_STATE_COLORS.unknown;
      const isSelected = this.selectedSlotId === item.slot_id;
      const points = item.polygon.flatMap(([x, y]) => [x * this.imgWidth, y * this.imgHeight]);
      const line = new Konva.Line({
        points,
        closed: true,
        stroke: isSelected ? "#f97316" : baseColor,
        strokeWidth: isSelected ? 3 : item.confirmed_state ? 3 : 1.5,
        dash: item.confirmed_state ? undefined : [6, 4],
        fill: baseColor,
        opacity: 0.3,
      });
      line.on("click tap", () => this._selectSlot(item));
      this.layer.add(line);

      const centroid = item.polygon.reduce((acc, [x, y]) => [acc[0] + x, acc[1] + y], [0, 0]).map((v) => v / item.polygon.length);
      const mark = item.confirmed_state ? "✓" : "";
      this.layer.add(
        new Konva.Text({
          x: centroid[0] * this.imgWidth - 20,
          y: centroid[1] * this.imgHeight - 7,
          text: `${item.code} ${mark}`,
          fontSize: 12,
          fill: "#fff",
          fontStyle: "bold",
          listening: false, // ไม่ให้ป้ายชื่อบังคลิกที่เส้นขอบด้านล่าง
        })
      );
    }
    this.layer.draw();
  }

  _selectSlot(item) {
    this.selectedSlotId = item.slot_id;
    document.getElementById("confirm-card").style.display = "block";
    document.getElementById("confirm-code").textContent = item.code;
    document.getElementById("confirm-detected").textContent = item.detected_state;
    document.getElementById("confirm-score").textContent = item.score.toFixed(2);
    document.getElementById("confirm-confirmed").textContent = item.confirmed_state || "ยังไม่ยืนยัน";
    this._renderSlots(this.selectedJob.samples[this.sampleIndex].slot_results);
  }

  async confirmSlot(state) {
    if (!this.selectedJob || this.selectedSlotId === null) return;
    const sample = this.selectedJob.samples[this.sampleIndex];
    try {
      await apiJson(
        `/api/admin/validation/jobs/${this.selectedJob.id}/samples/${sample.id}/confirm`,
        { method: "POST", body: JSON.stringify({ slot_id: this.selectedSlotId, confirmed_state: state }) }
      );
      const item = sample.slot_results.find((r) => r.slot_id === this.selectedSlotId);
      item.confirmed_state = state;
      document.getElementById("confirm-confirmed").textContent = state;
      this._renderSlots(sample.slot_results);
      await this._renderAccuracy();
    } catch (e) {
      alert("ยืนยันไม่สำเร็จ: " + e.message);
    }
  }

  async _renderAccuracy() {
    const result = await apiJson(`/api/admin/validation/jobs/${this.selectedJob.id}/result`);
    const text =
      result.accuracy_pct === null
        ? "ยังไม่มีข้อมูลยืนยัน"
        : `${result.accuracy_pct}% (${result.correct}/${result.total_compared})`;
    document.getElementById("accuracy-text").textContent = text;
  }

  _wireButtons() {
    document.getElementById("btn-start-job").addEventListener("click", () => this.startJob());
    document.getElementById("btn-prev-sample").addEventListener("click", () => this.prevSample());
    document.getElementById("btn-next-sample").addEventListener("click", () => this.nextSample());
    document.getElementById("btn-confirm-free").addEventListener("click", () => this.confirmSlot("free"));
    document.getElementById("btn-confirm-occupied").addEventListener("click", () => this.confirmSlot("occupied"));
  }
}

(async function bootstrap() {
  const page = new ValidationPage();
  await page.init();
})();
