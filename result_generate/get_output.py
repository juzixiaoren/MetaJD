import asyncio
import json
import os
import sys
from tqdm.asyncio import tqdm
from datetime import datetime
from oxygent import MAS, OxyResponse, OxyState
# --- 修改开始：保证能以 package 方式导入 service.main_oxy ---
# 1) 计算项目根（result_generate 和 service 同级）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 2) 将项目根加入 sys.path（优先）
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 3) 以 package 方式导入 service.main_oxy（更稳健）
import importlib
try:
    svc = importlib.import_module("service.main_oxy")
except Exception as e:
    print(f"导入 service.main_oxy 失败: {e}")
    print("请确认在项目根（e:/MetaJD）运行脚本，且 service/__init__.py 存在")
    raise

# 4) 获取 oxy_space（优先），若不存在尝试调用 create_oxy_space()
oxy_space = getattr(svc, "oxy_space", None)
if oxy_space is None:
    create_fn = getattr(svc, "create_oxy_space", None)
    if callable(create_fn):
        oxy_space = create_fn()
    else:
        raise ImportError("未在 service.main_oxy 中找到 oxy_space 或 create_oxy_space()，无法继续。")
# --- 修改结束 ---

# 定义文件路径 (根据你的项目结构调整)
TEST_DATA_PATH = os.path.join(PROJECT_ROOT, "test/初赛数据集/valid/test", "data.jsonl")
OUTPUT_RESULT_PATH = os.path.join(PROJECT_ROOT, "result.jsonl") # 输出文件
FILES_DIR = os.path.join(PROJECT_ROOT, "test/初赛数据集/valid/", "test") # 测试集附件目录

async def process_task(mas, task_data, files_dir):
    """处理单个测试任务"""
    task_id = task_data.get("task_id")
    query = task_data.get("query")
    file_names = task_data.get("file_name") # 可能是列表或字符串

    if not task_id or not query:
        print(f"警告: 跳过无效的任务数据: {task_data}")
        return None

    payload = {"query": query}

    # --- 处理附件 ---
    attachments = []
    if file_names:
        # 确保 file_names 是列表
        if isinstance(file_names, str):
            try:
                # 尝试解析 JSON 格式的字符串列表 (例如 "['file1.txt', 'file2.jpg']")
                # 先替换可能存在的中文引号
                cleaned_str = file_names.replace("‘", "'").replace("’", "'").replace('“', '"').replace('”', '"')
                # 尝试将单引号替换为双引号以符合JSON规范
                json_str = cleaned_str.replace("'", '"')
                parsed_list = json.loads(json_str)
                if isinstance(parsed_list, list):
                    file_names = parsed_list
                else:
                    file_names = [file_names] # 如果不是列表，视为单个文件名
            except json.JSONDecodeError:
                # 如果解析失败，尝试按常见分隔符分割
                common_separators = [',', ';', ' ']
                separated = False
                for sep in common_separators:
                    if sep in file_names:
                        file_names = [f.strip() for f in file_names.split(sep) if f.strip()]
                        separated = True
                        break
                if not separated:
                     file_names = [file_names] # 如果无法分割，视为单个文件名
        elif not isinstance(file_names, list):
             file_names = [str(file_names)] # 其他类型转为字符串列表

        for fname in file_names:
            # 移除文件名可能包含的路径分隔符，只保留文件名部分
            base_fname = os.path.basename(fname)
            file_path = os.path.join(files_dir, base_fname)
            if os.path.exists(file_path):
                # MAS.chat_with_agent 的 attachments 参数需要文件路径列表
                attachments.append(file_path)
            else:
                print(f"警告: 任务 {task_id} 的附件文件未找到: {file_path}")

    if attachments:
        payload["attachments"] = attachments
        print(f"任务 {task_id} 附加文件: {attachments}") # 调试信息

    # --- 调用 Agent ---
    try:
        # 调用 chat_with_agent 与 master agent 进行单轮交互
        # 注意：确保你的 MAS.chat_with_agent 支持 attachments 参数
        # 移除 timeout 参数
        oxy_response: OxyResponse = await mas.chat_with_agent(payload=payload)

        if oxy_response and oxy_response.state == OxyState.COMPLETED:
            answer = str(oxy_response.output) # 确保答案是字符串
            return {"task_id": task_id, "answer": answer}
        else:
            error_msg = f"Agent 处理失败或状态不为 COMPLETED。状态: {oxy_response.state if oxy_response else 'N/A'}"
            print(f"错误: 任务 {task_id} 处理失败: {error_msg}")
            # 即使失败，也按格式要求返回，但答案标记为错误
            return {"task_id": task_id, "answer": f"AGENT_PROCESSING_ERROR: {error_msg}"}

    # except asyncio.TimeoutError: # TimeoutError 不会再从此调用中直接引发
    #     print(f"错误: 任务 {task_id} 处理超时。")
    #     return {"task_id": task_id, "answer": "AGENT_PROCESSING_ERROR: Timeout"}
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
    results = []

    start_time = datetime.now()
    print(f"开始处理测试集... 开始时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # 初始化 MAS
    # 可以在这里设置 Config.set_app_name 用于日志/数据区分
    # Config.set_app_name(f"test_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    async with MAS(oxy_space=oxy_space) as mas:
        # 使用 tqdm.gather 来并发处理任务并显示进度条
        # 调整并发数 max_concurrent_tasks
        semaphore = asyncio.Semaphore(2) # 例如，限制并发数为 5

        async def limited_process_task(task):
            async with semaphore:
                return await process_task(mas, task, FILES_DIR)

        gather_results = await tqdm.gather(
            *(limited_process_task(task) for task in tasks),
            desc="处理任务", # 进度条描述
            unit="个任务" # 进度条单位
        )
        # 过滤掉处理失败返回 None 的结果
        results = [r for r in gather_results if r is not None]


    end_time = datetime.now()
    duration = end_time - start_time
    print(f"测试集处理完成。结束时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"总耗时: {duration}")
    print(f"成功处理 {len(results)} 个任务。")


    # --- 写入结果文件 ---
    try:
        with open(OUTPUT_RESULT_PATH, 'w', encoding='utf-8') as f:
            for result in results:
                # 确保 task_id 和 answer 存在
                if "task_id" in result and "answer" in result:
                     # 将结果对象序列化为 JSON 字符串并写入文件，确保每行是一个完整的 JSON
                    f.write(json.dumps(result, ensure_ascii=False) + '\n')
                else:
                    print(f"警告: 结果格式错误，缺少 task_id 或 answer: {result}")
        print(f"结果已成功写入到: {OUTPUT_RESULT_PATH}")
    except Exception as e:
        print(f"写入结果文件时出错: {e}")


if __name__ == "__main__":
    # 运行主异步函数
    asyncio.run(run_tests())