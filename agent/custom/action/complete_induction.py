import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.pipeline import JTemplateMatch, JColorMatch, JOCR, JRecognitionType

from utils import logger

_CATEGORY_UNLOCK_LEVEL: dict[str, int] = {
    "理性构成": 0,
    "妙想所得": 0,
    "容错装置": 0,
    "衍生物": 3,
}
_MATERIAL_UNLOCK_LEVEL: dict[str, int] = {
    "规则": 0,
    "知性": 0,
    "混沌": 2,
    "共感": 5,
}
_DEFAULT_CATEGORY_PRIORITY: tuple[str, ...] = (
    "理性构成",
    "妙想所得",
    "容错装置",
    "衍生物",
)
_DEFAULT_MATERIAL_PRIORITY: tuple[str, ...] = ("规则", "知性", "混沌", "共感")
_GENERIC_CATEGORY_LV0_1 = "理性构成"
_GENERIC_CATEGORY_LV2 = "妙想所得"
_GENERIC_CATEGORY_LV3_PLUS = "衍生物"
_GENERIC_MATERIALS_LV0_1: tuple[str, ...] = ("规则", "知性")
_GENERIC_MATERIALS_LV2_4: tuple[str, ...] = ("规则", "知性", "混沌")
_GENERIC_MATERIALS_LV5_PLUS: tuple[str, ...] = ("规则", "知性", "混沌", "共感")
_CATEGORY_ROIS: dict[str, tuple[int, int, int, int]] = {
    "理性构成": (76, 152, 160, 154),
    "妙想所得": (250, 152, 160, 154),
    "容错装置": (423, 152, 160, 154),
    "衍生物": (597, 152, 160, 154),
}
_MATERIAL_ROIS: dict[str, tuple[int, int, int, int]] = {
    "规则": (78, 412, 160, 154),
    "知性": (250, 412, 160, 154),
    "混沌": (424, 413, 160, 154),
    "共感": (595, 413, 160, 153),
}
_SELECTED_TARGET_OFFSET: tuple[int, int, int, int] = (48, 48, -99, -96)
_RESEARCHER_STATE_SELECTED = "selected"
_RESEARCHER_STATE_AVAILABLE = "available"
_RESEARCHER_STATE_UNLOCKABLE = "unlockable"
_RESEARCHER_STATE_BLOCKED = "blocked"
_RESEARCHER_MONEY_ROI: tuple[int, int, int, int] = (1096, 22, 130, 34)
_RESEARCHER_RECRUIT_PRICE_ROI: tuple[int, int, int, int] = (959, 542, 130, 40)
_RESEARCHER_RECRUIT_BUTTON_TARGET: tuple[int, int, int, int] = (822, 579, 402, 73)
_RESEARCHER_DEFAULT_UNLOCKABLE_OFFSET: tuple[int, int, int, int] = (38, 57, 66, 54)
_RESEARCHER_DEFAULT_UNLOCKABLE_PRICE_OFFSET: tuple[int, int, int, int] = (
    8,
    129,
    120,
    32,
)
_RESEARCHER_DEFAULT_BLOCKED_OFFSET: tuple[int, int, int, int] = (8, 129, 120, 32)


@dataclass(frozen=True)
class CIRecognitionSpec:
    kind: str
    roi: tuple[int, int, int, int]
    template: tuple[str, ...] = ()
    threshold: tuple[float, ...] = ()
    expected: tuple[str, ...] = ()
    method: int = 40
    lower: tuple[tuple[int, int, int], ...] = ()
    upper: tuple[tuple[int, int, int], ...] = ()
    count: int = 1


@dataclass(frozen=True)
class CIResearcherCardSpec:
    page: int
    index: int
    logical_index: int
    target: tuple[int, int, int, int]
    selected: CIRecognitionSpec
    unlockable: CIRecognitionSpec | None = None
    blocked: CIRecognitionSpec | None = None


@dataclass(frozen=True)
class CIResearcherCardState:
    spec: CIResearcherCardSpec
    state: str


_RESEARCHER_PAGE_LAYOUTS: tuple[tuple[CIResearcherCardSpec, ...], ...] = (
    (
        CIResearcherCardSpec(
            page=0,
            index=0,
            logical_index=0,
            target=(78, 119, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(79, 120, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
            unlockable=CIRecognitionSpec(
                kind="ocr",
                roi=(116, 176, 66, 54),
                expected=("解锁",),
            ),
            blocked=CIRecognitionSpec(
                kind="ocr",
                roi=(86, 248, 120, 32),
                expected=("评级",),
            ),
        ),
        CIResearcherCardSpec(
            page=0,
            index=1,
            logical_index=1,
            target=(262, 119, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(263, 120, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
            unlockable=CIRecognitionSpec(
                kind="ocr", roi=(300, 176, 66, 54), expected=("解锁",)
            ),
            blocked=CIRecognitionSpec(
                kind="ocr", roi=(270, 248, 120, 32), expected=("评级",)
            ),
        ),
        CIResearcherCardSpec(
            page=0,
            index=2,
            logical_index=2,
            target=(446, 119, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(447, 120, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
            unlockable=CIRecognitionSpec(
                kind="ocr", roi=(484, 176, 66, 54), expected=("解锁",)
            ),
            blocked=CIRecognitionSpec(
                kind="ocr", roi=(454, 248, 120, 32), expected=("评级",)
            ),
        ),
        CIResearcherCardSpec(
            page=0,
            index=3,
            logical_index=3,
            target=(630, 119, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(631, 120, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
            unlockable=CIRecognitionSpec(
                kind="ocr", roi=(668, 176, 66, 54), expected=("解锁",)
            ),
            blocked=CIRecognitionSpec(
                kind="ocr", roi=(638, 248, 120, 32), expected=("评级",)
            ),
        ),
        CIResearcherCardSpec(
            page=0,
            index=4,
            logical_index=4,
            target=(78, 323, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(79, 324, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
            unlockable=CIRecognitionSpec(
                kind="ocr", roi=(116, 380, 66, 54), expected=("解锁",)
            ),
            blocked=CIRecognitionSpec(
                kind="ocr", roi=(86, 452, 120, 32), expected=("评级",)
            ),
        ),
        CIResearcherCardSpec(
            page=0,
            index=5,
            logical_index=5,
            target=(262, 323, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(263, 324, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
            unlockable=CIRecognitionSpec(
                kind="ocr", roi=(300, 380, 66, 54), expected=("解锁",)
            ),
            blocked=CIRecognitionSpec(
                kind="ocr", roi=(270, 452, 120, 32), expected=("评级",)
            ),
        ),
        CIResearcherCardSpec(
            page=0,
            index=6,
            logical_index=6,
            target=(446, 323, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(447, 324, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
            unlockable=CIRecognitionSpec(
                kind="ocr", roi=(484, 380, 66, 54), expected=("解锁",)
            ),
            blocked=CIRecognitionSpec(
                kind="ocr", roi=(454, 452, 120, 32), expected=("评级",)
            ),
        ),
        CIResearcherCardSpec(
            page=0,
            index=7,
            logical_index=7,
            target=(630, 323, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(631, 324, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
            unlockable=CIRecognitionSpec(
                kind="ocr", roi=(668, 380, 66, 54), expected=("解锁",)
            ),
            blocked=CIRecognitionSpec(
                kind="ocr", roi=(638, 452, 120, 32), expected=("评级",)
            ),
        ),
    ),
    (
        CIResearcherCardSpec(
            page=1,
            index=0,
            logical_index=8,
            target=(78, 187, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(79, 188, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
        ),
        CIResearcherCardSpec(
            page=1,
            index=1,
            logical_index=9,
            target=(262, 187, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(263, 188, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
        ),
        CIResearcherCardSpec(
            page=1,
            index=2,
            logical_index=10,
            target=(446, 187, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(447, 188, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
        ),
        CIResearcherCardSpec(
            page=1,
            index=3,
            logical_index=11,
            target=(630, 187, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(631, 188, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
        ),
        CIResearcherCardSpec(
            page=1,
            index=4,
            logical_index=12,
            target=(78, 391, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(79, 392, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
        ),
        CIResearcherCardSpec(
            page=1,
            index=5,
            logical_index=13,
            target=(262, 391, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(263, 392, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
        ),
        CIResearcherCardSpec(
            page=1,
            index=6,
            logical_index=14,
            target=(446, 391, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(447, 392, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
        ),
        CIResearcherCardSpec(
            page=1,
            index=7,
            logical_index=15,
            target=(630, 391, 165, 177),
            selected=CIRecognitionSpec(
                kind="color",
                roi=(631, 392, 164, 18),
                method=40,
                lower=((10, 40, 180),),
                upper=((35, 180, 255),),
                count=140,
            ),
        ),
    ),
)
_RESEARCHER_PAGE_SWIPE_NEXT: tuple[tuple[int, int], tuple[int, int]] | None = (
    (528, 430),
    (528, 54),
)
_RESEARCHER_PAGE_SWIPE_PREV: tuple[tuple[int, int], tuple[int, int]] | None = (
    (528, 133),
    (528, 580),
)
_RESEARCHER_SWIPE_DURATION_MS = 600
_RESEARCHER_POST_DELAY_SEC = 0.8


class CIRecord:
    level: int = 0
    task: str = ""
    strategy: str = ""
    category: str = ""
    materials: tuple[str, ...] = ()
    researcher_max_count: int = 0
    researcher_known_available: set[int] = set()


@dataclass(frozen=True)
class CITaskStrategy:
    name: str
    category: str
    materials: tuple[str, ...]
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CIPlan:
    category: str
    materials: tuple[str, ...]
    source: tuple[str, ...]
    matched_task: str = ""
    similarity: float = 0.0

    def summary(self) -> str:
        source = "+".join(self.source) if self.source else "generic"
        material_text = "、".join(self.materials)
        if self.matched_task:
            return (
                f"source={source}, matched_task={self.matched_task}, "
                f"similarity={self.similarity:.2f}, category={self.category}, materials={material_text}"
            )
        return f"source={source}, category={self.category}, materials={material_text}"


CI_TASK_STRATEGIES: tuple[CITaskStrategy, ...] = (
    CITaskStrategy(
        name="完成1次使用了【规则】【知性】的研究",
        category="理性构成",
        materials=("规则", "知性"),
        aliases=("完成1次使用规则知性的研究",),
    ),
    CITaskStrategy(
        name="完成1次基于【妙想所得】的研究",
        category="妙想所得",
        materials=("规则", "知性"),
        aliases=("完成1次基于妙想所得的研究",),
    ),
    CITaskStrategy(
        name="完成1次基于【容错装置】的研究",
        category="容错装置",
        materials=("规则", "知性"),
        aliases=("完成1次基于容错装置的研究",),
    ),
    CITaskStrategy(
        name="完成1次基于【衍生物】的研究",
        category="衍生物",
        materials=("规则", "知性", "混沌"),
        aliases=("完成1次基于衍生物的研究",),
    ),
    CITaskStrategy(
        name="完成1次使用了【“共感”】的研究",
        category="衍生物",
        materials=("规则", "知性", "混沌", "共感"),
        aliases=("完成1次使用了共感的研究",),
    ),
)
_TASK_MATCH_THRESHOLD = 0.9


def _normalize_text(text: str) -> str:
    return re.sub(r'[\s"“”‘’\'`·•,，。!！?？:：;；\[\]【】()（）<>《》/\\-]+', "", text)


def _available_items(level: int, unlock_map: dict[str, int]) -> list[str]:
    return [name for name, unlock_level in unlock_map.items() if level >= unlock_level]


def _offset_roi(
    roi: tuple[int, int, int, int], offset: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    x, y, w, h = roi
    dx, dy, dw, dh = offset
    return (x + dx, y + dy, w + dw, h + dh)


def _match_task_strategy(task_text: str) -> tuple[CITaskStrategy | None, float]:
    normalized_task = _normalize_text(task_text)
    if not normalized_task:
        return None, 0.0

    best_strategy: CITaskStrategy | None = None
    best_score = 0.0

    for strategy in CI_TASK_STRATEGIES:
        candidates = (strategy.name, *strategy.aliases)
        for candidate in candidates:
            normalized_candidate = _normalize_text(candidate)
            if not normalized_candidate:
                continue

            if normalized_task == normalized_candidate:
                score = 1.0
            elif (
                normalized_task in normalized_candidate
                or normalized_candidate in normalized_task
            ):
                shorter = min(len(normalized_task), len(normalized_candidate))
                longer = max(len(normalized_task), len(normalized_candidate))
                score = 0.9 + 0.09 * (shorter / longer)
            else:
                score = SequenceMatcher(
                    None, normalized_task, normalized_candidate
                ).ratio()

            if score > best_score:
                best_strategy = strategy
                best_score = score

    if best_score < _TASK_MATCH_THRESHOLD:
        return None, best_score

    return best_strategy, best_score


def _resolve_plan(task_text: str, level: int) -> CIPlan | None:
    available_categories = _available_items(level, _CATEGORY_UNLOCK_LEVEL)
    available_materials = _available_items(level, _MATERIAL_UNLOCK_LEVEL)

    if not available_categories or not available_materials:
        logger.error("CompleteInduction 当前研究所等级没有可用的类别或材料")
        return None

    matched_strategy, similarity = _match_task_strategy(task_text)
    if matched_strategy is not None:
        if matched_strategy.category not in available_categories:
            logger.warning(
                f"任务匹配到预设策略，但类别未解锁: {matched_strategy.category}"
            )
        else:
            if matched_strategy.materials and all(
                material in available_materials
                for material in matched_strategy.materials
            ):
                return CIPlan(
                    category=matched_strategy.category,
                    materials=matched_strategy.materials,
                    source=("preset-task",),
                    matched_task=matched_strategy.name,
                    similarity=similarity,
                )

            if matched_strategy.materials:
                missing_materials = [
                    material
                    for material in matched_strategy.materials
                    if material not in available_materials
                ]
                logger.warning(
                    "任务匹配到预设策略，但部分材料未解锁: "
                    + "、".join(missing_materials)
                )
            else:
                logger.warning("任务匹配到预设策略，但未配置材料")

    if level >= 5:
        generic_category = _GENERIC_CATEGORY_LV3_PLUS
        generic_material_priority = _GENERIC_MATERIALS_LV5_PLUS
    elif level >= 3:
        generic_category = _GENERIC_CATEGORY_LV3_PLUS
        generic_material_priority = _GENERIC_MATERIALS_LV2_4
    elif level == 2:
        generic_category = _GENERIC_CATEGORY_LV2
        generic_material_priority = _GENERIC_MATERIALS_LV2_4
    else:
        generic_category = _GENERIC_CATEGORY_LV0_1
        generic_material_priority = _GENERIC_MATERIALS_LV0_1

    material_candidates = [
        name for name in generic_material_priority if name in available_materials
    ]
    if not material_candidates:
        logger.error("CompleteInduction 当前没有可用的材料")
        return None

    if generic_category not in available_categories:
        logger.error(f"CompleteInduction 通用策略类别未解锁: {generic_category}")
        return None

    if matched_strategy is None:
        logger.info(
            f"当前任务未匹配到预设策略，回退通用策略，最高相似度: {similarity:.2f}"
        )
    else:
        logger.info("预设策略不可直接使用，回退通用策略")

    return CIPlan(
        category=generic_category,
        materials=tuple(material_candidates),
        source=("generic",),
    )


@AgentServer.custom_action("CIRecordLevel")
class CIRecordLevel(CustomAction):
    _level_roi: tuple[int, int, int, int] = (1032, 176, 93, 65)

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        img = context.tasker.controller.cached_image

        reco_detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(roi=self._level_roi, expected=["[1]?[0-9]+"]),
            img,
        )
        if reco_detail and reco_detail.hit:
            CIRecord.level = int(reco_detail.best_result.text.strip())
            logger.info(f"当前研究所等级: {CIRecord.level}")
        else:
            logger.error("未识别出研究所等级")
            return CustomAction.RunResult(success=False)

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("CITask")
class CITask(CustomAction):
    _task_roi: tuple[int, int, int, int] = (822, 130, 385, 57)
    _click_delay_sec: float = 0.6

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        img = context.tasker.controller.cached_image

        reco_detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(roi=self._task_roi, order_by="Vertical"),
            img,
        )
        if reco_detail and reco_detail.hit:
            text_items: list[str] = []
            for item in getattr(reco_detail, "filtered_results", []) or []:
                text = (getattr(item, "text", "") or "").strip()
                if text:
                    text_items.append(text)

            if not text_items:
                best = getattr(reco_detail, "best_result", None)
                text = (getattr(best, "text", "") or "").strip() if best else ""
                if text:
                    text_items.append(text)

            CIRecord.task = "".join(text_items)
            logger.info(f"当前任务: {CIRecord.task}")
        else:
            logger.error("未识别出当前任务")
            return CustomAction.RunResult(success=False)

        plan = _resolve_plan(CIRecord.task, CIRecord.level)
        if plan is None:
            return CustomAction.RunResult(success=False)

        CIRecord.category = plan.category
        CIRecord.materials = plan.materials
        CIRecord.strategy = plan.summary()
        logger.info(f"研究策略: {CIRecord.strategy}")

        if not self._ensure_category(context, plan.category):
            return CustomAction.RunResult(success=False)

        if not self._ensure_materials(context, plan.materials):
            return CustomAction.RunResult(success=False)

        return CustomAction.RunResult(success=True)

    def _ensure_category(self, context: Context, category_name: str) -> bool:
        roi = _CATEGORY_ROIS.get(category_name)
        if roi is None:
            logger.error(f"未配置类别坐标: {category_name}")
            return False
        return self._set_option_selected(context, category_name, roi, True)

    def _ensure_materials(
        self, context: Context, target_materials: tuple[str, ...]
    ) -> bool:
        available_materials = _available_items(CIRecord.level, _MATERIAL_UNLOCK_LEVEL)
        target_material_set = set(target_materials)

        for material_name in available_materials:
            roi = _MATERIAL_ROIS.get(material_name)
            if roi is None:
                logger.error(f"未配置材料坐标: {material_name}")
                return False

            desired_selected = material_name in target_material_set
            if not self._set_option_selected(
                context, material_name, roi, desired_selected
            ):
                return False

        return True

    def _set_option_selected(
        self,
        context: Context,
        option_name: str,
        roi: tuple[int, int, int, int],
        desired_selected: bool,
    ) -> bool:
        for attempt in range(3):
            is_selected = self._is_option_selected(context, roi)
            if is_selected == desired_selected:
                logger.info(
                    f"{'已选中' if desired_selected else '已取消'}: {option_name}"
                )
                return True

            target = _offset_roi(roi, _SELECTED_TARGET_OFFSET)
            x, y, w, h = target
            context.tasker.controller.post_click(x + w // 2, y + h // 2).wait()
            time.sleep(self._click_delay_sec)

        logger.error(f"未能{'选中' if desired_selected else '取消'}选项: {option_name}")
        return False

    def _is_option_selected(
        self, context: Context, roi: tuple[int, int, int, int]
    ) -> bool:
        img = context.tasker.controller.post_screencap().wait().get()
        reco_detail = context.run_recognition_direct(
            JRecognitionType.ColorMatch,
            JColorMatch(
                roi=roi,
                method=40,
                lower=[[0, 0, 220]],
                upper=[[30, 120, 255]],
                count=700,
            ),
            img,
        )
        return bool(reco_detail and reco_detail.hit)


@AgentServer.custom_action("CIRecordPeopleMaxCount")
class CIRecordPeopleMaxCount(CustomAction):
    _people_count_roi: tuple[int, int, int, int] = (99, 229, 638, 270)

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        img = context.tasker.controller.cached_image

        reco_detail = context.run_recognition_direct(
            JRecognitionType.TemplateMatch,
            JTemplateMatch(
                roi=self._people_count_roi,
                template=["CompleteInduction/AddResearcher.png"],
                threshold=[0.9],
            ),
            img,
        )
        if reco_detail and reco_detail.hit:
            CIRecord.researcher_max_count = len(reco_detail.filtered_results)
            logger.info(f"当前最多可参与研究的人数: {CIRecord.researcher_max_count}")

        context.tasker.controller.post_click(138, 261).wait()
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("CISelectResearchers")
class CISelectResearchers(CustomAction):
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        if CIRecord.researcher_max_count <= 0:
            logger.error("未记录 researcher_max_count，无法执行研究员选择")
            return CustomAction.RunResult(success=False)

        if not self._is_configured():
            return CustomAction.RunResult(success=False)

        cards = self._collect_cards(context, stop_after_first_unlockable=True)
        if cards is None:
            return CustomAction.RunResult(success=False)

        cards = self._try_unlock_researchers(context, cards)
        if cards is None:
            return CustomAction.RunResult(success=False)

        selected_keys = self._choose_target_cards(cards, CIRecord.researcher_max_count)
        if not selected_keys:
            logger.error("未找到可用于研究的研究员卡位")
            return CustomAction.RunResult(success=False)

        if not self._apply_target_cards(context, cards, selected_keys):
            return CustomAction.RunResult(success=False)

        return CustomAction.RunResult(success=True)

    def _is_configured(self) -> bool:
        configured_pages = [page for page in _RESEARCHER_PAGE_LAYOUTS if page]
        if not configured_pages:
            logger.error("研究员页卡位布局未配置，无法执行 CISelectResearchers")
            return False

        if len(configured_pages) > 1 and (
            _RESEARCHER_PAGE_SWIPE_NEXT is None or _RESEARCHER_PAGE_SWIPE_PREV is None
        ):
            logger.error("研究员页存在多页，但未配置翻页滑动坐标")
            return False

        return True

    def _collect_cards(
        self,
        context: Context,
        stop_after_first_unlockable: bool = False,
    ) -> list[CIResearcherCardState] | None:
        current_page = 0
        all_cards: list[CIResearcherCardState] = []

        for page_index, page_layout in enumerate(_RESEARCHER_PAGE_LAYOUTS):
            if not page_layout:
                continue

            current_page = self._goto_page(context, current_page, page_index)
            if current_page != page_index:
                return None

            page_cards = self._scan_page(context, page_layout)
            all_cards.extend(page_cards)

            if stop_after_first_unlockable and any(
                card.state == _RESEARCHER_STATE_UNLOCKABLE for card in page_cards
            ):
                break

        if current_page != 0:
            current_page = self._goto_page(context, current_page, 0)
            if current_page != 0:
                return None

        return all_cards

    def _scan_page(
        self, context: Context, page_layout: tuple[CIResearcherCardSpec, ...]
    ) -> list[CIResearcherCardState]:
        page_cards: list[CIResearcherCardState] = []
        for spec in page_layout:
            card_state = self._detect_card_state(context, spec)
            page_cards.append(card_state)
            self._remember_known_available(card_state)

            if card_state.state == _RESEARCHER_STATE_BLOCKED:
                remaining_specs = page_layout[len(page_cards) :]
                page_cards.extend(
                    CIResearcherCardState(remaining_spec, _RESEARCHER_STATE_BLOCKED)
                    for remaining_spec in remaining_specs
                )
                break

        visible = [f"{card.spec.index}:{card.state}" for card in page_cards]
        if visible:
            logger.info(
                f"researcher page {page_layout[0].page + 1}: {' | '.join(visible)}"
            )
        return page_cards

    def _detect_card_state(
        self, context: Context, spec: CIResearcherCardSpec
    ) -> CIResearcherCardState:
        if self._hit_recognition(context, spec.selected):
            return CIResearcherCardState(spec, _RESEARCHER_STATE_SELECTED)

        if spec.logical_index in CIRecord.researcher_known_available:
            return CIResearcherCardState(spec, _RESEARCHER_STATE_AVAILABLE)

        blocked = self._get_blocked_recognition(spec)
        if blocked is not None and self._hit_recognition(context, blocked):
            return CIResearcherCardState(spec, _RESEARCHER_STATE_BLOCKED)

        unlockable = self._get_unlockable_recognition(spec)
        if unlockable is not None and self._hit_recognition(context, unlockable):
            return CIResearcherCardState(spec, _RESEARCHER_STATE_UNLOCKABLE)

        unlockable_price = self._get_unlockable_price_recognition(spec)
        if unlockable_price is not None and self._hit_recognition(
            context, unlockable_price
        ):
            return CIResearcherCardState(spec, _RESEARCHER_STATE_UNLOCKABLE)

        return CIResearcherCardState(spec, _RESEARCHER_STATE_AVAILABLE)

    def _get_unlockable_recognition(
        self, spec: CIResearcherCardSpec
    ) -> CIRecognitionSpec | None:
        if spec.unlockable is not None:
            return spec.unlockable

        x, y, _, _ = spec.target
        dx, dy, w, h = _RESEARCHER_DEFAULT_UNLOCKABLE_OFFSET
        return CIRecognitionSpec(
            kind="ocr",
            roi=(x + dx, y + dy, w, h),
            expected=("解锁",),
        )

    def _get_unlockable_price_recognition(
        self, spec: CIResearcherCardSpec
    ) -> CIRecognitionSpec | None:
        x, y, _, _ = spec.target
        dx, dy, w, h = _RESEARCHER_DEFAULT_UNLOCKABLE_PRICE_OFFSET
        return CIRecognitionSpec(
            kind="ocr",
            roi=(x + dx, y + dy, w, h),
            expected=(r"[1-9]\d{3,}",),
        )

    def _get_blocked_recognition(
        self, spec: CIResearcherCardSpec
    ) -> CIRecognitionSpec | None:
        if spec.blocked is not None:
            return spec.blocked

        x, y, _, _ = spec.target
        dx, dy, w, h = _RESEARCHER_DEFAULT_BLOCKED_OFFSET
        return CIRecognitionSpec(
            kind="ocr",
            roi=(x + dx, y + dy, w, h),
            expected=("评级",),
        )

    def _resolve_candidate_cards(
        self, cards: list[CIResearcherCardState]
    ) -> list[CIResearcherCardState]:
        deduped_cards = self._dedupe_cards(cards)
        return [
            card
            for card in deduped_cards
            if card.state
            in {
                _RESEARCHER_STATE_SELECTED,
                _RESEARCHER_STATE_AVAILABLE,
            }
        ]

    def _resolve_unlockable_cards(
        self, cards: list[CIResearcherCardState]
    ) -> list[CIResearcherCardState]:
        deduped_cards = self._dedupe_cards(cards)
        unlockable_cards = [
            card for card in deduped_cards if card.state == _RESEARCHER_STATE_UNLOCKABLE
        ]
        unlockable_cards.sort(key=lambda card: card.spec.logical_index)
        return unlockable_cards

    def _try_unlock_researchers(
        self, context: Context, cards: list[CIResearcherCardState]
    ) -> list[CIResearcherCardState] | None:
        current_cards = cards
        current_page = 0

        while True:
            unlockable_cards = self._resolve_unlockable_cards(current_cards)
            if not unlockable_cards:
                if current_page != 0:
                    self._goto_page(context, current_page, 0)
                return current_cards

            candidate = unlockable_cards[0]
            current_page = self._goto_page(context, current_page, candidate.spec.page)
            if current_page != candidate.spec.page:
                return None

            if not self._unlock_researcher(context, candidate.spec):
                if current_page != 0:
                    self._goto_page(context, current_page, 0)
                return current_cards

            current_cards = self._replace_card_state(
                current_cards,
                candidate.spec.logical_index,
                _RESEARCHER_STATE_SELECTED,
            )

    def _replace_card_state(
        self,
        cards: list[CIResearcherCardState],
        logical_index: int,
        new_state: str,
    ) -> list[CIResearcherCardState]:
        replaced_cards: list[CIResearcherCardState] = []
        for card in cards:
            if card.spec.logical_index == logical_index:
                replaced_cards.append(CIResearcherCardState(card.spec, new_state))
            else:
                replaced_cards.append(card)
        if new_state in {_RESEARCHER_STATE_SELECTED, _RESEARCHER_STATE_AVAILABLE}:
            CIRecord.researcher_known_available.add(logical_index)
        return replaced_cards

    def _remember_known_available(self, card: CIResearcherCardState) -> None:
        if card.state in {_RESEARCHER_STATE_SELECTED, _RESEARCHER_STATE_AVAILABLE}:
            CIRecord.researcher_known_available.add(card.spec.logical_index)

    def _choose_target_cards(
        self, cards: list[CIResearcherCardState], target_count: int
    ) -> set[int]:
        candidates = self._resolve_candidate_cards(cards)
        candidates.sort(key=lambda card: card.spec.logical_index, reverse=True)
        return {card.spec.logical_index for card in candidates[:target_count]}

    def _apply_target_cards(
        self,
        context: Context,
        cards: list[CIResearcherCardState],
        target_keys: set[int],
    ) -> bool:
        pages = sorted(
            {
                card.spec.page
                for card in cards
                if card.spec.logical_index in target_keys
            },
            reverse=True,
        )
        current_page = 0

        for page in pages:
            current_page = self._goto_page(context, current_page, page)
            if current_page != page:
                return False

            page_cards = [
                card
                for card in cards
                if card.spec.page == page
                and card.spec.logical_index in target_keys
                and card.state == _RESEARCHER_STATE_AVAILABLE
            ]
            page_cards.sort(key=lambda card: card.spec.logical_index, reverse=True)

            for card in page_cards:
                self._click_roi(context, card.spec.target)
                time.sleep(_RESEARCHER_POST_DELAY_SEC)

        if current_page != 0:
            current_page = self._goto_page(context, current_page, 0)
            if current_page != 0:
                return False

        return True

    def _unlock_researcher(self, context: Context, spec: CIResearcherCardSpec) -> bool:
        self._click_roi(context, spec.target)
        time.sleep(_RESEARCHER_POST_DELAY_SEC)

        money = self._read_number(context, _RESEARCHER_MONEY_ROI)
        price = self._read_number(context, _RESEARCHER_RECRUIT_PRICE_ROI)
        if money is None or price is None:
            logger.warning(
                f"无法识别研究员解锁价格或当前货币: page={spec.page + 1}, index={spec.index}, logical={spec.logical_index}"
            )
            return False

        if money < price:
            logger.warning(
                f"研究员资源不足，无法招聘: money={money}, price={price}, page={spec.page + 1}, index={spec.index}, logical={spec.logical_index}"
            )
            return False

        # 招聘按钮点击后立即生效；若资源不足只会弹右上角警告，不额外处理。
        self._click_roi(context, _RESEARCHER_RECRUIT_BUTTON_TARGET)
        time.sleep(_RESEARCHER_POST_DELAY_SEC)
        return True

    def _dedupe_cards(
        self, cards: list[CIResearcherCardState]
    ) -> list[CIResearcherCardState]:
        deduped: dict[int, CIResearcherCardState] = {}

        for card in cards:
            key = card.spec.logical_index
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = card
                continue

            # 重叠视图中优先保留更靠后的页面，通常可见区域更完整。
            if (card.spec.page, card.spec.index) >= (
                existing.spec.page,
                existing.spec.index,
            ):
                deduped[key] = card

        return list(deduped.values())

    def _goto_page(self, context: Context, current_page: int, target_page: int) -> int:
        while current_page < target_page:
            if not self._swipe_page(context, forward=True):
                return current_page
            current_page += 1

        while current_page > target_page:
            if not self._swipe_page(context, forward=False):
                return current_page
            current_page -= 1

        return current_page

    def _swipe_page(self, context: Context, forward: bool) -> bool:
        swipe = _RESEARCHER_PAGE_SWIPE_NEXT if forward else _RESEARCHER_PAGE_SWIPE_PREV
        if swipe is None:
            logger.error("未配置研究员页翻页滑动坐标")
            return False

        (x1, y1), (x2, y2) = swipe
        context.tasker.controller.post_swipe(
            x1,
            y1,
            x2,
            y2,
            duration=_RESEARCHER_SWIPE_DURATION_MS,
        ).wait()
        time.sleep(_RESEARCHER_POST_DELAY_SEC)
        return True

    def _hit_recognition(self, context: Context, spec: CIRecognitionSpec) -> bool:
        img = context.tasker.controller.post_screencap().wait().get()

        if spec.kind == "template":
            thresholds = (
                list(spec.threshold) if spec.threshold else [0.9 for _ in spec.template]
            )
            reco_detail = context.run_recognition_direct(
                JRecognitionType.TemplateMatch,
                JTemplateMatch(
                    roi=spec.roi,
                    template=list(spec.template),
                    threshold=thresholds,
                ),
                img,
            )
            return bool(reco_detail and reco_detail.hit)

        if spec.kind == "ocr":
            reco_detail = context.run_recognition_direct(
                JRecognitionType.OCR,
                JOCR(
                    roi=spec.roi,
                    expected=list(spec.expected) if spec.expected else [".*"],
                ),
                img,
            )
            return bool(reco_detail and reco_detail.hit)

        if spec.kind == "color":
            reco_detail = context.run_recognition_direct(
                JRecognitionType.ColorMatch,
                JColorMatch(
                    roi=spec.roi,
                    method=spec.method,
                    lower=[list(item) for item in spec.lower],
                    upper=[list(item) for item in spec.upper],
                    count=spec.count,
                ),
                img,
            )
            return bool(reco_detail and reco_detail.hit)

        logger.error(f"未知研究员识别类型: {spec.kind}")
        return False

    def _read_number(
        self, context: Context, roi: tuple[int, int, int, int]
    ) -> int | None:
        img = context.tasker.controller.post_screencap().wait().get()
        reco_detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(
                roi=roi,
                expected=[r"\d[\d,]*"],
            ),
            img,
        )
        if reco_detail is None or not reco_detail.hit:
            return None

        text = getattr(reco_detail.best_result, "text", "") or ""
        digits = re.sub(r"[^\d]", "", text)
        if not digits:
            return None
        return int(digits)

    def _click_roi(self, context: Context, roi: tuple[int, int, int, int]) -> None:
        x, y, w, h = roi
        context.tasker.controller.post_click(x + w // 2, y + h // 2).wait()
