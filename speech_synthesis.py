import asyncio
import logging
from threading import Lock

import edge_tts
from aiohttp import ClientResponseError
from edge_tts import communicate
from edge_tts.constants import TRUSTED_CLIENT_TOKEN

# 沿用脚本原先配置的 Edge TTS 连接地址。
communicate.WSS_URL = (  # type: ignore[attr-defined]
    "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
    f"?Ocp-Apim-Subscription-Key={TRUSTED_CLIENT_TOKEN}"
)

logger = logging.getLogger(__name__)
CACHE_STORE: dict[tuple[str, str, str], bytes] = {}
CACHE_LOCK = Lock()
CACHE_LIMIT_BYTES = 64 * 1024 * 1024


class InvalidVoice(ValueError):
    pass


class SynthesisError(RuntimeError):
    def __init__(self, *, upstream_status: int | None = None) -> None:
        super().__init__("语音合成失败。")
        self.upstream_status = upstream_status


async def generate_edge_tts(text: str, voice: str, rate: str) -> bytes:
    try:
        speech = edge_tts.Communicate(text, voice, rate=rate)
    except ValueError as exc:
        raise InvalidVoice from exc

    audio = bytearray()
    async for chunk in speech.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    return bytes(audio)


def synthesize(text: str, voice: str, rate: str) -> bytes:
    cache_key = (text, voice, rate)
    with CACHE_LOCK:
        cached_audio = CACHE_STORE.get(cache_key)
        if cached_audio is not None:
            return cached_audio

    try:
        audio = asyncio.run(generate_edge_tts(text, voice, rate))
    except InvalidVoice:
        raise
    except ClientResponseError as exc:
        message = "语音服务已限流" if exc.status == 429 else "合成请求失败"
        logger.warning("微软 Edge %s（HTTP %d）", message, exc.status)
        raise SynthesisError(upstream_status=exc.status) from exc
    except Exception as exc:
        logger.warning("微软 Edge 合成失败，错误类型=%s", type(exc).__name__)
        raise SynthesisError() from exc

    if not audio:
        logger.warning("微软 Edge 未返回音频")
        raise SynthesisError()
    if len(audio) > CACHE_LIMIT_BYTES:
        return audio

    with CACHE_LOCK:
        if cache_key not in CACHE_STORE:
            cache_bytes = sum(map(len, CACHE_STORE.values()))
            if cache_bytes + len(audio) > CACHE_LIMIT_BYTES:
                CACHE_STORE.clear()
            CACHE_STORE[cache_key] = audio
    return audio
