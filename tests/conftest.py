from collections.abc import AsyncGenerator

import edge_tts
import pytest
from edge_tts.typing import TTSChunk
from flask.testing import FlaskClient

import speech_synthesis
from app import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> FlaskClient:
    monkeypatch.setattr(speech_synthesis, "CACHE_STORE", {})
    return app.test_client()


@pytest.fixture
def edge_requests(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    requests: list[tuple[str, str, str]] = []

    class StubCommunicate(edge_tts.Communicate):
        def __init__(self, text: str, voice: str, *, rate: str) -> None:
            super().__init__(text, voice, rate=rate)
            requests.append((text, voice, rate))

        async def stream(self) -> AsyncGenerator[TTSChunk, None]:
            yield {"type": "SentenceBoundary", "text": "test"}
            yield {"type": "audio", "data": b"ID3test "}
            yield {"type": "audio", "data": b"audio"}

    monkeypatch.setattr(edge_tts, "Communicate", StubCommunicate)
    return requests
