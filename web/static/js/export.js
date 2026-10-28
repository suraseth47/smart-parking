// ปุ่มส่งออกตาราง: Excel / PDF / พิมพ์ — ใช้ร่วมกันทุกเมนู
//
// ใช้งานในหน้า:  ExportKit.run(kind, { title, filename, columns, rows, meta })
//   kind     = "excel" | "pdf" | "print"
//   columns  = ["หัวคอลัมน์", ...]
//   rows     = [[ค่า, ค่า, ...], ...]   (ข้อความหรือตัวเลข ตามที่เห็นบนจอ)
//   meta     = ["ตัวกรอง: ...", ...]   (ไม่บังคับ แสดงใต้ชื่อรายงาน)
//
// Excel สร้างที่ server (openpyxl) / PDF และพิมพ์ ใช้หน้าพิมพ์ของเบราว์เซอร์ (รองรับภาษาไทยเต็มที่)

(function () {
  const THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function thaiNow() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getDate()} ${THAI_MONTHS[d.getMonth()]} ${d.getFullYear() + 543} ${pad(d.getHours())}:${pad(d.getMinutes())} น.`;
  }

  function stamp() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`;
  }

  function who() {
    return (window.currentUser && window.currentUser.username) || "";
  }

  async function excel(spec) {
    const resp = await apiFetch("/api/admin/export/table", {
      method: "POST",
      body: JSON.stringify({
        title: spec.title, filename: spec.filename, columns: spec.columns,
        rows: spec.rows.map((r) => r.map((v) => (v === undefined ? null : v))), meta: spec.meta || [],
      }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(typeof data.detail === "string" ? data.detail : `ส่งออกไม่สำเร็จ (${resp.status})`);
    }
    const blob = await resp.blob();
    const match = (resp.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = match ? match[1] : `${spec.filename}.xlsx`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  // หน้าพิมพ์แยกแท็บ: ใช้ทั้ง "พิมพ์" และ "PDF" (เลือกเครื่องพิมพ์ "บันทึกเป็น PDF")
  function printView(spec, asPdf) {
    const landscape = spec.columns.length > 5;
    const name = `${spec.filename}-${stamp()}`;
    const head = spec.columns.map((c) => `<th>${esc(c)}</th>`).join("");
    const body = spec.rows.length
      ? spec.rows.map((r) => `<tr>${spec.columns.map((_, i) => `<td>${esc(r[i])}</td>`).join("")}</tr>`).join("")
      : `<tr><td colspan="${spec.columns.length}" class="empty">ไม่มีข้อมูล</td></tr>`;
    const meta = (spec.meta || []).map((m) => `<div>${esc(m)}</div>`).join("");
    const hint = asPdf
      ? `<div class="hint no-print">หน้าต่างพิมพ์จะเปิดขึ้น — ที่ "ปลายทาง/เครื่องพิมพ์" เลือก <b>บันทึกเป็น PDF</b> แล้วกดบันทึก
           <button onclick="window.print()">เปิดหน้าต่างพิมพ์อีกครั้ง</button></div>`
      : `<div class="hint no-print"><button onclick="window.print()">พิมพ์อีกครั้ง</button></div>`;
    const html = `<!doctype html><html lang="th"><head><meta charset="utf-8"><title>${esc(name)}</title>
<style>
  @page { size: A4 ${landscape ? "landscape" : "portrait"}; margin: 12mm; }
  body { font-family: "Sarabun", "TH Sarabun New", "Leelawadee UI", "Noto Sans Thai", Tahoma, sans-serif; color: #1f2937; margin: 16px; font-size: 12px; }
  .brand { font-size: 11px; color: #6b7486; letter-spacing: .04em; }
  h1 { font-size: 18px; margin: 2px 0 4px; }
  .meta { color: #4b5565; font-size: 11px; margin-bottom: 10px; line-height: 1.5; }
  table { width: 100%; border-collapse: collapse; }
  thead { display: table-header-group; }
  th { background: #e8eefb; text-align: left; font-weight: 700; }
  th, td { border: 1px solid #c9d2e3; padding: 4px 6px; vertical-align: top; overflow-wrap: anywhere; }
  tr { break-inside: avoid; }
  tbody tr:nth-child(even) td { background: #f8fafd; }
  .empty { text-align: center; color: #6b7486; padding: 16px; }
  .hint { background: #fff8e6; border: 1px solid #f0c36d; border-radius: 8px; padding: 8px 10px; margin-bottom: 12px; font-size: 13px; }
  .hint button { margin-left: 8px; font: inherit; padding: 4px 10px; cursor: pointer; }
  .foot { margin-top: 10px; font-size: 10px; color: #6b7486; }
  @media print { .no-print { display: none !important; } body { margin: 0; } th, tbody tr:nth-child(even) td { -webkit-print-color-adjust: exact; print-color-adjust: exact; } }
</style></head><body>
${hint}
<div class="brand">NASLINK SMART PARKING</div>
<h1>${esc(spec.title)}</h1>
<div class="meta">${meta}<div>พิมพ์เมื่อ ${esc(thaiNow())}${who() ? " โดย " + esc(who()) : ""} · ${spec.rows.length.toLocaleString("th-TH")} รายการ</div></div>
<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>
<div class="foot">เอกสารนี้ออกจากระบบ Smart Parking — อาจมีข้อมูลส่วนบุคคล โปรดเก็บรักษาตาม พ.ร.บ.คุ้มครองข้อมูลส่วนบุคคล</div>
<script>window.addEventListener("load", () => setTimeout(() => window.print(), 300));<\/script>
</body></html>`;
    const win = window.open("", "_blank");
    if (!win) throw new Error("เบราว์เซอร์บล็อกหน้าต่างใหม่ — กรุณาอนุญาตป๊อปอัปสำหรับเว็บนี้ แล้วกดอีกครั้ง");
    win.document.open();
    win.document.write(html);
    win.document.close();
    apiFetch("/api/admin/export/print-log", {
      method: "POST", body: JSON.stringify({ title: spec.title, rows: spec.rows.length, kind: asPdf ? "pdf" : "print" }),
    }).catch(() => {});
  }

  async function run(kind, spec) {
    if (kind === "excel") return excel(spec);
    return printView(spec, kind === "pdf");
  }

  window.ExportKit = { run, excel, print: printView };
})();
