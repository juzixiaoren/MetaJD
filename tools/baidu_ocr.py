import asyncio
import os
import base64
import requests  # 确保已安装: pip install requests
import json
from pathlib import Path
from typing import List, Optional, Union
from pydantic import Field
from oxygent.oxy import FunctionHub
from dotenv import dotenv_values

# 1. 创建一个新的 FunctionHub 实例
baidu_ocr_tool = FunctionHub(name="image_tools")

# 2. 加载此工具专用的 .env (或回退到全局)
#    (与 github_tools.py 相同的模式)
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_ENV_PATH = os.path.join(TOOLS_DIR, '.env')
local_env_vars = {}
if os.path.exists(LOCAL_ENV_PATH):
    local_env_vars = dotenv_values(LOCAL_ENV_PATH) 
    print(f"✅ (baidu_ocr_tool) 已从 '{LOCAL_ENV_PATH}' 加载本地 .env。")
else:
    print(f"⚠️ (baidu_ocr_tool) 未在 'tools/' 目录找到 .env，将依赖 'service/' 目录的 .env。")

# 3. 获取 Access Token
#    我们假设 Token 存在于环境变量中 (由 .env 加载)
#    你需要单独获取这个 Token 并添加到 .env 文件中
BAIDU_OCR_ACCESS_TOKEN = local_env_vars.get("BAIDU_OCR_ACCESS_TOKEN") or os.getenv("BAIDU_OCR_ACCESS_TOKEN")

if not BAIDU_OCR_ACCESS_TOKEN:
    print("⚠️ (baidu_ocr_tool) 警告: 未找到 BAIDU_OCR_ACCESS_TOKEN。百度 OCR 工具将无法工作。")
    print("   请参考文档获取 Token 并将其添加到 .env 文件中。")

# 4. 定义核心的、阻塞的 API 调用逻辑
def _blocking_baidu_ocr_call(image_path: str) -> dict:
    """
    (同步函数) 执行 Baidu OCR API 调用。
    """
    
    ocr_url = "https://aip.baidubce.com/rest/2.0/ocr/v1/general" # 使用通用文字识别
    
    # 准备 API URL，带上 access_token
    # (根据文档，Access Token 在 URL 参数中)
    api_url = f"{ocr_url}?access_token={BAIDU_OCR_ACCESS_TOKEN}"
    
    # 1. 读取图片为二进制
    with open(image_path, "rb") as f:
        image_binary = f.read()
    
    # 2. Base64 编码 (不带 'data:image/...' 头)
    image_base64 = base64.b64encode(image_binary).decode('utf-8')
    
    # 3. 准备请求体 (application/x-www-form-urlencoded)
    #    requests 会自动 urlencode
    payload = {
        'image': image_base64
    }
    
    # 4. 准备请求头
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
    }
    
    print(f"DEBUG (baidu_ocr_tool): 正在向 Baidu OCR API 发送请求 (图片大小: {len(image_base64)} bytes)...")
    
    # 5. 发送 POST 请求
    response = requests.post(api_url, headers=headers, data=payload, timeout=30) # 30秒超时
    response.raise_for_status() # 检查 HTTP 错误
    
    return response.json()

# 5. 注册为异步工具
@baidu_ocr_tool.tool(
    description="对本地图片文件执行百度 OCR（光学字符识别），提取图片中的所有文本。"
)
async def recognize_text_from_image(
    image_path: str = Field(..., description="要识别的本地图片文件的路径 (例如 'screenshots/image.jpg')。")
) -> str:
    """
    (异步封装) 接收图片路径，调用百度 OCR API 并返回提取的文本。
    """
    if not BAIDU_OCR_ACCESS_TOKEN:
        return "Error: BAIDU_OCR_ACCESS_TOKEN is not configured."
        
    p = Path(image_path)
    if not p.exists() or p.is_dir():
        return f"Error: File not found or is a directory: {image_path}"

    try:
        # 在单独的线程中运行阻塞的网络和 I/O 操作
        result_json = await asyncio.to_thread(_blocking_baidu_ocr_call, image_path)
        
        # 6. 解析 API 返回的 JSON
        if "error_code" in result_json:
            error_msg = result_json.get('error_msg', 'Unknown API error')
            print(f"DEBUG (baidu_ocr_tool): Baidu API Error - {error_msg}")
            return f"Error from Baidu API (Code {result_json['error_code']}): {error_msg}"
        
        words_result = result_json.get("words_result", [])
        if not words_result:
            print(f"DEBUG (baidu_ocr_tool): Baidu API Success - No text detected.")
            return "No text detected."
            
        # 提取所有文本行
        extracted_text_lines = [item.get("words", "") for item in words_result if item.get("words")]
        full_text = "\n".join(extracted_text_lines)
        
        print(f"DEBUG (baidu_ocr_tool): Baidu API Success - Extracted {len(extracted_text_lines)} lines.")
        return full_text
        
    except requests.exceptions.HTTPError as http_err:
        print(f"Error (baidu_ocr_tool): HTTP error during OCR request: {http_err}")
        return f"Error: HTTP {http_err.response.status_code} during API call."
    except Exception as e:
        print(f"Error (baidu_ocr_tool): Unexpected error in recognize_text_from_image: {e}")
        import traceback
        traceback.print_exc()
        return f"Error running OCR task: {e}"
