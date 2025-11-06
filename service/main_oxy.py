import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.all_agents import *
from tools.pre_tools import *
## plan_parser = PydanticOutputParser(Plan)  ## 目的解释器
## action_parser = PydanticOutputParser(Action) ## 行动解释器
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
oxy_space = [
    oxy.HttpLLM(
    name=LLM_MODEL,
    api_key=get_env_var("DEFAULT_LLM_API_KEY"),
    base_url=get_env_var("DEFAULT_LLM_BASE_URL"),
    model_name=get_env_var("DEFAULT_LLM_MODEL_NAME"),
    llm_params={"temperature": 0.01},
    verify=False,
    semaphore=4, #最多允许4个并发请求
    ),
    oxy.HttpLLM(
    name=VLM_MODEL,
    api_key=get_env_var("DEFAULT_VLM_API_KEY"),
    base_url=get_env_var("DEFAULT_VLM_BASE_URL"),
    model_name=get_env_var("DEFAULT_VLM_MODEL_NAME"),
    llm_params={"temperature": 0.6,"max_tokens":2048},
    max_pixels=10000000,
    is_multimodal_supported=True,
    is_convert_url_to_base64=True,
    verify=False,
    semaphore=4,
    max_tokens=10000,
    ),
    *all_tools,
    time_agent,
    file_agent,
    math_agent,
    python_agent,
    shell_agent,
    string_agent,
    system_check_agent,
    analyser,
    master,
    planner,
    executor,
    task_solver,
    multimodal_agent,
    search_agent,
    firecrawl_agent,
    file_reader_agent,
    github_agent,
    stock_agent,
    audio_agent,
    # audio_vlm_agent,
    browser_agent,
    logic_agent,
]

async def main():
    import asyncio
    
    async with MAS(oxy_space=oxy_space) as mas:
        await mas.start_web_service(first_query="How many chars in 'OxyGent'?")
        
if __name__ == "__main__":
    import asyncio
    asyncio.run(main()) 