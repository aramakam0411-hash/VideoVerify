"""MCP stdio server for local VideoVerify inspection."""
from mcp.server.fastmcp import FastMCP

from videoverify.core.video import InspectionError, inspect_media

mcp = FastMCP("VideoVerify")


@mcp.tool()
def inspect_video(video_path: str, timestamp: float = 0.0) -> dict:
    """Inspect an allowed local MP4 file at timestamp (seconds).

    Returns JSON-compatible metadata and evidence paths. The video path may be
    absolute or relative to VIDEOVERIFY_ALLOWED_DIR. Files outside the allowed
    directory are rejected. This does not make quality judgments.
    """
    try:
        return inspect_media(video_path, timestamp)
    except InspectionError as exc:
        return {"ok": False, "error": {"code": exc.code, "message": str(exc)}}


@mcp.tool()
def get_server_info() -> dict:
    """Return basic information about VideoVerify."""

    return {
        "name": "VideoVerify",
        "version": "0.1.0",
        "purpose": "Quality inspection of video files through AI agents",
        "status": "Under development"
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
