---
title: 协议文档总览
description: M9A 协议文档总览：活动、战斗、物品与仓库材料等游戏数据的存储格式，以及肉鸽玩法与活动推图的适配协议。
icon: basil:document-solid
index: false
dir:
    title: 协议文档
    order: 3
---

# 协议文档

本栏目记录 M9A 与游戏数据之间的约定：游戏数据以什么格式存放在仓库里，以及新增内容时需要按什么规则适配。想修改 `data/` 下的资源或为新活动接入识别，请看这里。

## 游戏数据

- [活动数据协议](activity.md) —— 游戏版本与活动数据的存储格式，以及按语言分文件的存放规则。
- [战斗数据协议](combat.md) —— 战斗物品与掉落索引等战斗相关数据的结构。
- [物品数据协议](items.md) —— 游戏中各类物品数据的结构与字段说明。
- [仓库材料识别协议](warehouse-inventory.md) —— 「仓库材料识别」任务的功能架构，以及 `config/warehouse_inventory.json` 的落盘格式。

## 玩法适配

- [局外演绎：无声综合征 肉鸽辅助协议](sos.md) —— 肉鸽玩法的资源目录与顶层数据结构。
- [活动推图适配协议](auto-promotion.md) —— 「活动推图」（AutoPromotion + AutoTrail）的换期适配方式：流程层固定不变，只替换识别层参数。
