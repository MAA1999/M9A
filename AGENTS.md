# M9A 开发指南

> **提交前，每一份生成的 diff 必须通过 `pnpm check`（Python 代码另需 `pnpm check:py`）。先跑格式化（`pnpm format` / `pnpm format:py`）。**
>
> **验收硬门（声明完成 / 交付 / 开 PR 时）：必须真机跑通并达到任务级成功；调用成功、截断、离线识别分数都不算通过。** 判定与取证见 `maafw-debug` / `maafw-live` skill。
>
> **Skill 先行：** 第一次读或改文件之前，先按下方 *Skill 与文档* 查表加载对应 skill —— 这是查表，不是判断。

## 项目结构与模块划分

```text
agent/          # Python agent —— 自定义动作、识别、工具（入口：main.py）
tasks/          # Project Interface 任务与预设定义（images/ 存 GUI 选项图标和任务截图）
announcement/   # GUI 欢迎页公告（PI `welcome` 协议，按语言）
locales/        # Project Interface 显示翻译
tools/          # 构建、发布、schema/i18n 校验与 CI 脚本
resource/       # MaaFW 运行时资源包（图片、pipeline、模型）
data/           # 游戏参考数据（活动排期、掉落表、物品数据库等）
tests/          # pytest 测试，镜像 agent/ 结构
docs/           # 开发者文档与用户手册（见下）
```

- `agent/custom/action/`、`agent/custom/reco/`、`agent/custom/sink/` —— 自定义 MaaFW 动作、识别与 sink（如宽高比处理）；每个功能组一个文件。
- `agent/utils/` —— 可复用工具（日志、HTTP、缩放等）。
- **新增自定义动作/识别**：沿用 `agent/custom/action/` 或 `agent/custom/reco/` 的既有写法，在对应 `__init__.py` 注册，并保证 `pnpm check:py` 通过。

## Skill 与文档

**第一次读或改文件前，按表加载对应 skill：这是查表，不是判断 —— 多行命中就全部加载，"改动很小"不是跳过的理由。** skill 承载 MaaFW 的详细打法（`pnpm check` 替代不了它们）。环境里没有 `skill` 工具时，改读文档列。

| 区域 / 触发条件 | Skill（先加载） | 文档 |
| --- | --- | --- |
| `resource/**/pipeline/**` —— pipeline 任务逻辑 | `maafw-pipeline` | `docs/*/develop/pipeline.md` |
| `tasks/**`、`interface.json`、`locales/**`、`announcement/**` | `maafw-interface` | `docs/*/develop/i18n.md` |
| `agent/**` —— 自定义动作 / 识别 / 运行时 | `maafw-custom` | `docs/*/develop/custom.md` |
| 修 bug、声明完成/交付/开 PR、真机验收 | `maafw-debug`（设备/验收）或 `maa-evidence`（日志） | `docs/*/develop/fix.md` |
| 实时观测、ROI/模板实测、关键帧留存 | `maafw-live` | — |
| MaaFW 字段语义、默认值、版本支持 | `maallmwiki` | — |
| Sentry 遥测 / 失败率分析 | `maafw-sentry-analysis` | — |
| 仓库结构、构建与发布 | — | `docs/*/develop/structure.md` |
| 格式化 / lint / 文档编写 | — | `docs/*/develop/formatting.md`、`docs/*/develop/doc.md` |
| 刷取材料目录 | — | `docs/*/develop/depot-catalog.md` |
| 外服适配 | — | `docs/*/develop/overseas-client-adaptation.md` |
| 活动 / 战斗 / 物品协议 | — | `docs/*/protocol/` |
| CLI / 连接 / FAQ（面向用户） | — | `docs/*/manual/` |

## 构建、测试与开发命令

| 命令 | 用途 |
| --- | --- |
| `pnpm check` | Prettier 检查 → schema 校验 → i18n 校验 → MaaFW 完整性 |
| `pnpm check:i18n` | 校验 interface/task 的 i18n key 在每种语言都能解析 |
| `pnpm check:py` | ruff lint → pyright 类型检查 → pytest |
| `pnpm format` / `pnpm format:py` | 自动格式化非 Python（Prettier）/ Python（ruff） |
| `pnpm test:py` | 跑测试（`uv run --frozen pytest`） |
| `pnpm lint:py` / `pnpm typecheck:py` | Python lint（ruff）/ 严格类型检查（pyright） |

测试：`pytest`（配置见 `pyproject.toml`），文件在 `tests/`，命名 `test_<module>_<behaviour>`；覆盖自定义动作/识别注册、工具模块与发布打包流程。

## 代码风格与命名

- **Python**：ruff + `pyright --strict`（配置见 `pyproject.toml`）；遵循 PEP 8 / PEP 484。
- **JSON / Markdown / YAML**：以 Prettier 配置（`.prettierrc.mjs`）为准 —— 跑 `pnpm format`，不要手工对齐。
- **资源**：路径用正斜杠；坐标、ROI 和模板图以 MaaFW **1280x720** 为基准。
- **命名**：模块/函数/变量用 `snake_case`，类用 `PascalCase`；自定义动作/识别名与其 pipeline 节点名一致。

## 提交与 PR

遵循 [Conventional Commits v1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)。分支命名、PR 描述格式与验证证据要求见 [CONTRIBUTING.md](/CONTRIBUTING.md)。

## 代码审查清单

在上面规则之外，额外检查：

- **协议与 next**：字段符合 MaaFW 协议（无拼错或不支持的属性）；每个 `next` 列表覆盖动作后所有可能界面，保证第一轮推理就落到正确节点。
- **界面 i18n 与一致性**：`name` 保持稳定，显示文本走 `label`，所有声明的语言表都更新，`interface.json` / `tasks/` / `locales/` / `resource/` 保持同步；跑 `pnpm check:i18n`。
- **边界情况**：处理中断（弹窗、意外对话框）；每个动作后跟一个识别步骤。

## 环境与编码

- **编码**：`.ps1` 文件为 **UTF-8 with BOM** —— 代码里读写都用 `encoding='utf-8-sig'`；其他源文件（`.py`、`.js`、`.json`、`.md`、`.sh`、`.yml` 等）为 **UTF-8 without BOM**（`encoding='utf-8'`）。
- **Shell**：不要用 PowerShell 默认参数的 `Out-File` / `Set-Content`（会写 UTF-16 或跟随本地代码页）；非 ASCII 文本避免用 `>` / `>>` 重定向。
- **改 `.ps1`**：**不要用 `apply_patch`**（BOM 会打乱行偏移）—— 用 Python `open()` / `pathlib` 整文件重写。其他文件优先 `apply_patch`。
- Python 3.13（用 `uv` 管理，锁定在 `uv.lock`）；pnpm workspace，Node.js >= 22.13。
