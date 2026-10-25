"""Opt-in, bounded public Instagram/YouTube/TikTok import. No accounts or cookies."""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit
import uuid

from .core import InspectionError, Inspector, Limits, file_hash


def canonical_url(value: str) -> str:
    """Accept individual public video pages, never profiles or arbitrary URLs."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
            raise ValueError
        host = (parsed.hostname or "").lower()
        if host in {"instagram.com", "www.instagram.com"}:
            match = re.fullmatch(r"/(reel|p)/([A-Za-z0-9_-]{5,32})/?", parsed.path)
            if match:
                return f"https://www.instagram.com/{match[1]}/{match[2]}/"
        if host in {"tiktok.com", "www.tiktok.com", "m.tiktok.com"}:
            match = re.fullmatch(r"/@([A-Za-z0-9_.]{1,32})/video/([0-9]{15,22})/?", parsed.path)
            if match:
                return f"https://www.tiktok.com/@{match[1]}/video/{match[2]}"
        identity = None
        if host == "youtu.be":
            identity = parsed.path.removeprefix("/")
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            if parsed.path == "/watch":
                values = parse_qs(parsed.query).get("v", [])
                identity = values[0] if len(values) == 1 else None
            else:
                match = re.fullmatch(r"/(shorts|embed)/([A-Za-z0-9_-]{11})/?", parsed.path)
                identity = match[2] if match else None
        if identity and re.fullmatch(r"[A-Za-z0-9_-]{11}", identity):
            return f"https://www.youtube.com/watch?v={identity}"
    except (TypeError, ValueError):
        pass
    raise InspectionError("unsupported_url", "Supply one HTTPS Instagram Reel/post, YouTube video, or full TikTok @user/video/id URL.")


@dataclass(frozen=True)
class ImportLimits:
    max_bytes: int = 64 * 1024 * 1024
    max_duration_seconds: float = 600
    timeout_seconds: float = 90
    reserve_bytes: int = 64 * 1024 * 1024


class Acquirer:
    def __init__(self, cache_root: Path, limits: ImportLimits | None = None):
        self.root = Path(cache_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.limits = limits or ImportLimits()

    def fetch(self, url: str) -> dict:
        canonical = canonical_url(url)
        if importlib.util.find_spec("yt_dlp") is None:
            raise InspectionError("dependency_missing", 'Install the optional "videoverify[fetch]" extra.')
        if shutil.disk_usage(self.root).free < self.limits.max_bytes + self.limits.reserve_bytes:
            raise InspectionError("insufficient_space", "Not enough space for the import and reserve.")
        destination = self.root / uuid.uuid4().hex
        destination.mkdir(mode=0o700)
        video = destination / "video.mp4"
        try:
            command = [sys.executable, "-m", "videoverify.fetch_worker", canonical, str(video),
                       str(self.limits.max_bytes), str(self.limits.max_duration_seconds)]
            try:
                process = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                         timeout=self.limits.timeout_seconds, check=False)
            except subprocess.TimeoutExpired as exc:
                raise InspectionError("acquisition_timeout", "Video import timed out; no automatic retry.") from exc
            try:
                result = json.loads(process.stdout)
            except (ValueError, UnicodeError) as exc:
                raise InspectionError("acquisition_failed", "The import worker did not return a valid result.") from exc
            if process.returncode or not result.get("ok"):
                error = result.get("error", {})
                raise InspectionError(error.get("code", "acquisition_failed"),
                                      error.get("message", "Video import failed."))
            if not video.is_file() or video.is_symlink() or video.stat().st_size > self.limits.max_bytes:
                raise InspectionError("input_limit", "The imported video is missing or exceeds the byte limit.")
            # Validate the real container/duration, not just untrusted platform metadata.
            inspector = Inspector([destination], destination / "validation",
                                  Limits(max_bytes=self.limits.max_bytes,
                                         max_duration_seconds=self.limits.max_duration_seconds))
            probe = inspector._json_probe(video, ["-show_format", "-show_streams"])
            duration = float(probe["format"]["duration"])
            import math
            if not math.isfinite(duration) or not 0 < duration <= self.limits.max_duration_seconds:
                raise InspectionError("input_limit", "The imported video exceeds the duration limit.")
            if "mp4" not in probe["format"].get("format_name", "").split(",") or not any(
                    stream.get("codec_type") == "video" for stream in probe.get("streams", [])):
                raise InspectionError("unsupported_format", "The imported content is not an MP4 video.")
            shutil.rmtree(destination / "validation")
            receipt = {"ok": True, "source_url": canonical, "video_path": str(video),
                       "sha256": file_hash(video), "bytes": video.stat().st_size,
                       "duration_seconds": duration, "access": "public_without_account",
                       "reuse_rights": "Not assessed. Access does not grant permission to republish."}
            (destination / "import.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            return receipt
        except (KeyError, TypeError, ValueError) as exc:
            shutil.rmtree(destination, ignore_errors=True)
            raise InspectionError("invalid_media", "Imported media metadata is invalid.") from exc
        except BaseException:
            shutil.rmtree(destination, ignore_errors=True)
            raise
