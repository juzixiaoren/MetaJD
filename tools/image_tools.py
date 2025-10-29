import os
from pathlib import Path
from typing import List
from pydantic import Field
from oxygent.oxy import FunctionHub

image_tools = FunctionHub(name="image_tools")

@image_tools.tool(
    description="Analyze one or more images to answer questions about their visual content. "
                "Supports tasks like: detecting UI elements, reading visible text, identifying objects, "
                "or checking for user interactions (e.g., mouse clicks). "
                "Provide a clear question such as 'Is there a product link?', 'What text is shown?', or 'Is a button clicked?'."
)
def analyze_images(
    image_paths: List[str] = Field(
        description="List of local image file paths (e.g., ['frame_000001.jpg', 'screenshot.png']). "
                    "All files must exist and be in a supported format (JPG, PNG, etc.)."
    ),
    question: str = Field(
        description="A specific, concrete question about the image content for the vision model to answer."
    )
) -> str:
    """
    Validates image paths and returns a structured request for the image_agent to delegate to multimodal_agent.
    This tool does NOT perform analysis itself — it signals that image understanding is required.
    """
    invalid_paths = []
    for path in image_paths:
        p = Path(path)
        if not p.exists():
            invalid_paths.append(str(p))
        elif p.is_dir():
            invalid_paths.append(f"{path} (is a directory)")

    if invalid_paths:
        return f"Error: The following image paths are invalid: {invalid_paths}"

    # Return a clear delegation signal that image_agent can parse and act on
    return (
        f"REQUEST_MULTIMODAL_ANALYSIS: "
        f"Images: {image_paths} | Question: {question}"
    )

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

@image_tools.tool(description="Extract visible text from an image using PaddleOCR.")
def extract_text(
    image_path: str = Field(description="Path to the image file (JPG/PNG).")
) -> str:
    try:
        print(f"🔍 正在处理图片: {image_path}")
        if not Path(image_path).exists():
            return f"❌ 文件不存在: {image_path}"

        results = _ocr_engine.predict(input=image_path)

        # 打印原始结果（调试用）
        print("📄 原始 OCR 结果:", results)

        if not results:
            return "No text detected."

        texts = []
        for res in results:
            # ✅ 正确解析：访问 rec_texts 字段
            if 'rec_texts' in res and isinstance(res['rec_texts'], list):
                for text in res['rec_texts']:
                    if text.strip():
                        texts.append(text.strip())

        return "\n".join(texts) if texts else "No text detected."

    except Exception as e:
        import traceback
        return f"❌ OCR 执行失败：\n{traceback.format_exc()}"