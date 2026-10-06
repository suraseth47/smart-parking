"""จุดเริ่มต้นของ web service (FastAPI)"""
from fastapi import FastAPI

from web.routers import auth, cameras, zones

app = FastAPI(title="Smart Parking")
app.include_router(auth.router)
app.include_router(cameras.router)
app.include_router(zones.router)
