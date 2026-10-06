from worker.camera_connection import classify_ffmpeg_error


def test_classify_auth_error():
    stderr = "method DESCRIBE failed: 401 Unauthorized"
    assert "รหัสผ่าน" in classify_ffmpeg_error(stderr)


def test_classify_stream_not_found():
    stderr = "HTTP error 404 Not Found"
    assert "ไม่พบ stream" in classify_ffmpeg_error(stderr)


def test_classify_timeout():
    stderr = "Connection to tcp://192.168.1.10:554 timed out"
    assert "timeout" in classify_ffmpeg_error(stderr) or "หมดเวลา" in classify_ffmpeg_error(stderr)


def test_classify_connection_refused():
    stderr = "tcp://192.168.1.10:554: Connection refused"
    assert "ปฏิเสธ" in classify_ffmpeg_error(stderr)


def test_classify_unknown_error_has_fallback_message():
    assert classify_ffmpeg_error("some unexpected ffmpeg output") != ""
