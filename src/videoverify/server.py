"""Optional local stdio MCP adapter. No live host configuration changes."""
import argparse
import json
import sys
from typing import Any

from .cli import configuration
from .core import Inspector, InspectionError


def create_server(inspector: Inspector):
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

    server = MCPServer("VideoVerify", instructions=(
        "Inspect allowlisted local MP4 files. Returned artifacts are evidence, "
        "not subjective quality ratings or publication approval."))

    @server.tool()
    def inspect_video(video_path: str, timestamp: float, audio_seconds: float = 4) -> dict[str, Any]:
        """Return metadata, the picture visible at timestamp, and an optional WAV excerpt."""
        try:
            return inspector.inspect(video_path, timestamp, audio_seconds)
        except InspectionError as exc:
            raise ToolError(json.dumps(exc.as_dict())) from exc
        except OSError as exc:
            raise ToolError(json.dumps({"ok": False, "error": {
                "code": "io_error", "message": "Unable to read or write local evidence."}})) from exc

    @server.resource("videoverify://artifacts/{inspection_id}/frame.png", mime_type="image/png")
    def frame(inspection_id: str) -> bytes:
        """Read a returned PNG artifact, never an arbitrary local file."""
        return inspector.read_artifact(inspection_id, "frame.png")

    @server.resource("videoverify://artifacts/{inspection_id}/audio.wav", mime_type="audio/wav")
    def audio(inspection_id: str) -> bytes:
        """Read a returned mono16kHz WAV excerpt."""
        return inspector.read_artifact(inspection_id, "audio.wav")

    @server.resource("videoverify://artifacts/{inspection_id}/inspection.json", mime_type="application/json")
    def report(inspection_id: str) -> str:
        """Read the saved structured inspection report."""
        return inspector.read_artifact(inspection_id, "inspection.json").decode()

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    configuration(parser)
    args = parser.parse_args()
    try:
        inspector = Inspector(args.allow_root, args.output_root)
        server = create_server(inspector)
    except ImportError:
        parser.error('Install MCP support with pip install "videoverify[mcp]" from this checkout.')
    except InspectionError as exc:
        print(json.dumps(exc.as_dict()), file=sys.stderr)
        raise SystemExit(2) from exc
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
