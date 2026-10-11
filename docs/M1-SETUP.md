# M1 — Local setup and smoke test

Prerequisites: Python 3.10+ and FFmpeg/FFprobe on PATH.

From the repository root on Windows PowerShell:

    .\.venv\Scripts\Activate.ps1
    python -m pip install -e ".[dev]"
    python -m pytest -q

Create a directory containing the MP4 files agents are allowed to inspect,
and set the environment variable in the terminal that launches the server:

    $env:VIDEOVERIFY_ALLOWED_DIR = "C:\Code\VideoVerify\VideoVerify\videos"
    videoverify-mcp

The server uses MCP stdio transport; it will appear to hang if launched
directly without an MCP client. In an MCP client, configure the command
to point at your virtual environment's \`videoverify-mcp\` executable (or
use \`python -m videoverify.server\`) and pass
\`VIDEOVERIFY_ALLOWED_DIR\` via the client environment configuration.

Example call to MCP tool \`inspect_video\`:

    {"video_path": "example.mp4", "timestamp": 72}

A successful response contains \`ok: true\`, duration, dimensions, and
temporary local file paths for a frame and (when available) an audio sample.
An expected failure contains \`ok: false\` with \`error.code\` and
\`error.message\`. No transcription, quality assessment, or comparison is
implemented yet.

Never allow untrusted clients to point this local filesystem tool at
arbitrary directories. Generated evidence artifacts are stored in the OS
temporary directory and should be cleaned up after use.
