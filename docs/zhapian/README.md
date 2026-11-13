# 魔精诈唬牌 · 状态判定证据

坐标基准：MaaFW **720p（1280×720）**。以下每张截图均先 resize 到 720p 再跑 `detect()`，
数值为实测（MuMu 模拟器 1920×1080 画面缩放而来）。

| 状态 | 判定依据 | 实测值 | 阈值 | 截图 |
|---|---|---|---|---|
| claim（出牌） | 手牌张数 ≥ 5 | hand = 5 | ≥ 5 | `claim.jpg` |
| adjudicate（判定） | 信任/质疑按钮金色像素计数 | trust = 137，doubt = 113 | > 90 | `adjudicate.jpg` |
| gameover（结算） | 全局暗度 + 无结果横幅 | dark = 0.776，banner = 0.20 | dark > 0.5 且 banner < 0.25 且 hand ≤ 1 | `gameover.jpg` |
| start（开始页） | 「开始游戏」按钮宽松金色计数 | start_gold = 2215 | > 1200 | `start.jpg` |
| reveal（诈唬结果横幅） | 中部红/金横幅占比 | banner = 0.28 | > 0.25 | `reveal.jpg` |

## 关键说明

1. **「确认出牌」按钮不是金色**：实测 `CONFIRM_BOX` 平均色 RGB ≈ (161, 150, 114)，
   达不到金色判据（R > 190）。因此 `has_confirm`（金色计数）在真实出牌页恒为 0，
   claim 状态实际由「手牌 ≥ 5」承担；点击「确认出牌」坐标是标定得到的，不是靠金色判据。
2. **gameover 必须先于 adjudicate 判定**：结算页顶部的金色横幅会落入信任框
   （实测 gold_trust = 1657，远超阈值 90），若先判 adjudicate 会把结算页误判成判定页。
   `detect()` 里 gameover 分支在最前，正是这个原因。
3. 以上阈值来自这 5 张实机截图与多局对局采样；换客户端版本 / 换设备分辨率后需要重新标定。

## 文件

- `claim.jpg` / `adjudicate.jpg` / `gameover.jpg` / `start.jpg` / `reveal.jpg`：各状态截图
  （1280×720，已压缩）。
