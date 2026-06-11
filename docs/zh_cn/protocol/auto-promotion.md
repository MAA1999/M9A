---
order: 5
icon: ri:route-line
---

# 活动推图适配协议

> [!TIP]
>
> 本文档是「(测试中)活动推图v2」（AutoPromotion + AutoTrail）的换期适配协议：
> 新活动上线后，按本协议逐项体检识别参数、校准失效项、跑完验收清单，即完成适配。
> 协议面向 AI 执行设计——把本文档交给具备模拟器控制能力（如 MaaMCP）的 AI，
> 说"按协议适配新活动"即可开工。

## 功能架构速览

| 文件 | 内容 |
|---|---|
| `assets/resource/base/pipeline/activity/auto_promotion.json` | 推图状态机，入口 `AutoPromotion`，完成后衔接 `AutoTrail` |
| `assets/resource/base/pipeline/activity/auto_trail.json` | 小径状态机，入口 `AutoTrail` |
| `agent/custom/reco/auto_promotion.py` | `APMapAnalyze`：找关卡 + 星标判定 + 滑动到头（本协议核心） |
| `agent/custom/reco/auto_trail.py` | `ATTrailAnalyze`：小径五态识别 |
| `assets/resource/tasks/AutoPromotion.json` | 任务声明 + 吃糖 WaitReplay override |

设计原则：所有识别基于 OCR 文本 + 像素统计（饱和度/亮度/网格哈希），不依赖模板图和精确颜色，
目标是换活动零配置。当某期活动 UI 变化超出参数容差时，按本协议校准而非重写。

## 核心：关卡发现与星标识别校准

> [!IMPORTANT]
>
> 这是历期适配中**最可能失效、必须每期体检**的部分。其余识别点（对话框、阅读面板、
> 制衡模式文案、底部条位置）历期稳定，做快速确认即可。

### 识别原理

1. **找关卡**：OCR 地图底部条（`APStageNumberOCR`，ROI `[81,538,1130,87]`）找 1-2 位数字 token，
   正则容忍 OCR 把右侧星标误读进来（如 `"01/3"`、`"A1333"`）
2. **星标判定**：取编号框右侧邻域，统计「高饱和且高亮」像素数。亮星不管被调成金/橙/红都高饱和，
   灰星（未完成）本质是低饱和——这就是不依赖具体颜色的原因
3. **三难度关卡**：编号左侧有红色难度标记 → 切三段星标区分组判定，任一段有亮星即该难度已过

### 参数表（`agent/custom/reco/auto_promotion.py` 的 `APMapAnalyze` 类常量）

| 参数 | 当前值 | 含义 | 校准依据 |
|---|---|---|---|
| `SAT_MIN` | 100 | 亮星像素饱和度下限（0-255） | 实测灰星邻域高饱和亮像素=0，亮星≈120-220 |
| `VAL_MIN` | 160 | 亮星像素亮度下限 | 必须 ≥150，否则关卡名底下的墨绿圆盘装饰会误判 |
| `LIT_PIXELS` | 40 | 判定「已完成」的亮像素数阈值 | 取灰星(0)与亮星(120+)的中间偏下 |
| `ZONE_PAD_LEFT/TOP` | 5 / 30 | 星标搜索区相对编号框的扩展 | 星标位于编号右侧约 30-90px 同行 |
| `ZONE_EXTRA_W/H` | 115 / 20 | 同上 | |
| `STAGE_BOX_*` | 见源码 | 编号 token 的位置/尺寸过滤 | 排除边缘 UI 和装饰误读 |
| `MULTI_*` / `DIFFICULTY_*` | 见源码 | 三难度关卡的标记检测与分段判定 | |

### 体检流程（每期必做）

1. **采样**：连接模拟器进入新活动地图页，截取至少 3 类画面——
   已完成关（亮星）、未完成关（灰星）、三难度关（若有）。注意截图工具的目录会轮换清理，及时另存
2. **定位**：OCR 全屏确认底部条编号 token 的 box 坐标（验证 `APStageNumberOCR` ROI 仍覆盖、
   `STAGE_BOX_*` 过滤仍命中）
3. **统计**：对每个编号框跑下方取样脚本，记录亮/灰关卡的像素计数
4. **判定**：灰星计数应 ≈0，亮星计数应 ≥80 且与 `LIT_PIXELS=40` 有 2 倍以上余量。
   余量不足则按「失效模式对照表」调参
5. **单测**：进程内 harness 跑识别（只识别不点击），确认返回的是第一个未完成关的点击区

### 取样脚本

```python
# 用法：替换截图路径与编号框 box（来自 OCR 结果），输出该关卡星标区亮像素数
import numpy as np
from PIL import Image

SAT_MIN, VAL_MIN = 100, 160
PAD_LEFT, PAD_TOP, EXTRA_W, EXTRA_H = 5, 30, 115, 20

img = np.asarray(Image.open(r"截图路径.png").convert("RGB")).astype(np.int32)
box = [60, 547, 90, 35]  # 编号 token 的 [x, y, w, h]，替换为实际 OCR 结果

h_img, w_img = img.shape[:2]
x0, y0 = max(box[0] - PAD_LEFT, 0), max(box[1] - PAD_TOP, 0)
x1 = min(box[0] + box[2] + EXTRA_W, w_img)
y1 = min(box[1] + box[3] + EXTRA_H, h_img)
c = img[y0:y1, x0:x1]
v = c.max(axis=2)
s = (v - c.min(axis=2)) * 255 // np.maximum(v, 1)
print("亮像素数:", int(((v >= VAL_MIN) & (s >= SAT_MIN)).sum()))
# 灰星应 ≈0，亮星应 ≥80；介于两者之间说明阈值需要重新校准
```

### 失效模式对照表

| 现象 | 原因 | 修法 |
|---|---|---|
| 日志无任何关卡识别，直接滑动/超时 | 底部条位置变了，OCR 不到编号 | 重踩底部条位置，调 `APStageNumberOCR` ROI 与 `STAGE_BOX_*` |
| 已完成关被判未完成（反复进已通关卡） | 星标偏移变了 / 新星标饱和度变低 | 重采样：先确认星标相对编号的位置（调 `ZONE_*`），再看亮星计数（调 `SAT_MIN`/`VAL_MIN`） |
| 未完成关被判完成（跳关） | 邻域混入新的高饱和装饰 | 提高 `VAL_MIN` 或 `LIT_PIXELS`，必要时收窄 `ZONE_*` |
| 三难度关判定错乱 | 难度标记颜色/布局变了 | 重采样难度标记区，调 `_looks_multi_difficulty` 的颜色条件与 `MULTI_*` |

## 其他识别点快速体检清单

历期稳定，每期只需逐项截图确认，不必重新取样：

| 识别点 | 特征与当前参数 | 失效表现 | 修法 |
|---|---|---|---|
| 地图页锚点 | 左上「探索模式/故事模式」标签，ROI `[30,70,190,80]` | 滑动确认中断超时 | 调 ROI 或 expected |
| 小径橙色交互框 | ROI `[730,295,180,100]` 橙像素 ≥2000（实测有框 6400+/无框 0） | 小径任务点开后不点交互框 | 若官方换框色，改 `_orange_pixels` 颜色条件 |
| 阅读面板 | 中央 `[400,250,480,200]` 米白占比 ≥0.5（实测 0.83 vs ≤0.03） | 面板不关闭直到超时 | 调 `READ_*` |
| 对话场景 | 非地图页 + 全屏暗像素占比 ≥0.75；点击位右下 `[1100,620,80,40]` | 对话不推进 | 确认点击位是空白（气泡会堆满屏幕中部，勿点中部） |
| BOSS 制衡模式 | OCR 正文「制衡模式」ROI `[60,20,520,440]`（大标题是艺术字读不出） | BOSS 介绍页超时而非优雅结束 | 历期文案一致，几乎不会变 |
| 战斗中标志 | `AP_FlagInCombat` 模板匹配右上角快进图标 | 战斗中调度超时 | 模板图加变体（参考 SOD_Combating_1.png 先例） |

## 验收清单（全部通过才算适配完成）

1. **识别单测**：进程内 harness 对地图页跑 `APMapAnalyze` query=stage，返回第一个未完成关且不误判
2. **首关端到端**：从第 1 关推到第 2 关（进关→战斗/剧情→结算→回地图）
3. **任意进度重启**：推图中途停止再启动，从当前进度无缝继续
4. **正常收尾**：全部完成后走 `AP_AllDone`（绿色提示）→ 衔接小径 → `AT_AllDone`，而非超时报错
5. **兜底验证**：遇到未知界面（如该期新小游戏）时优雅停止，`debug/on_error/` 有框架自动保存的现场截图

## 工具资产索引

- **实机踩点**：MaaMCP（ADB 连接模拟器，截图 + OCR + 点击/滑动）。模拟器必须用 ADB 方式连接，
  Win32 窗口方式截图会黑屏
- **进程内回归**：stub `maa.agent.agent_server.AgentServer` 后直接 `Resource.post_bundle` +
  `Tasker.post_task`，无需启动 GUI 即可跑任务与单测识别（harness 写法见
  `docs/zh_cn/develop/development.md` 或向维护者索取既有脚本）
- **出错现场**：MaaFramework 全局选项 SaveOnError 在任务出错时自动把当时帧存到
  `debug/on_error/`（带任务名+时间戳），无需自写截图逻辑
- **设计约定**：调度节点 `next` 按优先级排列 + `[JumpBack]` 兜底弹窗；自定义识别用
  `query` 参数多态复用一个类；公共节点（`CheckStopping`/`Confirm`/`ObtainedAwards`/
  `ClickBlank`/`EatCandyPage`）直接引用，不要复制。三阶段（故事/小径/探索）由
  `APPhaseGate` 闸门串联，任务选项通过 `enabled` 开关各阶段
