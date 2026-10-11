"""First milestone integration and validation tests."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from videoverify.core.video import InspectionError, inspect_media, resolve_video


def test_rejects_parent_traversal(tmp_path):
    with pytest.raises(InspectionError) as exc_info:
        resolve_video("../outside.mp4", tmp_path)
    assert exc_info.value.code == "PATH_NOT_ALLOWED"


def test_rejects_invalid_extension(tmp_path):
    with pytest.raises(InspectionError) as err:
        resolve_video("video.mov", tmp_path)
    assert err.value.code == "UNSUPPORTED_FORMAT"


def test_requires_allowed_directory(monkeypatch):
    monkeypatch.delenv("VIDEOVERIFY_ALLOWED_DIR", raising=False)
    with pytest.raises(InspectionError) as err:
        inspect_media("video.mp4", 0)
    assert err.value.code == "NOT_CONFIGURED"


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="FFmpeg required")
def test_inspect_generated_video(tmp_path, monkeypatch):
    """Synthetic one-second video with no audio keeps the test redistributable."""
    file = tmp_path / "fixture.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=black:s=160x120:r=10:d=1",
         "-c:v", "mpeg4", str(file)],
        check=True, timeout=30,
    )
    monkeypatch.setenv("VIDEOVERIFY_ALLOWED_DIR", str(tmp_path))
    result = inspect_media("fixture.mp4", 0.25)
    assert result["ok"] is True
    assert result["video"]["width"] == 160
    assert result["has_audio"] is False
    assert result["evidence"]["audio_path"] is None
    assert Path(result["evidence"]["frame_path"]).is_file()
    shutil.rmtree(result["evidence"]["artifact_directory"])


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="FFmpeg required")
def test_timestamp_outside_video(tmp_path, monkeypatch):
    file = tmp_path / "fixture.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=black:s=160x120:r=10:d=1",
         "-c:v", "mpeg4", str(file)],
        check=True, timeout=30,
    )
    monkeypatch.setenv("VIDEOVERIFY_ALLOWED_DIR", str(tmp_path))
    with pytest.raises(InspectionError) as err:
        inspect_media("fixture.mp4", 100)
    assert err.value.code == "TIMESTAMP_OUT_OF_RANGE"
