"""หน้าเว็บหลังบ้าน (HTML) — ตรวจสิทธิ์จริงฝั่ง client ผ่าน requireAuth() ใน api.js

ไม่เช็ค session ฝั่ง server ตอน render หน้า (เพื่อความง่าย) — ถ้ายังไม่ login
หน้าจะเรียก /api/admin/whoami แล้วโดน redirect ไป /admin/login เอง
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from web.templates_env import templates

router = APIRouter(prefix="/admin", tags=["admin-pages"])


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "admin/login.html")


@router.get("")
def dashboard_page(request: Request):
    return templates.TemplateResponse(request, "admin/dashboard.html")


@router.get("/layout")
def layout_editor_page(request: Request):
    return templates.TemplateResponse(request, "admin/layout_editor.html")


@router.get("/live")
def live_page(request: Request):
    return templates.TemplateResponse(request, "admin/live.html")


@router.get("/cctv")
def cctv_page(request: Request):
    return templates.TemplateResponse(request, "admin/cctv.html")


@router.get("/override")
def override_page(request: Request):
    return templates.TemplateResponse(request, "admin/override.html")


@router.get("/reports")
def reports_page(request: Request):
    return templates.TemplateResponse(request, "admin/reports.html")


@router.get("/audit")
def audit_page(request: Request):
    return templates.TemplateResponse(request, "admin/audit.html")


@router.get("/validation")
def validation_page(request: Request):
    return templates.TemplateResponse(request, "admin/validation.html")


@router.get("/calibration")
def calibration_page(request: Request):
    return templates.TemplateResponse(request, "admin/calibration.html")


@router.get("/sites")
def sites_page(request: Request):
    return templates.TemplateResponse(request, "admin/sites.html")


@router.get("/alerts")
def alerts_page(request: Request):
    return templates.TemplateResponse(request, "admin/alerts.html")


@router.get("/zones")
def zones_page(request: Request):
    return templates.TemplateResponse(request, "admin/zones.html")


@router.get("/users")
def users_page(request: Request):
    return templates.TemplateResponse(request, "admin/users.html")


@router.get("/settings")
def settings_page(request: Request):
    return templates.TemplateResponse(request, "admin/settings.html")
