---
order: 8
icon: mdi:format-align-left
---

# 代码格式化

M9A 使用一系列的格式化工具来保证仓库中的代码和资源文件美观统一，以便于维护和阅读

仓库 CI 会自动检查代码格式，也可以在本地手动格式化

## 格式化工具

| 文件类型               | 格式化工具                                     |
| ---------------------- | ---------------------------------------------- |
| JSON / YAML / Markdown | [prettier](https://prettier.io/)               |
| Python                 | [ruff](https://docs.astral.sh/ruff/formatter/) |

## 安装依赖

```bash
pnpm install          # 安装 Node.js 依赖（prettier 等）
```

ruff 已包含在项目的 Python 开发依赖中，运行 `uv sync` 后即可使用。

## 手动格式化

在项目根目录下执行以下命令：

```bash
pnpm format          # prettier 格式化所有文件
pnpm format:py       # ruff 格式化 Python 代码
```

或直接用 ruff：

```bash
ruff check --fix .  # 检查并自动修复 Python 问题
ruff format .       # 格式化 Python 代码
```
