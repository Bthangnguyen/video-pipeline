import time

from app.douyinsearch.result_store import ResultStore
from app.douyinsearch.schemas import DouyinResult


def test_result_store_expires_items():
    store = ResultStore(ttl_seconds=1)
    result = DouyinResult(result_id="r1", douyin_aweme_id="a1")

    store.put_many([result])
    assert store.get("r1") is not None

    store._results["r1"].expires_at = time.time() - 1
    assert store.get("r1") is None

