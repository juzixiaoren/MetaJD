import json
import sys
from pathlib import Path

def wrap_jsonl(input_path, output_path=None):
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path.with_name(input_path.stem + "_wrapped.jsonl")

    with open(input_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("[\n")
        for i, line in enumerate(lines):
            f.write(line)
            if i < len(lines) - 1:
                f.write(",\n")
        f.write("\n]")

    print(f"✅ 已成功包装为数组格式：{output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python wrap_jsonl_to_array.py <input.jsonl> [output.jsonl]")
    else:
        wrap_jsonl(*sys.argv[1:])
