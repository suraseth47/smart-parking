// แถบขั้นตอน ① ② ③ (ใช้ทุกหน้าที่ทำงานเป็นลำดับ) — ดูมาตรฐานใน naslink-app-standards
//
// StepBar.render(el, ["ดึงภาพ", "วาดช่อง", "Publish"], activeIndex, "ข้อความบอกว่าต้องกดอะไรต่อ")
//   activeIndex: ขั้นที่กำลังทำ (0 = ขั้นแรก) · ขั้นก่อนหน้าแสดง ✓ · ส่ง steps.length = ทำครบแล้ว
//   hint: (ไม่บังคับ) ข้อความใต้แถบ เช่น "กดปุ่ม + วาดช่องใหม่ แล้วคลิก 4 มุมของช่อง"
//   action: (ไม่บังคับ) ลิงก์ไปหน้าถัดไป {href: "/admin/layout?camera_id=1", label: "ไปหน้ากำหนดช่องจอด →"}
// หน้า Alpine ใช้ markup เดียวกันได้ตรง ๆ (class: stepbar / steps / step done|active / step-num / step-label)
(function () {
  const esc = (t) => String(t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function render(el, steps, active, hint, action) {
    if (!el) return;
    const items = steps.map((label, i) => {
      const cls = i < active ? "done" : i === active ? "active" : "";
      const num = i < active ? "✓" : String(i + 1);
      const sep = i < steps.length - 1 ? '<li class="step-sep" aria-hidden="true">›</li>' : "";
      return `<li class="step ${cls}"${i === active ? ' aria-current="step"' : ""}><span class="step-num">${num}</span><span class="step-label">${esc(label)}</span></li>${sep}`;
    }).join("");
    const done = active >= steps.length;
    el.classList.add("stepbar");
    el.innerHTML = `<ol class="steps">${items}</ol>` +
      (hint ? `<div class="step-hint${done ? " is-done" : ""}"><span>${done ? "✅" : "👉"} ${esc(hint)}</span>` +
        (action && /^\/[^/]/.test(action.href) ? ` <a class="step-action" href="${esc(action.href)}">${esc(action.label)}</a>` : "") +
        `</div>` : "");
  }

  // ลำดับตั้งค่าลานจอดใหม่ (ข้ามหลายหน้า): สถานที่ → โซน → กล้อง → วาดช่อง + Publish
  // ใส่ <div data-setup-guide="sites|zones|cameras"></div> ในหน้า แล้วสคริปต์นี้เติมให้เอง
  // ขั้นที่ทำแล้วดูจากข้อมูลจริง · ไม่มีสิทธิ์เรียก API = ไม่แสดง
  async function mountSetupGuide(el) {
    const get = async (url) => {
      const resp = await fetch(url, { credentials: "same-origin" });
      if (!resp.ok) throw new Error(String(resp.status));
      return resp.json();
    };
    let sites, zones, cameras;
    try {
      [sites, zones, cameras] = await Promise.all([get("/api/admin/sites"), get("/api/admin/zones"), get("/api/admin/cameras")]);
    } catch (e) {
      el.remove();
      return;
    }
    const enabled = cameras.filter((c) => c.enabled && c.counted !== false);  // ไม่นับกล้องทดสอบ
    const noSlots = enabled.find((c) => !c.slot_count);
    const notPublished = enabled.find((c) => c.slot_count && !c.reference_image_path);
    const steps = ["สร้างสถานที่", "สร้างโซน", "เพิ่มกล้อง", "วาดช่องจอด + Publish"];
    let active, hint, action;
    if (!sites.length) {
      active = 0; hint = "เริ่มจากสร้างสถานที่ (ลานจอด 1 แห่ง) — ชื่อ ที่อยู่ เวลาเปิด และพิกัดสำหรับนำทาง";
      action = { href: "/admin/sites", label: "ไปหน้าสถานที่ →" };
    } else if (!zones.length) {
      active = 1; hint = "สร้างโซนในสถานที่ (เช่น A ลานหน้าอาคาร) — ช่องจอดทุกช่องต้องอยู่ในโซน";
      action = { href: "/admin/zones", label: "ไปหน้าโซน →" };
    } else if (!enabled.length) {
      active = 2; hint = "เพิ่มกล้อง: กด \"+ เพิ่มกล้อง\" กรอกยี่ห้อ IP Username/Password แล้วกด \"ทดสอบการเชื่อมต่อ\" ก่อนบันทึก";
      action = { href: "/admin", label: "ไปหน้ากล้อง →" };
    } else if (noSlots || notPublished) {
      const cam = noSlots || notPublished;
      active = 3;
      hint = noSlots
        ? `กล้อง "${cam.name}" ยังไม่มีช่องจอด — กดปุ่ม "กำหนดช่องจอด" ของกล้อง แล้ววาดช่อง → Preview → Publish`
        : `กล้อง "${cam.name}" วาดช่องแล้วแต่ยังไม่ Publish — เปิดหน้ากำหนดช่อง กด Preview ตรวจ แล้วกด Publish`;
      action = { href: `/admin/layout?camera_id=${cam.id}`, label: "ไปกำหนดช่องจอด →" };
    } else {
      active = 4;
      hint = `ตั้งค่าครบแล้ว: ${sites.length} สถานที่ · ${zones.length} โซน · ${enabled.length} กล้อง — ลานใหม่เริ่มที่ขั้นที่ 1 ได้เลย`;
    }
    const current = { sites: 0, zones: 1, cameras: 2 }[el.dataset.setupGuide];
    if (action && current === active) action = null;  // อยู่หน้านั้นแล้ว ไม่ต้องมีลิงก์
    el.classList.add("setup-guide");
    render(el, steps, active, hint, action);
    const title = document.createElement("div");
    title.className = "setup-guide-title";
    title.textContent = "ลำดับการตั้งค่าลานจอดใหม่";
    el.prepend(title);
  }

  function mountAll() { document.querySelectorAll("[data-setup-guide]").forEach(mountSetupGuide); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mountAll);
  else mountAll();

  window.StepBar = { render, refreshSetupGuide: mountAll };
})();
