---
name: maafw-sentry-analysis
description: >-
    Analyze Sentry telemetry data for MaaFramework (MaaFW) applications including
    task failure rates, cross-version trend comparison, stability ranking, and regression detection.
    Activate when the user asks about task failure rates, version comparisons, regression analysis,
    or task stability inspection.
---

# MaaFramework Sentry 遥测数据分析指南

本指南指导 AI Agent 如何调用 `tools.sentry.cli` 分析 MaaFramework（MaaFW）应用在生产环境中的任务失败率、跨版本走势及异常回归。所有 org/project 取自 `tools/sentry/config.json` 的 `target` 字段。

> [!NOTE]
> 运行本工具依赖新一代 Sentry CLI（[cli.sentry.dev](https://cli.sentry.dev/)，命令名为 `sentry`，可通过 `pnpm add -g sentry` 安装并通过 `sentry auth` 登录）。若未安装，先提示用户安装认证。

---

## 执行纪律（先读这一节）

报告是**分钟级**操作：每个报告内部要串行 spawn 8~10 次 `sentry` 子进程（`task-failure` 约 20s、`task-trend` 约 50s），耗时几乎全在往返 Sentry。

1. **一次只跑一个报告，报告之间串行**。并发跑多个报告会互相拖慢——Sentry 侧瓶颈是单次请求延迟而非吞吐，串行反而更快；工具检测到并发报告时会向 stderr 提示一次。
2. **不要试探性地换参数重跑**。`--sort` / `--limit` 只影响展示，不减少查询量；换一次排序就要重新全量查询。需要多种视图时用 `--format json` 取一次全量再本地切片。
3. **重复试跑加 `--no-fresh`**。同一查询快 3~5 倍，且实测输出与 fresh 一致（该开关复用 Sentry CLI 本地缓存；缓存过期仍会重新拉取）。首次分析、以及需要最新数据时保持默认（每次都带 `--fresh`）。
4. **不要用 `--period` 试错**。默认值已经在 Sentry 可靠聚合窗口内（`task-trend` 30d / `task-failure` 7d）；超过 30 天 Sentry 只返回截断样本，**绝对计数不可用**，工具会向 stderr 警告但仍然照跑，白等一轮。
5. **先看 Issue，再跑报告**。见下文「快速定位：Issue 优先」。

---

## 快速决策树（Scenario → Command）

| 用户意图 / 场景                  | 推荐命令                                                                | 关注重点                                             |
| :------------------------------- | :---------------------------------------------------------------------- | :--------------------------------------------------- |
| **排查当前版本最不稳定的任务**   | `uv run python -m tools.sentry.cli task-failure --sort rate --limit 10` | 优先关注失败率排在最前的任务（Top 10）               |
| **排查新版本是否发生负向回归**   | `uv run python -m tools.sentry.cli task-trend --sort delta --limit 10`  | 关注 `+X.Xpp` 涨幅最大的任务（即新版显著恶化的任务） |
| **查看特定任务在各版本的表现**   | `uv run python -m tools.sentry.cli task-trend --task <任务名>`          | 查阅该任务在各历史版本下的样本总量、失败量与走势     |
| **全局多版本大盘概览**           | `uv run python -m tools.sentry.cli task-trend --versions 3`             | 查阅高频主干任务在各版本间的失败率走势               |
| **生成供汇报的 Markdown / JSON** | 追加 `--format markdown` 或 `--format json`                             | 便于直接嵌入工单、PR 或分析报表                      |

---

## 快速定位：Issue 优先

报告擅长回答「哪个版本退化了」，不擅长回答「失败长什么样」。用户问「最近什么情况」时，先用一次调用看 Issue 全貌，往往比先跑报告更快定位：

```bash
# 按出现频次排序的失败全貌（一次调用，秒级）
sentry issue list <org>/<project> --period 7d --limit 30 --sort freq \
    --json --fields shortId,title,count,userCount,firstSeen,lastSeen

# 单条 Issue 的 tags（failure.node / failure.stage / task.name）与堆栈
sentry issue view <SHORT-ID>
```

- `--sort` 的合法值只有 `recommended` / `date` / `new` / `freq` / `user`；传 `events` 会直接报错。
- `--sort new` 找新出现的问题，但新条目常常是 count=1~2 的孤例噪声，不要直接当成回归。
- 用 `count`（事件数）和 `userCount`（独立用户数）区分「高频噪声」与「真实影响面」。

### 用 explore 做自定义聚合

```bash
sentry explore <org>/<project> --dataset spans \
    --field span.description --field release --field 'count_unique(trace)' \
    --query 'span.op:mfa.error' --period 7d --sort '-count_unique(trace)' --limit 20 --json
```

已验证可用字段：`release`、`span.description`、`span.status`、`span.op`、`trace`、`id`、`project.name`、`environment`、`os.name`、`count_unique(trace)`、`count_unique(user)`。

两个高频报错：

- `orderby must also be in the selected columns or groupby` —— `--sort` 用到的列必须同时出现在 `--field` 里。
- `Invalid sort value` —— `sentry issue list` 与 `sentry explore` 的合法排序值不同，先看 `--help`。

**已验证不可用，不要在这些地方浪费往返**：

- `--field device` / `os` / `span.category` / `failure.node`：在 spans 上恒为空。`failure.node` 只存在于 Issue 事件的 tags，用 `sentry issue view` 看。
- `sentry span view <trace-id>` / `sentry span list <trace-id>`：`explore` 能查到的 trace 常常在 span 视图里查不到（保留期/采样不一致），只会报 `No trace found`。
- `sentry event view <span-id>`：`explore` 返回的 `id` 是 span id，不是 event id。

---

## 推荐分析流程

1. `sentry issue list ... --sort freq`（秒级）→ 先判断失败集中在**系统层**（控制器初始化 / 连接）还是**任务层**。
2. `task-failure --sort failures --limit 15`（~20s）→ 失败绝对量排行 + **失败节点标记**表。标记表里的共享节点（`ReturnMain`、`HomeFlag`、`FlagInWilderness` 等）通常是一次性能修好多个任务的抓手。
3. `task-trend --sort delta --limit 10`（~50s）→ 确认最新版本是否有负向回归。
4. 只对可疑任务做穿透：`task-trend --task <任务名> --versions 5`。

> 经验：M9A 的失败绝对量长期被「控制器初始化失败 / 连接失败」主导（属用户环境问题），而流水线层面的失败往往集中在少数几个共享返回节点上。报告时把这两类分开说，不要混成一个「失败率」。

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
- `--task <任务名>`：穿透查询单个任务（支持模糊匹配；匹配到多个候选会报错并列出候选）。
- `--include-beta`：版本序列中包含 beta / rc 测试版（默认仅对比正式稳定版）。
    - 注意：它切换的是**本项目自身版本号**的预发布标记，不是渠道（MFA / MXU）的版本号。因此当最新项目的正式版已经发布时，加不加这个开关结果可能完全相同——不要靠重复跑它来「换一个视角」。
- `--period`：默认 `30d`。
- `--no-fresh`：复用本地缓存，重复试跑时用。

### 2. `task-failure`（单版本深度体检）

- `--sort {failures,rate,total,name}`：
    - `rate`：按失败率降序排列；
    - `failures`：按失败绝对次数降序排列（默认）；
    - `total`：按总运行次数降序；
    - `name`：按任务名排序。
- `--limit N`：同时限制「任务表」与「失败节点标记表」的最大展示行数。
- `--release <release字符串>`：手动指定特定 release（未指定时自动通过 Sentry API 探索最新版本）。
- `--period`：默认 `7d`；`--no-fresh`：同上。

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
4. **小样本不可当真**：`--limit` 榜单末尾常见样本数只有个位数或几十的任务，`+7.0pp` 这种涨幅往往只是噪声。先看「运行数」列再下结论。

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
