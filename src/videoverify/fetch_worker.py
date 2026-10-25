"""Private subprocess boundary for a single public import; never emits signed URLs."""
from __future__ import annotations

import ipaddress
import importlib.util
import json
from pathlib import Path
import socket
import shutil
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .acquisition import canonical_url
from .core import InspectionError


def validate_media_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        allowed = ("cdninstagram.com", "fbcdn.net", "googlevideo.com",
                   "tiktokcdn.com", "tiktokcdn-us.com", "tiktokcdn-eu.com")
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port
                or not any(host == domain or host.endswith("." + domain) for domain in allowed)):
            raise ValueError
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or not all(ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError
    except (ValueError, OSError) as exc:
        raise InspectionError("media_destination_denied", "The media destination is not an allowed public HTTPS CDN.") from exc


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        validate_media_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class QuietLogger:
    def debug(self, message): pass
    def warning(self, message): pass
    def error(self, message): pass


def classify_error(message: str) -> InspectionError:
    text = message.lower()
    if "sign in to confirm" in text and "bot" in text:
        return InspectionError("access_restricted", "YouTube requested sign-in to confirm this is not a bot; stop without retry or login.")
    if "no supported javascript runtime" in text:
        return InspectionError("dependency_missing", "YouTube requires a supported local JavaScript runtime.")
    if any(term in text for term in ("429", "rate limit", "rate-limit", "too many requests")):
        return InspectionError("rate_limited", "The platform limited access; stop and do not automatically retry.")
    if any(term in text for term in ("login", "log in", "sign in", "cookies", "private", "403", "captcha", "challenge", "bot")):
        return InspectionError("access_restricted", "The platform requires access verification; no login or bypass was attempted.")
    if "requested format" in text:
        return InspectionError("format_unavailable", "No supported single-file HTTPS MP4 is available.")
    return InspectionError("acquisition_failed", "The public video could not be imported; raw platform details are withheld.")


def youtube_runtime_options() -> dict:
    """Use installed player-JS support only; no accounts or runtime downloads."""
    if importlib.util.find_spec("yt_dlp_ejs") is None:
        raise InspectionError("dependency_missing", "Install the fetch extra with yt-dlp default dependencies for YouTube player support.")
    for name in ("deno", "node"):
        executable = shutil.which(name)
        if executable:
            return {"js_runtimes": {name: {"path": executable}}, "remote_components": []}
    raise InspectionError("dependency_missing", "YouTube needs an installed supported Deno or Node runtime; see yt-dlp EJS setup.")


def fetch(url: str, destination: Path, max_bytes: int, max_duration: float) -> None:
    import yt_dlp
    options = {"quiet": True, "no_warnings": True, "logger": QuietLogger(),
               "socket_timeout": 15, "retries": 0, "extractor_retries": 0,
               "fragment_retries": 0, "noplaylist": True, "cachedir": False,
               "format": "best[ext=mp4][protocol=https]"}
    canonical = canonical_url(url)
    if urlsplit(canonical).hostname == "www.youtube.com":
        options.update(youtube_runtime_options())
    try:
        with yt_dlp.YoutubeDL(options) as extractor:
            info = extractor.extract_info(canonical, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise classify_error(str(exc)) from exc
    if not info or info.get("_type") in {"playlist", "multi_video"}:
        raise InspectionError("unsupported_url", "Import accepts one video, not a playlist or carousel.")
    duration = info.get("duration")
    if duration is not None and float(duration) > max_duration:
        raise InspectionError("input_limit", "The platform reports a video beyond the duration limit.")
    media_url = info.get("url", "")
    validate_media_url(media_url)
    headers = {key: value for key, value in info.get("http_headers", {}).items()
               if key.lower() in {"user-agent", "referer", "origin"}}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirects())
    try:
        with opener.open(urllib.request.Request(media_url, headers=headers), timeout=15) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                raise InspectionError("input_limit", "The video exceeds the import byte limit.")
            received = 0
            with destination.open("xb") as stream:
                while chunk := response.read(65536):
                    received += len(chunk)
                    if received > max_bytes:
                        raise InspectionError("input_limit", "The video exceeds the import byte limit.")
                    stream.write(chunk)
    except urllib.error.HTTPError as exc:
        raise classify_error(str(exc.code)) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise InspectionError("acquisition_failed", "The media connection failed; no automatic retry.") from exc


def main() -> int:
    try:
        fetch(sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4]))
        result = {"ok": True}
    except InspectionError as exc:
        result = exc.as_dict()
    except Exception:
        result = InspectionError("acquisition_failed", "The import failed; raw platform details are withheld.").as_dict()
    print(json.dumps(result))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
