import pytest

from core.models import CameraBrand, CameraStream
from core.rtsp import build_rtsp_url


def test_hikvision_main_stream():
    url = build_rtsp_url(
        CameraBrand.HIKVISION, "192.168.1.10", 554, 1, CameraStream.MAIN, "admin", "pass123", None
    )
    assert url == "rtsp://admin:pass123@192.168.1.10:554/Streaming/Channels/101"


def test_hikvision_sub_stream():
    url = build_rtsp_url(
        CameraBrand.HIKVISION, "192.168.1.10", 554, 2, CameraStream.SUB, "admin", "pass123", None
    )
    assert url == "rtsp://admin:pass123@192.168.1.10:554/Streaming/Channels/202"


def test_dahua_main_stream():
    url = build_rtsp_url(
        CameraBrand.DAHUA, "192.168.1.11", 554, 1, CameraStream.MAIN, "admin", "pass123", None
    )
    assert url == "rtsp://admin:pass123@192.168.1.11:554/cam/realmonitor?channel=1&subtype=0"


def test_dahua_sub_stream():
    url = build_rtsp_url(
        CameraBrand.DAHUA, "192.168.1.11", 554, 3, CameraStream.SUB, "admin", "pass123", None
    )
    assert url == "rtsp://admin:pass123@192.168.1.11:554/cam/realmonitor?channel=3&subtype=1"


def test_custom_uses_given_url():
    custom = "rtsp://custom.example.com/stream1"
    url = build_rtsp_url(CameraBrand.CUSTOM, "ignored", 554, 1, CameraStream.MAIN, "u", "p", custom)
    assert url == custom


def test_custom_without_url_raises():
    with pytest.raises(ValueError):
        build_rtsp_url(CameraBrand.CUSTOM, "ignored", 554, 1, CameraStream.MAIN, "u", "p", None)


def test_special_characters_in_password_are_encoded():
    url = build_rtsp_url(
        CameraBrand.HIKVISION, "192.168.1.10", 554, 1, CameraStream.MAIN, "admin", "Adm@n#1:x", None
    )
    assert url == "rtsp://admin:Adm%40n%231%3Ax@192.168.1.10:554/Streaming/Channels/101"


def test_tvt_main_and_sub_stream():
    main = build_rtsp_url(CameraBrand.TVT, "192.168.1.30", 554, 1, CameraStream.MAIN, "admin", "P@ss#1", None)
    sub = build_rtsp_url(CameraBrand.TVT, "192.168.1.30", 554, 1, CameraStream.SUB, "admin", "P@ss#1", None)
    assert main == "rtsp://admin:P%40ss%231@192.168.1.30:554/profile1"
    assert sub == "rtsp://admin:P%40ss%231@192.168.1.30:554/profile2"
