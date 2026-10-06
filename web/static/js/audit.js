// Audit log viewer (FR-43)

function auditPage() {
  return {
    entries: [],
    isOperator: false,
    actionFilter: "",
    limit: 50,
    offset: 0,
    error: "",

    async init() {
      const user = await requireAuth();
      if (!user) return;
      this.isOperator = user.role !== "admin";
      if (this.isOperator) return; // audit log เป็นสิทธิ์ Admin เท่านั้น
      await this.reload();
    },

    async reload() {
      this.offset = 0;
      await this.load();
    },

    async load() {
      const params = new URLSearchParams({ limit: this.limit, offset: this.offset });
      if (this.actionFilter) params.set("action", this.actionFilter);
      try {
        this.entries = await apiJson(`/api/admin/audit?${params.toString()}`);
      } catch (e) {
        this.error = e.message;
      }
    },

    async nextPage() {
      this.offset += this.limit;
      await this.load();
    },

    async prevPage() {
      this.offset = Math.max(0, this.offset - this.limit);
      await this.load();
    },

    formatTime(iso) {
      const d = new Date(iso + "Z");
      return d.toLocaleString("th-TH", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
    },
  };
}
