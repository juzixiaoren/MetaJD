import json
import os
import sys

# --- 1. 配置 (请修改这些路径) ---

# (基于您 'test_runner.py' 脚本的路径结构)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__)) 

# 您的原始测试集 .jsonl 文件
TASKS_PATH = os.path.join(PROJECT_ROOT, "test/初赛数据集/valid/test", "data.jsonl")

# 您的第一个结果文件 (JSONL 或 JSON 数组)
FILE1_PATH = "result_deduped.jsonl" 

# 您的第二个结果文件 (JSONL 或 JSON 数组)
FILE2_PATH = "result_wrapped.jsonl"

# 最终输出的 .txt 文件
OUTPUT_PATH = "comparison_results.txt"

# --- 2. 辅助函数：加载文件 ---

def load_results_to_dict(filepath: str, key_field: str = "task_id") -> dict:
    """
    加载 JSON 或 JSONL 文件到以 key_field 为键的字典。
    """
    results_db = {}
    if not os.path.exists(filepath):
        print(f"警告: 文件未找到: {filepath}。将跳过此文件。")
        return results_db

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            # 尝试将其作为 JSON 数组（例如您的 result_task_1_v1.json）读取
            try:
                data = json.load(f)
                if isinstance(data, list):
                    print(f"已加载 {filepath} (JSON 数组) ...")
                    for item in data:
                        if isinstance(item, dict) and key_field in item:
                            results_db[item[key_field]] = item
                    return results_db
            except json.JSONDecodeError:
                # 如果不是 JSON 数组，则回退到 JSONL
                f.seek(0) # 重置文件指针
                print(f"已加载 {filepath} (JSONL) ...")
                for line in f:
                    try:
                        item = json.loads(line.strip())
                        if isinstance(item, dict) and key_field in item:
                            results_db[item[key_field]] = item
                    except json.JSONDecodeError:
                        print(f"警告: 无法解析行: {line.strip()}")

    except Exception as e:
        print(f"读取文件 {filepath} 时出错: {e}")
    
    return results_db

def clean_text(text: str) -> str:
    """清理文本中的换行符以便于比较。"""
    if not isinstance(text, str):
        text = str(text)
    # 替换 JSON 中的 \n 和实际的 \n
    return text.replace(r'\n', ' ').replace(r'\r', ' ').replace('\n', ' ').replace('\r', ' ')

# --- 3. 主函数 ---

def main():
    
    # 检查输入文件
    if not os.path.exists(TASKS_PATH):
        print(f"错误: 找不到任务文件 {TASKS_PATH}。请检查 CONFIG。")
        sys.exit(1)

    # --- 步骤 1: 加载所有数据 ---
    print(f"正在从 {TASKS_PATH} 加载任务...")
    tasks_db = load_results_to_dict(TASKS_PATH, "task_id")
    
    print(f"正在从 {FILE1_PATH} 加载 Result 1...")
    results1_db = load_results_to_dict(FILE1_PATH, "task_id")
    
    print(f"正在从 {FILE2_PATH} 加载 Result 2...")
    results2_db = load_results_to_dict(FILE2_PATH, "task_id")
    
    print("所有文件加载完毕。开始合并...")

    comparison_lines = []
    
    # --- 步骤 2: 遍历主任务列表并合并 ---
    if not tasks_db:
        print("错误：任务文件为空或加载失败。")
        return

    for task_id, task_data in tasks_db.items():
        
        # 1. 获取任务和文件
        query = task_data.get("query", "QUERY_NOT_FOUND")
        file_name = task_data.get("file_name", "FILE_NOT_FOUND")

        # 2. 获取 Result 1
        result1_data = results1_db.get(task_id)
        result1 = result1_data.get("answer", "NOT_FOUND") if result1_data else "NOT_FOUND"

        # 3. 获取 Result 2
        result2_data = results2_db.get(task_id)
        result2 = result2_data.get("answer", "NOT_FOUND") if result2_data else "NOT_FOUND"

        # 4. 格式化输出
        output_entry = [
            f"task_id: {task_id}",
            f"任务： {clean_text(query)}",
            f"文件： {clean_text(str(file_name))}",
            f"result1: {clean_text(result1)}",
            f"result2: {clean_text(result2)}"
        ]
        comparison_lines.append("\n".join(output_entry))

    # --- 步骤 3: 写入到文件 ---
    print(f"正在将 {len(comparison_lines)} 条合并结果写入到 {OUTPUT_PATH}...")
    try:
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            # 用分隔符连接每个条目
            f.write("\n\n--------------------------------------------------\n\n".join(comparison_lines))
        
        print(f"✅ 成功！合并后的文件已保存到: {OUTPUT_PATH}")
        
    except Exception as e:
        print(f"写入输出文件时出错: {e}")


# --- 4. 运行 ---
if __name__ == "__main__":
    main()