import re

from flask import Blueprint, Response, current_app, jsonify, request
from flask.typing import ResponseReturnValue

from speech_synthesis import InvalidVoice, SynthesisError, synthesize

openai_compat = Blueprint("openai_compat", __name__, url_prefix="/v1")

SPEECH_MODEL = "tts-1"
VOICE_EXAMPLE = "zh-CN-XiaoxiaoNeural"
EDGE_VOICE_NAME = re.compile(
    r"[a-z]{2,}-[A-Z]{2,}-.+Neural|Microsoft Server Speech Text to Speech Voice \(.+,.+\)"
)
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

@openai_compat.after_app_request
def allow_read_aloud(response: Response) -> Response:
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
    message: str,
    *,
    status: int = 400,
    param: str | None = None,
    error_type: str = "invalid_request_error",
    code: str | None = None,
) -> tuple[Response, int]:
    return (
        jsonify(
            error={"message": message, "type": error_type, "param": param, "code": code}
        ),
        status,
    )


@openai_compat.get("/models")
def list_models() -> Response:
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


@openai_compat.post("/audio/speech")
def create_speech() -> ResponseReturnValue:
    payload = request.get_json(silent=True)
    current_app.logger.info(
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
            f"请指定 Edge 音色，例如 '{VOICE_EXAMPLE}'。", param="voice"
        )
    voice = voice.strip()
    if EDGE_VOICE_NAME.fullmatch(voice) is None:
        return openai_error(
            f"请指定完整的 Edge 音色名，例如 '{VOICE_EXAMPLE}'。",
            param="voice",
            code="unsupported_value",
        )

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
            f"当前服务不支持此音色，请使用 Edge 音色，例如 '{VOICE_EXAMPLE}'。",
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
