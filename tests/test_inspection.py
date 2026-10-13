import json
from pathlib import Path
import subprocess
import sys
import wave

import pytest

from videoverify.core import Inspector, InspectionError, Limits, file_hash


def inspector(media, tmp_path):
    return Inspector([media["root"]], tmp_path / "evidence")


def test_actual_frame_and_audio(media, tmp_path):
    engine = inspector(media, tmp_path)
    result = engine.inspect(str(media["tone"]), 1.3, 1)
    assert result["ok"] and result["metadata"]["duration_seconds"] == pytest.approx(2)
    assert result["metadata"]["width"] == 160 and result["metadata"]["height"] == 90
    assert result["frame"]["frame_index"] == 13
    assert result["frame"]["actual_seconds"] == pytest.approx(1.3)
    assert result["source"]["sha256"] == file_hash(media["tone"])
    picture = Path(result["frame"]["path"])
    pixels = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(picture),
                                     "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    assert pixels[2] > 200 and pixels[0] < 30  # The actual blue frame, not just a file existing.
    assert result["audio"]["status"] == "extracted"
    with wave.open(result["audio"]["path"]) as wav:
        assert wav.getnchannels() == 1 and wav.getframerate() == 16000
        assert wav.getnframes() == pytest.approx(16000, abs=1)
        assert any(wav.readframes(wav.getnframes()))
    assert engine.read_artifact(result["inspection_id"], "frame.png") == picture.read_bytes()
    assert json.loads(engine.read_artifact(result["inspection_id"], "inspection.json"))["source"] == result["source"]


def test_absent_audio_is_not_a_defect(media, tmp_path):
    result = inspector(media, tmp_path).inspect(str(media["silent"]), 0)
    assert result["audio"]["status"] == "absent"
    assert "uri" not in result["audio"] and "not a defect" in result["audio"]["reason"]


def test_between_frames_and_final_frame(media, tmp_path):
    engine = inspector(media, tmp_path)
    assert engine.inspect(str(media["silent"]), 0.15)["frame"]["actual_seconds"] == pytest.approx(0.1)
    assert engine.inspect(str(media["silent"]), 1.99)["frame"]["actual_seconds"] == pytest.approx(1.9)


@pytest.mark.parametrize("timestamp,code", [(-1, "invalid_timestamp"), (float("nan"), "invalid_timestamp"),
    (float("inf"), "invalid_timestamp"), (True, "invalid_timestamp"), (2, "timestamp_out_of_range")])
def test_bad_timestamps(media, tmp_path, timestamp, code):
    engine = inspector(media, tmp_path)
    with pytest.raises(InspectionError) as error:
        engine.inspect(str(media["silent"]), timestamp)
    assert error.value.code == code
    assert not list(engine.output.iterdir())


def test_paths_and_symlinks(media, tmp_path):
    engine = inspector(media, tmp_path)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(media["silent"].read_bytes())
    link = media["root"] / "escape.mp4"
    link.symlink_to(outside)
    for path in (str(outside), str(link), str(media["root"] / ".." / "outside.mp4")):
        with pytest.raises(InspectionError) as error:
            engine.inspect(path, 0)
        assert error.value.code == "path_not_allowed"
    with pytest.raises(InspectionError, match="not a URL"):
        engine.inspect("https://example.com/video.mp4", 0)
    with pytest.raises(InspectionError) as error:
        engine.inspect(str(media["root"] / "missing.mp4"), 0)
    assert error.value.code == "file_not_found"


def test_dependencies_and_corruption(media, tmp_path, monkeypatch):
    engine = inspector(media, tmp_path)
    broken = media["root"] / "broken.mp4"
    broken.write_bytes(b"This is not an MP4.")
    with pytest.raises(InspectionError) as error:
        engine.inspect(str(broken), 0)
    assert error.value.code == "media_processing_failed"
    monkeypatch.setattr("videoverify.core.shutil.which", lambda _: None)
    with pytest.raises(InspectionError) as error:
        engine.inspect(str(media["silent"]), 0)
    assert error.value.code == "dependency_missing"


def test_limits_and_resource_escape(media, tmp_path):
    engine = Inspector([media["root"]], tmp_path / "evidence", Limits(max_bytes=1))
    with pytest.raises(InspectionError) as error:
        engine.inspect(str(media["silent"]), 0)
    assert error.value.code == "input_limit"
    for identity, filename in [("../other", "frame.png"), ("a" * 32, "../../outside")]:
        with pytest.raises(InspectionError) as error:
            engine.read_artifact(identity, filename)
        assert error.value.code == "artifact_not_allowed"


def test_unique_artifacts_and_cli(media, tmp_path):
    command = [sys.executable, "-m", "videoverify.cli", "inspect", str(media["silent"]),
        "--timestamp", "0.5", "--allow-root", str(media["root"]), "--output-root", str(tmp_path)]
    first = json.loads(subprocess.check_output(command))
    second = json.loads(subprocess.check_output(command))
    assert first["inspection_id"] != second["inspection_id"]
    failed = subprocess.run([*command[:-1], str(tmp_path), "--timestamp", "-1"], capture_output=True)
    assert failed.returncode == 2 and json.loads(failed.stdout)["error"]["code"] == "invalid_timestamp"


def test_changed_input_cleans_partial_evidence(media, tmp_path, monkeypatch):
    engine = inspector(media, tmp_path)
    original_hash = file_hash
    visits = 0

    def changing_hash(path):
        nonlocal visits
        if path == media["silent"]:
            visits += 1
            if visits == 2:
                return "changed"
        return original_hash(path)

    monkeypatch.setattr("videoverify.core.file_hash", changing_hash)
    with pytest.raises(InspectionError) as error:
        engine.inspect(str(media["silent"]), 0)
    assert error.value.code == "source_changed"
    assert not list(engine.output.iterdir())


def test_processing_timeout_and_duration_limit(media, tmp_path, monkeypatch):
    engine = Inspector([media["root"]], tmp_path / "short", Limits(max_duration_seconds=1))
    with pytest.raises(InspectionError) as error:
        engine.inspect(str(media["silent"]), 0)
    assert error.value.code == "input_limit"

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("ffprobe", 0.01)

    monkeypatch.setattr("videoverify.core.subprocess.run", timeout)
    with pytest.raises(InspectionError) as error:
        inspector(media, tmp_path).inspect(str(media["silent"]), 0)
    assert error.value.code == "processing_timeout"
