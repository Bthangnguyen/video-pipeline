from app.douyinsearch.schemas import DouyinResult
from app.douyinsearch.stream_proxy import no_watermark_url_from_result


def test_no_watermark_url_prefers_bitrate_play_addr():
    result = DouyinResult(
        result_id="r1",
        douyin_aweme_id="a1",
        raw={"video": {"bit_rate": [{"play_addr": {"url_list": ["https://video.example/no-watermark.mp4"]}}]}},
    )

    assert no_watermark_url_from_result(result) == "https://video.example/no-watermark.mp4"


def test_no_watermark_url_rewrites_playwm_url():
    result = DouyinResult(
        result_id="r1",
        douyin_aweme_id="a1",
        raw={"video": {"play_addr": {"url_list": ["https://video.example/playwm/source.mp4"]}}},
    )

    assert no_watermark_url_from_result(result) == "https://video.example/play/source.mp4"


def test_no_watermark_url_builds_snssdk_play_url_from_uri():
    result = DouyinResult(
        result_id="r1",
        douyin_aweme_id="a1",
        raw={"video": {"play_addr": {"uri": "v0200fg10000"}}},
    )

    assert no_watermark_url_from_result(result) == "https://aweme.snssdk.com/aweme/v1/play/?video_id=v0200fg10000&ratio=1080p&line=0"
