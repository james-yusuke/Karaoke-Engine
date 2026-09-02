from __future__ import annotations

import importlib.metadata
import importlib.util
import math
import os
import shutil
import struct
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StemPaths:
    instrumental: Path
    vocals: Path
    engine: str


def _clamp_sample(value: float) -> int:
    return max(-32768, min(32767, int(round(value * 32767.0))))


def generate_synthetic_mix(path: Path, duration_seconds: float = 8.0, sample_rate: int = 44_100) -> Path:
    """Create a deterministic stereo WAV for debugging when no sample MP3 exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = int(duration_seconds * sample_rate)

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)

        frames = bytearray()
        for i in range(frame_count):
            t = i / sample_rate
            envelope = min(1.0, t / 0.15, max(0.0, (duration_seconds - t) / 0.2))
            vibrato = 5.0 * math.sin(2.0 * math.pi * 5.5 * t)
            vocal = 0.26 * math.sin(2.0 * math.pi * (440.0 + vibrato) * t)
            left_music = (
                0.22 * math.sin(2.0 * math.pi * 220.0 * t)
                + 0.12 * math.sin(2.0 * math.pi * 330.0 * t)
            )
            right_music = (
                0.20 * math.sin(2.0 * math.pi * 246.94 * t)
                + 0.10 * math.sin(2.0 * math.pi * 392.0 * t)
            )
            pulse = 0.08 if int(t * 4) % 4 == 0 and (t * 4) % 1 < 0.08 else 0.0
            left = envelope * (vocal + left_music + pulse)
            right = envelope * (vocal + right_music - pulse)
            frames.extend(struct.pack("<hh", _clamp_sample(left), _clamp_sample(right)))

        wav.writeframes(frames)
    return path


def phase_cancel_wav(input_path: Path, output_dir: Path) -> StemPaths:
    """Dependency-free debug/fallback separator for 16-bit stereo PCM WAV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    instrumental_path = output_dir / "no_vocals.wav"
    vocals_path = output_dir / "vocals.wav"

    with wave.open(str(input_path), "rb") as src:
        channels = src.getnchannels()
        width = src.getsampwidth()
        rate = src.getframerate()
        frames = src.readframes(src.getnframes())

    if channels != 2 or width != 2:
        raise ValueError("phase-cancellation fallback requires 16-bit stereo WAV")

    instrumental = bytearray()
    vocals = bytearray()
    for offset in range(0, len(frames), 4):
        left, right = struct.unpack_from("<hh", frames, offset)
        l = left / 32768.0
        r = right / 32768.0
        diff = max(-1.0, min(1.0, ((l - r) / 2.0) * 1.6))
        center = max(-1.0, min(1.0, (l + r) / 2.0))
        diff_sample = _clamp_sample(diff)
        center_sample = _clamp_sample(center)
        instrumental.extend(struct.pack("<hh", diff_sample, diff_sample))
        vocals.extend(struct.pack("<hh", center_sample, center_sample))

    for out_path, pcm in ((instrumental_path, instrumental), (vocals_path, vocals)):
        with wave.open(str(out_path), "wb") as dst:
            dst.setnchannels(2)
            dst.setsampwidth(2)
            dst.setframerate(rate)
            dst.writeframes(pcm)

    return StemPaths(
        instrumental=instrumental_path,
        vocals=vocals_path,
        engine="phase-cancellation",
    )


def _requirements_path() -> Path:
    return Path(__file__).resolve().parent / "requirements.txt"


def _install_hint() -> str:
    return f'"{sys.executable}" -m pip install -r "{_requirements_path()}"'


def _write_tensor_wav(path: Path, tensor: object, sample_rate: int) -> None:
    """Save a Demucs tensor as PCM16 WAV without torchaudio.save()."""
    try:
        import numpy as np
        import soundfile as sf
    except Exception as exc:
        raise RuntimeError(
            f"SoundFile/NumPy import failed ({type(exc).__name__}: {exc}). "
            f"Install dependencies with: {_install_hint()}"
        ) from exc

    try:
        array = tensor.detach().cpu().float().numpy()
    except AttributeError as exc:
        raise RuntimeError("Demucs returned an unsupported audio tensor") from exc

    if array.ndim == 1:
        audio = array
    elif array.ndim == 2:
        audio = array.T
    else:
        raise RuntimeError(f"unexpected Demucs tensor shape: {array.shape}")

    audio = np.clip(audio, -1.0, 1.0)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, int(sample_rate), format="WAV", subtype="PCM_16")


def _decode_with_ffmpeg(input_path: Path, sample_rate: int, channels: int):
    """Decode any FFmpeg-supported input directly into a float32 torch tensor."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is not installed or not on PATH")

    try:
        import numpy as np
        import torch
    except Exception as exc:
        raise RuntimeError(
            f"PyTorch/NumPy import failed ({type(exc).__name__}: {exc}). "
            f"Python: {sys.executable}. Install with: {_install_hint()}"
        ) from exc

    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "pipe:1",
    ]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg could not decode the audio: {stderr or 'unknown error'}")

    audio = np.frombuffer(completed.stdout, dtype="<f4")
    if audio.size == 0:
        raise RuntimeError("FFmpeg decoded zero audio samples")
    remainder = audio.size % channels
    if remainder:
        audio = audio[:-remainder]
    audio = audio.reshape(-1, channels).T.copy()
    return torch.from_numpy(audio)


def _transcode_to_pcm_wav(input_path: Path, output_path: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is required for the fallback separator")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg fallback conversion failed: {stderr or 'unknown error'}")
    return output_path


def _separate_with_demucs_core(input_path: Path, output_dir: Path) -> StemPaths:
    """Run Demucs without importing demucs.api or using torchaudio I/O."""
    try:
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model
    except Exception as exc:
        raise RuntimeError(
            "Demucs core import failed: "
            f"{type(exc).__name__}: {exc}. "
            f"Server Python: {sys.executable}. "
            f"Install into this exact Python with: {_install_hint()}"
        ) from exc

    model_name = os.getenv("KARAOKE_DEMUCS_MODEL", "htdemucs")
    device = os.getenv("KARAOKE_DEMUCS_DEVICE", "cpu")

    try:
        model = get_model(name=model_name)
        sample_rate = int(model.samplerate)
        channels = int(model.audio_channels)
        wav = _decode_with_ffmpeg(input_path, sample_rate, channels).float()

        ref = wav.mean(0)
        ref_mean = ref.mean()
        ref_std = ref.std()
        normalized = (wav - ref_mean) / (ref_std + 1e-8)

        with torch.no_grad():
            output = apply_model(
                model,
                normalized[None],
                shifts=1,
                split=True,
                overlap=0.25,
                device=device,
                num_workers=0,
                progress=False,
            )

        output = output * (ref_std + 1e-8) + ref_mean
        stems = dict(zip(model.sources, output[0]))
    except Exception as exc:
        raise RuntimeError(f"Demucs inference failed: {type(exc).__name__}: {exc}") from exc

    vocals = stems.get("vocals")
    if vocals is None:
        raise RuntimeError(
            "Demucs model did not return a 'vocals' stem "
            f"(available: {', '.join(sorted(stems.keys())) or 'none'})"
        )

    non_vocals = [stem for name, stem in stems.items() if name != "vocals"]
    if non_vocals:
        instrumental = non_vocals[0].clone()
        for stem in non_vocals[1:]:
            instrumental = instrumental + stem
    else:
        instrumental = wav - vocals

    output_root = output_dir / "demucs" / model_name / input_path.stem
    vocals_path = output_root / "vocals.wav"
    instrumental_path = output_root / "no_vocals.wav"
    _write_tensor_wav(vocals_path, vocals, sample_rate)
    _write_tensor_wav(instrumental_path, instrumental, sample_rate)

    return StemPaths(
        instrumental=instrumental_path,
        vocals=vocals_path,
        engine=f"demucs-core:{model_name}:{device}:ffmpeg+soundfile",
    )


def separate_with_demucs(input_path: Path, output_dir: Path) -> StemPaths:
    """Prefer Demucs; fall back to phase cancellation instead of returning HTTP 500."""
    try:
        return _separate_with_demucs_core(input_path, output_dir)
    except Exception as demucs_error:
        allow_fallback = os.getenv("KARAOKE_ALLOW_PHASE_FALLBACK", "true").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        if not allow_fallback:
            raise

        try:
            wav_path = _transcode_to_pcm_wav(input_path, output_dir / "fallback-input.wav")
            fallback = phase_cancel_wav(wav_path, output_dir / "fallback-stems")
        except Exception as fallback_error:
            raise RuntimeError(
                f"Demucs failed ({demucs_error}); fallback also failed ({fallback_error})"
            ) from fallback_error

        reason = f"{type(demucs_error).__name__}: {demucs_error}"
        if len(reason) > 180:
            reason = reason[:177] + "..."
        return StemPaths(
            instrumental=fallback.instrumental,
            vocals=fallback.vocals,
            engine=f"fallback-phase-cancellation [{reason}]",
        )


def separator_available() -> dict[str, object]:
    status: dict[str, object] = {
        "python": sys.executable,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "model": os.getenv("KARAOKE_DEMUCS_MODEL", "htdemucs"),
        "device": os.getenv("KARAOKE_DEMUCS_DEVICE", "cpu"),
        "phase_fallback": os.getenv("KARAOKE_ALLOW_PHASE_FALLBACK", "true").strip().lower()
        not in {"0", "false", "no", "off"},
    }

    for package in ("demucs", "torch", "soundfile", "numpy"):
        try:
            status[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            status[package] = None
        except Exception as exc:
            status[package] = f"error: {type(exc).__name__}: {exc}"

    status["demucs_spec"] = importlib.util.find_spec("demucs") is not None
    try:
        from demucs.apply import apply_model as _apply_model  # noqa: F401
        from demucs.pretrained import get_model as _get_model  # noqa: F401
    except Exception as exc:
        status["demucs_core"] = False
        status["demucs_error"] = f"{type(exc).__name__}: {exc}"
        status["install_command"] = _install_hint()
    else:
        status["demucs_core"] = True

    return status
