// ฟังก์ชันช่วยเรียก API หลังบ้าน แนบ CSRF token อัตโนมัติ (double-submit cookie ตาม FR-40)

function getCookie(name) {
  const match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
  return match ? decodeURIComponent(match[2]) : null;
}

async function apiFetch(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  const method = (options.method || "GET").toUpperCase();

  if (method !== "GET") {
    const csrf = getCookie("csrf_token");
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const resp = await fetch(path, Object.assign({}, options, { headers, credentials: "same-origin" }));
  if (resp.status === 401 && !path.endsWith("/whoami")) {
    window.location.href = "/admin/login";
  }
  return resp;
}

async function apiJson(path, options = {}) {
  const resp = await apiFetch(path, options);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const error = new Error(data.detail || `คำขอล้มเหลว (${resp.status})`);
    error.status = resp.status;
    error.data = data;
    throw error;
  }
  return data;
}

// เรียกตอนโหลดหน้าหลังบ้านทุกหน้า (ยกเว้นหน้า login) เพื่อเช็คว่า login อยู่ไหม
async function requireAuth() {
  const resp = await apiFetch("/api/admin/whoami");
  if (!resp.ok) {
    window.location.href = "/admin/login";
    return null;
  }
  return resp.json();
}

async function logout() {
  await apiFetch("/api/admin/logout", { method: "POST" });
  window.location.href = "/admin/login";
}
