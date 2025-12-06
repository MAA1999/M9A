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

1. 确认资源版本以及运行方式

   对于 M9A 来说，有两种运行方式：1. MaaPiCli 2. MFA

   log 一般在以下位置：
      - logs 文件夹下 MFA 的 log
      - debug 文件夹下的 maa.log
      - debug/custom 文件夹下 custom 生成的 log

   下面简单说下 maa.log 中的版本如何找。  
   根据观察，MaaPiCli 运行时有行log为

   ```plaintext
   [2024-11-28 19:46:32.571][INF][Px14600][Tx16498][Parser.cpp][L56][MaaNS::ProjectInterfaceNS::Parser::parse_interface] Interface Version: [data.version=v2.4.11]
   ```

   而 MFAWPF 运行时有log为

   ```plaintext
   MFAWPF Version: [mfa.version=v1.2.2.0] Interface Version: [data.version=v2.5.5] 
   ```

   由 data.version 可以确定资源版本。以此判断当前问题发生的版本是否已修复当前 bug。  
   同时确认运行方式。因为不同运行方式，可能影响问题的复刻。

2. 定位问题所在的 log 位置

   分两种情况：
   - 任务提前结束
   - 任务陷入无限循环

   前者全局搜素 **[ERR]** ，查看报错是与什么有关。  
   后者全局搜索 **Node Hit** ，查找不正常的匹配情况（如持续匹配一个本不该一直匹配的 node）。

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
