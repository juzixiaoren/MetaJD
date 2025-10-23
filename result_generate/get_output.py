import asyncio
import json
import os
import sys
from tqdm.asyncio import tqdm
from datetime import datetime
from oxygent import MAS, OxyResponse, OxyState
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
TEST_DATA_PATH = os.path.join(PROJECT_ROOT, "test/初赛数据集/valid/test", "data.jsonl")
OUTPUT_RESULT_PATH = os.path.join(PROJECT_ROOT, "result.jsonl") # 输出文件
FILES_DIR = os.path.join(PROJECT_ROOT, "test/初赛数据集/valid/", "test") # 测试集附件目录

async def process_task(mas, task_data, files_dir):
    """处理单个测试任务"""
    task_id = task_data.get("task_id")
    query = task_data.get("query")
    file_names = task_data.get("file_name")

    if not task_id or not query:
        print(f"警告: 跳过无效的任务数据: {task_data}")
        return None

    payload = {"query": query}

    # --- 处理附件 ---
    attachments = []
    if file_names:
        if isinstance(file_names, str):
            try:
                cleaned_str = file_names.replace("‘", "'").replace("’", "'").replace('“', '"').replace('”', '"')
                json_str = cleaned_str.replace("'", '"')
                parsed_list = json.loads(json_str)
                if isinstance(parsed_list, list):
                    file_names = parsed_list
                else:
                    file_names = [file_names]
            except json.JSONDecodeError:
                common_separators = [',', ';', ' ']
                separated = False
                for sep in common_separators:
                    if sep in file_names:
                        file_names = [f.strip() for f in file_names.split(sep) if f.strip()]
                        separated = True
                        break
                if not separated:
                       file_names = [file_names]
        elif not isinstance(file_names, list):
               file_names = [str(file_names)]

        for fname in file_names:
            base_fname = os.path.basename(fname)
            file_path = os.path.join(files_dir, base_fname)
            if os.path.exists(file_path):
                attachments.append(file_path)
            else:
                print(f"警告: 任务 {task_id} 的附件文件未找到: {file_path}")

    if attachments:
        payload["attachments"] = attachments
        print(f"任务 {task_id} 附加文件: {attachments}") # 按需取消注释

    # --- 调用 Agent ---
    try:
        # 移除 timeout 参数
        oxy_response: OxyResponse = await mas.chat_with_agent(payload=payload)

        if oxy_response and oxy_response.state == OxyState.COMPLETED:
            answer = str(oxy_response.output)
            return {"task_id": task_id, "answer": answer}
        else:
            error_msg = f"Agent 处理失败或状态不为 COMPLETED。状态: {oxy_response.state if oxy_response else 'N/A'}"
            print(f"错误: 任务 {task_id} 处理失败: {error_msg}")
            return {"task_id": task_id, "answer": f"AGENT_PROCESSING_ERROR: {error_msg}"}

    except Exception as e:
        print(f"错误: 任务 {task_id} 处理时发生异常: {e}")
        import traceback
        traceback.print_exc() # 打印详细错误堆栈
        return {"task_id": task_id, "answer": f"AGENT_PROCESSING_ERROR: Exception - {e}"}


async def run_tests():
    """主函数，读取测试集并处理"""
    if not os.path.exists(TEST_DATA_PATH):
        print(f"错误: 测试数据文件未找到于 {TEST_DATA_PATH}")
        return

    tasks = []
    try:
        with open(TEST_DATA_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    tasks.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    print(f"警告: 无法解析行: {line.strip()}")
    except Exception as e:
        print(f"读取测试数据时出错: {e}")
        return

    print(f"共加载 {len(tasks)} 个测试任务。")
    results = [] # <--- 将 results 移到 MAS 外部

    start_time = datetime.now()
    print(f"开始处理测试集... 开始时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    mas_instance = None # 初始化 MAS 实例变量
    try:
        # --- [修改] 手动初始化 MAS ---
        mas_instance = MAS(oxy_space=oxy_space)
        print("尝试初始化 MAS...")
        await mas_instance.init() # 显式初始化
        print("MAS 初始化完成。")

        semaphore = asyncio.Semaphore(2) # 保持较低的并发数

        async def limited_process_task(task):
            async with semaphore:
                # 传递已初始化的 mas_instance
                return await process_task(mas_instance, task, FILES_DIR)

        print("开始 tqdm.gather...")
        gather_results = await tqdm.gather(
            *(limited_process_task(task) for task in tasks),
            desc="处理任务",
            unit="个任务"
        )
        print("tqdm.gather 完成。")

        # 处理结果仍在 try 块内，但在 MAS 关闭前
        results = [r for r in gather_results if r is not None]

    except Exception as run_err:
         print(f"处理任务过程中发生严重错误: {run_err}")
         # 即使出错，也要尝试保存已有的结果
         if 'gather_results' in locals(): # 检查 gather_results 是否已定义
             results = [r for r in gather_results if r is not None]

    finally:
        # --- [修改] 手动关闭 MAS，无论是否成功 ---
        if mas_instance:
            print("尝试关闭 MAS...")
            try:
                # 假设关闭方法是 close()，请根据文档确认
                # 添加超时防止无限期挂起
                await asyncio.wait_for(mas_instance.close(), timeout=30.0) # 例如 30 秒超时
                print("MAS 关闭完成。")
            except asyncio.TimeoutError:
                print("警告: 关闭 MAS 超时（30秒），可能有后台进程未完全退出。但将继续保存结果。")
            except AttributeError:
                 print("MAS 对象没有 close() 方法，跳过显式关闭。清理将由 __aexit__ 处理。")
            except Exception as close_err:
                 print(f"关闭 MAS 时出错: {close_err}。将继续保存结果。")
        else:
            print("MAS 未成功初始化，无法关闭。")

        # --- [修改] 结果写入移到 finally 块，确保总是执行 ---
        end_time = datetime.now()
        duration = end_time - start_time
        print(f"测试集处理完成（或被中断）。结束时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"总耗时: {duration}")
        print(f"成功收集到 {len(results)} 个任务的结果。")

        # 写入结果文件
        print(f"尝试将 {len(results)} 条结果写入到 {OUTPUT_RESULT_PATH}...")
        try:
            # 使用 'a' 模式追加，如果文件已存在部分内容
            # 如果希望每次覆盖，使用 'w'
            with open(OUTPUT_RESULT_PATH, 'w', encoding='utf-8') as f:
                count = 0
                for result in results:
                    if "task_id" in result and "answer" in result:
                        f.write(json.dumps(result, ensure_ascii=False) + '\n')
                        count += 1
                    else:
                        print(f"警告: 结果格式错误，跳过写入: {result}")
            print(f"成功将 {count} 条有效结果写入到: {OUTPUT_RESULT_PATH}")
        except Exception as e:
            print(f"写入结果文件时出错: {e}")
            print("请检查 results 列表中的内容：")
            # print(results[:5]) # 打印前 5 条结果以供调试


if __name__ == "__main__":
    asyncio.run(run_tests())

