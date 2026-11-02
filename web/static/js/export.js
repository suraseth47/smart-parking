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

  // ---------- แถบเครื่องมือหน้าเฝ้าดู: รีเฟรช · คัดลอก (วางใน LINE) · บันทึกรูป · PDF · พิมพ์ ----------
  // markup: {% from "admin/_page_tools.html" import page_tools %} {{ page_tools("30 วินาที") }}
  // JS:     ExportKit.bindTools(el, { refresh, lineText, spec, image })   แล้วเรียก ExportKit.markUpdated(el) หลังโหลดข้อมูล
  //   lineText() -> ข้อความสรุปสำหรับวางใน LINE · spec() -> {title, filename, columns, rows, meta} (ใช้กับ PDF/พิมพ์/Excel/รูป)
  //   imageSpec() -> (ไม่บังคับ) ตารางแบบย่อสำหรับรูป (ตารางเต็มคอลัมน์เยอะเกินรูป)
  //   image()   -> (ไม่บังคับ) canvas/dataURL ภาพหลักของหน้า (เช่น ภาพกล้องพร้อมกรอบช่อง) ใส่ไว้ในรูปที่บันทึก

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch (e) { /* http (ไม่ใช่ https) ใช้ clipboard API ไม่ได้ → ใช้วิธีเดิม */ }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.cssText = "position:fixed;top:-1000px;opacity:0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    if (!ok) throw new Error("คัดลอกไม่สำเร็จ — เบราว์เซอร์ไม่อนุญาต");
  }

  function loadImage(src) {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null);
      img.src = src;
    });
  }

  // วาดรูปสรุป (หัวเรื่อง + ภาพหลัก + ตาราง) ลง canvas แล้วดาวน์โหลดเป็น PNG — ไม่ต้องใช้ library เพิ่ม
  async function saveImage(spec, picture) {
    const W = 1200, pad = 32, font = '"Sarabun","Leelawadee UI","Noto Sans Thai",Tahoma,sans-serif';
    let pic = null;
    if (picture) pic = typeof picture === "string" ? await loadImage(picture) : picture;
    const picH = pic ? Math.round((W - pad * 2) * (pic.height / pic.width)) : 0;
    const rows = spec.rows.slice(0, 40);
    const cols = spec.columns;
    const rowH = 30;
    const H = pad + 22 + 40 + (spec.meta || []).length * 24 + 28 + (pic ? picH + 20 : 0) + (rows.length + 1) * rowH + (spec.rows.length > rows.length ? 30 : 0) + 40 + pad;
    const c = document.createElement("canvas");
    c.width = W; c.height = H;
    const g = c.getContext("2d");
    g.fillStyle = "#ffffff"; g.fillRect(0, 0, W, H);
    let y = pad;
    g.fillStyle = "#6b7486"; g.font = `600 15px ${font}`; g.fillText("NASLINK SMART PARKING", pad, y + 14); y += 22;
    g.fillStyle = "#1e2532"; g.font = `700 28px ${font}`; g.fillText(spec.title, pad, y + 30); y += 40;
    g.font = `16px ${font}`; g.fillStyle = "#4b5565";
    for (const m of spec.meta || []) { g.fillText(m, pad, y + 18); y += 24; }
    g.fillText(`ข้อมูลเมื่อ ${thaiNow()}`, pad, y + 18); y += 28;
    if (pic) { g.drawImage(pic, pad, y, W - pad * 2, picH); y += picH + 20; }
    // ตาราง: ความกว้างคอลัมน์ตามความยาวข้อความ
    g.font = `15px ${font}`;
    const widths = cols.map((h, i) => Math.max(g.measureText(String(h)).width, ...rows.map((r) => g.measureText(String(r[i] ?? "")).width)) + 20);
    const total = widths.reduce((a, b) => a + b, 0);
    const scale = Math.min(1, (W - pad * 2) / total);
    const xs = [];
    widths.reduce((x, w) => { xs.push(x); return x + w * scale; }, pad);
    const drawRow = (cells, top, head) => {
      g.fillStyle = head ? "#e8eefb" : "#ffffff";
      g.fillRect(pad, top, W - pad * 2, rowH);
      g.strokeStyle = "#d3d9e4"; g.strokeRect(pad, top, W - pad * 2, rowH);
      g.fillStyle = "#1e2532"; g.font = `${head ? "700 " : ""}15px ${font}`;
      cells.forEach((v, i) => {
        g.save(); g.beginPath(); g.rect(xs[i], top, widths[i] * scale, rowH); g.clip();
        g.fillText(String(v ?? ""), xs[i] + 8, top + 20); g.restore();
      });
    };
    drawRow(cols, y, true); y += rowH;
    for (const r of rows) { drawRow(r, y, false); y += rowH; }
    if (spec.rows.length > rows.length) { g.fillStyle = "#6b7486"; g.fillText(`… และอีก ${spec.rows.length - rows.length} รายการ (ดูทั้งหมดใน PDF)`, pad, y + 20); y += 30; }
    g.fillStyle = "#6b7486"; g.font = `13px ${font}`;
    g.fillText(`บันทึกโดย ${who() || "-"} · ระบบ Smart Parking`, pad, y + 26);
    const a = document.createElement("a");
    a.href = c.toDataURL("image/png");
    a.download = `${spec.filename}-${stamp()}.png`;
    document.body.appendChild(a); a.click(); a.remove();
  }

  // ---------- ภาพสรุปสถานะสำหรับส่ง LINE (แบบเดียวกับ CCTV Monitor) ----------
  // statusCard(spec) วาดภาพ PNG สวย ๆ ด้วย canvas (ไม่ใช้ library เพิ่ม) แล้วคืน canvas
  // spec = {
  //   subtitle: "สถานะช่องจอดสด · กล้อง ...",
  //   hero: { label, value, unit, ratio (0-1 หรือ null), ratioText, tone: "green"|"red"|"blue" },
  //   pair: [{ label, value, unit, tone }, { ... }],          การ์ดเล็ก 2 ใบ (เขียว/แดง)
  //   info: "ข้อความ 1 บรรทัด",
  //   panel: { title, rows: [{ left, right, tone }], empty },  รายการด้านขวาล่าง
  //   picture: dataURL | canvas  หรือ  bars: [{ name, free, capacity, tag, tone }]  หรือ  items: [{ title, text, sub, tone }]
  // }
  const THAI_MONTHS_FULL = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"];
  const TONE = {
    green: { bg: "#ecfdf3", line: "#bbf7d0", ink: "#15803d" },
    red: { bg: "#fef2f2", line: "#fecaca", ink: "#dc2626" },
    blue: { bg: "#eff6ff", line: "#bfdbfe", ink: "#1d4ed8" },
    amber: { bg: "#fff7e6", line: "#fde0a8", ink: "#b45309" },
    gray: { bg: "#f8fafc", line: "#e2e8f0", ink: "#475569" },
  };

  async function statusCard(spec) {
    try { await document.fonts.ready; } catch (e) { /* ไม่เป็นไร */ }
    const FONT = getComputedStyle(document.body).fontFamily || "sans-serif";
    const f = (size, weight = 400) => `${weight} ${size}px ${FONT}`;
    const W = 1600, PAD = 36, HEAD = 150, GAP = 24;
    const RIGHT_W = 520, LEFT_W = W - PAD * 2 - GAP - RIGHT_W;
    const title = document.body.dataset.appTitle || "ระบบบริหารจัดการที่จอดรถอัจฉริยะ";
    const d = new Date();
    const when = `${d.getDate()} ${THAI_MONTHS_FULL[d.getMonth()]} ${d.getFullYear() + 543} เวลา ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")} น.`;

    let pic = null;
    if (spec.picture) pic = typeof spec.picture === "string" ? await loadImage(spec.picture) : spec.picture;

    // วัดความสูงฝั่งซ้าย / ขวา ก่อนสร้าง canvas จริง
    const probe = document.createElement("canvas").getContext("2d");
    const legend = pic && spec.legend ? 56 : 0;
    const leftH = pic ? Math.round(LEFT_W * pic.height / pic.width) + legend
      : spec.bars ? 70 + spec.bars.length * 92
      : spec.items ? 70 + Math.max(1, spec.items.length) * 118 : 300;
    const panelRows = spec.panel ? Math.max(1, spec.panel.rows.length) : 0;
    const rightH = 300 + GAP + (spec.pair ? 170 + GAP : 0) + (spec.info ? 76 + GAP : 0) + (spec.panel ? 74 + panelRows * 52 + 20 : 0);
    const bodyH = Math.max(leftH, rightH);
    const H = HEAD + PAD + bodyH + PAD + 44;

    const c = document.createElement("canvas");
    c.width = W; c.height = H;
    const g = c.getContext("2d");
    const rr = (x, y, w, h, r, fill, stroke) => {
      g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
      g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
      if (fill) { g.fillStyle = fill; g.fill(); }
      if (stroke) { g.strokeStyle = stroke; g.lineWidth = 2; g.stroke(); }
    };
    const fit = (text, max) => {
      text = String(text ?? "");
      if (g.measureText(text).width <= max) return text;
      while (text.length > 1 && g.measureText(text + "…").width > max) text = text.slice(0, -1);
      return text + "…";
    };
    const write = (text, x, y, font, color, align = "left", max) => {
      g.font = font; g.fillStyle = color; g.textAlign = align; g.textBaseline = "alphabetic";
      g.fillText(max ? fit(text, max) : String(text), x, y);
    };

    // พื้นหลัง + หัวสีน้ำเงิน
    g.fillStyle = "#f1f5f9"; g.fillRect(0, 0, W, H);
    const grad = g.createLinearGradient(0, 0, W, 0);
    grad.addColorStop(0, "#1e3a8a"); grad.addColorStop(1, "#1d4ed8");
    g.fillStyle = grad; g.fillRect(0, 0, W, HEAD);
    write(title, PAD, 66, f(40, 700), "#ffffff", "left", W - PAD * 2 - 470);
    write(spec.subtitle || "", PAD, 114, f(26), "#dbeafe", "left", W - PAD * 2 - 470);
    write("ข้อมูล ณ วันที่", W - PAD, 58, f(22), "#dbeafe", "right");
    write(when, W - PAD, 104, f(32, 700), "#ffffff", "right");

    const top = HEAD + PAD;
    // ---------- ฝั่งซ้าย ----------
    const L = PAD;
    if (pic) {
      const ph = leftH - legend;
      g.save(); rr(L, top, LEFT_W, ph, 18); g.clip(); g.drawImage(pic, L, top, LEFT_W, ph); g.restore();
      rr(L, top, LEFT_W, ph, 18, null, "#cbd5e1");
      // คำอธิบายสีใต้ภาพ: [{ color, text, dash }]
      let lx = L + 4;
      for (const item of spec.legend || []) {
        const ly = top + ph + 22;
        if (item.dash) { g.strokeStyle = item.color; g.lineWidth = 3; g.setLineDash([8, 5]); g.strokeRect(lx, ly, 30, 20); g.setLineDash([]); }
        else rr(lx, ly, 30, 20, 5, item.color);
        write(item.text, lx + 40, ly + 18, f(21), "#334155");
        g.font = f(21); lx += 40 + g.measureText(item.text).width + 34;
      }
    } else {
      rr(L, top, LEFT_W, bodyH, 18, "#ffffff", "#e2e8f0");
      if (spec.bars) {
        write(spec.barsTitle || "สถานที่จอดรถ", L + 28, top + 48, f(26, 700), "#0f172a");
        spec.bars.forEach((b, i) => {
          const y = top + 80 + i * 92;
          const t = TONE[b.tone] || TONE.green;
          write(b.name, L + 28, y + 30, f(24, 700), "#0f172a", "left", LEFT_W - 340);
          write(b.tag || "", L + LEFT_W - 28, y + 30, f(22, 700), t.ink, "right");
          rr(L + 28, y + 46, LEFT_W - 56, 18, 9, "#e2e8f0");
          const ratio = b.capacity ? Math.max(0, Math.min(1, b.free / b.capacity)) : 0;
          if (ratio > 0) rr(L + 28, y + 46, Math.max(18, (LEFT_W - 56) * ratio), 18, 9, t.ink);
        });
      } else if (spec.items) {
        write(spec.itemsTitle || "รายการ", L + 28, top + 48, f(26, 700), "#0f172a");
        if (!spec.items.length) write(spec.itemsEmpty || "ไม่มีรายการ", L + 28, top + 110, f(26), "#15803d");
        spec.items.forEach((it, i) => {
          const y = top + 74 + i * 118;
          const t = TONE[it.tone] || TONE.amber;
          rr(L + 24, y, LEFT_W - 48, 104, 14, t.bg, t.line);
          rr(L + 24, y, 8, 104, 4, t.ink);
          write(it.title, L + 50, y + 36, f(24, 700), t.ink, "left", LEFT_W - 110);
          write(it.text, L + 50, y + 68, f(21), "#1e293b", "left", LEFT_W - 110);
          write(it.sub || "", L + 50, y + 94, f(18), "#64748b", "left", LEFT_W - 110);
        });
      }
    }

    // ---------- ฝั่งขวา ----------
    const R = PAD + LEFT_W + GAP;
    let y = top;
    const hero = spec.hero || {};
    const ht = TONE[hero.tone] || TONE.blue;
    rr(R, y, RIGHT_W, 300, 22, ht.bg, ht.line);
    write(hero.label || "", R + 32, y + 56, f(30, 700), ht.ink, "left", RIGHT_W - 64);
    g.font = f(150, 800);
    const vw = g.measureText(String(hero.value ?? "-")).width;
    write(hero.value ?? "-", R + 30, y + 196, f(150, 800), ht.ink);
    write(hero.unit || "", R + 46 + vw, y + 196, f(40, 700), ht.ink);
    if (hero.ratio !== null && hero.ratio !== undefined) {
      rr(R + 32, y + 226, RIGHT_W - 64, 20, 10, "#e2e8f0");
      if (hero.ratio > 0) rr(R + 32, y + 226, Math.max(20, (RIGHT_W - 64) * Math.min(1, hero.ratio)), 20, 10, hero.barColor || "#16a34a");
    }
    write(hero.ratioText || "", R + 32, y + 280, f(24, 700), hero.barColor || "#15803d", "left", RIGHT_W - 64);
    y += 300 + GAP;

    if (spec.pair) {
      const pw = (RIGHT_W - GAP) / 2;
      spec.pair.slice(0, 2).forEach((p, i) => {
        const t = TONE[p.tone] || TONE.gray;
        const x = R + i * (pw + GAP);
        rr(x, y, pw, 170, 20, t.bg, t.line);
        write(p.label, x + 24, y + 48, f(26, 700), t.ink, "left", pw - 48);
        g.font = f(80, 800);
        const w2 = g.measureText(String(p.value)).width;
        write(p.value, x + 22, y + 140, f(80, 800), t.ink);
        write(p.unit || "", x + 36 + w2, y + 140, f(30, 700), t.ink);
      });
      y += 170 + GAP;
    }
    if (spec.info) {
      rr(R, y, RIGHT_W, 76, 16, "#ffffff", "#e2e8f0");
      write(spec.info, R + 24, y + 48, f(23), "#334155", "left", RIGHT_W - 48);
      y += 76 + GAP;
    }
    if (spec.panel) {
      const ph = 74 + panelRows * 52;
      rr(R, y, RIGHT_W, ph, 16, "#ffffff", "#e2e8f0");
      write(spec.panel.title, R + 24, y + 48, f(25, 700), "#0f172a", "left", RIGHT_W - 48);
      if (!spec.panel.rows.length) write(spec.panel.empty || "-", R + 24, y + 100, f(22), "#15803d", "left", RIGHT_W - 48);
      spec.panel.rows.forEach((row, i) => {
        const ry = y + 100 + i * 52;
        if (i) { g.fillStyle = "#eef2f7"; g.fillRect(R + 24, ry - 34, RIGHT_W - 48, 2); }
        g.font = f(22, 700);
        const rw = Math.min(220, g.measureText(String(row.right)).width);
        write(row.left, R + 24, ry, f(22), "#1e293b", "left", RIGHT_W - 72 - rw);
        write(row.right, R + RIGHT_W - 24, ry, f(22, 700), (TONE[row.tone] || TONE.red).ink, "right", 220);
      });
    }

    write(`Smart Parking · ${spec.footer || "NASLINK Solutions"}`, PAD, H - 18, f(18), "#94a3b8");
    write(location.host, W - PAD, H - 18, f(18), "#94a3b8", "right");
    return c;
  }

  const canvasBlob = (c) => new Promise((resolve) => c.toBlob(resolve, "image/png"));

  // คัดลอกภาพไปคลิปบอร์ด (วางใน LINE ด้วย Ctrl+V) · มือถือ/เบราว์เซอร์ที่คัดลอกภาพไม่ได้ → เปิดเมนูแชร์ หรือบันทึกไฟล์แทน
  // รับ spec หรือ Promise ของ spec — เรียก clipboard.write ทันทีตอนกดปุ่ม (Safari/Chrome ต้องอยู่ในจังหวะที่ผู้ใช้กด)
  async function copyCard(specOrPromise) {
    const specP = Promise.resolve(specOrPromise);
    const canvasP = specP.then(statusCard);
    if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write && window.isSecureContext) {
      try {
        await navigator.clipboard.write([new ClipboardItem({ "image/png": canvasP.then(canvasBlob) })]);
        return "copied";
      } catch (e) { /* ตกไปใช้วิธีถัดไป */ }
    }
    const spec = await specP;
    const c = await canvasP;
    const name = `${spec.filename || "smart-parking"}-${stamp()}.png`;
    const blob = await canvasBlob(c);
    const file = new File([blob], name, { type: "image/png" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file], title: spec.subtitle || "Smart Parking" }); return "shared"; } catch (e) { /* ผู้ใช้ยกเลิก */ return "cancel"; }
    }
    downloadCanvas(c, name);
    return "downloaded";
  }

  function downloadCanvas(c, name) {
    const a = document.createElement("a");
    a.href = c.toDataURL("image/png");
    a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
  }

  function bindTools(el, h) {
    if (!el || el.dataset.bound) return;
    el.dataset.bound = "1";
    const msg = el.querySelector(".pt-msg");
    const say = (text, bad) => {
      msg.textContent = text; msg.classList.toggle("bad", !!bad);
      clearTimeout(el._t); el._t = setTimeout(() => (msg.textContent = ""), 4000);
    };
    el.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-act]");
      if (!btn) return;
      const act = btn.dataset.act;
      try {
        if (act === "refresh") { await h.refresh(); return; }
        if (act === "line") {
          // ภาพสรุปสถานะ ณ ตอนนี้ → คลิปบอร์ด แล้วไปวางในแชต LINE (ไม่มี h.card → ใช้ข้อความแบบเดิม)
          if (!h.card) { await copyText(await h.lineText()); say("คัดลอกข้อความแล้ว — เปิด LINE แล้วกดวาง"); return; }
          btn.disabled = true;
          try {
            const how = await copyCard(h.card());
            say({ copied: "คัดลอกรูปแล้ว — เปิดแชต LINE แล้วกด Ctrl+V (มือถือ: กดค้างแล้ววาง)", shared: "ส่งรูปแล้ว",
                  downloaded: "เบราว์เซอร์นี้คัดลอกรูปไม่ได้ — บันทึกเป็นไฟล์แทน แล้วแนบใน LINE", cancel: "ยกเลิก" }[how]);
          } finally { btn.disabled = false; }
          return;
        }
        if (act === "image") {
          if (h.card) { const spec = await h.card(); downloadCanvas(await statusCard(spec), `${spec.filename || "smart-parking"}-${stamp()}.png`); }
          else await saveImage(await (h.imageSpec || h.spec)(), h.image ? await h.image() : null);
          say("บันทึกรูปแล้ว (โฟลเดอร์ดาวน์โหลด)"); return;
        }
        await run(act, await h.spec());
      } catch (err) {
        say(err.message || String(err), true);
      }
    });
  }

  function markUpdated(el) {
    const t = el && el.querySelector(".pt-time");
    if (t) t.textContent = new Date().toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  window.ExportKit = { run, excel, print: printView, copyText, saveImage, bindTools, markUpdated, thaiNow, statusCard, copyCard };
})();
