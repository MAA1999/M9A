---
index: 7
icon: carbon:ibm-watsonx-code-assistant-for-z-refactor
---
# 项目重构

## Image/Model

注意对其修改时不要落下任何用到该Image/Model的 node。

> [!TIP]
>
> 善用全局搜索

## Pipeline

### 其它 node

接下来按照其它 node 的重构目的来分别说明如何重构。

#### 规范 node 名称

如果只是想规范 node 名称，则只需通过 vscode 的全局搜索、替换功能完成即可。  
不过需要注意替换时带着双引号替换，以免出现包含该 node 名的其它 node 也被修改。

#### 简化任务流程、减少耦合

先行阅读 [Node 连接](./pipeline.md#node-连接)，向贴合连接原则的方向进行重构。

部分node 可放在 当前node 的 祖先node 的 `interrupt` 中。  
**注意移动后将不必要的 next node 删除，避免在 `interrupt` 中继续执行主任务链，导致后续任务报错后跳回 祖先node。**

#### 合并相同功能 node

如果有多个 node 都实现了相同的功能，则可以考虑合并为一个 node。

步骤为：

1. 合并前检查该 node `next` 中是否不相关的 node，如有则先将其拆分出来。
2. 合并时所有 node 改用相同规范名称。
3. 合并后检查该 node 在所有任务中的位置是否正确。如本该在 `interrupt` 中的 node 是否位于任务链主干的 `next` 部分。
