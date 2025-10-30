import os
from pathlib import Path
from typing import List
from pydantic import Field
from oxygent.oxy import FunctionHub

from agents.all_agents import get_env_var

image_tools = FunctionHub(name="image_tools")

@image_tools.tool(
    description="Analyze one or more images to answer questions about their visual content. "
                "Supports tasks like: detecting UI elements, identifying objects, "
                "Provide a clear question such as 'Is there a product link?', or 'Is a button clicked?'."
)
async def analyze_image_directly(path: str) -> str:
    """直接调用 VLM 分析图像，绕过 ReAct 循环"""
    import os
    import base64
    from pathlib import Path
    from openai import OpenAI

    print(f"[DEBUG] analyze_image_directly called with: {path}")
    p = Path(path).resolve()
    if not p.exists():
        return f"Error: File not found: {path}"

    # 读取图片并转成 base64
    with open(p, "rb") as f:
        image_data = f.read()
        b64 = base64.b64encode(image_data).decode("utf-8")

    # 自动检测图片格式（可选）
    ext = p.suffix.lower()
    mime_type = "image/jpeg"
    if ext in [".png"]:
        mime_type = "image/png"
    elif ext in [".gif"]:
        mime_type = "image/gif"
    elif ext in [".webp"]:
        mime_type = "image/webp"

    # 构造 Data URL（这是 OpenAI 支持的方式）
    data_url = f"data:{mime_type};base64,{b64}"

    client = OpenAI(
        api_key=os.getenv("DEFAULT_VLM_API_KEY"),
        base_url=os.getenv("DEFAULT_VLM_BASE_URL")
    )

    try:
        response = client.chat.completions.create(
            model=os.getenv("DEFAULT_VLM_MODEL_NAME"),
            messages=[
                {"role": "user", "content": "详细分析这张图片"},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]}
            ],
            max_tokens=500,
            timeout=30
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error calling VLM: {str(e)}"

@image_tools.tool(
    description="Check whether an image file exists and is readable."
)
def is_valid_image(image_path: str = Field(description="Path to the image file to check")) -> bool:
    p = Path(image_path)
    if not p.exists() or p.is_dir():
        return False
    # Try to open with OpenCV to verify it's a valid image
    try:
        import cv2
        img = cv2.imread(str(p))
        return img is not None
    except Exception:
        return False
    

from paddleocr import PaddleOCR
_ocr_engine = PaddleOCR(
    use_angle_cls=True,
    lang='ch',
    det_db_box_thresh=0.1,
    det_db_unclip_ratio=1.5,
)

# @image_tools.tool(description="Extract visible text from an image using PaddleOCR.")
# def extract_text(
#     image_path: str = Field(description="Path to the image file (JPG/PNG).")
# ) -> str:
#     try:
#         print(f"🔍 正在处理图片: {image_path}")
#         if not Path(image_path).exists():
#             return f"❌ 文件不存在: {image_path}"

#         results = _ocr_engine.predict(input=image_path)

#         # 打印原始结果（调试用）
#         print("📄 原始 OCR 结果:", results)

#         if not results:
#             return "No text detected."

#         texts = []
#         for res in results:
#             # ✅ 正确解析：访问 rec_texts 字段
#             if 'rec_texts' in res and isinstance(res['rec_texts'], list):
#                 for text in res['rec_texts']:
#                     if text.strip():
#                         texts.append(text.strip())

#         return "\n".join(texts) if texts else "No text detected."

#     except Exception as e:
#         import traceback
#         return f"❌ OCR 执行失败：\n{traceback.format_exc()}"