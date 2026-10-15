import base64
from pathlib import Path
import subprocess

import pytest

from videoverify.core import Inspector, InspectionError


def test_actual_sequence_pixels_and_duplicate_frame_mapping(media, tmp_path):
    engine = Inspector([media["root"]], tmp_path / "out")
    result = engine.inspect_sequence(str(media["silent"]), [0.11, 0.15, 1.3])
    assert [frame["frame_index"] for frame in result["frames"]] == [1, 13]
    assert result["frames"][0]["requested_seconds"] == [0.11, 0.15]
    for frame, color in zip(result["frames"], (0, 2)):
        pixels = subprocess.check_output(["ffmpeg", "-v", "error", "-i", frame["path"],
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
        assert pixels[color] > 200 and pixels[2 - color] < 30
    assert engine.read_artifact(result["inspection_id"], "frame-000.png").startswith(b"\x89PNG")


@pytest.mark.parametrize("timestamps", [[], [0] * 25, [1, 0], [0, float("nan")], [True], [-1]])
def test_invalid_sequences_make_no_artifacts(media, tmp_path, timestamps):
    engine = Inspector([media["root"]], tmp_path / "out")
    with pytest.raises(InspectionError) as failure:
        engine.inspect_sequence(str(media["silent"]), timestamps)
    assert failure.value.code == "invalid_timestamps" and not list(engine.output.iterdir())


def test_sequence_failed_decode_cleans(media, tmp_path, monkeypatch):
    engine = Inspector([media["root"]], tmp_path / "out")
    original = engine._run
    def fail(program, args):
        if program == "ffmpeg":
            raise InspectionError("media_processing_failed", "fixture failure")
        return original(program, args)
    monkeypatch.setattr(engine, "_run", fail)
    with pytest.raises(InspectionError):
        engine.inspect_sequence(str(media["silent"]), [0, 1])
    assert not list(engine.output.iterdir())
