# M9A

由 create-maa-project 生成的 MaaFW Python Agent 项目。

## 开发

```bash
pnpm install
uv sync
pnpm check
pnpm check:py
```

Agent 入口在 `agent/main.py`，启动前的 Python 版本和依赖检查在 `agent/bootstrap.py`。
Agent runtime 在 `agent/agent_runtime.py`，会导入 `agent/custom/action`、`agent/custom/reco`
和 `agent/custom/sink` 中的模块并注册自定义逻辑。PI 环境变量、参数解析、日志和路径工具在
`agent/utils/`。
VS Code Maa Support 插件通过 `uv run python agent/bootstrap.py` 启动 AgentServer；
调试会使用 `.vscode/launch.json` 中的 `Maa Agent: Debug` 配置，映射在
`maatools.config.mts`。

## 发布

推送 `v0.1.0` 这样的 tag 会触发生成的 release workflow。

English documentation: [README.en.md](./README.en.md)
