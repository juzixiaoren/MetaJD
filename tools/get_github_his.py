import asyncio
import os
import json
from typing import Union
import requests # 确保 requests 已安装: pip install requests
from typing import List, Optional
from pydantic import Field
from oxygent.oxy import FunctionHub
from datetime import datetime
from dotenv import dotenv_values

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_ENV_PATH = os.path.join(TOOLS_DIR, '.env')

local_env_vars = {}
if os.path.exists(LOCAL_ENV_PATH):
    # dotenv_values 只读取变量，不修改 os.environ
    local_env_vars = dotenv_values(LOCAL_ENV_PATH) 
    print(f"✅ (github_tools) 已从 '{LOCAL_ENV_PATH}' 加载本地环境变量。")
else:
    print(f"⚠️ (github_tools) 未找到本地 .env 文件: '{LOCAL_ENV_PATH}'。")
    
GITHUB_TOKEN = local_env_vars.get("GITHUB_TOKEN")
HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"
    print("已加载 GitHub Token (用于 github_h_tools)。")
else:
    print("警告：未找到 GITHUB_TOKEN 环境变量 (用于 github_h_tools)。可能会遇到 API 速率限制。")


github_h_tools = FunctionHub(name="github_h_tools")

# HEADERS 定义 (保持不变)
HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"
    print("✅ (github_tools) 已加载 GitHub Token。")
else:
    print("⚠️ (github_tools) 警告：未从 'tools/.env' 中加载 GITHUB_TOKEN。可能会遇到 API 速率限制。")


# 2. 定义核心的、阻塞的 API 调用逻辑
def _get_github_commits(repo: str, path: str, author: Optional[str] = None, until_date: Optional[str] = None, count_only: bool = False) -> Union[List[dict], int]:
    """
    (同步函数) 获取提交记录。
    如果 count_only 为 True，返回计数 (int)。
    否则，返回提交列表 (List[dict])。
    """
    all_commits = []
    api_base_url = f"https://api.github.com/repos/{repo}/commits"
    
    params = {
        "path": path,
        "per_page": 100
    }
    if author:
        params["author"] = author
    if until_date:
        params["until"] = until_date
    
    url = api_base_url
    page_count = 1
    
    while url:
        print(f"DEBUG (github_h_tools): 正在获取 {repo} 第 {page_count} 页数据 (Path: {path})...")
        
        try:
            response = requests.get(url, headers=HEADERS, params=params, timeout=20)
            response.raise_for_status() 
            
            data = response.json()
            
            if not isinstance(data, list):
                print(f"DEBUG (github_h_tools): 错误：API 未返回列表。响应: {data}")
                return [{"error": f"API did not return a list. Response: {data}"}] 
                
            if not data:
                print(f"DEBUG (github_h_tools): 未找到更多提交。")
                break
                
            all_commits.extend(data)
            
            if 'next' in response.links:
                url = response.links['next']['url']
                params = None 
                page_count += 1
            else:
                url = None 
                
        except requests.exceptions.HTTPError as http_err:
            print(f"DEBUG (github_h_tools): HTTP 错误: {http_err} | 响应: {response.text}")
            return [{"error": f"HTTP error: {http_err}", "response": response.text}]
        except requests.exceptions.RequestException as req_err:
            print(f"DEBUG (github_h_tools): 请求失败: {req_err}")
            return [{"error": f"Request failed: {req_err}"}]
            
    print(f"DEBUG (github_h_tools): 共找到 {len(all_commits)} 条记录。")
    
    # 👇 3. 根据 count_only 返回计数或列表
    if count_only:
        return len(all_commits)
    else:
        return all_commits

# 3. 注册为异步工具
@github_h_tools.tool(
    # 👇 4. 更新描述
    description="Fetches commit history for a specific file from a GitHub repository. Can filter by author and date. Can return the full list or just the count."
)
async def get_github_commits(
    repo: str = Field(..., description="The repository path in 'owner/repo' format (e.g., 'langgenius/dify')."),
    path: str = Field(..., description="The path to the file within the repository (e.g., 'README.md')."),
    author: Optional[str] = Field(
        default=None, 
        description="Optional. GitHub login or email of the author to filter by."
    ),
    until_date: Optional[str] = Field(
        default=None, 
        description="Optional. ISO 8601 format date (YYYY-MM-DDTHH:MM:SSZ). Returns commits on or before this date."
    ),
    # 👇 5. 添加新参数
    count_only: bool = Field(
        default=False, 
        description="Optional. If True, returns only the total count of commits found as a string."
    )
) -> str:
    """
    (异步封装) 运行阻塞的 GitHub API 调用。
    如果 count_only=True，返回计数（字符串）。
    否则，返回 JSON 字符串列表。
    """
    try:
        # 👇 6. 传递 count_only 参数
        commit_list_or_count = await asyncio.to_thread(
            _get_github_commits, repo, path, author, until_date, count_only
        )
        
        # 👇 7. 检查返回类型
        if isinstance(commit_list_or_count, int):
            # 如果是计数，返回字符串格式的数字
            return str(commit_list_or_count)
        else:
            # 否则（是列表或错误字典），返回 JSON 字符串
            return json.dumps(commit_list_or_count, indent=2, ensure_ascii=False)
        
    except Exception as e:
        print(f"Error calling github_h_tools thread: {e}")
        return json.dumps([{"error": f"Error running GitHub task: {e}"}])