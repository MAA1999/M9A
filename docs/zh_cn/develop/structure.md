---
order: 2
icon: hugeicons:structure-01
---
# 项目结构

```bash
.
|-- .github/                      # GitHub 相关配置
|   |-- ISSUE_TEMPLATE/           # Issue 模板
|   |-- workflows/                # GitHub Actions 工作流
|   `-- cliff.toml                # 变更日志生成配置
|-- .vscode/                      # VSCode 编辑器配置
|   |-- extensions.json           # 推荐扩展列表
|   `-- settings.json             # 项目设置
|-- agent/                        # Agent模块代码
|   |-- custom/                   # 自定义识别和任务
|   |-- utils/                    # 工具函数
|   |-- __init__.py               # 模块初始化
|   `-- main.py                   # 主入口文件
|-- assets/                       # 资源文件目录
|   |-- MaaCommonAssets/          # MAA 公共资源（子模块）
|   |-- resource/                 # 项目资源文件
|   |-- interface.json            # MaaFramework 标准化项目结构声明
|   `-- interface_cli.json        # 命令行接口配置
|-- deps/                         # MaaFramework 依赖库，存放 schema 的地方
|-- docs/                         # 文档目录
|   |-- en_us/                    # 英文文档
|   |-- zh_cn/                    # 中文文档
|   `-- .markdownlint.yaml        # Markdown 代码检查配置
|-- tools/                        # 工具脚本目录
|   |-- activity_data/            # 活动数据处理工具
|   |-- ci/                       # 持续集成相关脚本
|   |-- image/                    # 掉落物品图片处理工具
|   |-- OptimizeTemplates/        # 模板图片优化工具
|   |-- registry/                 # PC端注册表相关工具
|   |-- migrate_pipeline_v5.py    # Pipeline v5 迁移脚本
|   |-- minify_json.py            # JSON 压缩工具
|   `-- V1_upgrade.py             # Pipeline 版本升级脚本
|-- .editorconfig                 # 编辑器配置
|-- .gitattributes                # Git 属性配置
|-- .gitignore                    # Git 忽略文件配置
|-- .gitmodules                   # Git 子模块配置
|-- .pre-commit-config.yaml       # 预提交钩子配置
|-- .prettierrc                   # 代码格式化配置
|-- CONTACT                       # 联系方式
|-- LICENSE                       # 许可证文件
|-- README.md                     # 中文说明文档
|-- README_en.md                  # 英文说明文档
|-- package-lock.json             # npm 依赖锁定文件
|-- package.json                  # Node.js 项目配置
`-- requirements.txt              # Python 依赖列表
```
