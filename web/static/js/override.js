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

    selectAll() {
      this.selected = new Set(this.slots.map((s) => s.id));
    },

    selectNone() {
      this.selected = new Set();
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
        await this.loadSlots();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },
  };
}
