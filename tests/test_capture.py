import pytest

from worker.capture import grab_frame


def test_grab_frame_missing_image_raises_runtime_error():
    with pytest.raises(RuntimeError):
        grab_frame("data/samples/this_file_does_not_exist.jpg")


def test_grab_frame_missing_video_raises_runtime_error():
    with pytest.raises(RuntimeError):
        grab_frame("data/samples/this_file_does_not_exist.mp4")


def test_grab_frame_valid_image_returns_array():
    frame = grab_frame("data/samples/sample_frame.jpg")
    assert frame.ndim == 3
    assert frame.shape[2] == 3
