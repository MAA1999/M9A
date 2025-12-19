---
order: 6
icon: qlementine-icons:debug-16
---
# Bug 排查

修 bug 也是开发中重要的一环。  
如何快速准确地定位、分析、解决 bug 是有技巧的。  
本文将简单介绍排查 bug 的一般流程。

> [!NOTE]
>
> 以下内容仅供参考，注意时效性。

## 前置准备

与 bug 提出者沟通，尽可能的获取 bug 相关的信息，如：

- 问题的细节描述（发生的时间、场景等）
- 配置文件、日志、截图等必要信息

## 定位关键 log

### 使用 MaaLogAnalyzer 分析日志

推荐使用 [MaaLogAnalyzer](https://github.com/Windsland52/MAALogAnalyzer) 进行日志可视化分析，它可以：

- 自动识别版本
- 可视化展示 Pipeline 执行流程
- 快速定位错误和异常节点
- 分析节点匹配情况和执行耗时

**使用步骤**：

1. 从 [Releases](https://github.com/Windsland52/MAALogAnalyzer/releases) 下载最新版本
2. 打开工具，导入日志文件（`debug/maa.log` 或 `logs/` 下的 MFA 日志）
3. 查看可视化执行流程，定位问题节点

### 日志文件位置

M9A 的日志一般在以下位置：

- `debug/maa.log` - MaaFramework 核心日志
- `debug/custom/` - Custom 模块生成的日志
- `debug/sink/` - Sink 事件监听日志（结构化 JSONL 格式）（Deprecated）
- `logs/` - MFA 的日志（仅 MFA 运行时）

### 手动分析（备用方案）

如果无法使用 MaaLogAnalyzer，可以手动分析：

1. **确认版本信息**

   在 `maa.log` 中搜索：
   - `Interface Version: [data.version=` - 查看资源版本
   - `MFAA Version` 或 `MaaPiCli` - 确认运行方式

2. **定位问题**

   - **任务提前结束**：搜索 `[ERR]` 查看错误信息
   - **任务循环**：搜索 `reco hit` 查找异常匹配模式

## 分析问题

在这里我将问题大致分为三类：资源加载问题、连接问题以及 pipeline 问题。

### 资源加载问题

资源改名时覆盖安装导致的资源加载失败：

```log
[2024-11-17 22:29:04.185][ERR][Px10564][Tx9380][PipelineResMgr.cpp][L211][MaaNS::ResourceNS::PipelineResMgr::parse_config] key already exists [key=OutsideDeduction] 
```

### 连接问题

模拟器连接失败：

```log
[2024-11-24 23:44:05.539][ERR][Px26056][Tx55883][ControlUnitMgr.cpp][L55][MaaNS::CtrlUnitNs::ControlUnitMgr::connect] failed to connect [adb_path_=D:/MuMu Player 12/shell/adb.exe] [adb_serial_=127.0.0.1:16384]
```

### Pipeline 问题

这类是 M9A 主要需要关注的问题，需要了解原 pipeline 流程以及 log 展示的执行情况，加以分析。

1. 非 pipeline 流程类问题

   这种问题本身 pipeline 流程逻辑上没有问题。

   根据出问题的 node 分为两种：

   第一种是 非 无条件匹配/inverse node。  
   常见原因是截图截太快了，匹配到 `next` 中 node，但当前画面尚未未稳定。  
   解决方案是为当前 node 添加合适的 `post_wait_freezes`，等待画面稳定再做判断。

   第二种是 无条件匹配/inverse node。  
   这种可能是进到非预期界面，导致判断失误。  
   解决方案是按需修改。

2. pipeline 流程类问题

   这种是任务流程本身完备性不足，需在分析后修改。

## 解决问题

前两种参考[常见问题](../manual/faq.md)解决，pipeline 问题根据分析结果修改。

## 验证修复

修复后发布测试版，经测试无误后解决问题。
