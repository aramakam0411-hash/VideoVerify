import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import wave

import pytest

from videoverify.core import Inspector, InspectionError
from videoverify.transcription import Transcriber


@pytest.fixture
def transcriber(media, tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (model / name).write_text("original fixture model")
    return Transcriber(Inspector([media["root"]], tmp_path / "evidence"), model)


def fake_worker(monkeypatch, callback=None):
    original = subprocess.run
    calls = []
    def run(command, **kwargs):
        if not str(command[1]).endswith("transcribe_worker.py"):
            return original(command, **kwargs)
        calls.append((command, kwargs))
        if callback:
            return callback(command, kwargs)
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        with wave.open(command[3]) as audio:
            assert audio.getframerate() == 16000 and audio.getnchannels() == 1
        Path(command[4]).write_text(json.dumps({"ok": True,
            "segments": [{"start": 0.1, "end": 0.7, "text": " example speech "}],
            "language": "en", "versions": {"faster-whisper": "1.2.1", "ctranslate2": "4.8.2"}}))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("videoverify.transcription.subprocess.run", run)
    return calls


def test_real_audio_decode_source_timeline_and_resources(transcriber, media, monkeypatch):
    calls = fake_worker(monkeypatch)
    result = transcriber.transcribe(str(media["tone"]), 0.5, 1, "en")
    assert len(calls) == 1
    assert result["text"] == "example speech"
    assert result["segments"][0]["start"] == pytest.approx(0.6)
    assert result["segments"][0]["end"] == pytest.approx(1.2)
    assert result["window"]["samples"] == 16000
    assert result["source"]["sha256"] == hashlib.sha256(media["tone"].read_bytes()).hexdigest()
    assert transcriber.inspector.read_artifact(result["inspection_id"], "transcript.txt") == b"example speech\n"
    stored = json.loads(transcriber.inspector.read_artifact(result["inspection_id"], "transcript.json"))
    assert stored == result
    assert sorted(p.name for p in (transcriber.inspector.output / result["inspection_id"]).iterdir()) == ["inspection.json", "transcript.json", "transcript.txt"]


@pytest.mark.parametrize("start,duration", [(True, 1), (0, False), (-1, 2), (0, 301), (0, float("nan")), (float("inf"), 1)])
def test_bad_windows_are_rejected_before_decode(transcriber, media, start, duration):
    with pytest.raises(InspectionError, match="window|duration|finite|start"):
        transcriber.transcribe(str(media["tone"]), start, duration)
    assert not list(transcriber.inspector.output.iterdir())


def test_source_confinement_and_no_audio(transcriber, media, tmp_path):
    for value, code in [("https://example.com/a.mp4", "local_path_required"),
                        (str(tmp_path / "outside.wav"), "path_not_allowed"),
                        (str(media["silent"]), "no_audio_stream")]:
        with pytest.raises(InspectionError) as error:
            transcriber.transcribe(value)
        assert error.value.code == code
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"not decoded")
    link = media["root"] / "escape.wav"
    link.symlink_to(outside)
    with pytest.raises(InspectionError) as error:
        transcriber.transcribe(str(link))
    assert error.value.code == "path_not_allowed"


def test_local_wav_and_end_clip(transcriber, media, monkeypatch):
    audio = media["root"] / "original.wav"
    with wave.open(str(audio), "wb") as out:
        out.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        out.writeframes(b"\x00\x00" * 16000)
    fake_worker(monkeypatch)
    result = transcriber.transcribe(str(audio), duration_seconds=30)
    assert result["window"]["decoded_duration_seconds"] == 1
    assert result["window"]["requested_duration_seconds"] == 30


def test_recognizer_tail_overhang_preserves_observed_end_but_bounds_coverage():
    result = Transcriber._segments([{"start": 146.18, "end": 150.26, "text": "final phrase"}], 149.003875, 10)
    assert result == [{"start": 156.18, "end": 159.003875, "recognized_end": 160.26,
                       "text": "final phrase", "end_clipped_to_window": True}]
    for values in [[{"start": 150, "end": 151, "text": "outside"}],
                   [{"start": 146, "end": 180, "text": "invalid tail"}]]:
        with pytest.raises(ValueError):
            Transcriber._segments(values, 149, 0)


@pytest.mark.parametrize("failure,code", [("timeout", "transcription_timeout"),
    ("badjson", "invalid_transcription"), ("oversize", "transcription_failed"),
    ("missing", "dependency_missing"), ("changed", "source_changed"), ("badtime", "invalid_transcription")])
def test_failure_cleanup_and_sanitization(transcriber, media, monkeypatch, failure, code):
    def fail(command, kwargs):
        output = Path(command[4])
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1)
        if failure == "badjson":
            output.write_text("raw secret failure")
        elif failure == "oversize":
            output.write_bytes(b"x" * (2 * 1024**2 + 1))
        elif failure == "missing":
            output.write_text('{"ok":false,"error":"dependency_missing"}')
            return SimpleNamespace(returncode=2)
        else:
            output.write_text(json.dumps({"ok": True,
                "segments": [{"start": 0, "end": 500 if failure == "badtime" else 0.5, "text": "recognized"}],
                "language": "en", "versions": {"faster-whisper": "1.2.1", "ctranslate2": "4.8.2"}}))
            if failure == "changed":
                with media["tone"].open("ab") as stream:
                    stream.write(b"changed")
        return SimpleNamespace(returncode=0)
    calls = fake_worker(monkeypatch, fail)
    with pytest.raises(InspectionError) as error:
        transcriber.transcribe(str(media["tone"]))
    assert error.value.code == code and "secret" not in str(error.value)
    assert len(calls) == 1 and not list(transcriber.inspector.output.iterdir())
    if failure == "changed":
        with media["tone"].open("r+b") as stream:
            stream.truncate(media["tone"].stat().st_size - len(b"changed"))


def test_missing_model_does_not_download(media, tmp_path):
    with pytest.raises(InspectionError) as error:
        Transcriber(Inspector([media["root"]], tmp_path / "out"), tmp_path / "absent")
    assert error.value.code == "model_unavailable"


def test_low_space_stops_before_worker(transcriber, media, monkeypatch):
    monkeypatch.setattr("videoverify.transcription.shutil.disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(InspectionError) as error:
        transcriber.transcribe(str(media["tone"]))
    assert error.value.code == "insufficient_space"


def test_worker_missing_extra_is_typed_and_local(tmp_path):
    from videoverify import transcribe_worker
    output = tmp_path / "result.json"
    run = subprocess.run([sys.executable, "-S", str(Path(transcribe_worker.__file__)),
        str(tmp_path / "model"), str(tmp_path / "audio.wav"), str(output), "en"],
        capture_output=True, timeout=10)
    assert run.returncode == 2 and not run.stdout and not run.stderr
    assert json.loads(output.read_text()) == {"ok": False, "error": "dependency_missing"}


def test_real_stdio_asr_is_operator_opt_in(transcriber, media):
    pytest.importorskip("mcp")
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters
    async def scenario():
        parameters = StdioServerParameters(command=sys.executable, args=["-m", "videoverify.server",
            "--allow-root", str(media["root"]), "--output-root", str(transcriber.inspector.output),
            "--asr-model", str(transcriber.model)])
        async with Client(parameters) as client:
            tools = await client.list_tools()
            assert {t.name for t in tools.tools} == {"inspect_video", "inspect_sequence", "transcribe_media"}
            failed = await client.call_tool("transcribe_media", {"media_path": "https://example.com/a.mp4"})
            assert failed.is_error and "local_path_required" in failed.content[0].text
    asyncio.run(scenario())


def test_mcp_opt_in_text_and_errors(transcriber, media, monkeypatch):
    pytest.importorskip("mcp")
    from mcp import Client
    from videoverify.server import create_server
    fake_worker(monkeypatch)
    async def scenario():
        server = create_server(transcriber.inspector, transcriber=transcriber)
        async with Client(server) as client:
            tools = await client.list_tools()
            assert "transcribe_media" in {t.name for t in tools.tools}
            response = await client.call_tool("transcribe_media", {"media_path": str(media["tone"])})
            assert not response.is_error
            result = response.structured_content
            text = await client.read_resource(result["text_uri"])
            assert text.contents[0].text == "example speech\n"
            report = await client.read_resource(result["transcript_uri"])
            assert json.loads(report.contents[0].text) == result
            failed = await client.call_tool("transcribe_media", {"media_path": "https://example.com/a.mp4"})
            assert failed.is_error and "local_path_required" in failed.content[0].text
    asyncio.run(scenario())
