# MaaFramework Sentry 遥测数据分析工具

通用的 MaaFramework（MaaFW）应用 Sentry 性能与失败率分析套件。支持单版本任务深度体检、跨版本失败率趋势对比及环比变化量（Δpp）自动化计算。

---

## 目录

- [前置要求](#前置要求)
- [快速开始](#快速开始)
- [命令详解](#命令详解)
    - [1. 跨版本趋势报告 (task-trend)](#1-跨版本趋势报告-task-trend)
    - [2. 单版本深度分析 (task-failure)](#2-单版本深度分析-task-failure)
- [跨项目接入配置 (config.json)](#跨项目接入配置-configjson)
- [统计口径说明](#统计口径说明)

---

## 前置要求

本工具基于新一代面向开发者与 AI Agent 的 **Sentry CLI**（[cli.sentry.dev](https://cli.sentry.dev/)，命令名为 `sentry`，非旧版 `sentry-cli`）。

1. **安装 Sentry CLI**（详见 [官方安装文档](https://cli.sentry.dev/getting-started/)）：
    - **Node / 包管理器（跨平台 / Windows 推荐）**：
        ```bash
        pnpm add -g sentry
        # 或
        npm install -g sentry
        ```
    - **Linux / macOS 官方脚本**：
        ```bash
        curl https://cli.sentry.dev/install -fsS | bash
        ```
    - **Homebrew (macOS)**：
        ```bash
        brew install getsentry/tools/sentry
        ```

    _(使用 npm/pnpm 安装后可运行 `sentry cli setup` 启用自动补全与内置 Agent Skill)_

2. **完成 Sentry 认证**（支持 OAuth Device Flow，免手动复制作业 Token）：
    ```bash
    sentry auth
    ```
    按提示在浏览器中确认授权即可。认证完成后可通过 `sentry auth status` 查看状态。

---

## 快速开始

在项目根目录下通过 `python -m tools.sentry.cli` 运行：

```bash
# 1. 跨版本失败率走势（默认对比最近 3 个正式版）
uv run python -m tools.sentry.cli task-trend

# 2. 查看新版本中恶化最严重的 Top 10 任务（抓回归神器）
uv run python -m tools.sentry.cli task-trend --sort delta --limit 10

# 3. 查看最新版本中失败率最高的 Top 10 任务
uv run python -m tools.sentry.cli task-failure --sort rate --limit 10
```

---

## 命令详解

### 1. 跨版本趋势报告 (`task-trend`)

对比多个版本间任务的失败率变化，括号内标注相比上一版本的百分点环比变化量（如 `+12.7pp`、`-2.0pp`）。

```bash
uv run python -m tools.sentry.cli task-trend [选项]
```

**常用选项：**

| 参数             | 说明                                                                                        | 示例                |
| :--------------- | :------------------------------------------------------------------------------------------ | :------------------ |
| `--versions N`   | 对比最近 N 个版本（默认: `3`）                                                              | `--versions 5`      |
| `--sort`         | 排序维度：`runs`（总运行量，默认）、`rate`（失败率）、`delta`（恶化幅度）、`name`（任务名） | `--sort rate`       |
| `--limit N`      | 限制输出的任务数量                                                                          | `--limit 10`        |
| `--reverse`      | 反转排序（如升序看最稳定或改善最大的任务）                                                  | `--reverse`         |
| `--task <名称>`  | 穿透单个任务查看其在各个版本下的明细记录                                                    | `--task 常规作战`   |
| `--include-beta` | 包含 beta / rc 测试版（默认仅对比正式稳定版）                                               | `--include-beta`    |
| `--format`       | 输出格式：`console`（默认）、`markdown`、`json`                                             | `--format markdown` |
| `--period`       | 查询时间范围（默认: `90d`，确保覆盖多个版本）                                               | `--period 30d`      |

#### 单任务穿透示例：

```bash
uv run python -m tools.sentry.cli task-trend --task 常规作战
```

输出：

```text
任务趋势明细: 常规作战
┌────────┬────────┬────────┬────────┬──────────────┐
│ 版本   │ 运行数 │ 失败数 │ 失败率 │ 相对上一版本 │
├────────┼────────┼────────┼────────┼──────────────┤
│ v4.7.1 │    712 │    154 │  21.6% │      +12.7pp │
│ v4.7.0 │    258 │     23 │   8.9% │       -0.5pp │
│ v4.6.2 │   1363 │    129 │   9.5% │       -9.1pp │
└────────┴────────┴────────┴────────┴──────────────┘
```

---

### 2. 单版本深度分析 (`task-failure`)

针对指定或最新版本，全面分析任务成功/失败/取消分布、失败节点标记以及渠道 Umbrella Span 运行失败率。

```bash
uv run python -m tools.sentry.cli task-failure [选项]
```

**常用选项：**

| 参数        | 说明                                                                            | 示例                     |
| :---------- | :------------------------------------------------------------------------------ | :----------------------- |
| `--release` | 指定分析的 Sentry release（未指定时自动选择最新版本）                           | `--release "m9a@v4.7.1"` |
| `--sort`    | 排序规则：`failures`（失败数，默认）、`rate`（失败率）、`total`（总数）、`name` | `--sort rate`            |
| `--limit N` | 限制任务表和失败标记表的最大展示行数                                            | `--limit 15`             |
| `--reverse` | 反转排序                                                                        | `--reverse`              |
| `--period`  | 查询时间范围（默认: `7d`）                                                      | `--period 14d`           |
| `--format`  | 输出格式：`console`、`markdown`、`json`                                         | `--format json`          |

---

## 跨项目接入配置 (`config.json`)

本工具已实现完全通用化。任何 MaaFW 应用项目只需在 `tools/sentry/config.json` 中配置自身项目的标识即可使用。

> **注意**：脚本严格依赖 `config.json`；若未配置或缺少必填项，会直接抛出异常提示，不进行隐式硬编码回退。

### 配置字段说明

```json
{
    "target": "<sentry-org>/<sentry-project>",
    "project_prefix": "<release-prefix>",
    "release_pattern": null,
    "task_run_spans": ["<span_name>"],
    "ignored_prefixes": ["<prefix>"],
    "ignored_suffixes": [".task_run"]
}
```

- **`target`** _(必填)_：Sentry 的组织与项目标识，如 `"m9a/gui"` 或 `"maaend/maaend"`。
- **`project_prefix`** _(必填)_：Release 版本前缀，系统会自动构造匹配 `prefix@vX.Y.Z`（含稳定版与测试版）的标准语义化正则。
- **`release_pattern`** _(可选)_：自定义 Release 正则表达式。若项目采用非常规命名规范可填入，通常为 `null`。
- **`task_run_spans`** _(可选)_：上报整次管线运行的根 Span（Umbrella span）名称列表。
- **`ignored_prefixes`** _(可选)_：在大表中自动过滤的内部私有 Span 前缀。
- **`ignored_suffixes`** _(可选)_：在大表中自动过滤的 Span 后缀。

### 常用项目配置示例

#### 1. M9A (`tools/sentry/config.json`)

```json
{
    "target": "m9a/gui",
    "project_prefix": "m9a",
    "release_pattern": null,
    "task_run_spans": [
        "mfa.task_run",
        "mxu.task_run"
    ],
    "ignored_prefixes": [
        "__MXU"
    ],
    "ignored_suffixes": [
        ".task_run"
    ]
}
```

#### 2. MaaEnd (`tools/sentry/config.json`)

```json
{
    "target": "maaend/maaend",
    "project_prefix": "MaaEnd",
    "release_pattern": null,
    "task_run_spans": [
        "maaend.task_run"
    ],
    "ignored_prefixes": [],
    "ignored_suffixes": [
        ".task_run"
    ]
}
```

---

## 统计口径说明

1. **唯一 Trace 去重**：
    - 报告中所有计数字段均按 `count_unique(trace)` 统计，同一用户或同一次管线运行内部多次触发同一事件不会被重复计数。
2. **业务任务 vs 失败节点标记**：
    - **业务任务**：具有成功（`ok`）样本或至少被用户执行过的顶层任务，计算真实的失败概率（`失败数 / 总数`）；
    - **失败节点标记**：仅在失败时上报的内部标记（如系统级 `控制器初始化失败`、`连接失败` 或 pipeline 内部返回节点），没有成功样本，仅记录触发次数，不计入任务失败率计算。
3. **环比变化量（Δpp）**：
    - 标注格式为 `百分比 (Δ百分点)`，例如 `21.6% (+12.7pp)` 表示当前版本失败率为 21.6%，相比上一版本上升了 12.7 个百分点。
