import asyncio
import logging
from threading import Lock
from urllib.parse import unquote_plus

import edge_tts
from aiohttp import ClientResponseError
from edge_tts import communicate
from edge_tts.constants import TRUSTED_CLIENT_TOKEN
from flask import Flask, Response, jsonify, request

# 沿用脚本原先配置的 Edge TTS 连接地址。
communicate.WSS_URL = (
    "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
    f"?Ocp-Apim-Subscription-Key={TRUSTED_CLIENT_TOKEN}"
)

app = Flask(__name__)
app.json.ensure_ascii = False
app.logger.setLevel(logging.INFO)

CHINESE_VOICES = {
    "yunjian": "zh-CN-YunjianNeural",
    "yunxi": "zh-CN-YunxiNeural",
    "yunxia": "zh-CN-YunxiaNeural",
    "yunyang": "zh-CN-YunyangNeural",
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",
    "xiaoyi": "zh-CN-XiaoyiNeural",
}
VOICE_NAME = CHINESE_VOICES["xiaoxiao"]
VOICE_RATE = "+20%"
SPEECH_MODEL = "tts-1"
SPEECH_REQUEST_FIELDS = {
    "model",
    "input",
    "voice",
    "speed",
    "response_format",
    "stream_format",
    "instructions",
}
READ_ALOUD_ORIGIN = "chrome-extension://hdhinadidafjejdhmfkjgnolgimiaplp"

CACHE_STORE = {}
CACHE_LOCK = Lock()
CACHE_LIMIT_BYTES = 64 * 1024 * 1024


class InvalidVoice(ValueError):
    pass


class SynthesisError(RuntimeError):
    def __init__(self, *, upstream_status=None):
        super().__init__("语音合成失败。")
        self.upstream_status = upstream_status


def clean_text_logic(text):
    # /tts 的弹幕读音和停顿处理。
    if not text:
        return ""
    text = text.replace("弹幕", "旦幕").replace("彈幕", "旦幕")
    text = text.replace(":", "").replace("：", "")
    return " ".join(text.split())


async def generate_edge_tts(text, voice=VOICE_NAME, rate=VOICE_RATE):
    try:
        speech = edge_tts.Communicate(text, voice, rate=rate)
    except ValueError as exc:
        raise InvalidVoice from exc

    audio = bytearray()
    async for chunk in speech.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    return bytes(audio)


def synthesize(text, voice=VOICE_NAME, rate=VOICE_RATE):
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
        app.logger.warning("微软 Edge %s（HTTP %d）", message, exc.status)
        raise SynthesisError(upstream_status=exc.status) from exc
    except Exception as exc:
        app.logger.warning("微软 Edge 合成失败，错误类型=%s", type(exc).__name__)
        raise SynthesisError() from exc

    if not audio:
        app.logger.warning("微软 Edge 未返回音频")
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


@app.after_request
def allow_read_aloud(response):
    if request.path.startswith("/v1/"):
        response.vary.add("Origin")
        if request.headers.get("Origin") == READ_ALOUD_ORIGIN:
            response.headers["Access-Control-Allow-Origin"] = READ_ALOUD_ORIGIN
            if request.method == "OPTIONS":
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = (
                    "Authorization, Content-Type"
                )
    return response


def openai_error(
    message, *, status=400, param=None, error_type="invalid_request_error", code=None
):
    return (
        jsonify(
            error={"message": message, "type": error_type, "param": param, "code": code}
        ),
        status,
    )


@app.get("/v1/models")
def list_models():
    return jsonify(
        object="list",
        data=[
            {
                "id": SPEECH_MODEL,
                "object": "model",
                "created": 0,
                "owned_by": "edge-tts",
            }
        ],
    )


@app.post("/v1/audio/speech")
def create_speech():
    payload = request.get_json(silent=True)
    app.logger.info(
        "/v1/audio/speech 请求参数=%r",
        payload if payload is not None else request.get_data(as_text=True),
    )
    if not isinstance(payload, dict):
        return openai_error("请将 Content-Type 设为 application/json，并发送 JSON 对象。")

    for field in payload:
        if field not in SPEECH_REQUEST_FIELDS:
            return openai_error(
                f"不支持请求参数 '{field}'。", param=field, code="unknown_parameter"
            )

    if payload.get("model") != SPEECH_MODEL:
        return openai_error(f"请将语音模型设为 '{SPEECH_MODEL}'。", param="model")
    if "instructions" in payload:
        return openai_error(
            "当前语音模型不支持合成指令。",
            param="instructions",
            code="unsupported_parameter",
        )

    text = payload.get("input")
    if not isinstance(text, str) or not text.strip() or len(text) > 4096:
        return openai_error("请输入 1 至 4096 个字符的非空文本。", param="input")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return openai_error("输入必须是有效的 Unicode 文本。", param="input")

    voice = payload.get("voice")
    if isinstance(voice, dict):
        return openai_error(
            "当前服务不支持自定义音色对象，请使用 Edge 音色名称。",
            param="voice",
            code="unsupported_value",
        )
    if not isinstance(voice, str) or not voice.strip():
        return openai_error(
            f"请指定 Edge 音色，例如 '{VOICE_NAME}'。", param="voice"
        )
    voice = voice.strip()
    voice = VOICE_NAME if voice == "alloy" else CHINESE_VOICES.get(voice, voice)

    if payload.get("response_format", "mp3") != "mp3":
        return openai_error(
            "当前服务仅支持 MP3 音频。",
            param="response_format",
            code="unsupported_value",
        )
    if payload.get("stream_format", "audio") != "audio":
        return openai_error(
            "当前模型仅支持 'audio' 流式响应格式。",
            param="stream_format",
            code="unsupported_value",
        )

    speed = payload.get("speed", 1.0)
    if type(speed) not in (int, float) or not 0.25 <= speed <= 4.0:
        return openai_error("语速必须是 0.25 至 4.0 范围内的数值。", param="speed")
    rate = f"{round((speed - 1) * 100):+d}%"

    try:
        audio = synthesize(text, voice, rate)
    except InvalidVoice:
        return openai_error(
            f"当前服务不支持此音色，请使用 Edge 音色，例如 '{VOICE_NAME}'。",
            param="voice",
            code="unsupported_value",
        )
    except SynthesisError as exc:
        if exc.upstream_status == 429:
            return openai_error(
                "微软 Edge 语音服务已限流，请稍后重试。",
                status=429,
                error_type="rate_limit_error",
                code="rate_limit_exceeded",
            )
        return openai_error(
            "微软 Edge 未能生成音频。", status=502, error_type="server_error"
        )

    return Response(audio, mimetype="audio/mpeg")


@app.route("/tts", methods=["GET", "POST"])
@app.route("/tts/", methods=["GET", "POST"])
@app.route("/tts/<path:path_text>", methods=["GET", "POST"])
def tts_proxy(path_text=None):
    text = path_text or request.args.get("text")
    if not text:
        body = request.data.decode("utf-8")
        if body:
            app.logger.info("/tts 请求正文=%r", body)
        text = body.strip()
    text = clean_text_logic(unquote_plus(text))
    if not text or text == "$TTSTEXT":
        return "文本为空。", 400

    try:
        audio = synthesize(text)
    except (InvalidVoice, SynthesisError):
        return "语音合成失败。", 500
    return Response(audio, mimetype="audio/mpeg")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=1234, debug=False)
