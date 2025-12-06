---
order: 6
icon: qlementine-icons:debug-16
---
# Bug Troubleshooting

Fixing bugs is also an important part of development.  
There are techniques to quickly and accurately locate, analyze, and resolve bugs.  
This article will briefly introduce the general process of troubleshooting bugs.

> [!NOTE]
>
> The following content is for reference only. Please pay attention to its timeliness.

## Preparations

Communicate with the person who reported the bug to gather as much relevant information as possible, such as:

- Detailed description of the issue (time of occurrence, scenario, etc.)
- Necessary information like configuration files, logs, screenshots, etc.

## Locating Key Logs

1. Confirm the resource version and runtime mode

   For M9A, there are two runtime modes: 1. MaaPiCli 2. MFA

   Based on observations, the log for MaaPiCli runtime contains the line:

   ```plaintext
   [2024-11-28 19:46:32.571][INF][Px14600][Tx16498][Parser.cpp][L56][MaaNS::ProjectInterfaceNS::Parser::parse_interface] Interface Version: [data.version=v2.4.11]
   ```

   While the log for MFAWPF runtime contains the line:

   ```plaintext
   MFAWPF Version: [mfa.version=v1.2.2.0] Interface Version: [data.version=v2.5.5] 
   ```

   The `data.version` can be used to determine the resource version. This helps to check whether the bug in the current version has already been fixed.  
   Also, confirm the runtime mode, as different modes may affect the reproduction of the issue.

2. Locate the log position related to the issue

   There are two scenarios:
   - Task ends prematurely
   - Task gets stuck in an infinite loop

   For the former, globally search for **[ERR]** to check what the error is related to.  
   For the latter, globally search for **Node Hit** to find abnormal matching situations (e.g., continuously matching a node that shouldn't be matched repeatedly).

## Analyzing the Issue

Here, issues are roughly categorized into three types: resource loading issues, connection issues, and pipeline issues.

### Resource Loading Issues

Resource loading failure caused by overwriting installation when renaming resources:

```log
[2024-11-17 22:29:04.185][ERR][Px10564][Tx9380][PipelineResMgr.cpp][L211][MaaNS::ResourceNS::PipelineResMgr::parse_config] key already exists [key=OutsideDeduction] 
```

### Connection Issues

Simulator connection failure:

```log
[2024-11-24 23:44:05.539][ERR][Px26056][Tx55883][ControlUnitMgr.cpp][L55][MaaNS::CtrlUnitNs::ControlUnitMgr::connect] failed to connect [adb_path_=D:/MuMu Player 12/shell/adb.exe] [adb_serial_=127.0.0.1:16384]
```

### Pipeline Issues

These are the main issues M9A needs to focus on. Understanding the original pipeline process and analyzing the execution shown in the logs is necessary.

1. Non-pipeline process-related issues

   These issues are not caused by logical problems in the pipeline process itself.

   Based on the problematic node, there are two types:

   The first type is non-unconditional matching/inverse nodes.  
   A common cause is that screenshots are taken too quickly, matching the `next` node, but the current screen has not stabilized yet.  
   The solution is to add appropriate `post_wait_freezes` to the current node to wait for the screen to stabilize before making a judgment.

   The second type is unconditional matching/inverse nodes.  
   This may occur when entering an unexpected interface, leading to incorrect judgments.  
   The solution is to modify as needed.

2. Pipeline process-related issues

   These issues are due to the incompleteness of the task process itself and require modifications after analysis.

## Resolving the Issue

Refer to [Common Issues](../manual/faq.md) for the first two types of issues. For pipeline issues, modify based on the analysis results.

## Verifying the Fix

After fixing, release a test version. If the test is successful, the issue is resolved.
