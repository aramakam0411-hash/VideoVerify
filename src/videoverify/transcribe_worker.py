"""Private optional local faster-whisper worker. No automatic model download."""
import json
from pathlib import Path
import sys
from importlib.metadata import version


def main():
    model_path, audio_path, output_path, language = sys.argv[1:]
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        Path(output_path).write_text(json.dumps({"ok": False, "error": "dependency_missing"}))
        return 2
    try:
        model = WhisperModel(model_path, device="cpu", compute_type="int8", cpu_threads=1,
                             num_workers=1, local_files_only=True)
        segments, info = model.transcribe(audio_path, language=language or None, task="transcribe",
            beam_size=3, temperature=0.0, condition_on_previous_text=False,
            initial_prompt=None, hotwords=None, vad_filter=False, word_timestamps=False)
        rows = []
        characters = 0
        for segment in segments:
            characters += len(segment.text)
            if len(rows) >= 5000 or characters > 100000:
                raise ValueError("report limit")
            rows.append({"start": segment.start, "end": segment.end, "text": segment.text})
        result = {"ok": True, "segments": rows, "language": info.language,
                  "versions": {name: version(name) for name in ("faster-whisper", "ctranslate2")}}
    except Exception:
        result = {"ok": False, "error": "transcription_failed"}
    Path(output_path).write_text(json.dumps(result), encoding="utf-8")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
