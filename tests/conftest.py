from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Integration fixtures require FFmpeg and FFprobe")
    root = tmp_path_factory.mktemp("media")
    # Deterministic authored footage: red first second, blue second second.
    common = ["ffmpeg", "-nostdin", "-v", "error", "-threads", "2",
              "-f", "lavfi", "-i", "color=red:size=160x90:rate=10:duration=1",
              "-f", "lavfi", "-i", "color=blue:size=160x90:rate=10:duration=1"]
    graph = "[0:v][1:v]concat=n=2:v=1:a=0[v]"
    silent = root / "silent.mp4"
    tone = root / "tone.mp4"
    subprocess.run([*common, "-filter_complex", graph, "-map", "[v]", "-an",
                    "-c:v", "libx264", "-threads", "2", "-pix_fmt", "yuv420p", str(silent)], check=True)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-threads", "2",
                    "-i", str(silent), "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                    "-shortest", str(tone)], check=True)
    return {"root": root, "tone": tone, "silent": silent}
