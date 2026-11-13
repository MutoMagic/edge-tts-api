from collections.abc import AsyncIterator

import edge_tts
import pytest
from aiohttp import ClientResponseError, RequestInfo
from edge_tts.typing import TTSChunk
from flask.testing import FlaskClient
from multidict import CIMultiDict, CIMultiDictProxy
from werkzeug.test import TestResponse
from yarl import URL

READ_ALOUD_ORIGIN = "chrome-extension://hdhinadidafjejdhmfkjgnolgimiaplp"
READ_ALOUD_HEADERS = {"Origin": READ_ALOUD_ORIGIN, "Authorization": "Bearer local-test"}
READ_ALOUD_REQUEST = {
    "model": "tts-1",
    "voice": "zh-CN-XiaoxiaoNeural",
    "input": "弹幕：  你好，C++\n",
    "response_format": "mp3",
}


def assert_openai_error(
    response: TestResponse,
    *,
    status: int = 400,
    param: str | None = None,
    error_type: str = "invalid_request_error",
    code: str | None = None,
) -> None:
    assert response.status_code == status
    error = response.get_json()["error"]
    assert isinstance(error["message"], str) and error["message"]
    assert error == {"message": error["message"], "type": error_type, "param": param, "code": code}


def test_read_aloud_can_check_the_models_endpoint(client: FlaskClient) -> None:
    response = client.get("/v1/models", headers=READ_ALOUD_HEADERS)

    assert response.status_code == 200
    assert response.get_json() == {
        "object": "list",
        "data": [{"id": "tts-1", "object": "model", "created": 0, "owned_by": "edge-tts"}],
    }
    assert response.headers["Access-Control-Allow-Origin"] == READ_ALOUD_ORIGIN
    assert "Origin" in response.vary


def test_read_aloud_can_request_mp3_with_a_full_edge_voice_name(
    client: FlaskClient, edge_requests: list[tuple[str, str, str]]
) -> None:
    response = client.post("/v1/audio/speech", json=READ_ALOUD_REQUEST, headers=READ_ALOUD_HEADERS)

    assert response.status_code == 200
    assert response.mimetype == "audio/mpeg"
    assert response.data == b"ID3test audio"
    assert response.headers["Access-Control-Allow-Origin"] == READ_ALOUD_ORIGIN
    assert edge_requests == [("弹幕：  你好，C++\n", "zh-CN-XiaoxiaoNeural", "+0%")]


@pytest.mark.parametrize(
    ("voice", "code"),
    [("alloy", "unsupported_value"), ("yunxi", "unsupported_value"), ("", None)],
)
def test_openai_requires_a_full_edge_voice_name(
    client: FlaskClient, edge_requests: list[tuple[str, str, str]], voice: str, code: str | None
) -> None:
    response = client.post(
        "/v1/audio/speech",
        json={**READ_ALOUD_REQUEST, "input": "音色参数检查", "voice": voice},
        headers=READ_ALOUD_HEADERS,
    )

    assert_openai_error(response, param="voice", code=code)
    assert response.headers["Access-Control-Allow-Origin"] == READ_ALOUD_ORIGIN
    assert edge_requests == []


@pytest.mark.parametrize(("speed", "rate"), [(0.25, "-75%"), (1.2, "+20%"), (4, "+300%")])
def test_openai_converts_speed_and_defaults_to_mp3(
    client: FlaskClient, edge_requests: list[tuple[str, str, str]], speed: float, rate: str
) -> None:
    response = client.post(
        "/v1/audio/speech",
        json={"model": "tts-1", "input": "测试播放速度", "voice": "en-US-JennyNeural", "speed": speed},
    )

    assert response.status_code == 200
    assert response.mimetype == "audio/mpeg"
    assert response.data == b"ID3test audio"
    assert edge_requests == [("测试播放速度", "en-US-JennyNeural", rate)]


@pytest.mark.parametrize(
    ("param", "value", "code"),
    [
        ("model", "tts-1-hd", None),
        ("input", " \t", None),
        ("speed", True, None),
        ("speed", "1.2", None),
        ("speed", 0.2, None),
        ("speed", 4.1, None),
        ("response_format", "wav", "unsupported_value"),
        ("stream_format", "sse", "unsupported_value"),
    ],
)
def test_openai_rejects_unsupported_request_values(
    client: FlaskClient,
    edge_requests: list[tuple[str, str, str]],
    param: str,
    value: object,
    code: str | None,
) -> None:
    response = client.post("/v1/audio/speech", json={**READ_ALOUD_REQUEST, param: value})

    assert_openai_error(response, param=param, code=code)
    assert edge_requests == []


def test_openai_reports_invalid_json(client: FlaskClient) -> None:
    response = client.post("/v1/audio/speech", data="{", content_type="application/json")

    assert_openai_error(response)


@pytest.mark.parametrize(
    ("path", "method", "headers"),
    [
        ("/v1/models", "GET", "authorization"),
        ("/v1/audio/speech", "POST", "authorization,content-type"),
    ],
)
def test_read_aloud_preflight(
    client: FlaskClient, path: str, method: str, headers: str
) -> None:
    response = client.options(
        path,
        headers={
            "Origin": READ_ALOUD_ORIGIN,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == READ_ALOUD_ORIGIN
    assert method in response.headers["Access-Control-Allow-Methods"]
    assert response.headers["Access-Control-Allow-Headers"] == "Authorization, Content-Type"
    assert "Origin" in response.vary


def test_openai_cors_varies_by_origin(client: FlaskClient) -> None:
    response = client.get("/v1/models", headers={"Origin": "https://example.com"})

    assert response.status_code == 200
    assert "Origin" in response.vary
    assert "Access-Control-Allow-Origin" not in response.headers


@pytest.mark.parametrize(
    ("upstream_status", "status", "error_type", "code"),
    [(429, 429, "rate_limit_error", "rate_limit_exceeded"), (503, 502, "server_error", None)],
)
def test_openai_reports_edge_errors_and_allows_a_retry(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    edge_requests: list[tuple[str, str, str]],
    upstream_status: int,
    status: int,
    error_type: str,
    code: str | None,
) -> None:
    url = URL("https://example.com/tts")
    request_info = RequestInfo(url, "GET", CIMultiDictProxy(CIMultiDict()), url)

    async def interrupted_stream(_: edge_tts.Communicate) -> AsyncIterator[TTSChunk]:
        yield {"type": "audio", "data": b"partial audio"}
        raise ClientResponseError(request_info, (), status=upstream_status)

    payload = {**READ_ALOUD_REQUEST, "input": f"合成失败后重试 {upstream_status}"}
    with monkeypatch.context() as upstream:
        upstream.setattr(edge_tts.Communicate, "stream", interrupted_stream)
        response = client.post("/v1/audio/speech", json=payload, headers=READ_ALOUD_HEADERS)

    assert_openai_error(response, status=status, error_type=error_type, code=code)
    assert response.headers["Access-Control-Allow-Origin"] == READ_ALOUD_ORIGIN

    retry = client.post("/v1/audio/speech", json=payload, headers=READ_ALOUD_HEADERS)
    assert retry.status_code == 200
    assert retry.data == b"ID3test audio"
    assert len(edge_requests) == 2


def test_danmaku_and_openai_share_synthesized_audio(
    client: FlaskClient, edge_requests: list[tuple[str, str, str]]
) -> None:
    text = "同一段文本，C++"
    danmaku = client.get("/danmaku/tts", query_string={"text": text})
    openai = client.post(
        "/v1/audio/speech", json={**READ_ALOUD_REQUEST, "input": text, "speed": 1.2}
    )

    assert danmaku.status_code == openai.status_code == 200
    assert danmaku.data == openai.data == b"ID3test audio"
    assert edge_requests == [(text, "zh-CN-XiaoxiaoNeural", "+20%")]
