"""微尘 / 利齿子儿补足任务：数量不足时刷「尘埃运动」/「铸币美学」。

## 需求

一个**独立**任务：大部分复刻「常规作战」（`Combat`），但先 OCR 读出当前的
**利齿子儿**（203）与**微尘**（205）数量，少于设定阈值就刷对应的资源关卡：

- 微尘不足 → 刷 `LP-06`（尘埃运动 06，每局固定 12500 微尘）
- 利齿子儿不足 → 刷 `MA-06`（铸币美学 06，每局固定 9000 利齿子儿）

## 复用了源码的什么

**数量读取**：直接复用 `depot_maintain.DepotCurrencyRead`（`DepotCurrencyInspect` 入口）。
它已经实现了：进角色升级面板 → 识别右上角微尘/利齿子儿计数 → 合并进仓库快照。
对应 pipeline 节点 `CI_DustNumber` / `CI_CoinNumber`，解析器 `parse_abbreviated_number`
处理游戏里的 K/M 缩写值。**没有重新实现 OCR。**

**刷关**：复用 `Combat` 任务链（`resource/base/pipeline/combat.json` 的
`Combat` → `DisableUpload` → `SelectCombatStage` → 关卡导航 → `AllIn` 复现），
只是把 `SelectCombatStage` 的关卡改成 `LP-06` / `MA-06`、难度改成 `None`。
**没有重新实现进入副本的逻辑。**

**仓库快照**：数量读数落在 `config/warehouse_inventory.json`（按账号分桶），
与「库存保持」共用同一份数据，所以两个任务不会互相打架。

## 判断依据

- 微尘/利齿子儿**不在仓库页**，只在角色升级面板右上角显示 —— 这是源码
  `docs/zh_cn/develop/depot-catalog.md`「微尘 / 利齿子儿（角色升级页读数）」一节写明的。
- 两个货币的刷取关卡与每局掉落量取自材料目录 `data/combat/balanced_farming.json`：
  `205`（微尘）→ `LP-06`，`per_run: 12500`；`203`（利齿子儿）→ `MA-06`，`per_run: 9000`。
- 关卡族注册表 `material_catalog.STAGE_FAMILIES` 里 `LP`=尘埃运动、`MA`=铸币美学，
  且 `LP` 有入口模板 `Combat/ResourceChapter_LPEnter.png`（`MA` 用 OCR 识别「铸币/美学」）。

## 本任务的边界（用户明确要求）

- **与均衡刷材料完全独立**：自己的开关、自己的 GUI 阈值、自己的关卡；两个任务互不影响。
- **开关默认关闭**：GUI 上「补足微尘」「补足利齿子儿」默认都是关；关掉就不刷那个货币。
- **阈值是触发线不是目标值**：当前数量 **低于** 阈值才刷；**等于或高于**都不刷。
- **只用本轮有效读数**：缺读数的那个货币**不参与判断**，绝不用快照里的旧值决定刷不刷。
- **触发后一路刷到底**：选好资源关卡就沿原常规作战刷完当天体力，然后正常结束；
  **不回头重查阈值、不重复进零体力作战**。
"""

from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger
from utils.params import parse_params

# 相对导入：agent.custom.* 与 custom.* 是两张模块图，跨图导入会重复注册自定义动作
from .depot_maintain import parse_abbreviated_number

# 微尘 / 利齿子儿的材料 id（取自 data/combat/balanced_farming.json）
DUST_ITEM_ID = "205"
COIN_ITEM_ID = "203"

# 两种货币的固定处理顺序（用于「两个都缺时选哪个」的确定性规则）：
# 微尘在前（id 205），利齿子儿在后（id 203）。
_CURRENCY_ORDER = {DUST_ITEM_ID: 0, COIN_ITEM_ID: 1}

# 各自的最优刷取关卡与每局掉落量（取自材料目录，不另造数据）
DUST_STAGE = "LP-06"
DUST_PER_RUN = 12500
COIN_STAGE = "MA-06"
COIN_PER_RUN = 9000

# 默认阈值（低于该值就刷）。数值取自材料目录里「拉满一名 6★」的用量，
# 与「库存保持」的默认值一致（微尘 1352100 / 利齿子儿 1616830）。
DUST_DEFAULT_THRESHOLD = 1352100
COIN_DEFAULT_THRESHOLD = 1616830

# 复现次数上限：114514 = 「常规作战」的默认复现次数（all_in.json 的 AllIn 节点）。
# TargetCountDetermine 按剩余体力算复现次数、吃糖补体，体力用完才结束 ——
# 即「把当天体力刷完」。
UNLIMITED_RUNS = 114514

# 角色页读数入口（复用 depot_maintain 的既有节点）
CURRENCY_SCAN_ENTRY = "DepotCurrencyInspect"
# 刷关入口（常规作战的入口）
COMBAT_ENTRY_NODE = "Combat"
SELECT_STAGE_NODE = "SelectCombatStage"
# 关卡导航的 pipeline 节点
ALL_IN_NODE = "AllIn"
# 战斗计数初始化节点（清零本轮计数）
TARGET_COUNT_INIT_NODE = "TargetCountInit"


class _CurrencyTaskState:
    """任务内状态：本次要刷的货币与触发阈值。"""

    item_id: str | None = None
    item_name: str = ""
    stage: str = ""
    per_run: int = 1
    current: int = 0
    target: int = 0
    rounds: int = 0
    # 本轮覆写的 `TargetCountFinish.next`（刷完体力后去哪里）。
    # 记下来是为了让测试能断言「不回到 CT_Plan 重查阈值」——
    # 这条是需求明确要求的，不能靠「反正会结束」蒙混过去。
    target_count_finish_next: list[str] = []


_state = _CurrencyTaskState()

# 本轮生效的触发阈值（GUI 传入；缺省用上面的默认值）。
# 用小写名：这是**会变的运行时状态**，不是常量（大写名会被 pyright 当成常量而禁止重新赋值）。
dust_threshold = DUST_DEFAULT_THRESHOLD
coin_threshold = COIN_DEFAULT_THRESHOLD


def reset_currency_state() -> None:
    """重置任务状态。"""
    _state.item_id = None
    _state.item_name = ""
    _state.stage = ""
    _state.per_run = 1
    _state.current = 0
    _state.target = 0
    _state.rounds = 0
    _state.target_count_finish_next = []


@AgentServer.custom_action("CurrencyTopUpInit")
class CurrencyTopUpInit(CustomAction):
    """任务入口：重置状态。

    **不覆写 `CT_Plan` 的 attach** —— GUI 的「补足微尘 / 补足利齿子儿」开关与
    「微尘阈值 / 利齿子儿阈值」是通过 `CT_Plan.attach` 传进来的，
    入口再写一遍会把 GUI 的配置盖掉（用户明确要求：GUI 开关与阈值继续有效）。

    参数格式（可选，缺省时读 attach）：
    {
        "dust_threshold": 1352100,  # 微尘阈值（低于就刷）
        "coin_threshold": 1616830,  # 利齿子儿阈值（低于就刷）
        "dust_enabled": true,       # 是否补微尘
        "coin_enabled": true        # 是否补利齿子儿
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        parse_params(argv.custom_action_param)
        reset_currency_state()

        # 抬 `ReturnMain` 的命中上限。
        # `startup.json` 里它是 2，而命中计数在**整个顶层任务内累计**（`run_task` 子任务
        # 共享同一个 TaskState，只有 post_task 才清零）。本任务正常流程就要回家两次
        # （`DepotCurrencyRead` 收尾 + `CT_Done` 收尾），正好用满、没有余量；只要多一次
        # （例如从非主界面启动时 `DepotCurrencyNav` 的 `[JumpBack]ReturnMain` 先命中一次），
        # `CT_Done` 的 `ResetReturnMain → ReturnMain` 就会被静默过滤，收尾失败。
        # `DepotMaintainInit` 为同一原因早就在入口抬过（见 `RETURN_MAIN_MAX_HIT`）。
        from .depot_maintain import RETURN_MAIN_MAX_HIT

        context.override_pipeline({"ReturnMain": {"max_hit": RETURN_MAIN_MAX_HIT}})

        logger.info("微尘 / 利齿子儿刷取任务开始")
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("CurrencyTopUpPlan")
class CurrencyTopUpPlan(CustomAction):
    """规划：读当前数量，算缺口，决定刷哪个资源关卡。

    读数来源：复用 `DepotCurrencyInspect`（`DepotCurrencyRead`），它把读数合并进
    `config/warehouse_inventory.json` 的账号桶；本节点再从快照里取。

    **只用本轮有效读数**：`DepotCurrencyRead` 只把**这次真的读到**的货币写进快照，
    读不到的那个保留旧值。这里只认**本轮被刷新过**的那些货币 ——
    旧快照里的值不参与判断（需求：「只用本轮有效读数，不拿缺失项旧快照决定刷取」）。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        params = _plan_params(context)

        # 先读一次数量（复用库存保持的既有读数动作）
        # 读之前声明本轮参与读数的货币：`DepotCurrencyRead` 用它判断「读数是否齐全」，
        # 齐全才刷新 `currency_updated_at`；不声明的话没读到的那个也会盖上新鲜时间戳，
        # 下次任务就会拿旧值当新值用。
        from .depot_maintain import ensure_account_id, set_required_currency

        dust_enabled = _bool_param(params.get("dust_enabled"), False)
        coin_enabled = _bool_param(params.get("coin_enabled"), False)
        required = [DUST_ITEM_ID] if dust_enabled else []
        if coin_enabled:
            required.append(COIN_ITEM_ID)
        set_required_currency(required)

        if not required:
            logger.info("微尘 / 利齿子儿刷取的开关都关着，本次不刷取")
            context.override_next("CT_Plan", ["CT_Done"])
            return CustomAction.RunResult(success=True)

        # ⚠️ 读账号必须在读数**之前**。
        # `DepotCurrencyRead` 的顺序是「先写快照、再 run_task(HOME_ENTRY)」：写盘时若
        # `RecordId` 还没跑过（agent 刚启动，或本任务就是第一个任务），读数会落进
        # `__default__` 桶；紧接着 HOME_ENTRY 才把账号 id 填上。之后 `_read_currency_counts()`
        # 按真实账号桶取值 —— 那里可能是别的任务留下的旧值，于是旧值会被当成本轮读数。
        # `DepotMaintainPlan` 对同一风险已有这条守卫，这里同样需要。
        if not ensure_account_id(context):
            logger.error("未能读取账号信息，读数无法与账号对应，本次跳过刷取")
            context.override_next("CT_Plan", ["CT_Done"])
            return CustomAction.RunResult(success=True)

        # ⚠️ 解析阈值必须在**扫描之前**：读取数量要进角色页、是一次完整导航，
        # 如果两个阈值都无效（用户填了 `K` / `abc` 之类），根本不需要跑这一趟。
        global dust_threshold, coin_threshold
        parsed_dust = _int_param(params.get("dust_threshold"), DUST_DEFAULT_THRESHOLD)
        parsed_coin = _int_param(params.get("coin_threshold"), COIN_DEFAULT_THRESHOLD)

        # 用窄化后的局部变量：`_int_param` 返回 `int | None`，直接往下传会让类型检查
        # 报错（`should_farm_currency` 要求 `int`）。阈值无效 → 该货币本轮不参与。
        dust_limit: int | None = parsed_dust if dust_enabled else None
        coin_limit: int | None = parsed_coin if coin_enabled else None
        dust_threshold = dust_limit if dust_limit is not None else DUST_DEFAULT_THRESHOLD
        coin_threshold = coin_limit if coin_limit is not None else COIN_DEFAULT_THRESHOLD

        if dust_limit is None and coin_limit is None:
            logger.warning("没有可用的阈值（开关全关，或填写的阈值无法解析），本次跳过刷取")
            context.override_next("CT_Plan", ["CT_Done"])
            return CustomAction.RunResult(success=True)

        detail = context.run_task(CURRENCY_SCAN_ENTRY)
        if detail is None or detail.status.failed:
            logger.warning("读取微尘 / 利齿子儿数量失败，本次跳过刷取")
            context.override_next("CT_Plan", ["CT_Done"])
            return CustomAction.RunResult(success=True)

        counts = _read_currency_counts()

        dust_now = counts.get(DUST_ITEM_ID)
        coin_now = counts.get(COIN_ITEM_ID)
        logger.info(f"当前数量：微尘 {dust_now if dust_now is not None else '未读到'}，"
                    f"利齿子儿 {coin_now if coin_now is not None else '未读到'}")

        # 低于阈值就要刷（阈值是「触发线」，不是「补到多少」）
        choices: list[tuple[int, str, str, str, int]] = []
        if dust_limit is not None and should_farm_currency(DUST_ITEM_ID, dust_now, dust_limit, dust_enabled):
            choices.append(
                (dust_limit - int(dust_now or 0), DUST_ITEM_ID, "微尘", DUST_STAGE, DUST_PER_RUN)
            )
        if coin_limit is not None and should_farm_currency(COIN_ITEM_ID, coin_now, coin_limit, coin_enabled):
            choices.append(
                (coin_limit - int(coin_now or 0), COIN_ITEM_ID, "利齿子儿", COIN_STAGE, COIN_PER_RUN)
            )

        if not choices:
            if dust_now is None or coin_now is None:
                logger.warning("未读到完整的微尘 / 利齿子儿数量，无法判断是否低于阈值，跳过刷取")
            else:
                logger.info("微尘 / 利齿子儿数量均不低于阈值，无需刷取")
            context.override_next("CT_Plan", ["CT_Done"])
            return CustomAction.RunResult(success=True)

        # 两个货币都缺时用一条简单确定的规则：**缺口大的优先**；缺口相同时固定选微尘
        # （`_CURRENCY_ORDER` 里微尘在前）。需求只要求「一个简单确定的规则」并说明，
        # 不扩建资源分配或多轮调度系统。
        _, item_id, item_name, stage, per_run = max(choices, key=lambda c: (c[0], -_CURRENCY_ORDER[c[1]]))
        if len(choices) > 1:
            # 日志必须打**实际选中的**那个，不能固定写「微尘」——
            # 缺口更大时选中的可能是利齿子儿，固定文案会和实际刷的关卡对不上。
            logger.info(f"微尘与利齿子儿都低于阈值，本次刷缺口更大的 {item_name}（规则：缺口大者优先）")
        current = dust_now if item_id == DUST_ITEM_ID else coin_now
        threshold = dust_threshold if item_id == DUST_ITEM_ID else coin_threshold
        # 阈值解析失败的货币已在上面把 enabled 置 False，不可能进到 choices；
        # 这里断言一次，避免 None 泄漏到 _state.target。
        assert threshold is not None

        _state.item_id = item_id
        _state.item_name = item_name
        _state.stage = stage
        _state.per_run = per_run
        _state.current = int(current or 0)
        _state.target = threshold
        _state.rounds += 1

        logger.info(
            f"低于阈值：{item_name} 当前 {_state.current} < 阈值 {threshold}，"
            f"关卡 {stage}（每局 {per_run}），刷到当天体力用完"
        )

        # 覆盖选关与复现次数（复刻常规作战的进入副本链路）。
        # target_count 用 114514 = 「常规作战」的默认复现次数：
        # TargetCountDetermine 按剩余体力算复现次数、吃糖补体，体力用完才结束 ——
        # 即用户要的「把当天体力刷完」。
        context.override_pipeline(
            {
                SELECT_STAGE_NODE: {
                    "action": {"param": {"custom_action_param": {"stage": stage}}},
                    "attach": {"level": "None"},
                },
                ALL_IN_NODE: {
                    "action": {"param": {"custom_action_param": {"target_count": UNLIMITED_RUNS}}},
                },
                # 刷完体力就正常结束，**不回到 CT_Plan 重查阈值**
                # （否则会反复进零体力作战）。收尾直接走 CT_Done。
                "TargetCountFinish": {"next": ["CT_Done"]},
            }
        )
        _state.target_count_finish_next = ["CT_Done"]
        context.override_next("CT_Plan", ["Combat"])
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("CurrencyTopUpDone")
class CurrencyTopUpDone(CustomAction):
    """收尾：输出本次刷取结果并回到主界面。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        if _state.item_id:
            logger.info(
                f"微尘 / 利齿子儿刷取结束：{_state.item_name} 当前 {_state.current} / "
                f"阈值 {_state.target}，共 {_state.rounds} 轮"
            )
        else:
            logger.info("微尘 / 利齿子儿刷取结束：本次无需刷取")

        detail = context.run_task("ResetReturnMain")
        if detail is None or detail.status.failed:
            logger.warning("补足任务收尾未能回到主界面")
            return CustomAction.RunResult(success=False)
        return CustomAction.RunResult(success=True)


def _plan_params(context: Context) -> dict[str, Any]:
    """从 CT_Plan 的 attach 读规划参数。"""
    node = context.get_node_object("CT_Plan")
    attach = getattr(node, "attach", None)
    return dict(attach) if isinstance(attach, dict) else {}


def _read_currency_counts() -> dict[str, int]:
    """读微尘 / 利齿子儿数量，**只认本轮真的读到的那几个**。

    `DepotCurrencyRead` 只把这次读到的货币写进快照，读不到的那个**保留旧值**。
    所以这里必须知道「本轮哪些货币读到了」—— 复用 `depot_maintain` 的
    `required_currency` 与本轮新增的 `read_currency_ids`：

    - 本轮读到了 → 用快照里的值；
    - 本轮没读到 → **不返回这个键**（调用方据此判定「未读到」，
      绝不能用旧快照的值决定刷不刷）。

    读取本身不产生副作用：不用 `snapshot_bucket`（那个函数会就地搬动旧格式数据）。
    """
    from utils.account_store import DEFAULT_ACCOUNT_KEY, normalize_account_id
    from utils.warehouse_snapshot import SNAPSHOT_KEY, load_snapshot_file

    from .depot_maintain import current_account_id, read_currency_ids

    data = load_snapshot_file()
    store = data.get(SNAPSHOT_KEY)
    if not isinstance(store, dict):
        return {}
    # 只读，不走 `snapshot_bucket`（那个函数会就地搬动旧格式数据，读数不该有副作用）
    key = normalize_account_id(current_account_id()) or DEFAULT_ACCOUNT_KEY
    bucket = store.get(key)
    if not isinstance(bucket, dict):
        return {}
    raw = bucket.get("counts")
    if not isinstance(raw, dict):
        return {}

    fresh = read_currency_ids()
    counts: dict[str, int] = {}
    for item_id in (DUST_ITEM_ID, COIN_ITEM_ID):
        if item_id not in fresh:
            # 本轮没读到 → 不用旧值
            continue
        value = raw.get(item_id)
        if isinstance(value, int):
            counts[item_id] = value
    return counts


def _int_param(value: Any, default: int) -> int | None:
    """把 GUI 的阈值输入解析成整数，**支持 K/M 缩写**（`500K` = 500000）。

    与 `depot_maintain.parse_abbreviated_number` 同一口径（游戏的缩写显示）。

    Returns:
        - 正整数 —— 解析成功
        - `None`  —— 输入非空但**解析不出来**（例如 `K`、`abc`）。调用方应让
                     该货币本轮不参与刷取，**不能回落到默认阈值** —— 默认值是 135 万，
                     静默拿它当阈值会把当天体力一次刷光。

    输入为空时返回 `default`：GUI 没填阈值属于「用默认值」，与「填了但填错」
    是两回事，不能一并按错误处理。

    但**布尔值按无效处理**：`True` / `False` 只可能来自 GUI 之外的 pipeline 覆写，
    说明有人把开关值错填到阈值字段。此时若回落到默认阈值（135 万），任务会按一个
    用户从未输入过的数字把当天体力刷光。

    数值类型（int / float）**直接接受**：手写 pipeline 覆写可能传 `1e16` 之类的
    数值，先 `str()` 会变成科学计数法（`1e+16`），解析器反而拒绝。
    """
    if value is None:
        return default
    if isinstance(value, bool):
        logger.error(
            f"阈值收到布尔值 {value}（可能把开关值填到了阈值字段），"
            f"该货币本轮不参与刷取。不会用默认阈值 {default} 替代"
        )
        return None
    if isinstance(value, (int, float)):
        parsed = int(value)
        if parsed <= 0:
            logger.error(f"阈值 {value!r} 不是正数，该货币本轮不参与刷取")
            return None
        return parsed
    text = str(value).strip()
    if not text:
        return default
    parsed = parse_abbreviated_number(text)
    if parsed is None or parsed <= 0:
        logger.error(
            f"阈值 {text!r} 无法解析成有效数字，该货币本轮不参与刷取"
            f"（不会用默认阈值替代 —— 默认值 {default} 会让任务直接刷完当天体力）"
        )
        return None
    return parsed


def should_farm_currency(
    item_id: str,
    current: int | None,
    threshold: int,
    enabled: bool,
) -> bool:
    """这个货币现在要不要刷。

    规则：**低于阈值就刷**（阈值是触发线，不是补到多少）。
    - 开关关掉 → 不刷；
    - 没读到数量 → 不刷（不能凭猜测刷）；
    - 当前数量 ≥ 阈值 → 不刷。
    """
    if not enabled or current is None:
        return False
    return current < threshold


def _bool_param(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")
