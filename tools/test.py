# test.py
import asyncio
from image_tools import extract_text

import os
from pathlib import Path
current_dir = Path(__file__).parent
project_root = current_dir.parent

# ✅ 正确拼接路径
image_path = project_root / "data" / "初赛数据集" / "valid" / "aec58d53.jpg"

# 如果需要字符串（传给 OCR 工具），再转 str
image_path_str = str(image_path)

async def main():
    result = await extract_text(image_path_str)
    print("=== OCR 结果 ===")
    print(result)

if __name__ == "__main__":
    asyncio.run(main())