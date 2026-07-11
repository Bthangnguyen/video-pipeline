import math
from pathlib import Path
import wave

from fastapi.testclient import TestClient


def create_project(client: TestClient) -> str:
    response = client.post(
        "/api/videodesign/projects",
        json={
            "script": "Cats can recognize your voice. They often ignore it anyway. This makes cat videos funny.",
            "target_duration_seconds": 18,
            "language": "en",
        },
    )
    assert response.status_code == 200
    return response.json()["project"]["project_id"]


def write_test_wav(path: Path, duration_seconds: float = 0.5) -> None:
    sample_rate = 16000
    frame_count = max(1, int(sample_rate * duration_seconds))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            sample = int(math.sin(2 * math.pi * 440 * (index / sample_rate)) * 8000)
            frames.extend(sample.to_bytes(2, "little", signed=True))
        wav.writeframes(bytes(frames))
