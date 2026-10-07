---
order: 10
icon: material-symbols:inventory-2-outline-rounded
---

# 刷取材料目录维护

「智能均衡刷材料」任务（库存保持模式 + 原有均衡逻辑）的材料与关卡全部由数据表驱动：新增材料或新增关卡族都不需要改决策代码，只改数据与 pipeline。

## 数据流

1. `data/combat/balanced_farming.json` —— 材料目录：材料 id → 名称 / 关卡 / 难度（可选每局掉落量 / 读数来源）。同一份目录也被原有「智能均衡刷材料」（`BalancedFarmingAnalyze`）读取：它只扫仓库，会跳过 `source: "character"` 的条目，新增材料时无需额外处理
2. 目标库存 —— GUI「库存保持」总开关 + 每件材料一个开关，开关自己的「目标数量 / 吃糖次数」，`config/depot_maintain_targets.json` 可再按材料覆盖
3. `config/warehouse_inventory.json` —— 材料快照：仓库材料由 `WarehouseInventory`（仓库材料识别）落盘，微尘/利齿子儿由 `DepotCurrencyInspect`（角色升级页读数）合并
4. `DepotMaintainPlan`（pipeline 节点 `BF_Plan`）读上述三者，挑缺口最大的材料，覆盖 `SelectCombatStage`、`AllIn`、本轮吃糖与上报设置后进入战斗

## 新增一种材料

1. 在游戏里截图并裁剪图标 —— **模板不能由解包原画生成**：实测原画与屏幕渲染（仓库图标是原画的放大裁切）掩膜相关仅 0.28–0.66，低于 TemplateMatch 阈值 0.9；用「原画 × 0.66 居中裁切」配方做留一验证，30 个样本 0 个达标。两套模板都要实拍：

    - 仓库·消耗品页截图 → 裁出 `resource/base/image/Warehouse/Item-<id>.png`（紧贴图标裁切、含游戏自带阴影；现有模板尺寸 59×83 ~ 124×93 不等）
    - **同族近似图标（典类的残篇/孤卷/全章）只保留能区分家族的徽记区域，其余涂纯绿（RGB 0,255,0）**，匹配时由 `green_mask` 忽略 —— 四个家族的图标互相关度 0.94+，整图匹配会串到别家的格子读错数量。同时 `BF_ItemIcon` 固定 `order_by: Score`：MaaFW 默认按位置取**最左**达标框，不按分数取最高（实测四个家族全被最左那一格串号）
    - 该材料掉落时的结算页截图 → 裁出 `resource/base/image/Items_processed/Item-<id>.png`（结算行 5 格，x 起点 663/780/897/1014/1131，y 553，格 83×56）

2. 在 `data/combat/balanced_farming.json` 增加一条：

    ```json
    "110103": { "name": "啮咬盒", "stage": "7-26", "level": "Hard", "per_run": 1 }
    ```

    - `stage`：主线写「章节-关卡」（如 `7-26`），资源本写「族-关卡」（如 `MA-06`）
    - `level`：`Hard` / `Story` / `None`
    - `per_run`（可选）：每局掉落量的保守下界，用于折算刷取次数；省略时按每局 1 个估算

3. 在 `tasks/BalancedFarming.json` 里给新材料加 GUI 入口（三处）：
    - 材料开关：一个以材料名命名的 switch 选项，`Yes` case 挂参与标记并把配置项列为子项；`No` case 什么都不做（默认关）

        ```json
        "<材料名>": {
            "type": "switch",
            "label": "$Option.BalancedFarming.Material.<id>",
            "cases": [
                { "name": "No" },
                {
                    "name": "Yes",
                    "pipeline_override": { "BF_Plan": { "attach": { "mat_<id>": true } } },
                    "option": ["<材料名>·设置"]
                }
            ]
        }
        ```

    - 配置项：`<材料名>·设置` 输入选项，两个字段 `target_<id>` / `candy_<id>`（都用 `pipeline_type: string`、`verify: "^\\d*$"`、`default: ""`），`pipeline_override` 把两者挂到 `BF_Plan.attach`（**不要放 `custom_action_param`**——MaaFW 的覆盖对 `attach` 是叠加合并、对末端键是整体替换，多个材料各写一份 `custom_action_param` 会只剩最后一个）；label 用共享键 `$Option.BalancedFarming.Material.Settings`
    - 挂进总开关：把 `<材料名>` 加进「库存保持」case `Yes` 的 `option` 列表（顺序即界面顺序）
    - 同时在 `locales/zh_cn.json` 与 `locales/en_us.json` 补 `Option.BalancedFarming.Material.<id>`（显示名，惯例带关卡：`岩中典残篇（ME-02）`）
    - 用 switch 而不是勾选列表：MFAAvalonia 的 checkbox 把开关排成一行按钮、子项统一堆在下方（开关与内容分离）；switch 的卡片是「开关行 + 紧跟其下的子项框」，开关和它自己的两个数字框在一块
    - **不在仓库页的材料**（微尘 205 / 利齿子儿 203 这类货币）：条目里写 `"source": "character"`，读数改从角色升级页取（见下节），不需要仓库图标模板；刷新时会进角色页读一次而不是跑仓库扫描

4. 校验：

    ```bash
    uv run --frozen pytest tests/test_depot_maintain.py -k shipped -q
    pnpm check
    ```

    `-k shipped` 的用例会核对图标模板、章节进入模板与关卡入口节点是否齐全；`pnpm check` 覆盖任务文件 schema 与 i18n 键。

## 典籍（洞悉材料）的关卡与难度

四族洞悉本的掉落按难度分档（2026-10-07 由 wiki 关卡页奖励段实证）：

| 族（关卡前缀）           | 02   | 04   | 06   |
| ------------------------ | ---- | ---- | ---- |
| 岩中典（`ME`，群山之声） | 残篇 | 孤卷 | 全章 |
| 星升典（`SL`，星陨之所） | 残篇 | 孤卷 | 全章 |
| 木娑典（`SS`，深林之形） | 残篇 | 孤卷 | 全章 |
| 兽涎典（`BW`，荒兽之野） | 残篇 | 孤卷 | 全章 |

- 关卡代码写作 `ME-02` / `SS-04` / `BW-06` 这样，`level` 用 `None`；这与 `tasks/Combat.json` 的「作战关卡(岩/星/木/兽)」选项完全一致（它们同样用 `ME-02` + `TargetStageName_OCR.expected: ["02"]`），导航复用既有资源关卡流程，无需新代码。
- 掉落量按**难度奇偶**分档：**偶数档（02/04/06）每局 2 个，奇数档（01/03/05）每局 1 个**；奇数档虽然体力消耗略低，但只有 1 个，性价比不如偶数档 —— 所以目录一律只写偶数档、`per_run` 一律写 2 —— 即使掉落模板缺失，`ceil(缺口 / 2)` 的估算也是精确的。给奇数档建条目时才写 `per_run: 1`（且通常没必要建）。
- 目录固定用最高档（全章 = 06）；账号尚未解锁该档时关卡导航会失败，这是面向终局账号的取舍。
- 这些关卡不在 `drop_index.json` 里 → 库存保持走结算页自读；**若该材料没有掉落模板，会自动退回「按每局掉落量估算」模式**（固定掉落时估算即精确，不需要逐局核对，也不会刷屏告警）。
- **新加的材料不参与掉落上报**：`drop_index.json` 同时是掉落上报表，规划时按关卡查表——表内关卡（原有材料）照旧在胜利链里跑 `DropRecognition` 上报，表外关卡（如洞悉本）本轮直接关闭该节点、只自读结算页。不要往 `drop_index.json` 里补新关卡/新材料。
- 参考实现：`tasks/CharUpgrade.json` + `agent/custom/action/char_upgrade.py` 也在刷这批材料（从角色洞悉面板点「获取」进入对应关卡，逐局用 `CUB_IsEnoughMaterial` 复查是否够，`drop_per_run: 2`）；它走的是游戏 UI 自身跳转，与本目录的关卡代码导航等价。
- 典籍的**残篇/孤卷**按 wiki 物品页「来源」只写了开箱（残典瓶/圣篇轴），但关卡页奖励段证明 02/04 档同样固定掉落 —— 两者以关卡页为准。

## 名称、品质与关卡的来源

名称/品质/desc 在解包里拿不到（`datacfg_*.dat` 是密文），改从灰机 wiki 取：`Data:Item/map.json`（名称↔id 全表）与 `Data:<id>.json`（`name/rare(1..5 → 绿蓝紫黄金)/subType/来源`），抓取脚本与坑见 `G:\M9AA\M9A-pr\55\1999\wiki-抓取方法.md`。

关卡选择的两条硬规则（2026-10-07 核对）：

- **同家族共用关卡**：`data/combat/drop_index.json` 显示一个关卡常常掉整个家族的多档材料（如 `7-26E` 掉 110101–110104），因此同家族新条目可直接沿用现有关卡；某档材料只在别处掉落时以 drop_index 为准（如 110504 狂人絮语只在 `3-13E`）。
- **合成产物不进目录**：`111003-111006`（铂金通灵板 / 分别善恶之果 / 长青剑 / 金羊毛）是荒原合成产物，没有刷取关卡，只进 `items.json` 供识别命名。

## 新增一个关卡族

1. 在 `resource/base/pipeline/combat.json` 仿照现有族补入口节点：`ResourceChapter_<族>` → `ResourceChapter_<族>Enter`，识别该族的章节标签（模板或 OCR）
2. 在 `agent/utils/material_catalog.py` 的 `STAGE_FAMILIES` 登记：族代码 → 入口节点 / 显示名 / 识别模板
3. 同上跑 `-k shipped` 校验

`SelectCombatStage` 会把「族-关卡」拆成族代码与关卡序号（序号补零到两位）后交给对应 Enter 节点，因此 Python 侧不需要为新族写代码。

## 目标库存与逐材料吃糖

- GUI「库存保持」是 **总开关（默认关闭）**：关闭时整条任务走原有「均衡取最少」逻辑，下面两项在界面上不显示、覆盖也不生效；开启后才展开
    - 关闭由 `tasks/BalancedFarming.json` 中该开关 case `No` 的 `BF_Plan.action.param.custom_action_param.depot_disabled` 传给 `DepotMaintainPlan`，在解析目标前就直接回退旧流程
- GUI「库存保持」开启后，每种材料是一个 **独立开关**（`switch` 选项）：**打开才展开它自己的「目标数量 + 吃糖次数」两个输入框**（PI 的 case 子配置项：关闭时既不显示、覆盖也不生效），开关和内容在同一张卡片里。所有材料都不开 = 不限制（只由目标值决定谁参与）
- 每件材料自己的两个数字框（对齐 MAA 库存保持「自己挑材料 + 各自定量」）：
    - `目标数量`（`target_<id>`）：**留空 = 不刷该材料**、`0` = 不刷、正整数 = 该材料要补到的库存
    - `吃糖次数`（`candy_<id>`）：该材料体力不足时最多吃几个糖 —— **留空 = 不限（跟随全局「吃糖」选项）**、`0` = 不吃糖、`N` = 最多 N 个
- 逐材料吃糖由规划节点**每轮动态覆盖**：`DepotMaintainPlan` 记下任务开始时的全局设置（`EatCandy.enabled` / `EatCandyStart.max_hit`，即 GUI「吃糖」选项生效后的节点数据），本轮按所选材料改成 `enabled = 全局开 且 该材料不是 0`、`max_hit = 该材料次数（留空则还原全局值）`，下一轮自动重算，不会泄漏到别的材料
    - `EatCandy.enabled` 就是 `TargetCountCandyRoute` / `TargetCountDetermine` 判断「能不能吃糖续体力」的开关；只关某个材料的吃糖不影响其他材料
- `config/depot_maintain_targets.json`：**逐材料覆盖** GUI 的目标数量。首次以库存保持模式运行时自动生成模板（所有材料写 `null`），把关心的那几件改成正整数即可：

    ```json
    {
        "_说明": "正整数 = 覆盖 GUI 逐材料目标；null = 未设置（不刷）",
        "110103": 200,
        "110203": null
    }
    ```

    - `正整数` 覆盖 GUI 值；`null`（或直接删掉该行）= 未设置；`_` 开头的键是注释
    - 未列出的材料 = 未设置；非法值只忽略该条并告警；文件值优先于 GUI（**开关没打开的材料仍不参与**）

- 配置缺失 / JSON 损坏 / 值非法一律忽略并回退未设置，日志会说明原因

## 仓库快照

- 来源：`WarehouseInventory` 任务的 `config/warehouse_inventory.json`；微尘/利齿子儿的读数由角色升级页写入同一文件
- 有效期 24 小时，常量在 `agent/custom/action/depot_maintain.py` 的 `SNAPSHOT_TTL_HOURS`
- **两套读数各有自己的时间戳**：仓库读数看 `updated_at`（全量扫描写入），角色页读数看 `currency_updated_at`（`write_snapshot_counts` 写入）；刷新按来源各自判新旧，只跑需要的那一步（仓库材料 → 仓库全量扫描，角色页材料 → 进角色升级页读数）。仓库扫描整表重写时会**保留自己没扫的读数**，不会把角色页读数挤掉
- 刷新后仍不可用（扫描/读数失败）则退回实扫仓库的原有流程
- 规划只读取快照，不会重写它

## 微尘 / 利齿子儿（角色升级页读数）

这两个货币不在仓库页，计数只显示在**角色升级面板**右上角（微尘 roi `[966,20,96,26]`、利齿子儿 roi `[1122,20,96,26]`）。

- 读数流程（`resource/base/pipeline/depot_currency.json`，入口 `DepotCurrencyInspect`）：`DepotCurrencyRead` 复用「信任奖励领取」的角色页入口节点（`EnterCharacter` → `FlagInCharacter` → `FirstCharacter` → `FlagInCharacterDetail`，覆写 next 后接到 `CI_LevelPlus` 点「等级 +」）→ 打开升级面板 → 识别右上角两个数字并合并进快照 → 连点返回回到主界面
    - 「信任奖励领取」链本身假设主界面起步，所以导航入口 `DepotCurrencyNav` 带 `[JumpBack]ReturnMain` 守卫（与 `WarehouseInventory` 入口同形状）；只在运行时覆写 next，**不改 `character.json`**，信任奖励任务本身不受影响
- **精度**：面板显示的是缩写值（如 `9792K`），游戏用 K/M（不用中文单位），单位切换阈值未知——解析器按后缀换算、不假设阈值；千位精度带来 ≤1000 的显示误差，目标库存是几万～几百万量级时不影响决策
- 关卡：微尘 `LP-06`（尘埃运动 06，每局固定 12500）、利齿子儿 `MA-06`（铸币美学 06，每局固定 9000；wiki 关卡页 2026-10-08 核对）；两者都不在 `drop_index` 上报表内，走结算页自读
- GUI 里这两件的**目标数量框支持 K/M 缩写**（`5M` = 5000000，校验正则 `^\d*[KkMm]?$`），普通材料仍是纯数字
- 任意角色都行：升级面板右上角是通用货币栏，满级角色同样显示
- 导航与 roi 均为 1280×720 实机截取；改动前先用 `DepotCurrencyInspect` 在模拟器上跑一遍确认

## 结算掉落行与停止判定（已实机核对）

- 掉落行位置固定：图块 84×84、等距 117，共 5 格，y 553..637；`DropRegionRec` 的 roi `[661,549,598,68]` 覆盖全部图块。行内容会横向滚动，识别时最多滑 3 次
- 掉落模板用 `resource/base/image/Items_processed/Item-<id>.png`（图标区 83×56，**不含数量**，匹配与数量无关）
- 数量条在图块底部：`[box.x + 22, 613, box.w - 44, 17]`，**已越出 `DropRegionRec` 的 roi 下沿**，必须按命中 box 推算；读数字前先做灰度二值化（`agent/utils/settlement_drops.py` 的 `filter_digit_colors`）
- 累计来源二选一，由 `DepotMaintainAccumulate` 在规划时决定：官方发布版优先读 drop_core 的 `DropRecognitionState.total_drops`（要求该关卡在 `drop_index.json` 有验证数据、且「掉落统计上报」未关闭）；否则自读结算行。同一判断也决定本轮是否在胜利链里启用 `DropRecognition`——表外关卡不参与掉落上报
- 达标后按「当前批次收尾」：把本批设为最后一批，交给既有 `TargetCountProgress` 正常结束，不在结算页做任何退出操作（代价是最多多刷 3 局）
- 一轮作战补一种材料；`TargetCountFinish.next` 被覆写为回到 `BF_Plan`，于是同一次任务会继续补下一种缺口材料，直到：全部达标、上一轮没打成（体力不足 / 无法复现）、或达到轮数上限（`MAX_ROUNDS_PER_TASK`，默认 50）。**续刷同一关卡不回主界面**：库存保持模式下批次达标由 `combat.depot_batch_end_node()` 直接交回 `BF_Plan`（跳过 `TargetCountFinish` 的回家），规划节点探到关卡页「复现」按钮可见就用 `AllIn` 就地重选复现次数；换材料/换关卡或已经回到主界面时仍走 `Combat` 全量导航。就地结束时不会经过 `TargetCountFinish`，收尾的掉落总结与回主界面由 `DepotMaintainDone` 兜底
- 每局把已确认的掉落增量写回仓库快照；`updated_at` 保持不变（它表示上次全量扫描时间），只更新 `counts`
- 没有掉落模板的固定掉落关卡走估算模式，此时由**规划节点在每轮结束时按「本轮实际局数 × per_run」回写**（按轮号记账，一轮只结一次；同一轮内因快照回扫重入不会重复写）。不回写的话快照永远停在旧值，多轮循环会反复刷同一种材料
- 仓库图标（`Warehouse/Item-<id>.png`，紧贴裁切）与掉落图标（`Items_processed/`）是两套不同素材，交叉匹配分数低于 0.6：要参与库存保持并核对逐局掉落的材料，两套模板都要准备
- 进战斗用普通 `next`（`BF_Plan → Combat`），**不要用 `[JumpBack]Combat`**：JumpBack 的语义是「链执行完毕后跳回父节点重新尝试其 next 列表」，单条目列表会反复重进战斗

## 截图裁剪的操作步骤（MaaMCP）

设备连着模拟器时可以直接在会话里完成，不必手动截图（2026-10-07 实操验证）：

1. `find_adb_device_list` → `connect_adb_device` → `screencap`（落盘即 720p）
2. 需要滚动时用 `swipe`：**它的坐标是 720p 空间**（原生分辨率的坐标会被忽略），往上滚一屏用 `start (640, 620) → end (640, 300)`、`duration 2500`
3. 仓库图标：格子约 120×120，裁 `(tile.x + 2, tile.y + 2, 116, 94)`（去掉底部数量条）；存成 `Warehouse/Item-<id>.png`（RGB，保留格子底色，与既有模板一致）
4. 裁剪后自校验：对同分辨率截图做 `matchTemplate`，命中应 ≈ 1.000 且全屏无更高分

身份判别（没有 OCR 时）：先看**印章颜色**（岩中=金、星升=蓝、木娑=绿、兽涎=绯红），再用仓库数量与历史快照交叉核对。

## 已知边界

- 材料目录只覆盖仓库材料；货币类（微尘、利齿子儿等）显示为 K/M 紧凑数字，且有掉落模板而无仓库模板，drop_core 也明确不累计它们（`HELPER_ITEMS`），需要单独的读数通道，暂未纳入
- `per_run` 现在只是每轮刷取次数上限的依据（缺省按每局 1 个保守估算），真正的停止由实际掉落决定

## 校验

```bash
pnpm format:py
pnpm check:py          # ruff + pyright(strict) + pytest
pnpm check             # 格式 / schema / i18n / MaaFW 完整性
```
