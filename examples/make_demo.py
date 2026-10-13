"""Generate a tiny original fixture. Never overwrite an existing output."""
import argparse
from pathlib import Path
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    output = args.out.resolve()
    if output.exists():
        parser.error("Choose a new output path; existing videos are preserved.")
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-n", "-threads", "2",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-threads", "2", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(output)], check=True, timeout=30)
    print(output)


if __name__ == "__main__":
    main()
