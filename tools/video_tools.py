import os
from pathlib import Path
from pydantic import Field
from oxygent.oxy import FunctionHub
import cv2

video_tools = FunctionHub(name="video_tools")

@video_tools.tool(
    description="Check if a file is a valid video (e.g., .mp4, .avi) by reading its first frame. "
                "This tool does NOT process audio or extract content — only validates video format."
)
def is_valid_video(video_path: str = Field(description="Path to the file to check")) -> bool:
    p = Path(video_path)
    if not p.exists():
        return False
    if p.is_dir():
        return False
    cap = cv2.VideoCapture(str(p))
    ret, _ = cap.read()
    cap.release()
    return ret

@video_tools.tool(
    description="Get technical metadata of a video file: duration, FPS, resolution, total frames. "
                "Use this to inspect video properties before frame extraction. Does NOT extract audio or images."
)
def get_video_info(video_path: str = Field(description="Path to the video file")) -> str:
    p = Path(video_path)
    if not p.exists():
        return f"Error: The file at '{video_path}' does not exist."
    if p.is_dir():
        return f"Error: The path '{video_path}' is a directory, not a video file."
    
    cap = cv2.VideoCapture(str(p))
    if not cap.isOpened():
        cap.release()
        return f"Error: Cannot open video file '{video_path}'. It may be corrupted or in an unsupported format."
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps > 0 else 0
    cap.release()

    info_lines = [
        f"file: {p.absolute()}",
        f"duration_sec: {duration:.2f}",
        f"fps: {fps:.2f}",
        f"resolution: {width}x{height}",
        f"total_frames: {frame_count}"
    ]
    return "\n".join(info_lines)

@video_tools.tool(
    description="Extract frames from a video file (e.g., .mp4) and save as JPG images. "
                "Use when user asks to 'extract frames', 'get screenshots', or 'sample video'."
)
def extract_frames(
    video_path: str = Field(description="Path to the input video file (e.g., .mp4, .avi)"),
    output_dir: str = Field(description="Directory to save extracted frames (e.g., 'frames/')"),
    frame_interval: int = Field(default=1, description="Extract 1 frame every N frames (default: 1 = all frames)")
) -> str:
    p_video = Path(video_path)
    if not p_video.exists():
        return f"Error: The file at '{video_path}' does not exist."
    if p_video.is_dir():
        return f"Error: The path '{video_path}' is a directory, not a video file."

    out_dir = Path(output_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return f"Error: Cannot create output directory '{output_dir}': {e}"

    cap = cv2.VideoCapture(str(p_video))
    if not cap.isOpened():
        cap.release()
        return f"Error: Cannot open video file '{video_path}'."

    count = 0
    saved = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if count % frame_interval == 0:
                frame_path = out_dir / f"frame_{saved:06d}.jpg"
                success = cv2.imwrite(str(frame_path), frame)
                if not success:
                    cap.release()
                    return f"Error: Failed to write frame to '{frame_path}'."
                saved += 1
            count += 1
    except Exception as e:
        cap.release()
        return f"Error during frame extraction: {e}"
    finally:
        cap.release()

    return f"Successfully extracted {saved} frames from '{video_path}' to '{output_dir}'."