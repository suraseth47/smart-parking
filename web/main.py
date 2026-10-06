"""จุดเริ่มต้นของ web service (FastAPI)"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web.ip_allowlist import IPAllowlistMiddleware
from web.routers import (
    admin_pages,
    audit,
    auth,
    calibration,
    cameras,
    health,
    live,
    override,
    public,
    reports,
    settings,
    slots,
    validation,
    zones,
)

app = FastAPI(title="Smart Parking")
app.add_middleware(IPAllowlistMiddleware)  # NFR-12: จำกัด IP เข้าหลังบ้าน (ตั้งค่าได้ผ่าน UI)
app.include_router(auth.router)
app.include_router(cameras.router)
app.include_router(zones.router)
app.include_router(slots.router)
app.include_router(health.router)
app.include_router(live.router)
app.include_router(override.router)
app.include_router(reports.router)
app.include_router(audit.router)
app.include_router(validation.router)
app.include_router(calibration.router)
app.include_router(settings.router)
app.include_router(admin_pages.router)
app.include_router(public.router)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
