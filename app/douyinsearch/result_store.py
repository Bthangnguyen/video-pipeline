import time
import uuid
from dataclasses import dataclass

from app.douyinsearch.schemas import DouyinResult
from app.shared.redis_store import RedisJsonStore


@dataclass
class StoredResult:
    result: DouyinResult
    expires_at: float


class ResultStore:
    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = ttl_seconds
        self._results: dict[str, StoredResult] = {}
        self.redis = RedisJsonStore("douyin_result")

    def put_many(self, results: list[DouyinResult]) -> list[DouyinResult]:
        expires_at = time.time() + self.ttl_seconds
        stored: list[DouyinResult] = []
        for result in results:
            if not result.result_id:
                result.result_id = f"dyr_{uuid.uuid4().hex}"
            self._results[result.result_id] = StoredResult(result=result, expires_at=expires_at)
            self.redis.set_text(result.result_id, result.model_dump_json(), self.ttl_seconds)
            stored.append(result)
        self.cleanup()
        return stored

    def get(self, result_id: str) -> DouyinResult | None:
        record = self._results.get(result_id)
        if record:
            if record.expires_at <= time.time():
                self._results.pop(result_id, None)
            else:
                return record.result

        payload = self.redis.get_text(result_id)
        if not payload:
            return None
        try:
            result = DouyinResult.model_validate_json(payload)
        except Exception:
            self.redis.delete(result_id)
            return None
        self._results[result_id] = StoredResult(result=result, expires_at=time.time() + self.ttl_seconds)
        return result

    def cleanup(self) -> None:
        now = time.time()
        expired = [key for key, record in self._results.items() if record.expires_at <= now]
        for key in expired:
            self._results.pop(key, None)

