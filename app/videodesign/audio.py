import shutil
import subprocess
import wave
from pathlib import Path


def measure_audio_duration(path: str | Path) -> float:
    audio_path = Path(path)
    if not audio_path.exists():
        return 0.0
    if audio_path.suffix.lower() == ".wav":
        return _measure_wav_duration(audio_path)
    return _measure_with_ffprobe(audio_path) or _measure_mp3_duration(audio_path)


def concatenate_audio_files(paths: list[str | Path], output_dir: str | Path) -> tuple[Path, float]:
    audio_paths = [Path(path) for path in paths if path]
    if not audio_paths:
        raise ValueError("No audio files to combine.")
    for audio_path in audio_paths:
        if not audio_path.exists():
            raise ValueError(f"Audio file does not exist: {audio_path}")

    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    wav_output = output_root / "voiceover_combined.wav"
    if _try_concatenate_wav(audio_paths, wav_output):
        return wav_output, measure_audio_duration(wav_output)

    mp3_output = output_root / "voiceover_combined.mp3"
    _concatenate_with_ffmpeg(audio_paths, mp3_output)
    return mp3_output, measure_audio_duration(mp3_output)


def _measure_wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            frame_rate = handle.getframerate()
            if frame_rate <= 0:
                return 0.0
            return handle.getnframes() / float(frame_rate)
    except (wave.Error, OSError):
        return 0.0


def _measure_with_ffprobe(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0.0
    if result.returncode != 0:
        return 0.0
    try:
        return max(0.0, float((result.stdout or "").strip()))
    except ValueError:
        return 0.0


def _measure_mp3_duration(path: Path) -> float:
    try:
        data = path.read_bytes()
    except OSError:
        return 0.0
    if len(data) < 4:
        return 0.0

    index = _skip_id3v2(data)
    duration = 0.0
    frames = 0
    while index + 4 <= len(data):
        header = int.from_bytes(data[index:index + 4], "big")
        parsed = _parse_mp3_header(header)
        if not parsed:
            index += 1
            continue
        frame_length, samples_per_frame, sample_rate = parsed
        if frame_length <= 0 or index + frame_length > len(data):
            index += 1
            continue
        duration += samples_per_frame / sample_rate
        frames += 1
        index += frame_length
    return duration if frames else 0.0


def _skip_id3v2(data: bytes) -> int:
    if len(data) < 10 or data[:3] != b"ID3":
        return 0
    size = 0
    for byte in data[6:10]:
        size = (size << 7) | (byte & 0x7F)
    return min(len(data), 10 + size)


def _parse_mp3_header(header: int) -> tuple[int, int, int] | None:
    if ((header >> 21) & 0x7FF) != 0x7FF:
        return None
    version_id = (header >> 19) & 0x3
    layer = (header >> 17) & 0x3
    bitrate_index = (header >> 12) & 0xF
    sample_index = (header >> 10) & 0x3
    padding = (header >> 9) & 0x1
    if version_id == 1 or layer != 1 or bitrate_index in (0, 15) or sample_index == 3:
        return None

    mpeg1_bitrates = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
    mpeg2_bitrates = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]
    sample_rates = {
        3: [44100, 48000, 32000],
        2: [22050, 24000, 16000],
        0: [11025, 12000, 8000],
    }
    bitrate = (mpeg1_bitrates if version_id == 3 else mpeg2_bitrates)[bitrate_index] * 1000
    sample_rate = sample_rates[version_id][sample_index]
    samples_per_frame = 1152 if version_id == 3 else 576
    coefficient = 144 if version_id == 3 else 72
    frame_length = int((coefficient * bitrate) / sample_rate) + padding
    return frame_length, samples_per_frame, sample_rate


def _try_concatenate_wav(paths: list[Path], output_path: Path) -> bool:
    if not paths or any(path.suffix.lower() != ".wav" for path in paths):
        return False
    try:
        with wave.open(str(paths[0]), "rb") as first:
            params = first.getparams()
            signature = (params.nchannels, params.sampwidth, params.framerate, params.comptype, params.compname)
            frames = [first.readframes(first.getnframes())]
        for path in paths[1:]:
            with wave.open(str(path), "rb") as handle:
                next_params = handle.getparams()
                next_signature = (
                    next_params.nchannels,
                    next_params.sampwidth,
                    next_params.framerate,
                    next_params.comptype,
                    next_params.compname,
                )
                if next_signature != signature:
                    return False
                frames.append(handle.readframes(handle.getnframes()))
        with wave.open(str(output_path), "wb") as output:
            output.setparams(params)
            for frame_data in frames:
                output.writeframes(frame_data)
        return True
    except (wave.Error, OSError):
        return False


def _concatenate_with_ffmpeg(paths: list[Path], output_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("ffmpeg is required to combine non-WAV audio files.")

    list_path = output_path.with_suffix(".concat.txt")
    try:
        list_path.write_text(
            "\n".join(f"file '{_concat_path(path)}'" for path in paths),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-vn",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    finally:
        try:
            list_path.unlink()
        except OSError:
            pass
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "ffmpeg audio concat failed").strip()
        raise ValueError(message)


def _concat_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "'\\''")
