---
order: 11
icon: mdi:format-align-left
---
# 代码格式化

M9A 使用一系列的格式化工具来保证仓库中的代码和资源文件美观统一，以便于维护和阅读

仓库会每天自动运行格式化，也可以在本地手动执行格式化

## 格式化工具

| 文件类型 | 格式化工具 |
| --- | --- |
| JSON/Yaml | [prettier](https://prettier.io/) |
| Markdown | [MarkdownLint](https://github.com/DavidAnson/markdownlint-cli2) |
| Python | [black](https://black.readthedocs.io/) |

## 安装依赖

```bash
pnpm install          # 安装 Node.js 依赖（prettier 等）
pip install black     # 安装 Python 格式化工具
```

## 手动格式化

在项目根目录下执行以下命令：

```bash
pnpm format:all
```

或分别格式化：

```bash
pnpm format:json  # 格式化 JSON/Yaml
pnpm format:py    # 格式化 Python
```
