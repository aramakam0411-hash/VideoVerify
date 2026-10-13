"""Bounded local inspection. No network input, editing, or subjective scoring."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import uuid
import wave


class InspectionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)

    def as_dict(self) -> dict:
        return {"ok": False, "error": {"code": self.code, "message": str(self)}}


@dataclass(frozen=True)
class Limits:
    max_bytes: int = 512 * 1024 * 1024
    max_duration_seconds: float = 600
    subprocess_timeout_seconds: float = 120


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Inspector:
    """Roots are trusted operator configuration, never supplied by MCP callers."""

    def __init__(self, allowed_roots: list[Path], output_root: Path,
                 limits: Limits | None = None):
        if not allowed_roots:
            raise InspectionError("configuration_error", "Configure at least one allowed local directory.")
        try:
            self.roots = tuple(Path(p).resolve(strict=True) for p in allowed_roots)
            if any(not p.is_dir() for p in self.roots):
                raise ValueError("Input roots must be directories")
            self.output = Path(output_root).resolve()
            self.output.mkdir(parents=True, exist_ok=True)
            if not self.output.is_dir():
                raise ValueError("Output root must be a directory")
        except (OSError, ValueError) as exc:
            raise InspectionError("configuration_error", "Input/output directories are unavailable.") from exc
        self.limits = limits or Limits()

    def _source(self, value: str) -> Path:
        if not isinstance(value, str) or not value or "://" in value:
            raise InspectionError("local_path_required", "Supply a local MP4 path, not a URL.")
        unresolved = Path(value).expanduser()
        # Check confinement even for missing files; symlinks resolve before this test.
        try:
            resolved = unresolved.resolve()
        except (OSError, RuntimeError) as exc:
            raise InspectionError("invalid_path", "The local path could not be resolved.") from exc
        if not any(resolved.is_relative_to(root) for root in self.roots):
            raise InspectionError("path_not_allowed", "The file is outside configured input directories.")
        if not resolved.exists():
            raise InspectionError("file_not_found", "The local video does not exist.")
        if not resolved.is_file():
            raise InspectionError("invalid_file", "The input must be a regular file.")
        if resolved.suffix.lower() != ".mp4":
            raise InspectionError("unsupported_format", "M1 accepts MP4 files only.")
        if resolved.stat().st_size > self.limits.max_bytes:
            raise InspectionError("input_limit", "The input exceeds the configured byte limit.")
        return resolved

    def _run(self, program: str, arguments: list[str]) -> bytes:
        executable = shutil.which(program)
        if not executable:
            raise InspectionError("dependency_missing", f"Install {program} and make it available on PATH.")
        try:
            result = subprocess.run([executable, *arguments], stdin=subprocess.DEVNULL,
                                    capture_output=True, check=True,
                                    timeout=self.limits.subprocess_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise InspectionError("processing_timeout", f"{program} exceeded the configured timeout.") from exc
        except (OSError, subprocess.CalledProcessError) as exc:
            # Do not expose raw stderr, command lines or unrelated filesystem paths.
            raise InspectionError("media_processing_failed", f"{program} could not process the requested media.") from exc
        return result.stdout

    def _json_probe(self, source: Path, options: list[str]) -> dict:
        raw = self._run("ffprobe", ["-v", "error", "-threads", "2",
            "-protocol_whitelist", "file,pipe", *options, "-of", "json", str(source)])
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise InspectionError("invalid_probe", "FFprobe returned invalid metadata.") from exc

    def inspect(self, video_path: str, timestamp: float,
                audio_seconds: float = 4) -> dict:
        if isinstance(timestamp, bool) or not isinstance(timestamp, (float, int)) or not math.isfinite(timestamp) or timestamp < 0:
            raise InspectionError("invalid_timestamp", "Timestamp must be finite and nonnegative.")
        if isinstance(audio_seconds, bool) or not isinstance(audio_seconds, (float, int)) or not math.isfinite(audio_seconds) or not 0 < audio_seconds <= 10:
            raise InspectionError("invalid_audio_duration", "Audio excerpt duration must be between zero and ten seconds.")
        source = self._source(video_path)
        initial_hash = file_hash(source)
        metadata = self._json_probe(source, ["-show_format", "-show_streams"])
        try:
            duration = float(metadata["format"]["duration"])
        except (KeyError, ValueError, TypeError) as exc:
            raise InspectionError("unknown_duration", "A finite video duration is required.") from exc
        if not math.isfinite(duration) or duration <= 0:
            raise InspectionError("unknown_duration", "A finite positive video duration is required.")
        if duration > self.limits.max_duration_seconds:
            raise InspectionError("input_limit", "The video exceeds the configured duration limit.")
        if timestamp >= duration:
            raise InspectionError("timestamp_out_of_range", "Timestamp must be earlier than the end of the video.")
        if "mp4" not in metadata["format"].get("format_name", "").split(","):
            raise InspectionError("unsupported_format", "The content must be an MP4 container.")
        streams = metadata.get("streams", [])
        videos = [x for x in streams if x.get("codec_type") == "video"]
        audios = [x for x in streams if x.get("codec_type") == "audio"]
        if not videos:
            raise InspectionError("no_video_stream", "The MP4 has no video stream.")
        frames = self._json_probe(source, ["-select_streams", "v:0", "-show_frames",
            "-show_entries", "frame=best_effort_timestamp_time"])
        try:
            pts = [float(x["best_effort_timestamp_time"]) for x in frames["frames"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise InspectionError("unknown_frame_time", "Decoded frame timestamps are unavailable.") from exc
        if not pts or any(not math.isfinite(x) for x in pts) or any(a > b for a, b in zip(pts, pts[1:])):
            raise InspectionError("unknown_frame_time", "Decoded frame timestamps must be finite and ordered.")
        relative = [x - pts[0] for x in pts]
        index = max(0, bisect_right(relative, timestamp + 1e-7) - 1)
        inspection_id = uuid.uuid4().hex
        destination = self.output / inspection_id
        destination.mkdir(mode=0o700)
        try:
            picture = destination / "frame.png"
            self._run("ffmpeg", ["-nostdin", "-v", "error", "-threads", "2",
                "-protocol_whitelist", "file,pipe", "-i", str(source), "-map", "0:v:0", "-an",
                "-vf", f"select='eq(n,{index})',scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease",
                "-frames:v", "1", "-threads", "2", str(picture)])
            if not picture.is_file():
                raise InspectionError("frame_unavailable", "The requested picture could not be extracted.")
            frame = {"uri": f"videoverify://artifacts/{inspection_id}/frame.png",
                "path": str(picture), "sha256": file_hash(picture), "frame_index": index,
                "actual_seconds": relative[index], "source_pts_seconds": pts[index], "mime_type": "image/png"}
            audio = {"status": "absent", "reason": "No audio stream. This alone is not a defect."}
            if audios:
                start = max(0, timestamp - audio_seconds / 2)
                length = min(audio_seconds, duration - start)
                wav = destination / "audio.wav"
                self._run("ffmpeg", ["-nostdin", "-v", "error", "-threads", "2",
                    "-protocol_whitelist", "file,pipe", "-ss", str(start), "-i", str(source),
                    "-map", "0:a:0", "-vn", "-t", str(length), "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", str(wav)])
                with wave.open(str(wav)) as excerpt:
                    samples = excerpt.getnframes()
                    actual_length = samples / excerpt.getframerate()
                if not samples:
                    raise InspectionError("audio_unavailable", "The selected audio excerpt contains no samples.")
                audio = {"status": "extracted", "uri": f"videoverify://artifacts/{inspection_id}/audio.wav",
                    "path": str(wav), "sha256": file_hash(wav), "mime_type": "audio/wav",
                    "requested_start_seconds": start, "requested_duration_seconds": length,
                    "decoded_duration_seconds": actual_length, "sample_rate": 16000, "channels": 1}
            if file_hash(source) != initial_hash:
                raise InspectionError("source_changed", "The input changed during inspection; discard these observations.")
            result = {"ok": True, "schema_version": 1, "inspection_id": inspection_id,
                "source": {"path": str(source), "sha256": initial_hash, "bytes": source.stat().st_size},
                "timestamp_seconds": timestamp,
                "metadata": {"duration_seconds": duration, "width": videos[0]["width"],
                    "height": videos[0]["height"], "video_codec": videos[0].get("codec_name"),
                    "video_streams": len(videos), "audio_streams": len(audios),
                    "audio_codec": audios[0].get("codec_name") if audios else None},
                "frame": frame, "audio": audio,
                "report_uri": f"videoverify://artifacts/{inspection_id}/inspection.json",
                "limits": ["One sampled picture does not establish unseen motion or quality.",
                    "Audio extraction does not judge natural speech or intelligibility.",
                    "This inspection does not analyze defects, compare revisions or approve publication."]}
            (destination / "inspection.json").write_text(json.dumps(result, indent=2) + "\n")
            return result
        except Exception:
            shutil.rmtree(destination)
            raise

    def read_artifact(self, inspection_id: str, filename: str) -> bytes:
        if not re.fullmatch(r"[0-9a-f]{32}", inspection_id) or filename not in {"frame.png", "audio.wav", "inspection.json"}:
            raise InspectionError("artifact_not_allowed", "Use an artifact URI returned by an inspection.")
        path = self.output / inspection_id / filename
        if not path.resolve().is_relative_to(self.output) or not path.is_file():
            raise InspectionError("artifact_not_found", "The requested inspection artifact is unavailable.")
        return path.read_bytes()
