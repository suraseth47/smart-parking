// Override: บังคับสถานะช่อง/หลายช่อง/ทั้งโซน (FR-34)

function overridePage() {
  return {
    zones: [],
    zoneFilter: "",
    slots: [],
    selected: new Set(),
    overrideForm: { state: "occupied", note: "", until: "" },
    loading: false,
    error: "",
    exportError: "",

    async init() {
      const user = await requireAuth();
      if (!user) return;
      this.zones = await apiJson("/api/admin/zones");
      await this.loadSlots();
    },

    async loadSlots() {
      const qs = this.zoneFilter ? `?zone_id=${this.zoneFilter}` : "";
      this.slots = await apiJson(`/api/admin/slots${qs}`);
      // เอาช่องที่ถูกลบ/ไม่อยู่ในชุดใหม่ออกจากการเลือก
      const validIds = new Set(this.slots.map((s) => s.id));
      this.selected = new Set([...this.selected].filter((id) => validIds.has(id)));
    },

    toggle(slotId) {
      if (this.selected.has(slotId)) this.selected.delete(slotId);
      else this.selected.add(slotId);
      this.selected = new Set(this.selected); // trigger reactivity
    },

    // ส่งออกรายการช่องที่เห็นอยู่ (ตามตัวกรองโซน) เป็น Excel / PDF / พิมพ์
    async doExport(kind) {
      const STATE = { free: "ว่าง", occupied: "มีรถจอด", unknown: "ไม่ทราบ" };
      const TYPE = { normal: "ทั่วไป", disabled: "คนพิการ", ev: "รถไฟฟ้า (EV)", reserved: "สงวน" };
      const columns = ["รหัสช่อง", "โซน", "ประเภท", "สถานะตอนนี้", "บังคับสถานะ", "หมายเหตุ", "บังคับถึง"];
      const rows = this.slots.map((s) => [
        s.code, s.zone_code, TYPE[s.type] || s.type, STATE[s.state] || s.state,
        s.override_state ? (STATE[s.override_state] || s.override_state) : "", s.override_note || "",
        s.override_until ? new Date(s.override_until + (String(s.override_until).endsWith("Z") ? "" : "Z")).toLocaleString("th-TH") : "",
      ]);
      const z = this.zones.find((x) => String(x.id) === String(this.zoneFilter));
      try {
        this.exportError = "";
        await ExportKit.run(kind, { title: "สถานะช่องจอดและการบังคับสถานะ", filename: "slot-status", columns, rows, meta: z ? [`โซน: ${z.code} - ${z.name_th}`] : [] });
      } catch (e) { this.exportError = e.message; }
    },

    selectAll() {
      this.selected = new Set(this.slots.map((s) => s.id));
    },

    selectNone() {
      this.selected = new Set();
    },

    // แถบขั้นตอน: เลือกช่อง → ตั้งสถานะ/หมายเหตุ/เวลา → กดบังคับสถานะ
    doneMsg: "",
    get ovStep() {
      if (this.selected.size > 0) return 1;
      return this.doneMsg ? 3 : 0;
    },
    get ovHint() {
      if (this.selected.size > 0) {
        return `เลือกแล้ว ${this.selected.size} ช่อง — เลือกสถานะ ใส่หมายเหตุ/เวลาหมดอายุ (ถ้ามี) แล้วกด "บังคับสถานะ" · กด "ยกเลิก Override" เพื่อคืนให้ AI ตรวจตามปกติ`;
      }
      return this.doneMsg || "แตะแถวในตารางด้านล่างเพื่อเลือกช่องที่ต้องการ (เลือกได้หลายช่อง หรือกด \"เลือกทั้งหมดที่เห็น\")";
    },

    async applyOverride() {
      this.loading = true;
      this.error = "";
      const until = this.overrideForm.until ? this.overrideForm.until : null;
      try {
        for (const slotId of this.selected) {
          await apiJson(`/api/admin/slots/${slotId}/override`, {
            method: "POST",
            body: JSON.stringify({ state: this.overrideForm.state, note: this.overrideForm.note || null, until }),
          });
        }
        this.doneMsg = `บังคับสถานะ ${this.selected.size} ช่องแล้ว — มีผลทันที รวมถึงหน้าสาธารณะ`;
        this.selected = new Set();
        await this.loadSlots();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },

    async cancelOverride() {
      this.loading = true;
      this.error = "";
      try {
        for (const slotId of this.selected) {
          try {
            await apiJson(`/api/admin/slots/${slotId}/override`, { method: "DELETE" });
          } catch (e) {
            if (e.status !== 400) throw e; // 400 = ช่องนี้ไม่มี override อยู่แล้ว ข้ามไปได้
          }
        }
        this.doneMsg = `ยกเลิก Override ${this.selected.size} ช่องแล้ว — กลับไปใช้ผลตรวจจับของ AI`;
        this.selected = new Set();
        await this.loadSlots();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },
  };
}
