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


@image_tools.tool(description="Extract visible text from an image using VLM (qwen3-vl-plus). "
                              "This tool sends the image to a vision-language model for text extraction.")
def extract_text(
    image_path: str = Field(description="Path to the image file (JPG/PNG).")
) -> str:
    """
    使用 VLM 模型（qwen3-vl-plus）从图像中提取文字。
    返回特殊格式的请求信号，由 image_agent 转发给 VLM 进行处理。
    """
    try:
        print(f"🔍 [VLM-OCR] 正在处理图片: {image_path}")
        if not Path(image_path).exists():
            return f"❌ 文件不存在: {image_path}"

        # 返回一个特殊信号，告诉 image_agent 需要调用 VLM 进行 OCR
        return (
            f"REQUEST_VLM_OCR: "
            f"Image: {image_path} | "
            f"Task: 提取图像中的所有可见文字,包括中文、英文、数字和符号。请按从上到下、从左到右的顺序输出所有文字内容,每行文字单独一行。如果没有文字,输出'No text detected.'"
        )

    except Exception as e:
        import traceback
        return f"❌ OCR 请求失败：\n{traceback.format_exc()}"
