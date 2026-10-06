"""จุดเริ่มต้นของ web service (FastAPI)"""
from fastapi import FastAPI

from web.routers import auth

app = FastAPI(title="Smart Parking")
app.include_router(auth.router)
