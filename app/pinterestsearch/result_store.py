import time
import uuid
from dataclasses import dataclass

from app.pinterestsearch.schemas import PinterestResult


@dataclass
class StoredResult:
    result: PinterestResult
    expires_at: float


class ResultStore:
    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = ttl_seconds
        self._results: dict[str, StoredResult] = {}

    def put_many(self, results: list[PinterestResult]) -> list[PinterestResult]:
        expires_at = time.time() + self.ttl_seconds
        stored: list[PinterestResult] = []
        for result in results:
            if not result.result_id:
                result.result_id = f"pinr_{uuid.uuid4().hex}"
            self._results[result.result_id] = StoredResult(result=result, expires_at=expires_at)
            stored.append(result)
        self.cleanup()
        return stored

    def get(self, result_id: str) -> PinterestResult | None:
        record = self._results.get(result_id)
        if not record:
            return None
        if record.expires_at <= time.time():
            self._results.pop(result_id, None)
            return None
        return record.result

    def cleanup(self) -> None:
        now = time.time()
        expired = [key for key, record in self._results.items() if record.expires_at <= now]
        for key in expired:
            self._results.pop(key, None)
