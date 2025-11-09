import asyncio
import json
import os
import sys
from tqdm.asyncio import tqdm_asyncio
from datetime import datetime
from oxygent import MAS, OxyResponse, OxyState
from oxygent import Config

Config.set_app_name("task_1_v1")

# --- 保证能以 package 方式导入 service.main_oxy ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import importlib
try:
    svc = importlib.import_module("service.main_oxy")
except Exception as e:
    print(f"导入 service.main_oxy 失败: {e}")
    print("请确认在项目根（e:/MetaJD）运行脚本，且 service/__init__.py 存在")
    raise

oxy_space = getattr(svc, "oxy_space", None)
if oxy_space is None:
    create_fn = getattr(svc, "create_oxy_space", None)
    if callable(create_fn):
        oxy_space = create_fn()
    else:
        raise ImportError("未在 service.main_oxy 中找到 oxy_space 或 create_oxy_space()，无法继续。")
# --- 导入结束 ---

# 定义文件路径
TEST_DATA_PATH = os.path.join(PROJECT_ROOT, "data/初赛数据集/valid/test", "data.jsonl")
OUTPUT_RESULT_PATH = os.path.join(PROJECT_ROOT, f"result_{Config.get_app_name()}.json")
FILES_DIR = os.path.join(PROJECT_ROOT, "data/初赛数据集/valid/", "test")  # 测试集附件目录
async def save_results(existing_task_ids, new_results):
    """合并保存新旧结果"""
    try:
        all_results = []

        # 1️⃣ 先加载旧结果
        if os.path.exists(OUTPUT_RESULT_PATH):
            with open(OUTPUT_RESULT_PATH, "r", encoding="utf-8") as f:
                try:
                    old_data = json.load(f)
                    if isinstance(old_data, list):
                        all_results.extend(old_data)
                except json.JSONDecodeError:
                    print("警告: 旧结果文件损坏，重新生成新文件。")

        # 2️⃣ 添加新结果（去重）
        for res in new_results:
            if res["task_id"] not in existing_task_ids:
                all_results.append(res)

        # 3️⃣ 写回文件
        with open(OUTPUT_RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)

        print(f"✅ 已合并保存 {len(new_results)} 条新结果，总结果数: {len(all_results)}。")
    except Exception as e:
        print(f"写入结果文件时出错: {e}")

async def process_task(mas, task_data, files_dir):
    """
    处理单个测试任务。
    [已更新] 直接附加文件名，不判断文件是否存在。
    """
    task_id = task_data.get("task_id")
    query = task_data.get("query")
    file_names_raw = task_data.get("file_name")  # 任务中可能存在附件字段

    if not task_id or not query:
        print(f"警告: 跳过无效的任务数据: {task_data}")
        return None  # 无效数据仍然跳过

    # --- 1. 处理文件名 ---
    file_names_list = []
    if file_names_raw:
        if isinstance(file_names_raw, str):
            try:
                cleaned_str = file_names_raw.replace("‘", "'").replace("’", "'").replace('“', '"').replace('”', '"')
                json_str = cleaned_str.replace("'", '"')
                parsed_list = json.loads(json_str)
                if isinstance(parsed_list, list):
                    file_names_list = parsed_list
                else:
                    file_names_list = [file_names_raw]
            except json.JSONDecodeError:
                common_separators = [',', ';', ' ']
                separated = False
                for sep in common_separators:
                    if sep in file_names_raw:
                        file_names_list = [f.strip() for f in file_names_raw.split(sep) if f.strip()]
                        separated = True
                        break
                if not separated:
                    file_names_list = [file_names_raw]
        elif isinstance(file_names_raw, list):
            file_names_list = file_names_raw
        else:
            file_names_list = [str(file_names_raw)]

    # --- 2. 直接附加文件名到 query ---
    if file_names_list:
        query += f" The files name is: [ {', '.join(file_names_list)} ]"

    payload = {"query": query}
    
    print(f"任务 {task_id} 正在发送 Query: {query}")

    # --- 3. 调用 Agent (失败处理保留) ---
    try:
        oxy_response: OxyResponse = await mas.chat_with_agent(payload=payload)

        if oxy_response and oxy_response.state == OxyState.COMPLETED:
            answer = str(oxy_response.output)
            return {"task_id": task_id, "answer": answer}  # 成功
        else:
            error_msg = f"Agent 处理失败或状态不为 COMPLETED。状态: {oxy_response.state if oxy_response else 'N/A'}"
            print(f"错误: 任务 {task_id} 处理失败: {error_msg}。")
            return {"task_id": task_id, "answer": f"AGENT_PROCESSING_ERROR: {error_msg}"}

    except Exception as e:
        print(f"错误: 任务 {task_id} 处理时发生异常: {e}。")
        import traceback
        traceback.print_exc() 
        return {"task_id": task_id, "answer": f"AGENT_PROCESSING_ERROR: Exception - {e}"}



async def run_tests():
    """主函数，读取测试集并处理 (使用 async with 修复关闭错误)"""
    
    # --- Step 1 & 2: 加载已有结果和新任务 (不变) ---
    if not os.path.exists(TEST_DATA_PATH):
        print(f"错误: 测试数据文件未找到于 {TEST_DATA_PATH}")
        return

    existing_task_ids = set()
    if os.path.exists(OUTPUT_RESULT_PATH):
        try:
            with open(OUTPUT_RESULT_PATH, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                if isinstance(existing_data, list):
                    existing_task_ids = {item.get("task_id") for item in existing_data if "task_id" in item}
                    print(f"检测到已有结果文件，共 {len(existing_task_ids)} 条任务已完成，将跳过这些任务。")
        except Exception as e:
            print(f"警告: 无法读取已有结果文件 {OUTPUT_RESULT_PATH}，将从头开始。错误: {e}")

    tasks = []
    try:
        with open(TEST_DATA_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    task = json.loads(line.strip())
                    task_id = task.get("task_id")
                    if task_id in existing_task_ids: # <--- (跳过逻辑)
                        continue
                    tasks.append(task)
                except json.JSONDecodeError:
                    print(f"警告: 无法解析行: {line.strip()}")
    except Exception as e:
        print(f"读取测试数据时出错: {e}")
        return

    print(f"共加载 {len(tasks)} 个待处理任务（已跳过 {len(existing_task_ids)} 个已完成任务）。")

    # --- 修正 1：重命名 results 列表 ---
    new_results_buffer = [] # <--- 用于存储*批次*
    
    start_time = datetime.now()
    print(f"开始处理测试集... 开始时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        async with MAS(oxy_space=oxy_space) as mas_instance:
            print("MAS 初始化完成。")

            semaphore = asyncio.Semaphore(1) # 并发数

            async def limited_process_task(task, task_count):
                async with semaphore:
                    result = await process_task(mas_instance, task, FILES_DIR)
                    if result:
                        # --- 修正 2：添加到批次 ---
                        new_results_buffer.append(result)
                        
                    # --- 修正 3：检查批次大小并保存/清空 ---
                    if len(new_results_buffer) > 0 and len(new_results_buffer) % 10 == 0:
                        await save_results(existing_task_ids,new_results_buffer) # <--- 仅传递新批次
                        print(f"已保存 {len(new_results_buffer)} 条新增结果。")
                        new_results_buffer.clear() # <--- 关键：清空批次
                    return result

            print("开始 tqdm.gather...")
            await tqdm_asyncio.gather(
                *(limited_process_task(task, idx) for idx, task in enumerate(tasks)),
                desc="处理任务",
                unit="个任务"
            )
            print("tqdm.gather 完成。")
        
        print("MAS 关闭完成。") 

    except Exception as run_err:
        print(f"处理任务过程中发生严重错误: {run_err}")
    
    finally:
        # --- 修正 4：保存剩余的（少于10个的）结果 ---
        if new_results_buffer:
            await save_results(existing_task_ids,new_results_buffer) 
            print(f"已保存最后 {len(new_results_buffer)} 条结果。")

        end_time = datetime.now()
        duration = end_time - start_time
        print(f"测试集处理完成。结束时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}  总耗时: {duration}")
        # (修正 'results' 变量名)
        print(f"成功处理 {len(tasks)} 条新任务。") # (注意：这只反映了本次运行的尝试次数)


if __name__ == "__main__":
    asyncio.run(run_tests())
