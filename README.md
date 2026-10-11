# VideoVerify

**Agent-first video quality assurance and fix verification.**

VideoVerify is an open-source project that helps AI agents inspect videos, identify verifiable problems, and determine whether a revision fixed an issue without introducing new regressions.

> **Status:** Early development. The interfaces and features below are planned, not yet implemented.

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
         +-- Speech and subtitle alignment (later)
         +-- Quality checks (later)
         +-- Before/after comparison (later)
         |
         v
  Structured results + evidence artifacts
```

The analysis core will be independent of MCP so it can also power a CLI and an optional human-facing viewer without duplicating logic.

## First milestone: inspect a local video

The first MCP tool, tentatively named `inspect_video`, will accept a local MP4 path and timestamp. It will return structured metadata, a still frame, and an audio excerpt (if an audio stream exists). It must also report missing files, invalid timestamps, and unavailable dependencies as explicit errors.

Planned stack: **Python**, **FFmpeg/FFprobe**, and the **official MCP Python SDK**. A frontend and AI-based subjective video scoring are not required for the first milestone.

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

- [ ] **M1 — Inspect:** MP4 validation, metadata, frame/audio extraction, an MCP tool, and tests.
- [ ] **M2 — Analyze:** transcript/subtitle support and reliable timestamped checks.
- [ ] **M3 — Verify:** compare before/after revisions and detect regressions.
- [ ] **M4 — Release:** documentation, examples, automated tests in CI, and optional human-readable reports.

## Getting started

The project is **not runnable yet**. Installation and MCP client configuration will be added when the first functional milestone is implemented.

```bash
git clone https://github.com/aramakam0411-hash/VideoVerify.git
cd VideoVerify
```

## Contributing

Feedback and contributions are welcome. For substantial changes, open an issue to discuss the proposed behavior and how it will be tested.

## License

MIT. See [LICENSE](LICENSE).
