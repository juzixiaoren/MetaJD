# tools/file_tools.py
import os
from pathlib import Path
from pydantic import Field
from oxygent.oxy import FunctionHub

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


@file_tools.tool(
    description="Read an image file (jpg, png, etc.) and return its base64-encoded string. "
                "This is used for multimodal analysis. Input must be a valid image file path."
)
def read_image_as_base64(path: str = Field(description="Path to the image file (e.g., .jpg, .png)")) -> str:
    """
    读取图像文件并返回 base64 字符串（不含 data URI 前缀，仅纯 base64）
    """
    p = Path(path).resolve()
    if not p.exists():
        return f"Error: Image file not found at '{path}'."
    if p.is_dir():
        return f"Error: Path '{path}' is a directory, not an image file."
    try:
        with open(p, "rb") as f:
            import base64
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        return f"Error reading image file '{path}': {e}"