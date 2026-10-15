"""JSON inspection CLI. MCP uses the same core."""
import argparse
import json
from pathlib import Path
import sys

from .core import Inspector, InspectionError


def configuration(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--allow-root", type=Path, action="append", required=True,
                        help="Local input directory, repeat for additional roots")
    parser.add_argument("--output-root", type=Path, required=True,
                        help="Directory for unique inspection artifacts")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="Extract metadata, one frame and an optional audio excerpt")
    configuration(inspect)
    inspect.add_argument("video")
    inspect.add_argument("--timestamp", type=float, required=True)
    inspect.add_argument("--audio-seconds", type=float, default=4)
    fetch = sub.add_parser("fetch", help="Import one public Instagram/YouTube video (optional fetch extra)")
    fetch.add_argument("url")
    fetch.add_argument("--cache-root", type=Path, required=True)
    sequence = sub.add_parser("sequence", help="Extract up to 24 timestamped pictures in one pass")
    configuration(sequence)
    sequence.add_argument("video")
    sequence.add_argument("--timestamps", type=float, nargs="+", required=True)
    args = parser.parse_args()
    try:
        if args.command == "fetch":
            from .acquisition import Acquirer
            result = Acquirer(args.cache_root).fetch(args.url)
        elif args.command == "sequence":
            result = Inspector(args.allow_root, args.output_root).inspect_sequence(args.video, args.timestamps)
        else:
            result = Inspector(args.allow_root, args.output_root).inspect(args.video, args.timestamp, args.audio_seconds)
    except InspectionError as exc:
        print(json.dumps(exc.as_dict()))
        return 2
    except OSError:
        print(json.dumps({"ok": False, "error": {"code": "io_error", "message": "Unable to read or write local evidence."}}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
