import hashlib
import os
import subprocess
import zipfile

import pytest

from videoverify.browser_capture import capture_page, validate_times, youtube_url
from videoverify.core import InspectionError

URL = "https://www.youtube.com/watch?v=x7X9w_GIm1s"


@pytest.mark.parametrize("url", ["https://www.instagram.com/reel/abcdef/", "https://youtube.com/playlist?list=abc", "file:///tmp/test.mp4", "https://evil.example/watch?v=x7X9w_GIm1s"])
def test_only_individual_youtube_urls(url):
    with pytest.raises(InspectionError):
        youtube_url(url)


@pytest.mark.parametrize("times", [[], [1, 1], [2, 1], [-1], [float("nan")], [float("inf")], [True], list(range(25))])
def test_invalid_capture_times(times):
    with pytest.raises(InspectionError) as failure:
        validate_times(times)
    assert failure.value.code == "invalid_timestamps"


@pytest.fixture
def browser_page(media):
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as pw:
        options = {"headless": True}
        if os.environ.get("VIDEOVERIFY_TEST_BROWSER"):
            options["executable_path"] = os.environ["VIDEOVERIFY_TEST_BROWSER"]
        try:
            browser = pw.chromium.launch(**options)
        except api.Error:
            pytest.skip("Browser integration needs a locally installed Chromium")
        context = browser.new_context(viewport={"width": 800, "height": 600})
        page = context.new_page()
        html = """<body style='margin:0'>PRIVATE OUTSIDE PLAYER
        <div id='movie_player'><video width='160' height='90' preload='auto' src='/fixture.mp4'></video></div>
        <script>window.ytInitialPlayerResponse={videoDetails:{videoId:'x7X9w_GIm1s'}};</script></body>"""
        # Every request is intercepted. No fixture test contacts YouTube.
        def serve(route):
            if route.request.url.endswith("/fixture.mp4"):
                data = media["silent"].read_bytes()
                byte_range = route.request.headers.get("range", "")
                headers = {"Accept-Ranges": "bytes"}
                if byte_range.startswith("bytes="):
                    first, last = byte_range[6:].split("-", 1)
                    start = int(first or 0)
                    end = min(int(last) if last else len(data) - 1, len(data) - 1)
                    headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
                    route.fulfill(status=206, body=data[start:end + 1], content_type="video/mp4", headers=headers)
                else:
                    route.fulfill(body=data, content_type="video/mp4", headers=headers)
            else:
                route.fulfill(body=html, content_type="text/html")
        page.route("**/*", serve)
        page.goto(URL)
        page.wait_for_function("document.querySelector('video').readyState>=2")
        try:
            yield page
        finally:
            context.close()
            browser.close()


def test_real_browser_frames_zip_and_private_region_excluded(browser_page, tmp_path):
    result = capture_page(browser_page, URL, [0.2, 1.3], tmp_path)
    assert result["method"] == "attended_browser_player_screenshots"
    assert len(result["frames"]) == 2
    with zipfile.ZipFile(result["packet"]) as archive:
        assert sorted(archive.namelist()) == ["frame-000.jpg", "frame-001.jpg", "inspection.json"]
        report = archive.read("inspection.json")
        assert b"PRIVATE OUTSIDE" not in report
        for frame, channel in zip(result["frames"], (0, 2)):
            pixels = archive.read(frame["file"])
            assert hashlib.sha256(pixels).hexdigest() == frame["sha256"]
            decoded = subprocess.check_output(["ffmpeg", "-v", "error", "-i", "pipe:0",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], input=pixels)
            assert len(decoded) == 160 * 90 * 3
            offset = (45 * 160 + 80) * 3
            sample = decoded[offset:offset + 3]
            assert sample[channel] > 200 and sample[2 - channel] < 30
            assert abs(frame["requested_seconds"] - frame["browser_time_seconds"]) < 0.15


@pytest.mark.parametrize("state,expected", [("ad", "ad_playing"), ("challenge", "access_restricted"), ("identity", "source_unverified")])
def test_no_packet_for_ads_verification_or_changed_video(browser_page, tmp_path, state, expected):
    if state == "ad":
        browser_page.eval_on_selector("#movie_player", "p=>p.classList.add('ad-showing')")
    elif state == "challenge":
        browser_page.evaluate("document.body.append('Sign in to confirm you are not a bot')")
    else:
        browser_page.evaluate("window.ytInitialPlayerResponse.videoDetails.videoId='abcdefghijk'")
    with pytest.raises(InspectionError) as failure:
        capture_page(browser_page, URL, [0.2], tmp_path)
    assert failure.value.code == expected and not list(tmp_path.iterdir())


def test_mid_capture_failure_removes_partial_packet(browser_page, tmp_path, monkeypatch):
    from playwright.sync_api import Locator
    screenshot = Locator.screenshot
    calls = 0
    def failing(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise InspectionError("fixture_failure", "Second screenshot failed")
        return screenshot(self, *args, **kwargs)
    monkeypatch.setattr(Locator, "screenshot", failing)
    with pytest.raises(InspectionError):
        capture_page(browser_page, URL, [0.2, 1.3], tmp_path)
    assert calls == 2 and not list(tmp_path.iterdir())
