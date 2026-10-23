"""เลือกโมเดล AI ผ่าน .env (DETECTOR_MODEL) และกลับไปใช้ yolox_s เมื่อไม่พบไฟล์"""
import core.config as config


def _path_for(monkeypatch, tmp_path, env_value, files):
    for name in files:
        (tmp_path / name).write_bytes(b"x")
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setenv("DETECTOR_MODEL", env_value)
    config.get_settings.cache_clear()
    try:
        return config.get_detector_model_path()
    finally:
        config.get_settings.cache_clear()


def test_uses_model_from_env_when_file_exists(monkeypatch, tmp_path):
    path = _path_for(monkeypatch, tmp_path, "yolox_m.onnx", ["yolox_s.onnx", "yolox_m.onnx"])
    assert path.name == "yolox_m.onnx"


def test_falls_back_to_yolox_s_when_file_missing(monkeypatch, tmp_path):
    path = _path_for(monkeypatch, tmp_path, "yolox_m.onnx", ["yolox_s.onnx"])
    assert path.name == "yolox_s.onnx"


def test_ignores_directories_in_env_value(monkeypatch, tmp_path):
    path = _path_for(monkeypatch, tmp_path, "../../etc/yolox_m.onnx", ["yolox_s.onnx", "yolox_m.onnx"])
    assert path == tmp_path / "yolox_m.onnx"
