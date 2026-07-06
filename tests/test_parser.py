from app.douyinsearch.parser import parse_dom_cards, parse_search_payload


def test_parse_search_payload_aweme_info():
    payload = {
        "data": [
            {
                "type": 1,
                "aweme_info": {
                    "aweme_id": "735",
                    "desc": "caption",
                    "author": {"nickname": "alice", "sec_uid": "sec"},
                    "video": {
                        "duration": 12300,
                        "width": 1080,
                        "height": 1920,
                        "cover": {"url_list": ["https://cover"]},
                        "play_addr": {"url_list": ["https://video"]},
                    },
                    "statistics": {"digg_count": 10},
                },
            }
        ]
    }

    results = parse_search_payload(payload, 10)

    assert len(results) == 1
    assert results[0].douyin_aweme_id == "735"
    assert results[0].duration == 12.3
    assert results[0].stream_remote_url == "https://video"


def test_parse_dom_cards_deduplicates_video_ids():
    cards = [
        {"href": "https://www.douyin.com/video/1", "title": "one"},
        {"href": "https://www.douyin.com/video/1", "title": "duplicate"},
        {"href": "https://www.douyin.com/video/2", "title": "two"},
    ]

    results = parse_dom_cards(cards, 10)

    assert [result.douyin_aweme_id for result in results] == ["1", "2"]

