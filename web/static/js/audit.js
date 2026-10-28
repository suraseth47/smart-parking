// Audit log viewer (FR-43) + ส่งออก Excel/CSV (TOR 4.5)

const DETAIL_KEY_LABELS = {
  ip: "IP", reason: "สาเหตุ", note: "ข้อความ", fields: "ช่องที่แก้", rows: "จำนวนแถว", format: "รูปแบบ",
  from: "ตั้งแต่", to: "ถึง", zone: "โซน", slot_count: "จำนวนช่อง", message: "ข้อความ",
};
const REASON_LABELS = { wrong_password: "รหัสผ่านผิด", unknown_or_inactive: "ไม่พบบัญชี/บัญชีถูกปิด", locked: "บัญชีถูกล็อก" };

function auditPage() {
  return {
    ready: false,
    entries: [],
    total: 0,
    actions: [],
    isOperator: false,
    f: { from: "", to: "", action: "", username: "" },
    limit: 50,
    offset: 0,
    error: "",
    downloading: "",

    async init() {
      const user = await requireAuth();
      if (!user) return;
      this.isOperator = user.role !== "admin";
      this.ready = true;
      if (this.isOperator) return; // audit log เป็นสิทธิ์ Admin เท่านั้น
      this.actions = await apiJson("/api/admin/audit/actions").catch(() => []);
      await this.reload();
    },

    params() {
      const p = new URLSearchParams();
      if (this.f.from) p.set("from", this.f.from);
      if (this.f.to) p.set("to", this.f.to);
      if (this.f.action) p.set("action", this.f.action);
      if (this.f.username.trim()) p.set("username", this.f.username.trim());
      return p;
    },

    clearFilters() {
      this.f = { from: "", to: "", action: "", username: "" };
      this.reload();
    },

    async reload() {
      this.offset = 0;
      await this.load();
    },

    async load() {
      const p = this.params();
      p.set("limit", this.limit);
      p.set("offset", this.offset);
      try {
        const data = await apiJson(`/api/admin/audit?${p.toString()}`);
        this.entries = data.items;
        this.total = data.total;
        this.error = "";
      } catch (e) {
        this.error = e.message;
      }
    },

    async nextPage() { this.offset += this.limit; await this.load(); },
    async prevPage() { this.offset = Math.max(0, this.offset - this.limit); await this.load(); },

    async download(format) {
      const p = this.params();
      p.set("format", format);
      this.downloading = format;
      this.error = "";
      try {
        const resp = await apiFetch(`/api/admin/audit/export?${p.toString()}`);
        if (!resp.ok) {
          const data = await resp.json().catch(() => ({}));
          throw new Error(typeof data.detail === "string" ? data.detail : `ส่งออกไม่สำเร็จ (${resp.status})`);
        }
        const blob = await resp.blob();
        const match = (resp.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/);
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = match ? match[1] : `audit-log.${format}`;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
        await this.load(); // การส่งออกเองก็ถูกบันทึกไว้ด้วย
      } catch (e) {
        this.error = e.message;
      } finally {
        this.downloading = "";
      }
    },

    // PDF / พิมพ์: ดึงรายการตามตัวกรอง (ไม่เกิน 2,000 รายการล่าสุด) แล้วเปิดหน้าพิมพ์
    async printOut(kind) {
      this.downloading = kind;
      this.error = "";
      try {
        const items = [];
        for (let offset = 0; offset < 2000; offset += 200) {
          const p = this.params();
          p.set("limit", 200);
          p.set("offset", offset);
          const page = await apiJson(`/api/admin/audit?${p.toString()}`);
          items.push(...page.items);
          if (items.length >= page.total || page.items.length < 200) break;
        }
        const meta = [];
        if (this.f.from || this.f.to) meta.push(`ช่วงวันที่: ${this.f.from || "-"} ถึง ${this.f.to || "-"}`);
        if (this.f.action) meta.push("การกระทำ: " + ((this.actions.find((a) => a.action === this.f.action) || {}).label || this.f.action));
        if (this.f.username.trim()) meta.push("ผู้ใช้: " + this.f.username.trim());
        if (this.total > items.length) meta.push(`แสดง ${items.length.toLocaleString("th-TH")} รายการล่าสุด จากทั้งหมด ${this.total.toLocaleString("th-TH")} รายการ`);
        await ExportKit.run(kind, {
          title: "ประวัติการใช้งานระบบ (Audit log)", filename: "audit-log",
          columns: ["เวลา", "ผู้ใช้", "การกระทำ", "เป้าหมาย", "รายละเอียด"],
          rows: items.map((e) => [this.formatTime(e.ts), e.username || "-", e.action_label, e.target || "-", this.detailText(e.detail)]),
          meta,
        });
      } catch (e) {
        this.error = e.message;
      } finally {
        this.downloading = "";
      }
    },

    detailText(detail) {
      if (!detail) return "";
      return Object.entries(detail)
        .filter(([, v]) => v !== null && v !== undefined && v !== "")
        .map(([k, v]) => {
          const label = DETAIL_KEY_LABELS[k] || k;
          let value = Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v);
          if (k === "reason") value = REASON_LABELS[v] || value;
          return `${label}: ${value}`;
        })
        .join(" · ");
    },

    formatTime(iso) {
      const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
      return d.toLocaleString("th-TH", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
    },
  };
}
