---
order: 6
icon: ri:archive-line
---

# 仓库材料识别协议

> [!TIP]
>
> 本文档说明「仓库材料识别」（WarehouseInventory）任务的功能与数据协议。
> 该任务扫描仓库素材页全部已配模板的材料数量，落盘到
> `data/combat/warehouse_inventory.json`，供未来功能（如自动补货、材料缺口提示）读取。

## 功能架构速览

| 文件                                              | 内容                                                                     |
| ------------------------------------------------- | ------------------------------------------------------------------------ |
| `tasks/WarehouseInventory.json`                   | 任务入口定义（group: `daily`）                                           |
| `resource/base/pipeline/warehouse_inventory.json` | 流程：进入仓库 → 确认页签 → 扫描 → 退出仓库 → 回主界面                   |
| `agent/custom/action/warehouse_inventory.py`      | `WarehouseInventoryScan`：三段往返扫描 + 数量 OCR + 众数纠错 + 落盘 JSON |
| `data/combat/items.json`                          | 材料数据源（按稀有度分组），决定扫描哪些材料                             |
| `resource/base/image/Warehouse/Item-<id>.png`     | 材料图标模板（TemplateMatch 用）                                         |
| `data/combat/warehouse_inventory.json`            | 运行产物：数量快照（已加入 `.gitignore`，不入库）                        |

## Pipeline 流程

```
WarehouseInventory（入口）
  └─ WI_EnterWarehouse    OCR「仓库」→ 点击进入仓库（未找到则重试）
       └─ WI_WarehouseFlag  OCR「素材」页签 → 确认已进入素材页
            └─ WI_Scan     Custom action: WarehouseInventoryScan（核心扫描）
                 └─ WI_ExitWarehouse  TemplateMatch 返回键 → 退出仓库
                      └─ WI_AtMain     OCR「仓库」入口 → 确认回到主界面
                           └─ [JumpBack]ReturnMain
```

## 扫描机制（WarehouseInventoryScan）

### 数据源与模板过滤

- 数据源：`data/combat/items.json`（金/黄/紫/蓝/绿 五档，共 46 种可刷取材料）
- **只扫描有模板的材料**：`resource/base/image/Warehouse/Item-<id>.png` 存在才纳入扫描，
  模板缺失的材料自动跳过并记录状态——**未来新增材料只需补模板图，无需改代码**

### 回顶与往返扫描

仓库会记住上次滚动位置，进入时可能停在列表任意位置。扫描前先向上滚动 6 屏回到顶部，
再执行三段往返扫描（向下 6 屏 → 向上 6 屏 → 向下 6 屏，共 12 屏），
保证每个材料经过屏幕 2-3 次；每个材料至少读到 3 次有效读数后提前结束。

### 数量识别（BF_ItemCount OCR）

数量数字在图标下方的格子底部，位置随图标高度分两组：

| 图标高度                    | 数字位置          | 偏移组             |
| --------------------------- | ----------------- | ------------------ |
| `h >= 80`（金/紫/蓝高图标） | 图标顶 `+82~95px` | `(82, 85, 90, 95)` |
| `h < 80`（绿/蓝矮图标）     | 图标底 `+2~10px`  | `(h+2, h+6, h+10)` |

- 横向 ROI：只取图标中部一半（`dx = w*0.25, dw = -w*0.5`），
  避免把两侧稀有度装饰竖线卷入（金羊毛数字 1 + 装饰线会被 OCR 读成 11）
- 每个偏移各 OCR 一次，取文本中最长数字组（真实数量位数多于边缘噪声）
- 实测：50% 宽已覆盖 1~5 位数（如 20023/1919）；放宽到 70% 会把金色装饰条卷入，不可取

### 防误读：多读数众数

单次读数可能被装饰条干扰（3→31、1→11、231→21），通过两个层级纠正：

1. **单屏多偏移**：同一图标用 4/3 个偏移分别 OCR，取众数
2. **往返多屏**：同一材料在多次经过屏幕时累计读数，最终取众数；
   无众数时取最长位数（截断误读比真值短）

## 输出格式

`data/combat/warehouse_inventory.json`：

```jsonc
{
    "updated_at": "2026-08-06 15:12:18", // 扫描完成时间
    "counts": {
        "110101": 81, // 材料 id → 数量
        "110102": 60,
    },
    "skipped": [], // 图标找到但数量识别失败的材料 id
    "materials": {
        // 材料元信息（id → 名称/稀有度）
        "110101": {"name": "颤颤之齿", "rarity": "green"},
    },
}
```

- `counts` 缺省的材料 = 仓库中未找到（按 0 计，不写入）
- `skipped` 中的材料不能按 0 计（图标在但数量没读到），需人工确认
- 该文件是运行产物，已加入 `.gitignore`

## 维护指南

- **新增材料**：往 `data/combat/items.json` 对应稀有度分组加 `"id": {"name": "材料名"}`，
  并放模板图到 `resource/base/image/Warehouse/Item-<id>.png`（1280x720 基准、深色底图标）
- **模板图要求**：与游戏内仓库图标渲染一致（尺寸、色调），建议直接从仓库界面截图裁剪
- **误读排查**：查看 `debug/custom/<日期>.log` 中 `多次读数不一致` 警告，
  定位是哪类装饰干扰后调整 ROI 注释中的经验值
