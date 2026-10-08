---
title: 开发文档
icon: ph:code-bold
index: false
dir:
    order: 2
---

# 开发文档

本栏目面向想给 M9A 提交代码或适配新内容的开发者。建议先读「入门」，了解 M9A 的技术选型与仓库结构，再按需要进入「编写指南」或「工程实践」。

只想改一点点 JSON 或文档、不熟悉 Git 的读者，请从 [开发前须知](development.md) 的 Pull Request 流程看起。

## 入门

- [开发前须知](development.md) —— GitHub Pull Request 流程、克隆仓库与拉取子模块、搭建 Python 开发环境。
- [项目结构](structure.md) —— 仓库各目录的职责，以及发布包与打包脚本的位置。

## 编写指南

- [Custom 编写指南](custom.md) —— 通过 AgentServer 注册自定义模块，扩展 MaaFramework 的 JSON 流程做不到的逻辑。
- [Pipeline 编写指南](pipeline.md) —— MaaFramework 的核心概念，用 JSON 描述自动化任务的执行流程与识别方式。
- [界面本地化](i18n.md) —— `interface.json` 与 `tasks/` 下的项目文本如何做多语言。

## 工程实践

- [代码格式化](formatting.md) —— 仓库使用的格式化工具，以及本地与 CI 的检查方式。
- [文档编写](doc.md) —— 本站文档的 MarkdownLint 规范与 VuePress 容器用法。
- [Bug 排查](fix.md) —— 定位、分析与解决 bug 的一般流程。
- [外服适配](overseas-client-adaptation.md) —— 国际服与国际服 PC 端的功能适配要点。
