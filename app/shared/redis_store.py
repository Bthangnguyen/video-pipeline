import os
from typing import Any


class RedisJsonStore:
    def __init__(self, namespace: str, url: str | None = None, client: Any | None = None):
        self.namespace = namespace.strip(":")
        self.url = url if url is not None else os.getenv("REDIS_URL", "")
        self._client = client
        self._available = client is not None or bool(self.url)

    @property
    def enabled(self) -> bool:
        return self._available and self._client_or_none() is not None

    def get_text(self, key: str) -> str | None:
        client = self._client_or_none()
        if not client:
            return None
        try:
            value = client.get(self._key(key))
        except Exception:
            self._available = False
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return value if isinstance(value, str) else None

    def set_text(self, key: str, value: str, ttl_seconds: int | None = None) -> bool:
        client = self._client_or_none()
        if not client:
            return False
        try:
            if ttl_seconds:
                client.set(self._key(key), value, ex=ttl_seconds)
            else:
                client.set(self._key(key), value)
            return True
        except Exception:
            self._available = False
            return False

    def delete(self, key: str) -> bool:
        client = self._client_or_none()
        if not client:
            return False
        try:
            client.delete(self._key(key))
            return True
        except Exception:
            self._available = False
            return False

    def ping(self) -> bool:
        client = self._client_or_none()
        if not client:
            return False
        try:
            return bool(client.ping())
        except Exception:
            self._available = False
            return False

    def _client_or_none(self):
        if not self._available:
            return None
        if self._client is not None:
            return self._client
        if not self.url:
            self._available = False
            return None
        try:
            import redis

            self._client = redis.Redis.from_url(
                self.url,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
            self._client.ping()
            return self._client
        except Exception:
            self._available = False
            self._client = None
            return None

    def _key(self, key: str) -> str:
        return f"vp:{self.namespace}:{key}"
