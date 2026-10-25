"""Attended desktop player screenshots. No media extraction or saved login state."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import uuid
import zipfile

from .acquisition import canonical_url
from .core import InspectionError


def youtube_url(value: str) -> str:
    url = canonical_url(value)
    if not url.startswith("https://www.youtube.com/watch?v="):
        raise InspectionError("unsupported_url", "Browser capture accepts one YouTube video URL.")
    return url


def validate_times(times: list[float]) -> list[float]:
    if (not isinstance(times, list) or not 1 <= len(times) <= 24 or
            any(isinstance(t, bool) or not isinstance(t, (int, float)) or
                not math.isfinite(t) or t < 0 for t in times) or
            any(a >= b for a, b in zip(times, times[1:]))):
        raise InspectionError("invalid_timestamps", "Supply 1 to 24 increasing nonnegative timestamps.")
    return times


def check_page(page, source_url: str) -> dict:
    """Allowlist returned data; never inspect cookies or export page HTML."""
    if youtube_url(page.url) != source_url:
        raise InspectionError("source_changed", "The selected video page changed; capture stopped.")
    body = page.locator("body").inner_text(timeout=5000).lower()
    if any(term in body for term in ("sign in to confirm", "unusual traffic",
                                    "verify you are human", "confirm you're not a bot",
                                    "confirm you’re not a bot")):
        raise InspectionError("access_restricted", "The normal player requires access verification; capture stopped.")
    state = page.evaluate("""() => {
        const p=document.querySelector('#movie_player'), v=p?.querySelector('video');
        const id=p?.getVideoData?.()?.video_id ?? window.ytInitialPlayerResponse?.videoDetails?.videoId;
        return {video_id:id??null, ad:!!p?.matches('.ad-showing, .ad-interrupting'),
            available:!!v, ready:v?.readyState??0, seeking:v?.seeking??true,
            width:v?.videoWidth??0,height:v?.videoHeight??0,
            time:v?.currentTime??null,duration:Number.isFinite(v?.duration)?v.duration:null};
    }""")
    if state["ad"]:
        raise InspectionError("ad_playing", "An advertisement is visible; no reference pictures captured.")
    if state["video_id"] != source_url.rsplit("=", 1)[1]:
        raise InspectionError("source_unverified", "The player's video identity could not be confirmed.")
    if (not state["available"] or state["ready"] < 2 or not state["width"] or
            not state["height"] or not state["duration"] or state["duration"] > 600):
        raise InspectionError("player_not_ready", "Start ordinary playback of a video up to 600 seconds, then capture.")
    return state


def capture_page(page, source_url: str, timestamps: list[float], output_root: Path) -> dict:
    """Capture rendered video elements, not a decoded source-file frame sequence."""
    source_url = youtube_url(source_url)
    validate_times(timestamps)
    before = check_page(page, source_url)
    if timestamps[-1] >= before["duration"]:
        raise InspectionError("timestamp_out_of_range", "A requested timestamp is outside this video.")
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < 128 * 1024 * 1024:
        raise InspectionError("insufficient_space", "Keep at least 128 MiB free for screenshots.")
    dest = root / uuid.uuid4().hex
    dest.mkdir(mode=0o700)
    archive = root / f"{dest.name}.zip"
    try:
        video = page.locator("#movie_player video").first
        frames = []
        total_bytes = 0
        for index, timestamp in enumerate(timestamps):
            check_page(page, source_url)
            video.evaluate("(v,t) => {v.pause(); v.currentTime=t;}", timestamp)
            page.wait_for_function("""t => {
                const v=document.querySelector('#movie_player video');
                return v && !v.seeking && v.readyState>=2 && Math.abs(v.currentTime-t)<0.15;
            }""", arg=timestamp, timeout=15000)
            page.evaluate("() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
            state = check_page(page, source_url)
            picture = video.screenshot(type="jpeg", quality=85, timeout=10000)
            after = check_page(page, source_url)
            if abs(after["time"] - timestamp) >= 0.15 or after["seeking"]:
                raise InspectionError("source_changed", "Player time changed while capturing; no packet exported.")
            if len(picture) > 8 * 1024 * 1024:
                raise InspectionError("input_limit", "A screenshot exceeds the packet limit.")
            total_bytes += len(picture)
            if total_bytes > 32 * 1024 * 1024:
                raise InspectionError("input_limit", "Screenshots exceed the 32 MiB packet limit.")
            name = f"frame-{index:03}.jpg"
            (dest / name).write_bytes(picture)
            frames.append({"file": name, "requested_seconds": timestamp,
                "browser_time_seconds": state["time"], "sha256": hashlib.sha256(picture).hexdigest()})
        result = {"ok": True, "schema_version": 1, "method": "attended_browser_player_screenshots",
            "source_url": source_url, "video_id": before["video_id"],
            "checked_at": datetime.now(timezone.utc).isoformat(), "duration_seconds": before["duration"],
            "frames": frames, "scope": "Rendered player screenshots at browser clock times, not decoded source frame indices. No audio, transcript, continuous motion, reuse rights or quality approval.",
            "privacy": "No cookies, browser profile, credentials, HTML or full-page screenshots exported."}
        (dest / "inspection.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_STORED) as package:
            for path in [dest / "inspection.json", *(dest / f["file"] for f in frames)]:
                package.write(path, path.name)
        return {**result, "packet": str(archive), "output_directory": str(dest)}
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        archive.unlink(missing_ok=True)
        raise


def attended_capture(url: str, timestamps: list[float], output_root: Path, channel: str | None = None) -> dict:
    source_url = youtube_url(url)
    validate_times(timestamps)
    try:
        from playwright.sync_api import sync_playwright, Error
    except ImportError as exc:
        raise InspectionError("dependency_missing", "Install videoverify[browser] on the desktop capture machine.") from exc
    try:
        with sync_playwright() as pw:
            # Fresh visible browser only. No profile, CDP connection, credentials,
            # cookies, proxy, stealth flags, media-file extraction or retry loop.
            options = {"headless": False}
            if channel:
                options["channel"] = channel
            browser = pw.chromium.launch(**options)
            try:
                context = browser.new_context(viewport={"width": 1280, "height": 800}, accept_downloads=False)
                page = context.new_page()
                response = page.goto(source_url, wait_until="domcontentloaded", timeout=30000)
                if response and response.status in (403, 429):
                    raise InspectionError("access_restricted", "The normal watch page rejected access; no retry or login.")
                print("In the opened desktop browser, start ordinary public playback. If login or verification is required, cancel. No login data will be exported.", file=sys.stderr)
                print("Press Enter when the requested video is playing, or type q to cancel: ", file=sys.stderr)
                answer = input().strip()
                if answer:
                    raise InspectionError("cancelled", "Capture cancelled; no packet exported.")
                return capture_page(page, source_url, timestamps, output_root)
            finally:
                browser.close()
    except (EOFError, KeyboardInterrupt) as exc:
        raise InspectionError("cancelled", "Capture cancelled; no packet exported.") from exc
    except Error as exc:
        raise InspectionError("browser_unavailable", "Browser launch, playback or capture failed. Check the desktop browser installation and visible playback; no automatic retry.") from exc
