# tools/file_tools.py
"""
Enhanced universal file_tools for OxyGent
- recursive listing including directories (dir entries end with '/')
- read/write/delete
- supports text/doc formats: txt/json/md/code-workspace/csv/pdf/docx/pptx/xlsx
- auto-convert old .ppt -> .pptx via LibreOffice soffice (if available)
- layered PDF extraction: PyPDF2 -> pdfplumber -> optional OCR (pdf2image+pytesseract)
- multimedia (image/audio/video) returns absolute path for downstream tools
- find_files / find_and_read_file utilities
"""
import os
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Union, Optional
from fnmatch import fnmatch
import re
import mimetypes
import playwright
import time


from pydantic import Field
from oxygent.oxy import FunctionHub

file_tools = FunctionHub(name="file_tools")

print("✅ Loaded enhanced file_tools (full version)")

# -------------------------
# Helpers
# -------------------------
def _norm_path(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p)
    return p

def _to_return_path(root: Path, p: Path, absolute: bool) -> str:
    try:
        return str(p.resolve()) if absolute else str(p.relative_to(root))
    except Exception:
        return str(p.resolve())

def _find_soffice_executable() -> Optional[str]:
    """Try to find LibreOffice soffice executable"""
    soffice = shutil.which("soffice") or shutil.which("soffice.exe")
    if soffice:
        return soffice
    common_paths = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for p in common_paths:
        if Path(p).exists():
            return p
    return None

def _convert_ppt_to_pptx_via_soffice(ppt_path: Path, out_dir: Path, soffice_path: Optional[str] = None, timeout: int = 60) -> Optional[Path]:
    soffice_exec = soffice_path or _find_soffice_executable()
    if not soffice_exec:
        return None
    try:
        cmd = [
            str(soffice_exec),
            "--headless",
            "--convert-to", "pptx",
            "--outdir", str(out_dir),
            str(ppt_path)
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        converted = out_dir / (ppt_path.stem + ".pptx")
        if converted.exists():
            return converted
        for f in out_dir.iterdir():
            if f.suffix.lower() == ".pptx" and f.stem.startswith(ppt_path.stem):
                return f
        return None
    except Exception:
        return None

def _read_pptx_text_safe(pptx_path: Path) -> str:
    try:
        from pptx import Presentation
    except Exception as e:
        return f"Missing dependency python-pptx: {e}"
    try:
        prs = Presentation(str(pptx_path))
        parts = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    parts.append(shape.text)
        return "\n".join(parts).strip() or "(Empty presentation)"
    except Exception as e:
        return f"Error extracting pptx text: {e}"

# -------------------------
# PDF extraction (layered)
# -------------------------
def _extract_text_from_pdf(p: Path, enable_ocr: bool = False, poppler_path: Optional[str] = None) -> str:
    """
    Attempt extraction in layers:
      1) PyPDF2
      2) pdfplumber
      3) OCR via pdf2image + pytesseract (if enable_ocr=True and dependencies present)
    Returns extracted text or a diagnostic string including file absolute path.
    """
    # quick checks
    if not p.exists():
        return f"Error: File not found: {p}"
    # 1) PyPDF2
    pdfpy_missing = False
    try:
        from PyPDF2 import PdfReader
    except Exception as e:
        pdfpy_missing = True
        pdfpy_err = e
    else:
        try:
            reader = PdfReader(str(p))
            if getattr(reader, "is_encrypted", False):
                try:
                    reader.decrypt("")  # common case: empty password
                except Exception:
                    return f"PDF is encrypted and requires a password. File: {p.resolve()}"
            text_parts = []
            for page in reader.pages:
                try:
                    t = page.extract_text()
                except Exception:
                    t = None
                if t:
                    text_parts.append(t)
            if text_parts:
                return "\n".join(text_parts).strip()
        except Exception:
            pass

    # 2) pdfplumber (stronger extraction)
    pdfpl_missing = False
    try:
        import pdfplumber
    except Exception as e:
        pdfpl_missing = True
        pdfpl_err = e
    else:
        try:
            with pdfplumber.open(str(p)) as pdf:
                pages_text = []
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        pages_text.append(t)
                if pages_text:
                    return "\n".join(pages_text).strip()
        except Exception:
            pass

    # 3) OCR fallback
    if enable_ocr:
        ocr_missing = False
        try:
            from pdf2image import convert_from_path
            import pytesseract
        except Exception as e:
            ocr_missing = True
            ocr_err = e
        else:
            try:
                images = convert_from_path(str(p), dpi=200, poppler_path=poppler_path)
                ocr_texts = []
                for img in images:
                    try:
                        t = pytesseract.image_to_string(img)
                    except Exception:
                        t = ""
                    if t and t.strip():
                        ocr_texts.append(t)
                if ocr_texts:
                    return "\n".join(ocr_texts).strip()
            except Exception:
                pass

    # compose diagnostic
    msgs = []
    if pdfpy_missing:
        msgs.append(f"PyPDF2 missing: {pdfpy_err}")
    else:
        msgs.append("PyPDF2 attempted but extracted no text (or failed) on this PDF.")
    if pdfpl_missing:
        msgs.append(f"pdfplumber missing: {pdfpl_err}")
    else:
        msgs.append("pdfplumber attempted but extracted no text.")
    if enable_ocr:
        if ocr_missing:
            msgs.append(f"OCR dependencies missing (pdf2image/pytesseract): {ocr_err}")
        else:
            msgs.append("OCR attempted but returned no text or failed.")
    msgs.append(f"File absolute path: {str(p.resolve())}")
    msgs.append("If this PDF is a scanned image with watermarks, enable OCR and ensure poppler+tesseract installed.")
    return " | ".join(msgs)

# -------------------------
# list_directory: directories AND files (recursive) — directories suffixed with '/'
# -------------------------
@file_tools.tool(
    description="List files and folders under a path (recursive by default). Directories suffixed with '/'."
)
def list_directory(
    path: str = Field(default=".", description="Root directory to list"),
    recursive: bool = Field(default=True, description="Whether to recurse into subdirectories"),
    absolute: bool = Field(default=False, description="Return absolute paths if True; else relative to root"),
    follow_symlinks: bool = Field(default=False, description="Whether to follow symbolic links"),
    sort_results: bool = Field(default=True, description="Whether to sort results")
) -> Union[List[str], str]:
    root = _norm_path(path)
    if not root.exists():
        return f"Error: Path '{path}' does not exist."
    if not root.is_dir():
        return f"Error: Path '{path}' is not a directory."

    entries: List[str] = []
    try:
        if recursive:
            for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
                dirpath_p = Path(dirpath)
                # include directory itself (skip root itself if you prefer)
                if dirpath_p != root:
                    if absolute:
                        entries.append(str(dirpath_p.resolve()) + ("/" if not str(dirpath_p).endswith(os.sep) else ""))
                    else:
                        entries.append(str(dirpath_p.relative_to(root)) + "/")
                # include files
                for fn in filenames:
                    p = dirpath_p / fn
                    if absolute:
                        entries.append(str(p.resolve()))
                    else:
                        entries.append(str(p.relative_to(root)))
        else:
            for item in sorted(root.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if item.is_dir():
                    if absolute:
                        entries.append(str(item.resolve()) + ("/" if not str(item).endswith(os.sep) else ""))
                    else:
                        entries.append(str(item.relative_to(root)) + "/")
                else:
                    if absolute:
                        entries.append(str(item.resolve()))
                    else:
                        entries.append(str(item.relative_to(root)))
        if sort_results:
            entries.sort(key=lambda x: (not x.endswith("/"), x.lower()))
        return entries
    except Exception as e:
        return f"Error listing directory '{path}': {e}"

@file_tools.tool(description="Return the current working directory.")
def get_current_directory() -> str:
    return str(Path.cwd().resolve())

# -------------------------
# read_file (multi-type)
# -------------------------
@file_tools.tool(
    description="Read textual content from many file types; for images/audio/video/binary returns absolute path. "
                "If not found, it will automatically search subdirectories recursively."
)
def read_file(
    path: str = Field(description="Path or filename of the file to read"),
    pdf_enable_ocr: bool = Field(default=False, description="Enable OCR for PDFs (requires poppler + tesseract)"),
    pdf_poppler_path: Optional[str] = Field(default=None, description="Optional poppler path for pdf2image on Windows"),
    search_root: str = Field(default=".", description="Root directory to search recursively if file not found"),
    case_sensitive: bool = Field(default=False, description="Whether filename match is case sensitive"),
) -> str:
    """
    Enhanced read_file:
      - If 'path' exists, read directly.
      - If not, recursively search under 'search_root' for matching filenames.
      - If unique match, read and return its content.
      - If multiple matches, return a list of candidate paths.
    """
    p = _norm_path(path)
    if not p.exists():
        # auto search if not found
        fname = Path(path).name
        root = _norm_path(search_root)
        matches = []
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                fcmp = fn if case_sensitive else fn.lower()
                target = fname if case_sensitive else fname.lower()
                if fcmp == target:
                    found_path = Path(dirpath) / fn
                    matches.append(found_path)
        if not matches:
            return f"File '{path}' not found anywhere under '{root}'."
        if len(matches) > 1:
            msg = "Multiple matches found:\n" + "\n".join(str(m.resolve()) for m in matches)
            return msg
        # unique match: use it
        p = matches[0]

    # normal read logic
    if p.is_dir():
        return f"Error: Path '{p}' is a directory, not a file."

    ext = p.suffix.lower()
    mime_type, _ = mimetypes.guess_type(str(p))

    try:
        if ext in [".txt", ".json", ".md", ".code-workspace", ".csv", ".py", ".log", ".yaml", ".yml", ".ini", ".cfg"]:
            try:
                return p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return p.read_text(errors="ignore")

        if ext == ".pdf":
            return _extract_text_from_pdf(p, enable_ocr=pdf_enable_ocr, poppler_path=pdf_poppler_path)

        if ext == ".docx":
            from docx import Document
            doc = Document(p)
            return "\n".join(para.text for para in doc.paragraphs)

        if ext == ".pptx":
            return _read_pptx_text_safe(p)

        if ext == ".ppt":
            soffice_exec = _find_soffice_executable()
            if not soffice_exec:
                return f"Cannot convert PPT automatically (LibreOffice not found). File: {p.resolve()}"
            with tempfile.TemporaryDirectory() as td:
                out_dir = Path(td)
                converted = _convert_ppt_to_pptx_via_soffice(p, out_dir, soffice_exec)
                if converted and converted.exists():
                    return _read_pptx_text_safe(converted)
                return f"Conversion failed for {p.resolve()}"

        if ext == ".xlsx":
            from openpyxl import load_workbook
            wb = load_workbook(p, read_only=True, data_only=True)
            out = []
            for s in wb.sheetnames:
                ws = wb[s]
                out.append(f"=== {s} ===")
                for row in ws.iter_rows(values_only=True):
                    out.append("\t".join(str(c or "") for c in row))
            wb.close()
            return "\n".join(out)

        # Non-text types
        if mime_type and (mime_type.startswith("image/") or mime_type.startswith("video/") or mime_type.startswith("audio/")):
            return f"[Non-text file: {mime_type}] -> {p.resolve()}"

        # fallback try text
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return f"[Binary or unsupported type] -> {p.resolve()}"

    except Exception as e:
        return f"Error reading '{p}': {e}"

# -------------------------
# write/delete/count
# -------------------------
@file_tools.tool(description="Create or overwrite a text file with new content. Uses UTF-8 encoding.")
def write_file(path: str = Field(description="Path to the file to write"),
               content: str = Field(description="Text content to write into the file")) -> str:
    p = _norm_path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote to '{path}'."
    except Exception as e:
        return f"Error writing to file '{path}': {e}"

@file_tools.tool(description="Delete a file. Returns success message if deleted, or error if it does not exist.")
def delete_file(path: str = Field(description="Path to the file to delete")) -> str:
    p = _norm_path(path)
    if not p.exists():
        return f"Error: The file at '{path}' does not exist."
    if p.is_dir():
        return f"Error: The path '{path}' is a directory, not a file."
    try:
        p.unlink()
        return f"Successfully deleted '{path}'."
    except Exception as e:
        return f"Error deleting file '{path}': {e}"

@file_tools.tool(description="Count files by extension or MIME type. Can operate recursively.")
def count_file_type(
    path: str = Field(default=".", description="Directory path to search"),
    extension: str = Field(default="*", description="File extension ('.txt' or 'txt') or MIME prefix like 'image/'"),
    recursive: bool = Field(default=True, description="Whether to recurse into subdirectories"),
    follow_symlinks: bool = Field(default=False, description="Whether to follow symbolic links")
) -> int:
    root = _norm_path(path)
    if not root.exists() or not root.is_dir():
        return 0
    ext = extension.strip()
    total = 0
    try:
        if recursive:
            for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
                dirpath_p = Path(dirpath)
                for fn in filenames:
                    fpath = dirpath_p / fn
                    mime_type, _ = mimetypes.guess_type(str(fpath))
                    if ext in ["*", "", None]:
                        total += 1
                    elif ext.startswith("."):
                        if fpath.suffix.lower() == ext.lower():
                            total += 1
                    elif "/" in ext:
                        if mime_type and mime_type.startswith(ext):
                            total += 1
                    else:
                        if fpath.suffix.lower() == f".{ext.lower()}":
                            total += 1
        else:
            for item in root.iterdir():
                if not item.is_file():
                    continue
                mime_type, _ = mimetypes.guess_type(str(item))
                if ext in ["*", "", None]:
                    total += 1
                elif ext.startswith("."):
                    if item.suffix.lower() == ext.lower():
                        total += 1
                elif "/" in ext:
                    if mime_type and mime_type.startswith(ext):
                        total += 1
                else:
                    if item.suffix.lower() == f".{ext.lower()}":
                        total += 1
    except Exception:
        return 0
    return total

# -------------------------
# find utilities
# -------------------------
@file_tools.tool(
    description="Find files under root by name. Modes: exact/contains/glob/regex. Returns matched paths (relative by default)."
)
def find_files(
    root: str = Field(default=".", description="Root directory to search"),
    name: str = Field(description="Filename or pattern to search for (e.g. 'report.pdf' or '*.log' or 'part_of_name')"),
    mode: str = Field(default="contains", description="Match mode: 'exact', 'contains', 'glob', or 'regex'"),
    case_sensitive: bool = Field(default=False, description="Whether matching is case sensitive"),
    recursive: bool = Field(default=True, description="Whether to search recursively"),
    max_results: int = Field(default=50, description="Max number of results to return"),
    max_depth: Optional[int] = Field(default=None, description="Optional max recursion depth (None = unlimited)"),
    absolute: bool = Field(default=False, description="Return absolute paths if True, else relative to root")
) -> List[str]:
    root_p = _norm_path(root)
    if not root_p.exists() or not root_p.is_dir():
        return [f"Error: Root '{root}' does not exist or is not a directory."]
    results: List[str] = []
    name_test = name if case_sensitive else name.lower()

    def _match(fname: str) -> bool:
        fcheck = fname if case_sensitive else fname.lower()
        if mode == "exact":
            return fcheck == name_test
        if mode == "contains":
            return name_test in fcheck
        if mode == "glob":
            pattern = name if case_sensitive else name.lower()
            return fnmatch(fcheck, pattern)
        if mode == "regex":
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                return re.search(name, fname, flags) is not None
            except re.error:
                return False
        return False

    root_depth = len(root_p.resolve().parts)
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root_p):
            dir_p = Path(dirpath)
            if max_depth is not None:
                cur_depth = len(dir_p.resolve().parts) - root_depth
                if cur_depth > max_depth:
                    dirnames.clear()
                    continue
            for fn in filenames:
                if _match(fn):
                    p = dir_p / fn
                    results.append(str(p.resolve()) if absolute else str(p.relative_to(root_p)))
                    if len(results) >= max_results:
                        return results
    else:
        for item in root_p.iterdir():
            if item.is_file() and _match(item.name):
                results.append(str(item.resolve()) if absolute else str(item.relative_to(root_p)))
                if len(results) >= max_results:
                    return results
    return results

@file_tools.tool(
    description="Find and read a file. If single match found, read and return content; if multiple matches, return list; if none, return message."
)
def find_and_read_file(
    root: str = Field(default=".", description="Root directory to search"),
    name: str = Field(description="Filename or pattern to search for"),
    mode: str = Field(default="contains", description="Match mode"),
    case_sensitive: bool = Field(default=False, description="Case sensitive match?"),
    recursive: bool = Field(default=True, description="Search recursively?"),
    prefer_first: bool = Field(default=False, description="If multiple matches, automatically read first"),
    max_results: int = Field(default=20, description="Max matches"),
    max_depth: Optional[int] = Field(default=None, description="Limit recursion depth"),
    absolute: bool = Field(default=False, description="Return absolute paths")
) -> Union[str, List[str]]:
    matches = find_files(root=root, name=name, mode=mode, case_sensitive=case_sensitive,
                         recursive=recursive, max_results=max_results, max_depth=max_depth,
                         absolute=absolute)
    if isinstance(matches, list) and len(matches) == 1 and isinstance(matches[0], str) and matches[0].startswith("Error:"):
        return matches[0]
    if not matches:
        return f"No matches found for '{name}' under '{root}' (mode={mode})."
    if len(matches) == 1:
        match_path = Path(matches[0]) if absolute else (_norm_path(root) / matches[0])
        return read_file(str(match_path))
    if prefer_first:
        first = matches[0]
        match_path = Path(first) if absolute else (_norm_path(root) / first)
        return read_file(str(match_path))
    return matches
    
@file_tools.tool(description="Convert a web page to an image (screenshot) and save to ./temp_data with timestamped filename.")
async def html_to_img(
    url: str = Field(description="Target web page URL"),
    wait_until: str = Field(default="networkidle", description="Wait condition before taking screenshot"),
    full_page: bool = Field(default=True, description="Capture full page screenshot if True")
) -> str:
    """
    Take a screenshot of a web page using Playwright (async version).
    Saves the image to ./temp_data/<timestamp>.png and returns the filename.
    """
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        return f"Error: playwright not installed or not configured correctly. {e}"

    try:
        import asyncio
        from pathlib import Path
        import time

        # ensure output directory exists
        out_dir = Path.cwd() / "temp_data"
        out_dir.mkdir(parents=True, exist_ok=True)

        # timestamp filename
        timestamp = int(time.time() * 1000)
        out_path = out_dir / f"{timestamp}.png"

        # take screenshot
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until=wait_until)
            await page.screenshot(path=str(out_path), full_page=full_page)
            await browser.close()

        return f"{out_path.name}"
    except Exception as e:
        return f"Error taking screenshot of {url}: {e}"