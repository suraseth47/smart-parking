// ช่องวันที่แบบ วว/ดด/ปปปป (dd/mm/yyyy) ทั้งโปรแกรม
//
// ช่อง <input type="date"> / "datetime-local" ของเบราว์เซอร์แสดงตามภาษาของเครื่อง (เครื่องภาษาอังกฤษ US = mm/dd/yyyy)
// สคริปต์นี้ซ่อนช่องเดิมไว้ แล้ววางช่องข้อความ dd/mm/yyyy (และ HH:MM สำหรับช่องที่มีเวลา) แทน พร้อมปุ่มปฏิทิน
// ช่องเดิมยังอยู่และเก็บค่าแบบเดิม (yyyy-mm-dd) — x-model / @change ในหน้าต่าง ๆ ไม่ต้องแก้ และ server ได้ค่าเหมือนเดิม
// แสดงปีเป็น พ.ศ. (เหมือน CCTV Manager) — พิมพ์ได้ทั้ง พ.ศ. และ ค.ศ. (ปีต่ำกว่า 2400 ถือเป็น ค.ศ.)

(function () {
  const pad = (n) => String(n).padStart(2, "0");

  // yyyy-mm-dd[Thh:mm] (ค.ศ.) -> dd/mm/ปปปป[ hh:mm] (พ.ศ.)
  function toDisplay(value, withTime) {
    const m = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/);
    if (!m) return "";
    const date = `${m[3]}/${m[2]}/${Number(m[1]) + 543}`;
    return withTime ? `${date} ${m[4] || "00"}:${m[5] || "00"}` : date;
  }

  // dd/mm/yyyy[ hh:mm] -> yyyy-mm-dd[Thh:mm]; คืน null ถ้ารูปแบบผิด, "" ถ้าว่าง
  function toValue(text, withTime) {
    const s = String(text || "").trim();
    if (!s) return "";
    const m = s.match(/^(\d{1,2})[\/.\-](\d{1,2})[\/.\-](\d{2,4})(?:\s+(\d{1,2})[:.](\d{2}))?$/);
    if (!m) return null;
    let [day, month, year] = [Number(m[1]), Number(m[2]), Number(m[3])];
    if (year < 100) year += 2000;
    if (year >= 2400) year -= 543; // ปี พ.ศ.
    const d = new Date(year, month - 1, day);
    if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day) return null;
    const date = `${year}-${pad(month)}-${pad(day)}`;
    if (!withTime) return date;
    const hh = m[4] !== undefined ? Number(m[4]) : 0;
    const mm = m[5] !== undefined ? Number(m[5]) : 0;
    if (hh > 23 || mm > 59) return null;
    return `${date}T${pad(hh)}:${pad(mm)}`;
  }

  function enhance(input) {
    if (input.dataset.ddmm) return;
    input.dataset.ddmm = "1";
    const withTime = input.type === "datetime-local";

    const wrap = document.createElement("span");
    wrap.className = "ddmm-field" + (withTime ? " with-time" : "");
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    const text = document.createElement("input");
    text.type = "text";
    text.inputMode = "numeric";
    text.autocomplete = "off";
    text.className = "ddmm-text";
    text.placeholder = withTime ? "วว/ดด/ปปปป ชช:นน" : "วว/ดด/ปปปป";
    text.setAttribute("aria-label", (input.getAttribute("aria-label") || "") + " (วัน/เดือน/ปี)");
    if (input.id) { text.id = input.id; input.id = input.id + "-native"; } // label for="..." ชี้มาที่ช่องที่พิมพ์ได้
    if (input.style.width) text.style.width = input.style.width;
    wrap.insertBefore(text, input);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ddmm-btn";
    btn.tabIndex = -1;
    btn.setAttribute("aria-label", "เลือกจากปฏิทิน");
    btn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>';
    wrap.appendChild(btn);

    input.classList.add("ddmm-native");
    input.tabIndex = -1;
    input.setAttribute("aria-hidden", "true");

    // ค่าในช่องเดิมเปลี่ยนจากโค้ด (x-model, ปุ่มลัด 7 วัน ฯลฯ) -> อัปเดตช่องที่แสดง
    const proto = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
    Object.defineProperty(input, "value", {
      configurable: true,
      get() { return proto.get.call(this); },
      set(v) { proto.set.call(this, v); if (document.activeElement !== text) text.value = toDisplay(v, withTime); text.classList.remove("invalid"); },
    });
    text.value = toDisplay(input.value, withTime);

    const commit = () => {
      const v = toValue(text.value, withTime);
      if (v === null) { text.classList.add("invalid"); text.title = "รูปแบบวันที่ไม่ถูกต้อง ใช้ วว/ดด/ปปปป เช่น 31/10/2569"; return; }
      text.classList.remove("invalid"); text.title = "";
      if (v !== input.value) {
        proto.set.call(input, v);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
      text.value = toDisplay(v, withTime);
    };
    text.addEventListener("change", commit);
    text.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } });

    // เลือกจากปฏิทินของเบราว์เซอร์ -> แสดงเป็น dd/mm/yyyy
    input.addEventListener("change", () => { text.value = toDisplay(input.value, withTime); text.classList.remove("invalid"); });
    btn.addEventListener("click", () => {
      try { input.showPicker(); } catch (e) { input.focus(); input.click(); }
    });

    // ซิงก์สถานะปิดใช้งาน
    const syncDisabled = () => { text.disabled = input.disabled; btn.disabled = input.disabled; };
    syncDisabled();
    new MutationObserver(syncDisabled).observe(input, { attributes: true, attributeFilter: ["disabled"] });
  }

  function scan(root) {
    (root.querySelectorAll ? root.querySelectorAll('input[type="date"], input[type="datetime-local"]') : []).forEach(enhance);
  }

  function start() {
    scan(document);
    // ช่องที่เกิดทีหลัง (Alpine x-if, แท็บ, หน้าต่างแก้ไข)
    new MutationObserver((list) => list.forEach((m) => m.addedNodes.forEach((n) => {
      if (n.nodeType !== 1) return;
      if (n.matches && n.matches('input[type="date"], input[type="datetime-local"]')) enhance(n);
      else scan(n);
    }))).observe(document.body, { childList: true, subtree: true });
  }

  window.DateDDMM = { toDisplay, toValue };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
