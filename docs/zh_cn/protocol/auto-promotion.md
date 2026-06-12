---
order: 5
icon: ri:route-line
---

# 活动推图适配协议

> [!TIP]
>
> 本文档是「活动推图」（AutoPromotion + AutoTrail）的换期适配协议。
> 功能采用**流程与识别分层**：流程层（调度状态机、阶段闸门）固定不变；
> 识别层的全部参数可经 pipeline JSON 的 `custom_recognition_param` 覆盖——
> **换期适配只改 JSON，不动 Python**。本协议面向 AI 执行设计：
> 把文档交给具备模拟器控制能力（如 MaaMCP）的 AI，说"按协议适配新活动"即可。

## 功能架构速览

| 文件 | 内容 | 层 |
|---|---|---|
| `assets/resource/base/pipeline/activity/auto_promotion.json` | 三阶段调度 + 推图循环 + 辅助 OCR 节点 | 流程 + 适配面 |
| `assets/resource/base/pipeline/activity/auto_trail.json` | 小径调度循环 | 流程 + 适配面 |
| `agent/custom/reco/auto_promotion.py` | `APPhaseGate`（阶段闸门）、`APMapAnalyze`（找关/星标/滑到头） | 识别算法（默认值事实源） |
| `agent/custom/reco/auto_trail.py` | `ATTrailAnalyze`（小径五态） | 识别算法（默认值事实源） |
| `deps/tools/custom.recognition.schema.json` | 全部可覆盖参数的声明（key/type/default） | 适配面清单 |

## 参数覆盖机制（v2 分层核心）

识别类的全部阈值/偏移/颜色/点击位常量都可在节点的 `custom_recognition_param`
中以**常量名小写**为 key 覆盖：

```jsonc
"AP_EnterStage": {
    "recognition": {
        "type": "Custom",
        "param": {
            "custom_recognition": "APMapAnalyze",
            "custom_recognition_param": {
                "query": "stage",
                "lit_pixels": 25        // 仅本期需要的差异项
            }
        }
    }
}
```

规则：
- **默认值唯一事实源 = Python 类常量**，pipeline JSON 平时只写 `query`，
  换期只写差异项（避免 JSON 与代码默认值漂移）
- 可覆盖参数全集见 schema 中 `APMapAnalyze` / `ATTrailAnalyze` 的
  `custom_recognition_param` properties（含 type/default/description），
  schema 与类常量的一致性由 `tests/test_schema_drift.py` 锁定
- 非法值回落默认并记 error；未知 key 记 warning 后忽略；参数 JSON 整体损坏时
  使用全部默认值继续（不会中断任务）
- 国际服等多服差异走资源覆盖层（`global_en/` 等放同名节点覆盖文件），
  与参数覆盖正交

## 识别器契约

每个识别器（类 × query）的契约固定；某期 UI 大改导致参数调不动时，
替换对应实现方法即可，契约不变则流程层无感。

### APPhaseGate（阶段闸门，无可调参数）

| query | 语义 | 命中返回 | 副作用 |
|---|---|---|---|
| entry | 任务入口，总命中 | box=[0,0,0,0] | 重置全部阶段与识别状态 |
| story / trail / explore | 本次任务未进入过该阶段则命中 | 同上，detail.phase | 标记已进入 + 重置滑动计数 |

阶段启停由任务选项对节点 `enabled` 的 override 控制。

### APMapAnalyze（推图地图分析）

依赖辅助 OCR 节点：`APStageNumberOCR`（底部编号条）、`APExploreAnchorOCR`
（左上模式标签锚点）——两者 ROI 直接在 pipeline JSON 调。

| query | 语义 | 命中返回 | 不命中含义 |
|---|---|---|---|
| stage | 找编号最小的未完成关 | box=关卡点击区, detail.stage | 无未完成关（或亮星为 0 待下帧确认） |
| swipe | 无未完成关且未确认到头 | box=[0,0,0,0]（供 Swipe 动作） | 有未完成关 / 已到头 / 不在地图页 |
| done | 已确认滑到头且无未完成关 | box=[0,0,0,0] | 尚未确认到头 |

关键参数（全集见 schema，36 项）：

| json key | 默认 | 含义 / 调参依据 |
|---|---|---|
| `sat_min` / `val_min` | 100 / 160 | 亮星像素的饱和度/亮度下限。`val_min` ≥150 才能排除关卡名底下的深色圆盘装饰 |
| `lit_pixels` | 15 | 判完成的亮像素阈值。当期活动亮星 ≈120+，1987 的细四角星仅 ≈27-62，灰星恒 ≈0，故取 15 跨活动通用 |
| `zone_pad_left/top`、`zone_extra_w/h` | 5/30/115/20 | 星标搜索区相对编号框的扩展（星标在编号右侧同行） |
| `stage_box_*` | 见 schema | 编号 token 的位置/尺寸过滤 |
| `multi_*`、`difficulty_*`、`marker_*` | 见 schema | 三难度关卡的红色标记检测与分段判定 |
| `sig_pos_quant` | 50 | 滑到头编号签名的位置量化粒度 |
| `unchanged_limit` | 3 | 连续多少次滑动签名不变视为到头 |

**滑到头判定**（1987 实测教训）：用底部编号签名（编号集合 + 量化位置）连续
`unchanged_limit` 次不变判到头；编号为空（章节交界处）不计数也不重置。
**不能用画面哈希**——1987 等活动的星空背景有持续动画，静止画面的哈希也不稳定。

### ATTrailAnalyze（小径五态）

| query | 语义 | 命中返回 |
|---|---|---|
| orange | 任务点橙色交互框（文案不定，统一点击） | box=`orange_click_box` |
| reading | 米白阅读面板（点面板外关闭） | box=`read_close_box` |
| dialogue | 对话场景（非地图 + 大面积暗，连续两帧确认） | box=`dialog_click_box`（右下空白，避开气泡） |
| task | 地图页小径列表最上面的任务项 | box=任务项 OCR 框 |
| done | 列表空（或剩余项反复点击无响应） | box=[0,0,0,0] |

参数全集见 schema（26 项）：橙框颜色掩码 `orange_*`、面板判定 `cream_*`/`read_*`、
对话判定 `dark_v_max`/`dialog_*`、列表过滤 `item_*` 等。
小径每期差异较大（用户决策：不强求通用），失效时停在超时兜底即可。

## 换期体检流程

1. **直接跑**：新活动地图页启动任务。大多数情况零修改可用（识别全部基于
   OCR 文本 + 像素统计，已在「灰与砂的巨木」「1987宇宙组曲」两期验证）
2. **失效时采样诊断**：MaaMCP 截图 → OCR 拿编号 box → 跑取样脚本统计亮/灰星
   像素 → 对照失效模式表定位参数
3. **修复 = 写 JSON**：把差异参数写进对应节点的 `custom_recognition_param`
   （或调整辅助 OCR 节点 ROI），不改 Python
4. **回验**：对两期历史截图样本回跑判定（确认不退化）+ 实机全流程

### 取样脚本

```python
# 输出指定编号框邻域的亮像素数：灰星应 ≈0，亮星应明显高于 lit_pixels
import numpy as np
from PIL import Image

SAT_MIN, VAL_MIN = 100, 160
PAD_LEFT, PAD_TOP, EXTRA_W, EXTRA_H = 5, 30, 115, 20

img = np.asarray(Image.open(r"截图路径.png").convert("RGB")).astype(np.int32)
box = [400, 547, 44, 35]  # 编号 token 的 [x, y, w, h]，替换为实际 OCR 结果

h_img, w_img = img.shape[:2]
x0, y0 = max(box[0] - PAD_LEFT, 0), max(box[1] - PAD_TOP, 0)
x1 = min(box[0] + box[2] + EXTRA_W, w_img)
y1 = min(box[1] + box[3] + EXTRA_H, h_img)
c = img[y0:y1, x0:x1]
v = c.max(axis=2)
s = (v - c.min(axis=2)) * 255 // np.maximum(v, 1)
print("亮像素数:", int(((v >= VAL_MIN) & (s >= SAT_MIN)).sum()))
```

### 失效模式对照表

| 现象 | 原因 | 修法（写 JSON） |
|---|---|---|
| 无任何关卡识别，直接滑动/超时 | 底部条位置变，OCR 不到编号 | 调 `APStageNumberOCR` ROI 与 `stage_box_*` |
| 已完成关被判未完成（反复进已通关卡） | 星标偏移/饱和度变 | 先调 `zone_*` 对准星标位置，再按取样调 `lit_pixels`/`sat_min`/`val_min` |
| 未完成关被判完成（跳关） | 邻域混入高饱和装饰 | 提高 `val_min` 或 `lit_pixels`，必要时收窄 `zone_*` |
| 滑动确认中断超时 | 模式标签位置超出锚点 ROI | 调 `APExploreAnchorOCR` ROI（当前 [20,60,220,260] 已覆盖单按钮与双按钮两种布局） |
| 滑个不停不判到头 | 编号签名异常（如 OCR 不稳） | 查 `APStageNumberOCR`；勿改回画面哈希（动态背景下不可用） |
| 三难度判定错乱 | 难度标记颜色/布局变 | 调 `marker_*` 颜色掩码与 `multi_*` |

## 活动入口导航（已自动化）

入口分**两条路径**，由任务选项「选择活动」决定：

**当期活动**（case「当期活动」）：主页 → 点「入场」上方的**版本名标题区**
（固定位置 [966,226,184,42]，文字每期变化故按位置点击不依赖文案）→ 当期活动
入口界面 → 点右侧「步入剧情」→ 当期活动关卡地图。专用节点
`AP_NavCurrentEntry` / `AP_NavStoryEnter` 默认禁用，由该 case 启用。

**历史活动/主线**（其余 20 个 case）：走映像页卡片查找，见下文。

到达判定 `AP_NavArrived`（is_stage_map）是两条路径共同的导航出口，且要求
**先离开过地图页再回到地图页**——否则从某张地图页启动导航会在错误的地图上
直接开推。

### 历史活动（映像页）

任务选项「选择活动」默认「当前页面」（手动进入地图页再运行）；选择具体活动名
则全自动导航（`auto_entry.json`，已实测 1987宇宙组曲/唐人街影话端到端通过）：

任意页面 → `ReturnMain` 回主页 →「入场」→ 世纪末尺度页 →「映像」→ 卡片横排
**先回卷到最左**（右滑至标题集合连续不变）→ 逐屏向右查找（慢速短距左滑，
快滑会触发惯性滚动跳屏）→ 点目标卡片（标题子串匹配，含屏幕边缘截断标题的
残缺反向匹配；点击不重置状态，未生效自动重试）→ 详情页「活动正篇/主线正篇」
（OCR 命中后**点击上偏 40px** 落在主按钮上——正篇文字是小字，直接点小字无响应；
按钮位置随活动浮动：唐人街在中下、1987 在右下，ROI [300,400,980,320] 通吃）→
关卡地图页 → 接入三阶段推图。

导航识别器 `APCardFinder`（query=nav/card/rewind/swipe/notfound）依赖辅助节点
`APImagePageOCR`（映像页「显影罐」横幅锚点，防止在地图页/世纪末页误触发滑动）
与 `APCardTitleOCR`（标题行）。新活动入卡片清单 = 在任务选项「选择活动」加一个
case（注入 card_name），多服卡片名差异经资源覆盖层处理。

卡片清单（自最左起，标题即任务选项「选择活动」的 case；全部 20 张已逐卡验证）：
雷米特杯失窃案 / 绿湖噩梦 / 行至摩卢旁卡 / 两人的同谋 / 洞穴的囚徒※ /
复兴！乌卢鲁运动会 / 朔日手记 / 今夜星光灿烂※ / 再见，来亚什基 / 孤独之歌 /
飞驰！明日之城※ / 7号往事 / 忧郁的热带 / 圣火纪行：东区黎明※ /
地球上最后的夜晚 / 唐人街影话 / 疯癫与文明 / 1987宇宙组曲 / 复乐园 /
行于漫漫长路上※（※=主线卡，详情页为「主线正篇」、地图无模式按钮）

## 跨活动实测记录

| 活动 | 结果 | 适配动作 |
|---|---|---|
| 灰与砂的巨木（当期，2026-06） | 全流程通过（01→19 + 小径 12 项 + BOSS） | 基线 |
| 1987宇宙组曲（映像/历史） | 全流程通过（故事→小径空过→切探索→探索推完） | ① 锚点/切换 ROI 放宽至 [20,60,220,260] 覆盖双按钮布局；② `lit_pixels` 40→15（细四角星亮像素仅 27-62）；③ 滑到头判定从画面哈希改为编号签名（星空动画致哈希永不稳定） |
| 唐人街影话（映像/历史） | 识别验证通过（双按钮布局锚点/找关/详情页开始行动/三难度红标均正确） | ① `stage_box_center_x_max` 1160→1240：地图到尽头时末关停在屏幕右缘（21 关 cx=1226），过滤掉会被永久跳过；② stage 增加锚点校验：关卡详情页底部有缩略关卡条，曾被当成地图页反复点击；③ `AP_StartAction` ROI 放宽至 [1000,560,280,160] 并去掉 `only_rec`（详情页按钮位置随活动浮动；only_rec 在宽 ROI 下会把背景文字混入整行识别）；④ 小径列表排除词改为「模式」：双按钮布局的模式按钮落在列表区，曾被当成任务项点击 |
| 雷米特杯失窃案 / 绿湖噩梦 / 行至摩卢旁卡 / 复兴！乌卢鲁运动会 / 朔日手记 / 两人的同谋 / 再见，来亚什基 / 孤独之歌 / 7号往事 / 忧郁的热带 / 地球上最后的夜晚 / 疯癫与文明 / 复乐园（映像/历史活动） | 导航+地图页识别验证全部通过（is_map ✓，均为双按钮布局） | 共性修复见上表与导航章节（PV 链/双帧确认/三档偏移） |
| 洞穴的囚徒 / 今夜星光灿烂 / 飞驰！明日之城 / 圣火纪行：东区黎明 / 行于漫漫长路上（映像/历史，**主线卡**） | 详情页为「主线正篇」，主线地图**无模式按钮**——锚点经 is_stage_map 备选判定（底部编号条 + 无开始行动按钮）全部通过 | 主线地图判定已通用化；早期误点相邻卡片由双帧位置确认修复 |

> [!NOTE]
>
> 历史活动适配采用**识别验证模式**：用离线截图逐节点跑 `run_recognition`
> 确认命中/不命中符合预期即可，不真实点击进关（任务本就全部完成，无需重打）。
> 验证脚本模式：post_task 一个挂自定义 action 的入口节点，在 action 内对
> 截图调 `context.run_recognition(节点名, image)`。

## 验收清单

1. 识别单测：harness 对地图页跑 query=stage，未完成关识别正确且已完成关不误报
2. 首关端到端：进关 → 战斗/剧情 → 结算 → 回地图
3. 任意进度重启：中途停止再启动无缝继续
4. 正常收尾：`AP_AllDone` → 小径 → 探索 → `AP_AllPhasesDone`，而非超时报错
5. 兜底验证：未知界面优雅停止，`debug/on_error/` 有框架自动保存的现场截图
6. `python -m pytest tests/` 全绿（含 schema 防漂移）

## 工具资产索引

- **实机踩点**：MaaMCP（ADB 连接模拟器；Win32 窗口方式截图会黑屏）
- **进程内回归**：stub `maa.agent.agent_server.AgentServer` 后 `Resource.post_bundle` +
  `Tasker.post_task`，无需 GUI
- **出错现场**：框架 SaveOnError 自动存图到 `debug/on_error/`，无需自写截图
- **设计约定**：调度节点 `next` 按优先级排列 + `[JumpBack]` 兜底；自定义识别用
  `query` 多态；公共节点（`CheckStopping`/`Confirm`/`ObtainedAwards`/`ClickBlank`/
  `EatCandyPage`）直接引用；三阶段由 `APPhaseGate` 串联，任务选项经 `enabled` 开关
