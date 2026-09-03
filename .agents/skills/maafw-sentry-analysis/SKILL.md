---
name: maafw-sentry-analysis
description: >-
    Analyze Sentry telemetry data for MaaFramework (MaaFW) applications including
    task failure rates, cross-version trend comparison, stability ranking, and regression detection.
    Activate when the user asks about task failure rates, version comparisons, regression analysis,
    or task stability inspection.
---

# MaaFramework Sentry 遥测数据分析指南

本指南指导 AI Agent 如何调用 `tools.sentry.cli` 分析 MaaFramework（MaaFW）应用在生产环境中的任务失败率、跨版本走势及异常回归。

> [!NOTE]
> 运行本工具依赖新一代 Sentry CLI（[cli.sentry.dev](https://cli.sentry.dev/)，命令名为 `sentry`，可通过 `pnpm add -g sentry` 安装并通过 `sentry auth` 登录）。若未安装，先提示用户安装认证。

---

## 快速决策树（Scenario $\rightarrow$ Command）

| 用户意图 / 场景                  | 推荐命令                                                                | 关注重点                                             |
| :------------------------------- | :---------------------------------------------------------------------- | :--------------------------------------------------- |
| **排查当前版本最不稳定的任务**   | `uv run python -m tools.sentry.cli task-failure --sort rate --limit 10` | 优先关注失败率排在最前的任务（Top 10）               |
| **排查新版本是否发生负向回归**   | `uv run python -m tools.sentry.cli task-trend --sort delta --limit 10`  | 关注 `+X.Xpp` 涨幅最大的任务（即新版显著恶化的任务） |
| **查看特定任务在各版本的表现**   | `uv run python -m tools.sentry.cli task-trend --task <任务名>`          | 查阅该任务在各历史版本下的样本总量、失败量与走势     |
| **全局多版本大盘概览**           | `uv run python -m tools.sentry.cli task-trend --versions 3`             | 查阅高频主干任务在各版本间的失败率走势               |
| **生成供汇报的 Markdown / JSON** | 追加 `--format markdown` 或 `--format json`                             | 便于直接嵌入工单、PR 或分析报表                      |

---

## 核心命令与常用参数

统一通过 Python 模块入口运行：`uv run python -m tools.sentry.cli <子命令>`。

### 1. `task-trend`（跨版本趋势与环比对比）

- `--versions N`：对比最近 N 个版本（默认 `3`）。
- `--sort {runs,rate,delta,name}`：
    - `rate`：按最新版本失败率降序排列（找高危任务）；
    - `delta`：按环比恶化幅度降序排列（找回归任务，`+12.7pp` > `+1.0pp` > `-2.0pp`）；
    - `runs`：按运行量降序（默认）；
    - `name`：按任务名字典序。
- `--limit N`：限制输出行数（强烈建议配合 `--sort` 使用，如 `--limit 10`，避免大表溢出屏幕）。
- `--reverse`：反转排序（如排查稳定性最高或改善最明显的任务）。
- `--task <任务名>`：穿透查询单个任务（支持模糊匹配）。
- `--include-beta`：在版本序列中包含 beta / rc 测试版（默认仅对比正式稳定版）。

### 2. `task-failure`（单版本深度体检）

- `--sort {failures,rate,total,name}`：
    - `rate`：按失败率降序排列；
    - `failures`：按失败绝对次数降序排列（默认）；
    - `total`：按总运行次数降序；
    - `name`：按任务名排序。
- `--limit N`：同时限制「任务表」与「失败节点标记表」的最大展示行数。
- `--release <release字符串>`：手动指定特定 release（未指定时自动通过 Sentry API 探索最新版本）。

---

## 数据解读与统计口径

1. **唯一 Trace 去重**：
   所有样本按 `count_unique(trace)` 聚合，一次管线运行内部多次触发同一事件不会被重复计数。
2. **环比百分点（Δpp）**：
    - 格式形如 `21.6% (+12.7pp)`：表示该版本失败率为 21.6%，相较于上一版本上升了 12.7 个百分点（恶化）；
    - 格式形如 `3.9% (-2.0pp)`：表示相较于上一版本下降了 2.0 个百分点（优化改善）；
    - `0.0pp`：表现持平。
3. **任务 vs 失败节点标记**：
    - **顶层任务**：具有成功（`ok`）样本或实际业务任务名，展示 `总次数 / 失败 / 取消 / 失败率`；
    - **失败节点标记**：内部节点或系统事件（如 `控制器初始化失败`、`连接失败`、`ReturnMain`），仅在失败时上报，不具备成功样本，因此仅计触发次数，不参与失败率计算。

---

## 配置文件规范 (`tools/sentry/config.json`)

工具从同级目录下的 `config.json` 加载配置，若文件不存在或缺少必填字段会直接抛出异常：

```json
{
    "target": "m9a/gui",
    "project_prefix": "m9a",
    "release_pattern": null,
    "task_run_spans": [
        "mfa.task_run",
        "mxu.task_run"
    ],
    "ignored_prefixes": ["__MXU"],
    "ignored_suffixes": [".task_run"]
}
```

当协助用户将本工具迁移到其他 MaaFW 项目（如 MaaEnd、MAA 等）时，只需告知用户修改上述 JSON 即可，无需改动任何 Python 源码。
