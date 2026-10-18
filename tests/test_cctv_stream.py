from web.cctv_stream import prefer_substream, scaled_size


def test_dahua_main_to_substream():
    url = "rtsp://u:p@1.2.3.4:554/cam/realmonitor?channel=1&subtype=0"
    assert prefer_substream(url).endswith("channel=1&subtype=1")


def test_hikvision_main_to_substream():
    url = "rtsp://u:p@1.2.3.4:554/Streaming/Channels/101"
    assert prefer_substream(url).endswith("/Streaming/Channels/102")


def test_already_substream_unchanged():
    url = "rtsp://u:p@1.2.3.4:554/cam/realmonitor?channel=1&subtype=1"
    assert prefer_substream(url) == url


def test_other_url_unchanged():
    assert prefer_substream("rtsp://x/stream") == "rtsp://x/stream"


def test_scaled_size_keeps_ratio():
    assert scaled_size(1920, 1080, 960) == (960, 540)


def test_scaled_size_no_upscale():
    assert scaled_size(640, 360, 960) == (640, 360)
