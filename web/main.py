"""จุดเริ่มต้นของ web service (FastAPI)"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web.routers import admin_pages, auth, cameras, health, public, slots, zones

app = FastAPI(title="Smart Parking")
app.include_router(auth.router)
app.include_router(cameras.router)
app.include_router(zones.router)
app.include_router(slots.router)
app.include_router(health.router)
app.include_router(admin_pages.router)
app.include_router(public.router)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
