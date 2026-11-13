import pytest
from flask.testing import FlaskClient


def test_danmaku_preserves_encoded_plus_signs(
    client: FlaskClient, edge_requests: list[tuple[str, str, str]]
) -> None:
    response = client.get("/danmaku/tts?text=%E4%BD%A0%E5%A5%BD%EF%BC%8CC%2B%2B")

    assert response.status_code == 200
    assert response.mimetype == "audio/mpeg"
    assert response.data == b"ID3test audio"
    assert edge_requests == [("你好，C++", "zh-CN-XiaoxiaoNeural", "+20%")]


@pytest.mark.parametrize(
    ("options", "voice", "rate"),
    [
        ({"voice": "yunxi"}, "zh-CN-YunxiNeural", "+20%"),
        ({"rate": "-10%"}, "zh-CN-XiaoxiaoNeural", "-10%"),
        ({"voice": "yunxi", "rate": "+0%"}, "zh-CN-YunxiNeural", "+0%"),
        ({"voice": "yunxi", "rate": "+30%"}, "zh-CN-YunxiNeural", "+30%"),
    ],
)
def test_danmaku_sets_voice_and_rate_independently(
    client: FlaskClient,
    edge_requests: list[tuple[str, str, str]],
    options: dict[str, str],
    voice: str,
    rate: str,
) -> None:
    response = client.get("/danmaku/tts", query_string={"text": "早上好", **options})

    assert response.status_code == 200
    assert edge_requests == [("早上好", voice, rate)]


@pytest.mark.parametrize(
    ("param", "value"),
    [
        ("voice", ""),
        ("voice", "alloy"),
        ("rate", ""),
        ("rate", "20%"),
        ("rate", "+1.5%"),
        ("rate", "+20"),
        ("rate", "+20%\n"),
    ],
)
def test_danmaku_reports_invalid_voice_or_rate(
    client: FlaskClient,
    edge_requests: list[tuple[str, str, str]],
    param: str,
    value: str,
) -> None:
    response = client.get("/danmaku/tts", query_string={"text": "无效设置", param: value})

    assert response.status_code == 400
    assert param in response.get_data(as_text=True)
    assert edge_requests == []


@pytest.mark.parametrize("query", ["", "?text=", "?text=%20%09", "?text=%24TTSTEXT"])
def test_danmaku_requires_substituted_text(
    client: FlaskClient, edge_requests: list[tuple[str, str, str]], query: str
) -> None:
    response = client.get(f"/danmaku/tts{query}")

    assert response.status_code == 400
    assert ("$TTSTEXT" if "TTSTEXT" in query else "text") in response.get_data(as_text=True)
    assert edge_requests == []


def test_danmaku_applies_pronunciation_and_pause_rules(
    client: FlaskClient, edge_requests: list[tuple[str, str, str]]
) -> None:
    response = client.get("/danmaku/tts", query_string={"text": "弹幕：  彈幕:\n来了"})

    assert response.status_code == 200
    assert edge_requests == [("旦幕 旦幕 来了", "zh-CN-XiaoxiaoNeural", "+20%")]


def test_danmaku_uses_only_get_and_query_text(
    client: FlaskClient, edge_requests: list[tuple[str, str, str]]
) -> None:
    assert client.get("/tts?text=hello").status_code == 404
    assert client.get("/danmaku/tts/hello?text=hello").status_code == 404
    assert client.post("/danmaku/tts?text=hello").status_code == 405
    assert client.get("/danmaku/tts", data="hello").status_code == 400
    assert edge_requests == []
