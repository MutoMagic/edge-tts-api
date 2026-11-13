import re

from flask import Blueprint, Response, request
from flask.typing import ResponseReturnValue

from speech_synthesis import InvalidVoice, SynthesisError, synthesize

danmaku_api = Blueprint("danmaku_api", __name__, url_prefix="/danmaku")

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


def clean_text_logic(text: str) -> str:
    # 弹幕读音和停顿处理。
    text = text.replace("弹幕", "旦幕").replace("彈幕", "旦幕")
    text = text.replace(":", "").replace("：", "")
    return " ".join(text.split())


@danmaku_api.get("/tts", strict_slashes=False)
def tts_proxy() -> ResponseReturnValue:
    text = clean_text_logic(request.args.get("text", ""))
    if not text:
        return "text 参数不能为空。", 400
    if text == "$TTSTEXT":
        return "请将 text 参数中的 $TTSTEXT 替换为待播报文本。", 400

    voice_alias = request.args.get("voice")
    voice = VOICE_NAME if voice_alias is None else CHINESE_VOICES.get(voice_alias)
    if voice is None:
        return "voice 参数必须是有效的音色短名，例如 yunxi。", 400
    rate = request.args.get("rate", VOICE_RATE)
    if re.fullmatch(r"[+-][0-9]+%", rate) is None:
        return "rate 参数必须是带符号的整数百分比，例如 +20%（URL 编码为 %2B20%25）。", 400

    try:
        audio = synthesize(text, voice, rate)
    except (InvalidVoice, SynthesisError):
        return "语音合成失败。", 500
    return Response(audio, mimetype="audio/mpeg")
