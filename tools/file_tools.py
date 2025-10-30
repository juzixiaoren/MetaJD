# tools/file_tools.py
import os
from pathlib import Path
from pydantic import Field
from oxygent.oxy import FunctionHub
import base64
file_tools = FunctionHub(name="file_tools")
@file_tools.tool(
    description="Return the current working directory."
)
def get_current_directory() -> str:
    return os.getcwd()

@file_tools.tool(
    description="List all files and folders in the given directory. Default is current directory."
)
def list_directory(path: str = Field(default=".", description="Directory path to list")) -> list[str]:
    p = Path(path)
    if not p.exists():
        return f"Error: Path '{path}' does not exist."
    if not p.is_dir():
        return f"Error: Path '{path}' is not a directory."
    # 返回所有项名称列表
    return [item.name for item in p.iterdir()]

@file_tools.tool(
    description="Read the content of a text file. Returns error if file does not exist or is a directory."
)
def read_file(path: str = Field(description="Path to the file to read")) -> str:
    p = Path(path)
    if not p.exists():
        return f"Error: The file at '{path}' does not exist."
    if p.is_dir():
        return f"Error: The path '{path}' is a directory, not a file."
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file '{path}': {e}"

@file_tools.tool(
    description="Create or overwrite a file with new content. Uses UTF-8 encoding."
)
def write_file(path: str = Field(description="Path to the file to write"),
               content: str = Field(description="Text content to write into the file")) -> str:
    p = Path(path)
    # 确保父目录存在
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote to '{path}'."
    except Exception as e:
        return f"Error writing to file '{path}': {e}"

@file_tools.tool(
    description="Delete a file. Returns success message if deleted, or error if it does not exist."
)
def delete_file(path: str = Field(description="Path to the file to delete")) -> str:
    p = Path(path)
    if not p.exists():
        return f"Error: The file at '{path}' does not exist."
    if p.is_dir():
        return f"Error: The path '{path}' is a directory, not a file."
    try:
        p.unlink()
        return f"Successfully deleted '{path}'."
    except Exception as e:
        return f"Error deleting file '{path}': {e}"

@file_tools.tool(
    description="Count files with the given extension in the directory (non-recursive)."
)
def count_file_type(path: str = Field(default=".", description="Directory path to search"),
                    extension: str = Field(description="File extension (e.g. 'txt' or '.txt')")) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    if not p.is_dir():
        return 0
    # 标准化扩展名
    ext = extension if extension.startswith(".") else f".{extension}"
    count = 0
    for f in p.iterdir():
        if f.is_file() and f.suffix.lower() == ext.lower():
            count += 1
    return count


# @file_tools.tool(
#     description="Read image and return data URI string for DashScope VLM."
# )
# def read_image_as_base64(path: str = Field(description="Path to the image file")) -> str:
#     p = Path(path).resolve()
#     if not p.exists():
#         return f"Error: Image file not found at '{path}'."
#     try:
#         with open(p, "rb") as f:
#             b64 = base64.b64encode(f.read()).decode("utf-8")
#         suffix = p.suffix.lower()
#         mime = "image/jpeg"
#         if suffix in (".png",): mime = "image/png"
#         elif suffix in (".bmp",): mime = "image/bmp"
#         elif suffix in (".webp",): mime = "image/webp"
#         return f"{mime};base64,{b64}"  # ✅ 无  前缀
#     except Exception as e:
#         return f"data:{mime};base64,{b64}" 
def read_image_as_base64(path: str) -> str:
    p = Path(path).resolve()
    print(f"[DEBUG] Resolved path: {p}")
    print(f"[DEBUG] File exists: {p.exists()}")
    if not p.exists():
        err = f"Error: Image file not found at '{path}'."
        print(f"[DEBUG] Tool error: {err}")
        return err
    try:
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        # ✅ 只返回纯 base64，不加任何前缀
        print(f"[DEBUG] Base64 length: {len(b64)}")
        return b64  # ← 关键：不要加 "data:image/...;base64,"
    except Exception as e:
        err = f"Error reading image file '{path}': {e}"
        print(f"[DEBUG] Tool exception: {err}")
        return err