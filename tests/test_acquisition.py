import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
from types import SimpleNamespace

import pytest

from videoverify.acquisition import Acquirer, ImportLimits, canonical_url
from videoverify.core import Inspector, InspectionError
from videoverify.fetch_worker import classify_error, validate_media_url


@pytest.mark.parametrize("url,expected", [
    ("https://www.instagram.com/reel/Abcdef_123/?tracking=secret", "https://www.instagram.com/reel/Abcdef_123/"),
    ("https://youtu.be/abcdefghijk?t=12", "https://www.youtube.com/watch?v=abcdefghijk"),
    ("https://youtube.com/shorts/abcdefghijk", "https://www.youtube.com/watch?v=abcdefghijk"),
])
def test_canonical_single_video(url, expected):
    assert canonical_url(url) == expected


@pytest.mark.parametrize("url", ["http://youtube.com/watch?v=abcdefghijk", "https://127.0.0.1/reel/abcdef/",
    "https://www.instagram.com.evil.test/reel/abcdef/", "https://user:pass@instagram.com/reel/abcdef/",
    "https://youtube.com/playlist?list=abc", "https://instagram.com/someone/", "file:///tmp/a.mp4",
    "https://instagram.com:443/reel/abcdef/", "https://youtube.com/watch?v=abcdefghijk&v=12345678901"])
def test_reject_nonvideo_or_untrusted_urls(url):
    with pytest.raises(InspectionError) as failure:
        canonical_url(url)
    assert failure.value.code == "unsupported_url"


def test_media_hosts_and_private_resolution(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])
    validate_media_url("https://video.example.fbcdn.net/a.mp4?private_signature=withheld")
    for url in ["https://evil.test/a.mp4", "https://fbcdn.net.evil.test/a", "http://video.fbcdn.net/a"]:
        with pytest.raises(InspectionError):
            validate_media_url(url)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(InspectionError) as failure:
        validate_media_url("https://video.fbcdn.net/a")
    assert failure.value.code == "media_destination_denied"


@pytest.mark.parametrize("message,code", [("HTTP 429 secret-url", "rate_limited"),
    ("Please login with cookies secret", "access_restricted"), ("HTTP 403", "access_restricted"),
    ("Requested format unavailable", "format_unavailable"), ("unexpected secret", "acquisition_failed")])
def test_errors_are_classified_without_sensitive_details(message, code):
    result = classify_error(message)
    assert result.code == code and "secret" not in str(result)


def test_youtube_requires_installed_player_support_and_selects_local_node(monkeypatch):
    from videoverify.fetch_worker import youtube_runtime_options
    monkeypatch.setattr("videoverify.fetch_worker.importlib.util.find_spec", lambda _: None)
    with pytest.raises(InspectionError) as failure:
        youtube_runtime_options()
    assert failure.value.code == "dependency_missing"
    monkeypatch.setattr("videoverify.fetch_worker.importlib.util.find_spec", lambda _: object())
    monkeypatch.setattr("videoverify.fetch_worker.shutil.which", lambda name: "/installed/node" if name == "node" else None)
    assert youtube_runtime_options() == {"js_runtimes": {"node": {"path": "/installed/node"}}, "remote_components": []}
    monkeypatch.setattr("videoverify.fetch_worker.shutil.which", lambda _: None)
    with pytest.raises(InspectionError) as failure:
        youtube_runtime_options()
    assert failure.value.code == "dependency_missing"


def test_youtube_bot_verification_is_identified_without_raw_error():
    failure = classify_error("Sign in to confirm you're not a bot. raw-secret-url")
    assert failure.code == "access_restricted" and "sign-in" in str(failure)
    assert "raw-secret" not in str(failure)


def ready(monkeypatch):
    monkeypatch.setattr("videoverify.acquisition.importlib.util.find_spec", lambda _: object())
    monkeypatch.setattr("videoverify.acquisition.shutil.disk_usage", lambda _: SimpleNamespace(free=10**10))


def test_import_to_real_frame(media, tmp_path, monkeypatch):
    ready(monkeypatch)
    original = subprocess.run
    calls = []
    def worker(command, **kwargs):
        if "videoverify.fetch_worker" not in command:
            return original(command, **kwargs)
        calls.append(command)
        shutil.copyfile(media["silent"], command[4])
        return SimpleNamespace(returncode=0, stdout=b'{"ok":true}')
    monkeypatch.setattr("videoverify.acquisition.subprocess.run", worker)
    receipt = Acquirer(tmp_path / "imports").fetch("https://instagram.com/reel/abcdef/?tracking=secret")
    assert len(calls) == 1
    assert receipt["source_url"] == "https://www.instagram.com/reel/abcdef/"
    assert receipt["duration_seconds"] == pytest.approx(2)
    picture = Inspector([tmp_path / "imports"], tmp_path / "evidence").inspect(receipt["video_path"], 1.3)
    assert picture["frame"]["frame_index"] == 13
    assert "secret" not in Path(receipt["video_path"]).with_name("import.json").read_text()


def test_restricted_access_stops_once_and_cleans(tmp_path, monkeypatch):
    ready(monkeypatch)
    calls = []
    def worker(command, **kwargs):
        calls.append(command)
        Path(command[4]).write_bytes(b"partial")
        return SimpleNamespace(returncode=2, stdout=json.dumps(classify_error("HTTP 429").as_dict()).encode())
    monkeypatch.setattr("videoverify.acquisition.subprocess.run", worker)
    importer = Acquirer(tmp_path / "imports")
    with pytest.raises(InspectionError) as failure:
        importer.fetch("https://instagram.com/reel/abcdef/")
    assert failure.value.code == "rate_limited" and len(calls) == 1
    assert not list(importer.root.iterdir())


def test_timeout_and_low_space_cleanup(tmp_path, monkeypatch):
    ready(monkeypatch)
    def worker(command, **kwargs):
        Path(command[4]).write_bytes(b"partial")
        raise subprocess.TimeoutExpired(command, 1)
    monkeypatch.setattr("videoverify.acquisition.subprocess.run", worker)
    importer = Acquirer(tmp_path / "imports")
    with pytest.raises(InspectionError) as failure:
        importer.fetch("https://youtu.be/abcdefghijk")
    assert failure.value.code == "acquisition_timeout" and not list(importer.root.iterdir())
    monkeypatch.setattr("videoverify.acquisition.shutil.disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(InspectionError) as failure:
        importer.fetch("https://youtu.be/abcdefghijk")
    assert failure.value.code == "insufficient_space"


def test_worker_bounds_stream_and_sanitizes(monkeypatch, tmp_path):
    yt_dlp = pytest.importorskip("yt_dlp")
    import videoverify.fetch_worker as worker
    class Resolver:
        def __init__(self, options):
            assert options["retries"] == options["extractor_retries"] == 0
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url, download):
            assert download is False
            return {"url": "https://video.fbcdn.net/signed", "duration": 2}
    class Response(io.BytesIO):
        headers = {}
    monkeypatch.setattr(yt_dlp, "YoutubeDL", Resolver)
    monkeypatch.setattr(worker, "validate_media_url", lambda _: None)
    monkeypatch.setattr(worker.urllib.request, "build_opener", lambda *a: SimpleNamespace(
        open=lambda *a, **k: Response(b"too many bytes")))
    with pytest.raises(InspectionError) as failure:
        worker.fetch("https://instagram.com/reel/abcdef/", tmp_path / "bounded.mp4", 3, 600)
    assert failure.value.code == "input_limit"
    assert (tmp_path / "bounded.mp4").stat().st_size == 0
