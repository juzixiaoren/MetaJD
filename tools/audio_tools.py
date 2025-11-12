import asyncio
import os
from pathlib import Path
import dashscope
from oxygent.oxy import FunctionHub
from pydantic import Field

# 1. 创建 FunctionHub
audio_tools = FunctionHub(name="audio_tools")
os.environ["DASHSCOPE_API_KEY"] = "sk-32563fc60b6d4ca69b000299020e3114"
# 2. 配置 Dashscope API 密钥
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY") #
if DASHSCOPE_API_KEY:
    dashscope.api_key = DASHSCOPE_API_KEY
    dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'
else:
    print("⚠️ (audio_tools) 警告: 未在 .env 中找到 DASHSCOPE_API_KEY。Qwen-Audio 将无法工作。")

# 3. 定义*阻塞*的 SDK 调用
def _blocking_audio_call(file_path: str, model_name: str) -> str: # <--- 修正 1: 移除 query
    """
    这是一个同步函数，用于执行 Dashscope (ASR) 的阻塞调用。
    """
    abs_path = Path(file_path).resolve()
    file_url = f"file://{abs_path}"

    messages = [
        {
            "role": "system",
            "content": [{"text": ""}] # <--- (来自新示例)
        },
        {
            "role": "user",
            "content": [
                {"audio": file_url}, # <--- (来自新示例)
                # <--- 修正 2: 移除 {"text": query}
            ]
        }
    ]
    
    # 修正 3: 添加 asr_options
    asr_options = {
        "enable_lid": True,
        "enable_itn": False
    }

    try:
        response = dashscope.MultiModalConversation.call(
            api_key=DASHSCOPE_API_KEY, # <--- (明确传递 api_key)
            model=model_name,
            messages=messages,
            result_format="message",
            asr_options=asr_options # <--- 修正 4: 传入 new param
        )
        
        if response.status_code == 200:
            content = response["output"]["choices"][0]["message"]["content"]
            for part in content:
                if "text" in part:
                    return part["text"]
            return f"Error: 未在 {model_name} 的响应中找到 'text' 部分。"
        else:
            return f"Error from Dashscope API: (Code: {response.status_code}) {response.message}"
    except Exception as e:
        return f"Error calling {model_name}: {e}"

@audio_tools.tool(
    description="将本地音频文件（MP3, MP4） 识别为文本。输入文件路径和模型名称。"
)
async def transcribe_audio_file( # <--- 修正 5: 移除 query
    path: str = Field(description="要识别的本地音频文件路径 (e.g., 'audio.mp3')"),
) -> str:
    """
    OxyGent 调用的异步封装器。
    """
    if not DASHSCOPE_API_KEY:
        return "Error: DASHSCOPE_API_KEY is not configured."
    
    # <--- 修正 6: 移除 query
    result = await asyncio.to_thread(_blocking_audio_call, path, "qwen3-asr-flash")
    return result