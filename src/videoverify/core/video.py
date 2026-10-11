"""Local FFprobe / FFmpeg inspection utilities.

Do not pass user input through a shell. Only local MP4 files under the
configured allowed directory are accepted.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


class InspectionError(Exception):
    """Expected inspection failure with a machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def allowed_root() -> Path:
    configured = os.environ.get("VIDEOVERIFY_ALLOWED_DIR")
    if not configured:
        raise InspectionError(
            "NOT_CONFIGURED",
            "Set VIDEOVERIFY_ALLOWED_DIR to the directory containing allowed videos.",
        )
    root = Path(configured).expanduser().resolve()
    if not root.is_dir():
        raise InspectionError("INVALID_ROOT", "VIDEOVERIFY_ALLOWED_DIR is not a directory.")
    return root


def resolve_video(video_path: str, root: Path) -> Path:
    if not video_path or not isinstance(video_path, str):
        raise InspectionError("INVALID_PATH", "video_path must be a non-empty string.")
    candidate = Path(video_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    path = candidate.resolve()
    if not path.is_relative_to(root.resolve()):
        raise InspectionError("PATH_NOT_ALLOWED", "Video must be inside VIDEOVERIFY_ALLOWED_DIR.")
    if path.suffix.lower() != ".mp4":
        raise InspectionError("UNSUPPORTED_FORMAT", "Only .mp4 files are supported.")
    if not path.is_file():
        raise InspectionError("FILE_NOT_FOUND", "Video file does not exist.")
    return path


def run_command(arguments: list[str]) -> bytes:
    executable = shutil.which(arguments[0])
    if executable is None:
        raise InspectionError("DEPENDENCY_MISSING", f"{arguments[0]} was not found on PATH.")
    try:
        result = subprocess.run(
            [executable, *arguments[1:]], capture_output=True, timeout=45, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise InspectionError("PROCESS_TIMEOUT", "Media processing exceeded 45 seconds.") from exc
    except OSError as exc:
        raise InspectionError("PROCESS_ERROR", f"Could not launch {arguments[0]}.") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[-500:]
        raise InspectionError("MEDIA_PROCESSING_FAILED", detail or "Media processing failed.")
    return result.stdout


def inspect_media(video_path: str, timestamp: float) -> dict:
    root = allowed_root()
    path = resolve_video(video_path, root)
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        raise InspectionError("INVALID_TIMESTAMP", "timestamp must be a number in seconds.")
    import math
    if not math.isfinite(timestamp) or timestamp < 0:
        raise InspectionError("INVALID_TIMESTAMP", "timestamp must be finite and non-negative.")

    raw = run_command([
        "ffprobe", "-v", "error", "-show_format", "-show_streams",
        "-of", "json", str(path)
    ])
    try:
        metadata = json.loads(raw)
        duration = float(metadata["format"]["duration"])
    except (ValueError, KeyError, TypeError) as exc:
        raise InspectionError("INVALID_MEDIA", "Unable to determine video duration.") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise InspectionError("INVALID_MEDIA", "Video duration is invalid.")
    if timestamp >= duration:
        raise InspectionError("TIMESTAMP_OUT_OF_RANGE", "Timestamp must be before video end.")

    streams = metadata.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video_stream is None:
        raise InspectionError("NO_VIDEO_STREAM", "MP4 does not contain a video stream.")
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    # Artifacts live in a temporary directory; the MCP caller receives absolute paths.
    artifact_dir = Path(tempfile.mkdtemp(prefix="videoverify-"))
    frame_path = artifact_dir / "frame.jpg"
    audio_path = artifact_dir / "audio.wav" if has_audio else None
    try:
        run_command([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-ss", str(timestamp), "-i", str(path), "-frames:v", "1", str(frame_path)
        ])
        if not frame_path.is_file() or frame_path.stat().st_size == 0:
            raise InspectionError("FRAME_EXTRACTION_FAILED", "No frame was produced.")
        if has_audio:
            # Up to two seconds of audio starting at the requested position.
            run_command([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-ss", str(timestamp), "-i", str(path),
                "-t", str(min(2.0, duration - timestamp)),
                "-vn", "-ac", "1", "-ar", "16000", str(audio_path)
            ])
            if not audio_path.is_file() or audio_path.stat().st_size == 0:
                raise InspectionError("AUDIO_EXTRACTION_FAILED", "No audio was produced.")
    except Exception:
        shutil.rmtree(artifact_dir, ignore_errors=True)
        raise

    return {
        "ok": True,
        "video_path": str(path),
        "timestamp_seconds": float(timestamp),
        "duration_seconds": duration,
        "video": {
            "codec": video_stream.get("codec_name"),
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "frame_rate": video_stream.get("avg_frame_rate"),
        },
        "has_audio": has_audio,
        "evidence": {
            "frame_path": str(frame_path),
            "audio_path": str(audio_path) if audio_path else None,
            "artifact_directory": str(artifact_dir),
        },
        "limitations": [
            "This tool extracts evidence only; it does not assess content quality.",
            "Artifacts are temporary files; consumers should copy them if persistence is needed.",
        ],
    }
