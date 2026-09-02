from __future__ import annotations

import tempfile
import wave
from pathlib import Path

try:
    from .separation import generate_synthetic_mix, phase_cancel_wav
except ImportError:
    from separation import generate_synthetic_mix, phase_cancel_wav


def _peak(path: Path) -> int:
    with wave.open(str(path), "rb") as wav:
        data = wav.readframes(wav.getnframes())
    samples = memoryview(data).cast("h")
    return max(abs(int(sample)) for sample in samples)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="karaoke-self-test-") as temp:
        root = Path(temp)
        mix = generate_synthetic_mix(root / "mix.wav", duration_seconds=2.0)
        stems = phase_cancel_wav(mix, root / "stems")

        assert mix.exists() and mix.stat().st_size > 44
        assert stems.instrumental.exists() and stems.instrumental.stat().st_size > 44
        assert stems.vocals.exists() and stems.vocals.stat().st_size > 44
        assert _peak(stems.instrumental) > 0
        assert _peak(stems.vocals) > 0

        print("self-test: OK")
        print(f"engine: {stems.engine}")
        print("synthetic input and both stems were generated successfully")


if __name__ == "__main__":
    main()
