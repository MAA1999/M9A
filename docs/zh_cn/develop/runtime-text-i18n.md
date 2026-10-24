---
order: 10
icon: mdi:translate-variant
---

# 运行时文本国际化

M9A 的文本分两层：**界面文案**（任务名、选项、说明等，走 Project Interface V2 的 `$key` 机制，见[界面本地化](./i18n.md)）与**运行时文本**（任务执行过程中和游戏交互时出现的文本）。本文档是后者的总参考。

运行时文本按出现位置分四类，各自走不同的机制：

| 位置                    | 内容                               | 机制                         | 状态                                        |
| ----------------------- | ---------------------------------- | ---------------------------- | ------------------------------------------- |
| pipeline `focus`        | 节点通知/toast：任务进度与失败提示 | PI `$key` → `locales/*.json` | 已落地                                      |
| pipeline OCR `expected` | 识别游戏内文字                     | 简中书写 + 映射表展开        | 已落地                                      |
| 物品名数据              | `data/combat/items.json`           | 五语 `names` 随数据提交      | 部分落地                                    |
| agent 日志              | Python agent 的过程输出            | loguru 直出                  | **刻意不做**，见[下文](#agent-文案刻意不做) |

共同点：MaaFW 运行时只加载一份 pipeline，识别与显示是否正确取决于文本能否匹配/表达当前语言的内容，所以翻译不靠复制多份资源，而是各层就地解决。

## Focus 消息

pipeline 节点的 `focus` 字段是用户在客户端通知面板看到的第一手反馈（任务进度、失败原因与自救指引）。MaaFW PI v2 对 focus 模板支持 `$key` 解析——简写字符串与对象形态的 `content` 都支持：

```json
"Start1999Error": {
    "focus": {
        "Node.Action.Starting": "$Focus.Start1999Error"
    }
},
"CUB_LackOfMaterial": {
    "focus": {
        "Node.Recognition.True": {
            "content": "$Focus.CUB_LackOfMaterial",
            "display": ["log", "toast"]
        }
    }
}
```

规范：

- focus 文案一律写 `$Focus.<节点名>`；同一节点有多个事件时追加事件后缀区分；
- `<span>` 等展示标记放进 locale 值，不留在 pipeline；
- `tools/validate-i18n.mjs` 扫描全部 `resource/*/pipeline` 的 focus：出现非 `$key` 的中文直接报错，键缺失/孤儿键走与界面文案同一套校验。

## 翻译数据随仓库维护

OCR `expected` 的多语言方案：pipeline 保持单一版本，用工具把简中 `expected` 原地展开为五语数组（CN/TC/EN/JP/KR），不复制多份 pipeline，也不在 overlay 里逐语言重写识别字段。

展开依赖的翻译数据**全部随本仓库维护**，不依赖任何外部数据源：

- 展开所需的「简中 → 其他四语」映射表与展开后的五语 `expected` 都**提交在本仓库**；
- 映射表手工可编辑：修正译文、补充新文案都是普通 PR；
- 游戏版本更新带来新文本、出现同词异译或版本改名时，由维护者负责核对并补充映射表（见[版本更新维护清单](#版本更新维护清单)）。

也就是说，日常维护对普通贡献者是自洽的：改映射表或跑工具即可，`pnpm check` 保证 pipeline 与映射表的一致性。

## 数据契约：OCR 文本映射表

`tools/i18n/ocr_text.json` 是识别文本的唯一翻译数据源，手工可编辑。它只服务开发期的维护工具与校验，agent 运行时不读取，因此放在 `tools/` 下、不随发布包分发——与 `data/`（随包分发的运行时数据，如物品名）划清边界：

```json
{
    "texts": {
        "确认": {"tw": "確認", "en": [
                "Confirm",
                "Exit"
            ], "jp": "決定", "kr": "확인"},
        "显影罐": {"tw": "顯影罐", "en": "Penumbra Can", "jp": "現像液缶", "kr": "현상 탱크"}
    },
    "node_overrides": {
        "8bitLevelEntry": {"zh": "进入", "tw": "進入", "en": "Enter", "jp": "始める", "kr": "진입"}
    },
    "untranslatable": [
        "^挂载$",
        "售",
        "市场(.*| 雏)形"
    ],
    "excluded_keys": ["language_90011687"]
}
```

- `texts` 以简中原文（换行与空白归一化后）为键，值为 tw/en/jp/kr 四语；简中即键本身，不重复存储；
- 每种语言的值可以是字符串，也可以是**候选数组**——同一简中文本在游戏里有多个官方译法时全部列入（如「确认」的 en 同时有 Confirm / Exit），MaaFW 命中数组任一项即可，歧义由此天然消解；
- 同一简中文本在特定节点语境下需要收窄译法时，在 `node_overrides` 按节点名覆盖整行（值可以是单行或行数组），优先级高于 `texts`。上方 `8bitLevelEntry` 条目仅演示格式，当前仓库中 `node_overrides` 为空——「进入」的全局行已覆盖该场景；
- 英文存**纯文本**；`(?i)` 忽略大小写、词间空格放宽为 `\s*` 的正则化由工具在展开时统一生成；所有映射值写入 expected 前都会做正则转义（MaaFW 按 regex 校验/匹配 expected 项）；
- `untranslatable` 是刻意保留单语的文本：正则片段（`^挂载$`）、截断单字（「售」）等反查不回整句的项，此处显式登记，check 不再要求可展开；
- `excluded_keys` 是 key 级排除：官方文本表里偶有 dev 残留行（如实测的 `language_90011687`，简中「未解锁」对应的四语是 `uuuuer`/`iagoMBZ` 之类），其值会作为候选混入反查结果；把 key 登记在此处后，同步工具构建反查索引时整体剔除，且历史脏候选在合并时被识别丢弃——手工删候选是压不住下次同步的，必须在这里排除；
- 修正某语言的译文直接改表走普通 PR，无需任何特殊流程。

## 同步工具

工具在 `tools/i18n/sync-ocr.mjs`，消费上面的映射表：

```bash
node tools/i18n/sync-ocr.mjs            # 按映射原地展开/重写 base pipeline 的 OCR expected
node tools/i18n/sync-ocr.mjs --check    # dry-run 校验，已接入 pnpm check（check:ocr）
```

- **expand**：JSONC 感知的原位替换——注释与排版保留；重复运行幂等；
- **check**：expected 与映射展开结果不一致、或出现映射之外且未登记的简中文本时直接失败。

### 判定与写回规则

- OCR 节点判定：`recognition == "OCR"` 或 `recognition.type == "OCR"`；Or/And 复合识别的 `any_of`/`all_of` 子识别（含嵌套）同样纳入；
- `expected` 取值位置依次为 `recognition.param.expected` → `recognition.expected` → 节点级 `expected`；字符串与字符串数组都接受，写回统一展开为数组；
- 按映射展开五语；跨语种相同文本去重，缺失语种跳过；
- 写回时在数组上方保留一行 `// @i18n-src: ["原文", ...]` 注释，固化作者的原始意图：重跑时从注释重建，映射变更后旧的展开产物不会残留；
- 作者手写的非映射项（正则、数字等）原样保留在数组中。

### ROI 扩宽

五语中最长显示宽度超过原文时，工具按比例扩宽识别区域：不修改 `roi`，而是把 `roi_offset` 右边距补足到「基准宽 × 五语/简中宽度比」（MaaFW 语义），并以 720p 基准屏宽 1280 截断；`roi` 为节点引用时，编辑只落在引用方自己的 `roi_offset` 上，不碰被引用节点。扩宽对 `only_rec` 节点一视同仁——数值读取类节点（`5/5` 这类 expected）不产生翻译展开，天然不受影响；文本 flag 节点漏扩会在宽语言客户端被裁切，比扩宽引入的误匹配风险更确定。无 `roi` 的节点跳过此步。扩宽以「不足则补足」保证幂等：右边距已达计算值时不再变动，roi 引用链上的联动扩宽由工具内部循环到不动点。

### `@i18n-skip` 逃生口

确需保留正则/片段形态、不参与翻译的节点，在 `expected` 数组内部写注释跳过：

```json
"expected": [
    // @i18n-skip 截断匹配，整句反查无意义
    "^售"
],
```

注释须写在数组括号以内；命中后整个节点不再被工具触碰，check 也不再要求其可展开。

## 物品名五语

`data/combat/items.json` 以五语 `names` 直接提交（数十种材料的短名，随发布包分发）。新增物品、版本改名核对由维护者负责，以普通 PR 合入；新增物品时保持既有品质分组与排序。

## 编写规范

新增或修改 pipeline 时：

- OCR `expected` 默认写**完整的简中文本**，由工具按映射展开，不要手写五语数组；
- 只有确需正则/片段时才加 `@i18n-skip`，并在注释里说明保留原因；
- focus 文案一律 `$Focus.<节点名>`，并在 `locales/*.json` 补齐所有已声明语言；
- 不要在外服 overlay 里写单语 `expected` 或单语 focus——它会覆盖回单语，破坏 base 的多语数组；
- 映射表里没有的新文本，先补映射再跑展开，check 会拦截遗漏；
- 生成型 pipeline（`tools/pipeline-generate/`）在生成器内维护五语 `names` 映射，直接烘焙多语 `expected`，并对缺翻译直接报错。

## 与外服 overlay 的分工

base 展开后，`resource/global_*/pipeline` 与 `resource/tw/pipeline` 只保留**与语言无关的区域差异**：启动包名、入口 action、渠道资源选择等。识别字段与 focus 一律不进 overlay。

## 版本更新维护清单

游戏版本更新、出现新界面文本时：

1. **维护者**：核对并补充映射表（新文案的五语译文、同词异译裁决、版本改名核对），提交映射 diff；
2. **所有贡献者**：跑 expand 写回 pipeline，review diff；
3. 新物品名合回 `items.json`；
4. `pnpm check` 与 `pnpm check:py` 通过后随版本适配 PR 提交。

## Agent 文案：刻意不做

Agent 内 i18n 在技术上没有障碍——MaaFW PI v2 启动 agent 时会注入 `PI_CLIENT_LANGUAGE` 环境变量，配合 `locales/<lang>/agent.json` 命名空间扩展（见[界面本地化](./i18n.md)）即可支撑。M9A 评估后决定**不做**这一层：

- M9A agent 的 354 条消息全部走 logger（日志面板），以过程诊断为主（其中 122 条是 debug 级），主 UX 文案在 focus 与 pipeline 里；
- 日志的主要读者是排查问题的维护者，中文原文更利于排障；外服用户反馈问题时贴的也正是原文；
- 全量翻译 354 条 × 4 语 ≈ 1400 个翻译单元的持续维护成本，与收益不成比例。

重新评估的时机：当 agent 需要主动向用户推送消息时（如把战况/结果汇总以 toast 呈现——Python binding 可以构造带 focus 的临时节点实现），为**这批新文案**接入 `PI_CLIENT_LANGUAGE`（`agent/utils/pienv.py` 已定义该常量）与 `locales/<lang>/agent.json` 命名空间，而不是回填存量日志。

## 边界与已知限制

- 模板图与 ROI 初值仍需模拟器实拍（1280x720 基准），工具只在已有 ROI 上扩宽；
- 映射表只收录出现过的文本；新文本在补充映射之前会被 check 拦截，属于预期行为；
- 掉落概率等服务端权威数据不在范围内，映射与物品名只覆盖名称与声明性数据；
- 映射表的语境消歧（同词异译）由维护者在更新映射表时裁决，贡献者发现译文与实际界面不符时，优先用 `node_overrides` 修正。

## 落地状态

- **focus 消息**：已落地（33 条 `$Focus.*`，校验已接入 `pnpm check`）；
- **OCR 映射表与同步工具**：已落地（275 条映射、71 条 untranslatable 登记项；536 个 OCR 节点中 376 个已展开五语，其余为无需翻译的正则/片段；`check:ocr` 已接入 `pnpm check`）。
