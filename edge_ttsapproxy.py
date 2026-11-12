import asyncio
import edge_tts
import urllib.parse
from flask import Flask, request, Response
from aiohttp import ClientResponseError
from edge_tts import communicate
from edge_tts.constants import TRUSTED_CLIENT_TOKEN

# 覆盖默认 WSS URL 解决 403 问题
communicate.WSS_URL = (
    "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
    f"?Ocp-Apim-Subscription-Key={TRUSTED_CLIENT_TOKEN}"
)

app = Flask(__name__)

# ======================= Edge-TTS 配置 =======================
VOICE_NAME = "zh-CN-XiaoxiaoNeural"
VOICE_RATE = "+20%"
VOICE_PITCH = "+0Hz"
# =============================================================

# 保留内存缓存器 & 限制缓存上限 64MB
# 使用字典存储多条弹幕历史，总大小到达 64MB 时全自动释放旧内存
CACHE_STORE = {}  # 格式: { "清洗后的文本": b"音频二进制数据" }
CACHE_LIMIT_BYTES = 64 * 1024 * 1024  # 64MB 换算为字节

print("=" * 50)
print("正在监听本地 1234 端口... 坐等高能弹幕...")
print("=" * 50)

def clean_text_logic(text):
    if not text:
        return ""
    # 保留修复多音字：强行将“弹幕/彈幕”替换为同音字“旦幕”确保发音正确
    text = text.replace("弹幕", "旦幕").replace("彈幕", "旦幕")
    # 清理掉可能导致断句和停顿的符号，保持语流连贯
    text = text.replace(":", "").replace("：", "")
    text = " ".join(text.split())
    return text

async def generate_edge_tts(text):
    # 增加重试机制应对 429 速率限制
    for attempt in range(3):
        communicate_obj = edge_tts.Communicate(text, VOICE_NAME, rate=VOICE_RATE, pitch=VOICE_PITCH)
        audio_bytes = b""
        try:
            async for chunk in communicate_obj.stream():
                if chunk["type"] == "audio":
                    audio_bytes += chunk["data"]
            return audio_bytes
        except ClientResponseError as e:
            if e.status == 429 and attempt < 2:
                await asyncio.sleep(3)
                continue
            raise
    return b""

@app.route('/tts', methods=['GET', 'POST'])
@app.route('/tts/', methods=['GET', 'POST'])
@app.route('/tts/<path:path_text>', methods=['GET', 'POST'])
def tts_proxy(path_text=None):
    global CACHE_STORE
    
    # 1. 提取并清洗文本
    text_data = path_text if path_text else request.args.get('text', '')
    if not text_data:
        text_data = request.data.decode('utf-8').strip()
        
    text_data = urllib.parse.unquote_plus(text_data)
    text_data = clean_text_logic(text_data)
    
    if not text_data or text_data == "$TTSTEXT":
        return "Text Empty", 400
        
    # 2. 保留内存缓存器：如果这句弹幕之前读过，直接秒回传本地音频
    if text_data in CACHE_STORE:
        print(f"[命中内存缓存] \"{text_data}\" -> 0ms 响应")
        return Response(CACHE_STORE[text_data], mimetype="audio/mpeg")
        
    print("\n" + "-" * 40)
    print(f"-> [新请求] 正在调用微软 Edge 合成: \"{text_data}\"")
    
    # 3. 强健的线程隔离异步循环，规避 Windows + Flask 底层报错
    audio_content = b""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        audio_content = loop.run_until_complete(generate_edge_tts(text_data))
    except Exception as edge_err:
        print(f"[微软 Edge 引擎异常]: {edge_err}")
    finally:
        loop.close()
        
    # 4. 处理音频并控制 64MB 缓存闸门
    if audio_content:
        # 限制缓存上限 64MB：动态计算字典内所有音频的总字节大小
        current_total_bytes = sum(len(v) for v in CACHE_STORE.values())
        
        # 如果塞入新音频后会撑爆 64MB，则一键清空旧缓存防爆内存
        if current_total_bytes + len(audio_content) > CACHE_LIMIT_BYTES:
            print(f"[警告] 缓存池已逼近 64MB 安全线（当前: {current_total_bytes/1024/1024:.2f}MB），正在全自动回收旧内存...")
            CACHE_STORE.clear()
            
        # 写入缓存并回传播放
        CACHE_STORE[text_data] = audio_content
        print(f"[微软 Edge] 新音频合成成功！已存入全局缓存字典。")
        return Response(audio_content, mimetype="audio/mpeg")
    else:
        return "TTS Failed", 500

if __name__ == '__main__':
    # 维持关闭 debug 模式，保持多线程高并发下的绝对稳定
    app.run(host='127.0.0.1', port=1234, debug=False)