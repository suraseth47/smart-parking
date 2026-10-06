"""ตั้งค่าระบบ: จำกัด IP เข้าหลังบ้านผ่าน UI (NFR-12, P4)"""
from __future__ import annotations

import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import AuditLog, Setting
from web.deps import CurrentUser, require_admin, verify_csrf
from web.ip_allowlist import IP_ALLOWLIST_SETTING_KEY

router = APIRouter(prefix="/api/admin/settings", tags=["settings"])


class IpAllowlistIn(BaseModel):
    enabled: bool
    ips: list[str]


class IpAllowlistOut(BaseModel):
    enabled: bool
    ips: list[str]


class SettingsOut(BaseModel):
    ip_allowlist: IpAllowlistOut
    your_ip: str


@router.get("", response_model=SettingsOut)
def get_settings_api(
    request: Request, db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)
):
    setting = db.get(Setting, IP_ALLOWLIST_SETTING_KEY)
    value = setting.value if setting else {"enabled": False, "ips": []}
    return SettingsOut(
        ip_allowlist=IpAllowlistOut(enabled=value.get("enabled", False), ips=value.get("ips", [])),
        your_ip=request.client.host if request.client else "",
    )


@router.put("/ip-allowlist", response_model=IpAllowlistOut)
def update_ip_allowlist(
    data: IpAllowlistIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    invalid = [entry for entry in data.ips if not _is_valid_ip_or_cidr(entry)]
    if invalid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"รูปแบบ IP/CIDR ไม่ถูกต้อง: {', '.join(invalid)}")

    setting = db.get(Setting, IP_ALLOWLIST_SETTING_KEY)
    value = {"enabled": data.enabled, "ips": data.ips}
    if setting is None:
        setting = Setting(key=IP_ALLOWLIST_SETTING_KEY, value=value)
        db.add(setting)
    else:
        setting.value = value

    db.add(
        AuditLog(
            user_id=admin.id,
            action="update_ip_allowlist",
            target="settings:ip_allowlist",
            detail=value,
        )
    )
    db.commit()
    return IpAllowlistOut(**value)


def _is_valid_ip_or_cidr(entry: str) -> bool:
    try:
        ipaddress.ip_network(entry, strict=False)
        return True
    except ValueError:
        return False
