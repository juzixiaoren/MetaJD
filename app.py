"""
MetaJD - 京东多智能体应用主程序
基于开源框架OxyGent的多智能体系统
"""
import service.main_oxy as oxy_service

def main():
    """主程序入口"""
    print("MetaJD 京东多智能体系统启动...")
    import asyncio
    asyncio.run(oxy_service.main()) # ✅ 正确启动异步循环

if __name__ == "__main__":
    main()
