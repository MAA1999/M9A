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
|   |-- cliff.toml                # 变更日志生成配置
|   |-- dependabot.yml            # Dependabot 自动依赖更新
|   `-- PULL_REQUEST_TEMPLATE.md  # PR 模板
|-- .vscode/                      # VSCode 编辑器配置
|   |-- extensions.json           # 推荐扩展列表
|   |-- launch.json               # 调试配置
|   |-- settings.json             # 项目设置
|   `-- tasks.json                # 任务配置
|-- agent/                        # Agent模块代码
|   |-- custom/                   # 自定义识别和任务
|   |-- utils/                    # 工具函数
|   |-- __init__.py               # 模块初始化
|   |-- agent_runtime.py          # Agent 服务运行入口
|   |-- bootstrap.py              # Agent 引导与虚拟环境管理
|   `-- main.py                   # 主入口文件
|-- data/                         # 数据
|-- docs/                         # 文档目录
|   |-- en_us/                    # 英文文档
|   |-- zh_cn/                    # 中文文档
|   `-- .markdownlint.yaml        # Markdown 代码检查配置
|-- MaaCommonAssets/              # MAA 公共资源（子模块）
|   `-- OCR/                      # OCR 模型
|-- tasks/                        # 任务管线定义
|-- tests/                        # 测试
|-- tools/                        # 工具脚本目录
|   |-- activity_data/            # 活动数据处理工具
|   |-- ci/                       # 持续集成相关脚本
|   |-- registry/                 # PC端注册表工具
|   |-- schema/                   # 接口与管线 Schema
|   |-- build-release.mjs         # 发布包构建脚本
|   |-- check-project.mjs         # 项目验证脚本
|   |-- configure.py              # OCR 模型配置
|   |-- optimize-images.mjs       # 图片优化脚本
|   |-- sync-runtime.mjs          # 运行时同步脚本
|   |-- sync-schema.mjs           # Schema 同步脚本
|   `-- validate-schema.mjs       # Schema 校验脚本
|-- .editorconfig                 # 编辑器配置
|-- .gitattributes                # Git 属性配置
|-- .gitignore                    # Git 忽略文件配置
|-- .gitmodules                   # Git 子模块配置
|-- .node-version                 # Node.js 版本
|-- .prettierignore               # Prettier 忽略配置
|-- .prettierrc.mjs               # 代码格式化配置
|-- .python-version               # Python 版本
|-- CONTACT                       # 联系方式
|-- CONTRIBUTING.md               # 贡献指南
|-- interface.json                # MaaFramework 项目接口声明
|-- LICENSE                       # 许可证文件
|-- logo.ico                      # 应用图标
|-- maa-project.json              # MAA 项目配置
|-- maa-project.lock.json         # MAA 项目锁定文件
|-- maatools.config.mts           # MAA Tools 配置
|-- package.json                  # Node.js 项目配置
|-- pnpm-lock.yaml                # pnpm 依赖锁定文件
|-- pnpm-workspace.yaml           # pnpm 工作区配置
|-- pyproject.toml                # Python 项目配置
|-- README.en.md                  # 英文说明文档
|-- README.md                     # 中文说明文档
|-- requirements.txt              # Python 依赖列表
`-- uv.lock                       # uv 锁定文件
```
