# MetaJD

京东多智能体，基于开源框架OxyGent，推动多智能体系统在复杂场景下的协同决策与创新应用的项目

## 项目信息

- **项目名称**: MetaJD
- **项目描述**: 京东多智能体系统，基于开源框架OxyGent实现
- **技术栈**: Python
- **开源协议**: MIT License

## 文件结构

```
MetaJD/
├── app.py              # 主程序入口文件
├── dao/                # 数据访问层 (Data Access Object)
│   └── __init__.py     # 负责数据库操作和数据持久化
├── data/               # 数据文件夹
│   └── __init__.py     # 用于存放数据文件、配置文件等
├── service/            # 业务逻辑层 (Service Layer)
│   └── __init__.py     # 负责处理业务逻辑和服务实现
├── util/               # 工具类文件夹
│   └── __init__.py     # 存放通用的工具函数和辅助类
├── .gitignore          # Git忽略文件配置
├── README.md           # 项目说明文档
└── LICENSE             # 开源许可证
```

## 快速开始

```bash
# 运行主程序
python app.py
```

## 开发说明

本项目采用分层架构设计：
- **app.py**: 应用程序入口
- **dao/**: 数据访问层，处理数据持久化
- **service/**: 业务逻辑层，实现核心业务功能
- **util/**: 工具类，提供通用辅助功能
- **data/**: 数据存储目录
