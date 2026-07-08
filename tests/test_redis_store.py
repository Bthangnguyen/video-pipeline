
from datetime import datetime, timezone

from app.douyinsearch.result_store import ResultStore
from app.douyinsearch.schemas import DouyinResult
from app.shared.redis_store import RedisJsonStore
from app.videodesign.schemas import VideoDesignProject
from app.videodesign.store import VideoDesignStore


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.ttls[key] = ex
        return True

    def delete(self, key):
        self.values.pop(key, None)
        return True

    def ping(self):
        return True


def test_result_store_restores_from_redis():
    client = FakeRedis()
    store = ResultStore(ttl_seconds=60)
    store.redis = RedisJsonStore("douyin_result", client=client)
    result = DouyinResult(result_id="redis-result", douyin_aweme_id="aweme")

    store.put_many([result])
    store._results.clear()

    restored = store.get("redis-result")

    assert restored is not None
    assert restored.douyin_aweme_id == "aweme"
    assert client.ttls["vp:douyin_result:redis-result"] == 60


def test_videodesign_store_restores_project_from_redis(tmp_path, monkeypatch):
    client = FakeRedis()
    store = VideoDesignStore()
    store.redis = RedisJsonStore("project", client=client)
    monkeypatch.setattr(store, "_project_path", lambda project_id: tmp_path / project_id / "project.json")
    project = VideoDesignProject(
        project_id="redis-project",
        script="hello",
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    store.put(project)
    store._projects.clear()
    (tmp_path / "redis-project" / "project.json").unlink()

    restored = store.get("redis-project")

    assert restored.project_id == "redis-project"
    assert restored.script == "hello"
