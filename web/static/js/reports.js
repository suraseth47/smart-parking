// รายงาน: กราฟรายชั่วโมง/รายวัน/heatmap (FR-38)

const DOW_LABELS_TH = ["จันทร์", "อังคาร", "พุธ", "พฤหัส", "ศุกร์", "เสาร์", "อาทิตย์"];

function toDateInputValue(d) {
  return d.toISOString().slice(0, 10);
}

function reportsPage() {
  return {
    zones: [],
    zoneId: null,
    hourlyDate: toDateInputValue(new Date()),
    dailyFrom: toDateInputValue(new Date(Date.now() - 7 * 24 * 60 * 60 * 1000)),
    dailyTo: toDateInputValue(new Date()),
    heatmapWeeks: 4,
    error: "",
    hourlyChart: null,
    dailyChart: null,

    async init() {
      const user = await requireAuth();
      if (!user) return;
      this.zones = await apiJson("/api/admin/zones");
      if (this.zones.length === 0) {
        this.error = "ยังไม่มีโซนในระบบ";
        return;
      }
      this.zoneId = this.zones[0].id;
      await this.loadAll();
    },

    async loadAll() {
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
      const requestedZone = this.zoneId;
      try {
        const data = await apiJson(
          `/api/admin/reports/daily?zone=${requestedZone}&from=${this.dailyFrom}&to=${this.dailyTo}`
        );
        if (requestedZone !== this.zoneId) return;
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

    _renderHourlyChart(points) {
      const ctx = document.getElementById("hourly-chart");
      const labels = points.map((p) => `${p.hour}:00`);
      const avgData = points.map((p) => p.avg_occ_pct);
      const maxData = points.map((p) => p.max_occ_pct);
      Chart.getChart(ctx)?.destroy(); // กันกรณี chart เดิมติดอยู่บน canvas แต่ reference ของเราไม่ sync
      this.hourlyChart = new Chart(ctx, {
        type: "bar",
        data: {
          labels,
          datasets: [
            { label: "เฉลี่ย %", data: avgData, backgroundColor: "#2563eb" },
            { label: "สูงสุด %", data: maxData, type: "line", borderColor: "#dc2626", fill: false },
          ],
        },
        options: { responsive: true, scales: { y: { beginAtZero: true, max: 100 } } },
      });
    },

    _renderDailyChart(points) {
      const ctx = document.getElementById("daily-chart");
      const labels = points.map((p) => p.date);
      const avgData = points.map((p) => p.avg_occ_pct);
      const maxData = points.map((p) => p.max_occ_pct);
      Chart.getChart(ctx)?.destroy();
      this.dailyChart = new Chart(ctx, {
        type: "bar",
        data: {
          labels,
          datasets: [
            { label: "เฉลี่ย %", data: avgData, backgroundColor: "#2563eb" },
            { label: "สูงสุด %", data: maxData, type: "line", borderColor: "#dc2626", fill: false },
          ],
        },
        options: { responsive: true, scales: { y: { beginAtZero: true, max: 100 } } },
      });
    },

    _renderHeatmap(cells) {
      const byKey = {};
      for (const c of cells) byKey[`${c.day_of_week}-${c.hour}`] = c.avg_occ_pct;

      const table = document.getElementById("heatmap-table");
      let html = "<tr><th></th>";
      for (let h = 0; h < 24; h++) html += `<th>${h}</th>`;
      html += "</tr>";

      for (let dow = 0; dow < 7; dow++) {
        html += `<tr><th>${DOW_LABELS_TH[dow]}</th>`;
        for (let h = 0; h < 24; h++) {
          const val = byKey[`${dow}-${h}`];
          const color = val === undefined ? "transparent" : this._heatColor(val);
          const title = val === undefined ? "ไม่มีข้อมูล" : `${val.toFixed(0)}%`;
          html += `<td><div class="heatmap-cell" style="background:${color};" title="${title}"></div></td>`;
        }
        html += "</tr>";
      }
      table.innerHTML = html;
    },

    _heatColor(pct) {
      // 0% = ฟ้าอ่อน, 100% = แดงเข้ม
      const t = Math.max(0, Math.min(100, pct)) / 100;
      const r = Math.round(37 + t * (220 - 37));
      const g = Math.round(99 + t * (38 - 99));
      const b = Math.round(235 + t * (38 - 235));
      return `rgb(${r},${g},${b})`;
    },
  };
}
