// รายงาน: กราฟรายวัน/รายชั่วโมง/heatmap (FR-38) + ส่งออก Excel/CSV/PDF (TOR 4.5)
// วันที่และชั่วโมงทั้งหมดเป็นเวลาท้องถิ่น (server แปลงจาก UTC ให้แล้ว)

const DOW_LABELS_TH = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"];
const THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];

// YYYY-MM-DD ตามเวลาเครื่อง (toISOString เป็น UTC — ก่อน 7 โมงเช้าจะได้วันที่ของเมื่อวาน)
function toDateInputValue(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function addDays(d, n) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}

function reportsPage() {
  const today = new Date();
  return {
    zones: [],
    sites: [],
    zoneId: null,
    hourlyDate: toDateInputValue(today),
    dailyFrom: toDateInputValue(addDays(today, -29)),
    dailyTo: toDateInputValue(today),
    heatmapWeeks: 4,
    error: "",
    summary: null,
    dailyEmpty: false,
    exportScope: "all",
    downloading: "",
    exportError: "",

    async init() {
      const user = await requireAuth();
      if (!user) return;
      [this.zones, this.sites] = await Promise.all([apiJson("/api/admin/zones"), apiJson("/api/admin/sites").catch(() => [])]);
      if (this.zones.length === 0) {
        this.error = "ยังไม่มีโซนในระบบ";
        return;
      }
      this.zoneId = String(this.zones[0].id);
      await this.loadAll();
    },

    zoneLabel(z) {
      const site = this.sites.length > 1 ? this.sites.find((s) => s.id === z.site_id) : null;
      return (site ? site.name_th + " · " : "") + z.code + " - " + z.name_th;
    },

    zoneName() {
      const z = this.zones.find((x) => String(x.id) === String(this.zoneId));
      return z ? this.zoneLabel(z) : "";
    },

    thaiDate(iso) {
      if (!iso) return "";
      const [y, m, d] = iso.split("-").map(Number);
      return `${d} ${THAI_MONTHS[m - 1]} ${y + 543}`;
    },

    preset(days) {
      const t = new Date();
      this.dailyFrom = toDateInputValue(addDays(t, -(days - 1)));
      this.dailyTo = toDateInputValue(t);
      this.loadDaily();
    },

    presetMonth(delta) {
      const t = new Date();
      const first = new Date(t.getFullYear(), t.getMonth() + delta, 1);
      const last = delta === 0 ? t : new Date(t.getFullYear(), t.getMonth() + delta + 1, 0);
      this.dailyFrom = toDateInputValue(first);
      this.dailyTo = toDateInputValue(last);
      this.loadDaily();
    },

    async loadAll() {
      this.error = "";
      await Promise.all([this.loadHourly(), this.loadDaily(), this.loadHeatmap()]);
    },

    async loadHourly() {
      if (!this.zoneId) return;
      const requestedZone = this.zoneId;
      try {
        const data = await apiJson(`/api/admin/reports/hourly?zone=${requestedZone}&date=${this.hourlyDate}`);
        if (requestedZone !== this.zoneId) return; // ผู้ใช้เปลี่ยนโซนไปแล้วระหว่างรอผล ไม่ต้อง render ทับ
        this._renderHourlyChart(data);
      } catch (e) {
        this.error = e.message;
      }
    },

    async loadDaily() {
      if (!this.zoneId) return;
      if (this.dailyTo < this.dailyFrom) { this.error = "วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่ม"; return; }
      this.error = "";
      const requestedZone = this.zoneId;
      try {
        const data = await apiJson(
          `/api/admin/reports/daily?zone=${requestedZone}&from=${this.dailyFrom}&to=${this.dailyTo}`
        );
        if (requestedZone !== this.zoneId) return;
        this.dailyEmpty = data.length === 0;
        this.summary = data.length
          ? (() => {
              const busiest = data.reduce((a, b) => (b.avg_occ_pct > a.avg_occ_pct ? b : a));
              return {
                avg: (data.reduce((s, p) => s + p.avg_occ_pct, 0) / data.length).toFixed(1),
                max: Math.max(...data.map((p) => p.max_occ_pct)).toFixed(1),
                busiest: `${this.thaiDate(busiest.date)} (${busiest.avg_occ_pct.toFixed(0)}%)`,
                days: data.length,
              };
            })()
          : null;
        this._renderDailyChart(data);
      } catch (e) {
        this.error = e.message;
      }
    },

    async loadHeatmap() {
      if (!this.zoneId) return;
      const requestedZone = this.zoneId;
      try {
        const data = await apiJson(`/api/admin/reports/heatmap?zone=${requestedZone}&weeks=${this.heatmapWeeks}`);
        if (requestedZone !== this.zoneId) return;
        this._renderHeatmap(data);
      } catch (e) {
        this.error = e.message;
      }
    },

    // ---------- ส่งออก ----------
    async download(format) {
      this.exportError = "";
      if (this.dailyTo < this.dailyFrom) { this.exportError = "วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่ม"; return; }
      const zone = this.exportScope === "all" ? "all" : this.zoneId;
      const url = `/api/admin/reports/export?format=${format}&zone=${zone}&from=${this.dailyFrom}&to=${this.dailyTo}`;
      this.downloading = format;
      try {
        const resp = await apiFetch(url);
        if (!resp.ok) {
          const data = await resp.json().catch(() => ({}));
          throw new Error(typeof data.detail === "string" ? data.detail : `ส่งออกไม่สำเร็จ (${resp.status})`);
        }
        const blob = await resp.blob();
        const match = (resp.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/);
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = match ? match[1] : `parking-report.${format}`;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
      } catch (e) {
        this.exportError = e.message;
      } finally {
        this.downloading = "";
      }
    },

    printReport() {
      window.print();
    },

    // ---------- กราฟ ----------
    _renderHourlyChart(points) {
      const ctx = document.getElementById("hourly-chart");
      const labels = points.map((p) => `${String(p.hour).padStart(2, "0")}:00`);
      const avgData = points.map((p) => (p.samples ? p.avg_occ_pct : null));
      const maxData = points.map((p) => (p.samples ? p.max_occ_pct : null));
      Chart.getChart(ctx)?.destroy(); // กันกรณี chart เดิมติดอยู่บน canvas แต่ reference ของเราไม่ sync
      new Chart(ctx, {
        type: "bar",
        data: {
          labels,
          datasets: [
            { label: "เฉลี่ย %", data: avgData, backgroundColor: "#2563eb" },
            { label: "สูงสุด %", data: maxData, type: "line", borderColor: "#dc2626", fill: false, spanGaps: false },
          ],
        },
        options: { responsive: true, animation: false, scales: { y: { beginAtZero: true, max: 100 } } },
      });
    },

    _renderDailyChart(points) {
      const ctx = document.getElementById("daily-chart");
      const labels = points.map((p) => {
        const [y, m, d] = p.date.split("-").map(Number);
        return `${d} ${THAI_MONTHS[m - 1]}`;
      });
      Chart.getChart(ctx)?.destroy();
      new Chart(ctx, {
        type: "bar",
        data: {
          labels,
          datasets: [
            { label: "เฉลี่ย %", data: points.map((p) => p.avg_occ_pct), backgroundColor: "#2563eb" },
            { label: "สูงสุด %", data: points.map((p) => p.max_occ_pct), type: "line", borderColor: "#dc2626", fill: false },
          ],
        },
        options: { responsive: true, animation: false, scales: { y: { beginAtZero: true, max: 100 } } },
      });
    },

    _renderHeatmap(cells) {
      const byKey = {};
      for (const c of cells) byKey[`${c.day_of_week}-${c.hour}`] = c.avg_occ_pct;

      const table = document.getElementById("heatmap-table");
      let html = "<tr><th></th>";
      for (let h = 0; h < 24; h++) html += `<th>${String(h).padStart(2, "0")}</th>`;
      html += "</tr>";

      for (let dow = 0; dow < 7; dow++) {
        html += `<tr><th class="dow">${DOW_LABELS_TH[dow]}</th>`;
        for (let h = 0; h < 24; h++) {
          const val = byKey[`${dow}-${h}`];
          if (val === undefined) {
            html += `<td><div class="heatmap-cell empty" title="ไม่มีข้อมูล"></div></td>`;
          } else {
            const pct = Math.round(val);
            html += `<td><div class="heatmap-cell" style="background:${this._heatColor(pct)};" title="${DOW_LABELS_TH[dow]} ${h}:00 น. · ${pct}%">${pct}</div></td>`;
          }
        }
        html += "</tr>";
      }
      table.innerHTML = html;
    },

    _heatColor(pct) {
      // เขียวอ่อน (ว่าง) -> เหลือง -> แดง (หนาแน่น) — สีเดียวกับไฟล์ Excel
      const t = Math.max(0, Math.min(100, pct)) / 100;
      const [a, b, k] = t < 0.5 ? [[220, 252, 231], [254, 240, 138], t / 0.5] : [[254, 240, 138], [248, 113, 113], (t - 0.5) / 0.5];
      const c = a.map((v, i) => Math.round(v + (b[i] - v) * k));
      return `rgb(${c[0]},${c[1]},${c[2]})`;
    },
  };
}
