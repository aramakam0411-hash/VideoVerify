# VideoVerify

**Agent-first video quality assurance and fix verification.**

VideoVerify is an open-source project that helps AI agents inspect videos, identify verifiable problems, and determine whether a revision fixed an issue without introducing new regressions.

> **Status (0.4.0):** local MP4 inspection, timestamped picture sequences, optional public Instagram/YouTube import, optional local speech transcription through CLI/MCP, and an attended desktop browser screenshot command. Subtitle alignment, quality analysis and comparison remain planned. Platform access is not guaranteed.

## When a YouTube URL cannot be imported

A successful upload API connection does not grant access to other videos' media.
A site may reject public imports and ordinary browser playback from a server.
Do not retry against a verification screen, rotate accounts/proxies or treat a
thumbnail as an inspected video frame.

Version0.4 adds a separate **attended desktop capture** command. Run it on a
machine where the selected public video already plays normally. It opens a
fresh visible browser, lets the person start ordinary playback, pauses/seeks
the player and saves cropped video-element screenshots with browser timestamps.
It does not download a source video, collect a profile/cookies, automate login,
solve verification, open a remote browser connection or fix a blocked server.
If normal access is rejected, it stops. This is a CLI handoff, not an unattended
MCP operation or automatic fallback.

From a checkout of this repository, with uv and existing Chrome:

```bash
uv run --extra browser videoverify browser-capture \
  'https://www.youtube.com/watch?v=VIDEO_ID_HERE' \
  --channel chrome --timestamps 0.5 1 2 3 5 10 20 --output-root ./review-packets
```

Use a real video ID in the example. `--channel msedge` uses installed Edge.
Alternatively omit the channel after installing Playwright's Chromium with
`uv run --extra browser playwright install chromium`. Chrome/Edge availability
and video playback on your desktop are prerequisites, not checked by our VPS.
Follow the visible browser instructions, then press Enter in the terminal.
Do not sign in or resolve an access-verification gate for this command; cancel
if one is required. No existing browser profile is connected or exported.

The generated ZIP contains only `inspection.json` and the requested JPEGs.
Send that packet through your existing trusted file-sharing route to the agent.
It can inspect the pictures without transferring the browser session. The
manifest labels these as rendered screenshots at **browser clock times**,
not decoded source-file frame indices. No audio or transcript is captured.
Pictures do not establish continuous motion, audio quality, rights to reuse
the creator's footage or audience performance. Public access is not a licence.

Limits: up to24 increasing timestamps, a finite video duration up to600seconds,
8MiB per screenshot and32MiB total picture data. Partial packets are removed on
failure. Ad playback, a changed/unconfirmed video identity and unreadable media
stop capture. Page/DOM changes may also stop it; this command uses the normal
watch page and does not promise a stable YouTube API for screenshots.

Validation: deterministic red/blue test footage is served through intercepted
browser requests. Real Chromium seeks and screenshots verify image pixels,
video-only crops, timestamps, packet hashes and partial-failure cleanup. All
fixture requests are local; this is **not a live desktop YouTube acceptance**.
Other tests reject unsupported URLs, invalid times, ads and verification pages.
The server's live watch-page restriction remains a separate observed result.
The fetch dependency floor is also updated to the maintainer's2026.10.21release;
upgrading an extractor is not presented as removing a site access restriction.

## Purpose

AI video workflows often require separate tools for video frames, audio clips, transcripts, scripts, and subtitles. VideoVerify aims to expose these capabilities through one consistent **Model Context Protocol (MCP)** interface. Its primary users are AI agents, not people uploading videos through a website.

The intended workflow is:

1. An AI agent produces a local video, optionally with a script and subtitle file.
2. VideoVerify analyzes the output and returns timestamped findings with supporting evidence.
3. The agent edits the video using its own editing tools.
4. VideoVerify compares the original and updated versions, distinguishing fixed issues, remaining issues, potential regressions, and checks it could not complete.

VideoVerify **does not generate or edit videos**. It provides inspection and verification capabilities to agents that do.

## Planned architecture

```text
AI agent / MCP client
         |
         v
  VideoVerify MCP server
         |
         v
  Python analysis core
         |
         +-- FFprobe / FFmpeg: metadata, frames, audio clips
         +-- Local speech transcription (optional); subtitle alignment (later)
         +-- Quality checks (later)
         +-- Before/after comparison (later)
         |
         v
  Structured results + evidence artifacts
```

The analysis core will be independent of MCP so it can also power a CLI and an optional human-facing viewer without duplicating logic.

## First milestone: inspect a local video

The `inspect_video` MCP tool accepts a local MP4 path and timestamp. It returns structured metadata, a still frame, and a WAV audio excerpt when audio exists. Each inspection gets its own output directory, source hash and artifact hashes. Returned resource URIs let a client retrieve the actual PNG, WAV and saved JSON report.

Implemented stack: **Python**, **FFmpeg/FFprobe**, and the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk). The analysis core uses the standard library; MCP is an optional extra. A frontend and AI-based subjective video scoring are not part of this milestone.

## Future MCP capabilities

- **`analyze_video`** — Check a video against optional script/subtitles, recording timestamped findings for possible missing speech, unexpected silence, subtitle timing problems, and similar issues.
- **`compare_versions`** — Compare video revisions, match related findings even when timings shift, and identify whether issues were corrected or regressions appeared.
- **Evidence access** — Provide paths or references to frames/audio excerpts and clear machine-readable timestamps.

Findings must not overstate certainty. Silence may be intentional, speech recognition may be wrong, and a signal-level audio check cannot judge whether narration sounds natural. The system should explicitly distinguish measurable violations, suspected defects, and conditions it could not assess.

## Engineering principles

- **Agent-first:** typed inputs, stable structured outputs, actionable error messages.
- **Local-first:** no YouTube or social platform account required.
- **Separation of concerns:** MCP transport is a thin wrapper around reusable analysis functions.
- **Reproducibility:** small test fixtures with known problems and expected outcomes.
- **Safety:** allowlisted local file roots, validated paths and timestamps, and no arbitrary shell execution exposed through MCP.
- **Incremental delivery:** implement and test inspection before advancing to checks and comparisons.

## Roadmap

* [x] **M1: Inspect:** MP4 validation, metadata, frame/audio extraction, an MCP tool, and tests.
* [ ] **M2: Analyze:** transcript/subtitle support and reliable timestamped checks.
* [ ] **M3: Verify:** compare before/after revisions and detect regressions.
* [ ] **M4: Release:** automated tests in CI, and optional human-readable reports. Basic installation, tests and examples are available now.

## Getting started

Requirements: Python 3.10+, FFmpeg and FFprobe on PATH, and [uv](https://docs.astral.sh/uv/) or pip. On Ubuntu, `sudo apt install ffmpeg` installs both media commands. Install FFmpeg using your operating system's package manager before running the examples.

```bash
git clone https://github.com/aramakam0411-hash/VideoVerify.git
cd VideoVerify
uv sync --extra mcp --extra dev
```

Generate a small original test video, then inspect it:

```bash
uv run python examples/make_demo.py --out ./demo.mp4
uv run videoverify inspect ./demo.mp4 --timestamp 1.3 \
  --allow-root . --output-root ./evidence
```

The demo contains two seconds of changing colors and a synthetic440Hz tone. It is a fixture, not a speech-quality test. For a pip installation, use `python -m pip install ".[mcp,dev]"` in your own virtual environment and omit `uv run` from the examples.

An inspection returns JSON with:

* `metadata`: duration, source dimensions, video/audio stream counts and codecs.
* `frame`: the picture visible at the requested time, decoded frame index, actual frame time, PNG path, SHA256 and resource URI. Pictures are scaled down to at most1280pixels per side without upscaling.
* `audio`: a mono16kHz WAV excerpt centered on the requested time where possible. The duration defaults to four seconds and is clipped at the video's boundaries. A video with no audio returns `status: "absent"`, not a defect.
* `source`: local path, byte count and SHA256. A changing input invalidates the inspection.
* `report_uri` and `limits`: saved evidence access and what this inspection cannot establish.

Default M1 limits are512MiB input, ten minutes of video, at most ten seconds per audio excerpt, and120seconds per media subprocess. These bound the initial implementation; this is not a general long-video service. Use trusted local inputs and keep FFmpeg updated. Input-directory restrictions reduce file access but do not sandbox a media decoder against hostile files.

### Picture sequences and public video links

Extract several pictures in one decoding pass to inspect changes around a moment:

```bash
uv run videoverify sequence ./demo.mp4 --timestamps 0.8 1.0 1.2 \
  --allow-root . --output-root ./evidence
```

The `inspect_sequence` MCP tool accepts the same `video_path` and `timestamps`.
It returns up to 24 pictures, each with its decoded time/index, hash and PNG
resource URI. Timestamps must increase; requests mapping to the same decoded
picture share one artifact. Sequences contain no audio. Sparse samples do not
establish everything happening between pictures or whether speech sounds natural.

Optional public import uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) for platform
resolution and a bounded HTTPS transfer for the selected MP4:

```bash
uv sync --extra fetch --extra mcp --extra dev
uv run --extra fetch videoverify fetch 'https://www.youtube.com/watch?v=VIDEO_ID_HERE' \
  --cache-root ./imports
```

Supply a real individual YouTube video/Short or Instagram Reel/video-post URL.
The JSON result includes `video_path`, canonical source URL, byte count, duration
and SHA256; use that local path with `inspect` or `sequence` and allow the import
directory as an input root. Import does not itself inspect pictures or establish
reuse rights. Tracking parameters and signed CDN URLs are not saved in receipts.

To expose `import_video` through MCP, explicitly add `--import-root /path/to/imports`
to the server command. That directory must be inside an existing `--allow-root`.
Without this operator option the server remains local-only; no accounts or host
configuration are changed. With pip, install `".[fetch,mcp]"` instead.

Import limits: one public video, 64MiB, ten minutes, 90 seconds for resolution
and transfer, plus bounded media validation. A 64MiB free-space reserve is required
in addition to the import budget. The adapter selects a single HTTPS MP4, so
adaptive-only formats, photo posts/carousels, live streams and playlists are not
supported. Neither cookies, login credentials, CAPTCHA solving, proxies nor
automatic retries are implemented. Actual login/rate-limit challenges stop with
typed errors; partial imports are removed. Public access can vary by video and
machine. An unrelated web fetch failure does not establish failure of this adapter.

Page hosts and HTTPS media CDN domains are allowlisted; resolved private IPs and
unapproved redirect targets are rejected for media transfers. This is not a
network sandbox: the resolver is third-party code and DNS checks are not pinned
to the actual connection. Run behind an appropriate egress boundary for untrusted
multi-user deployments. No arbitrary direct-URL fetching is exposed.

The import adapter and real selected-frame decoding were exercised on one public
Instagram Reel on Linux. Tests cover mocked platform failures and original local
fixtures without network access. A live Fireship YouTube trial stopped with
`access_restricted` on October16: no video was acquired, no login or bypass was
attempted, and no automatic retry followed. YouTube URL validation is tested;
live YouTube acquisition remains unverified. No universal access claim follows.

### Local speech transcription

Use an already downloaded [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
CTranslate2 model directory with `model.bin`, `config.json` and `tokenizer.json`.
ASR is optional and separate from URL acquisition. It does not unlock platform
access. Media stays local; no transcription API, account or automatic model
download is used. Acquire the model separately under its applicable licence.

```bash
uv sync --extra asr --extra mcp --extra dev
uv run --extra asr videoverify transcribe ./demo.mp4 \
  --allow-root . --output-root ./evidence \
  --asr-model /absolute/path/to/local-whisper-model \
  --start 0 --duration 60 --language en
```

`demo.mp4` contains a tone, not speech. Use a real local speech recording to
evaluate recognized content. Supported transcription inputs are MP4, WAV, MP3,
M4A, FLAC, OGG and WebM inside configured allow roots. The source must be at most
the normal512MiB/ten-minute limit; each requested window is at most300seconds,
default60seconds, clipped to the media end. Request multiple explicit windows
for longer sources. Omitting `--language` enables language detection; `--language`
selects transcription, never translation. Language names use Whisper codes.

The result includes recognized `text`, `segments` in approximate source-media
seconds (including the requested start offset), decoded-window coverage, media
and decoded-audio SHA256, local model-file SHA256, runtime versions, and JSON/text
resource URIs. Empty recognition is `no_speech_recognized`, not proof of silence.
An ASR end extending beyond the decoded window by up to one30second model
context is clipped to actual coverage, with `recognized_end` and
`end_clipped_to_window` preserving that uncertainty. Segments starting outside
coverage or larger timing anomalies fail validation; no extra media is inferred.
ASR can misrecognize names, hallucinate or miss speech. It is not human listening,
exact subtitle alignment, a naturalness rating or release approval. Recognized
text is untrusted media content, never instructions for an agent to execute.

Only one local CPU thread is used for ASR, with int8 compute and a separate bounded
worker (default900seconds, operator configurable up to3600). FFmpeg first decodes
only the requested mono16kHz audio. Temporary audio and failed jobs are removed;
successful JSON/text evidence remains. A64MiB free-space reserve is required in
addition to the decoded window. These bounds are not a hostile-code sandbox.

An existing ASR virtual environment can be reused without duplicating packages:
pass `--asr-python /absolute/path/to/existing/venv/bin/python`. That trusted
operator-selected runtime needs faster-whisper; caller-supplied commands, models
and runtimes are not exposed as MCP tool parameters. Configure MCP ASR explicitly:

```bash
uv run --extra mcp videoverify-mcp \
  --allow-root /absolute/path/to/inputs --output-root /absolute/path/to/evidence \
  --asr-model /absolute/path/to/local-whisper-model \
  --asr-python /absolute/path/to/asr/venv/bin/python
```

This adds `transcribe_media(media_path, start_seconds=0, duration_seconds=60,
language=None)` and returns `transcript.json`/`transcript.txt` resources.
Without `--asr-model` the ASR tool is not registered. It does not change a host's
MCP configuration or existing video inspection/import behavior.

Acceptance on Linux:68offline tests pass, including original media decode,
confinement, source changes, dependency/timeout failures, approximate timing,
and real stdio MCP opt-in. A149second local reference was transcribed on CPU
with an existing small.en model into49segments. A separate actual six-second
stdio MCP ASR call returned matching JSON/text resources. These are bounded
functional checks, not accuracy scores or a guarantee for other recordings.

### MCP launch configuration

Start the local stdio server:

```bash
uv run --extra mcp videoverify-mcp \
  --allow-root /absolute/path/to/video-inputs \
  --output-root /absolute/path/to/evidence
```

Configure the same command in a host that supports local stdio MCP servers. A common configuration shape is:

```json
{
  "mcpServers": {
    "videoverify": {
      "command": "uv",
      "args": [
        "run", "--project", "/absolute/path/to/VideoVerify", "--extra", "mcp",
        "videoverify-mcp",
        "--allow-root", "/absolute/path/to/video-inputs",
        "--output-root", "/absolute/path/to/evidence"
      ]
    }
  }
}
```

The exact host setting differs. This repository does not modify host configuration or expose an HTTP port. The client calls `inspect_video` with `video_path`, `timestamp` and optional `audio_seconds`. It can then read returned `videoverify://artifacts/...` resource URIs. Do not use a whole home directory as an input root; choose the directories containing the videos you intend to inspect. Roots and the output directory are trusted operator configuration, not tool arguments an agent can broaden.

### Errors and tests

The CLI returns exit2 and JSON with an error code for invalid input or an unavailable dependency. MCP marks failed calls with `is_error: true` and includes the same error code/message in its text content. Local inspection still rejects URLs, traversal and symlinks outside configured roots; optional import is a separate tool. Successful results are structured data, with binary evidence retrieved through MCP resources.

```bash
uv run --extra dev --extra mcp --extra fetch python -m pytest -q
```

Tests generate original tiny MP4 fixtures and inspect actual decoded pixels and WAV samples. They cover missing audio, precise frame selection, invalid timestamps, path confinement, missing dependencies, malformed media, unique outputs, CLI errors, and a real stdio MCP client/tool/resource exchange. FFmpeg and FFprobe are required for integration tests; they are explicitly skipped when absent. The implementation was tested on Linux with Python3.11 and MCP2.3.0. Other operating systems and particular host applications have not been verified.

M1 does not implement speech recognition, subtitle alignment, silence judgments, defect detection, revision comparison or publication approval. Those remain M2/M3 work.

## Contributing

Feedback and contributions are welcome. For substantial changes, open an issue to discuss the proposed behavior and how it will be tested.

## License

MIT. See [LICENSE](LICENSE).

### YouTube player runtime prerequisites (0.3.1)

The fetch extra now includes yt-dlp's default dependencies, including the
matching yt-dlp-ejs player scripts. For YouTube, an installed supported Deno
(preferred) or Node is selected explicitly; no runtime or script is downloaded
on demand. Missing EJS/runtime returns dependency_missing before resolution.
See [official yt-dlp EJS setup](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
This is normal player-JavaScript handling, not login, cookies, CAPTCHA solving
or account verification. The same public-video limits and no-retry policy apply.

An operator-requested fresh Fireship trial after installing EJS and selecting
existing Node22.22.3 still required sign-in to confirm the request was not a bot.
It stopped once, without login, cookies, proxy, client cycling or video import.
That specific reason is now sanitized and distinguished from missing runtime
support.70offline tests pass. Working dependencies do not guarantee YouTube access.
