"""requirements.txt (ใช้ build Docker image) ต้องตรงกับ pyproject.toml เสมอ"""
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_requirements_txt_matches_pyproject_dependencies():
    with open(PROJECT_ROOT / "pyproject.toml", "rb") as f:
        pyproject = tomllib.load(f)
    pyproject_deps = set(pyproject["project"]["dependencies"])

    with open(PROJECT_ROOT / "requirements.txt", encoding="utf-8") as f:
        requirements = {line.strip() for line in f if line.strip() and not line.startswith("#")}

    assert requirements == pyproject_deps, (
        f"requirements.txt ไม่ตรงกับ pyproject.toml — "
        f"ขาด: {pyproject_deps - requirements}, เกิน: {requirements - pyproject_deps}"
    )
