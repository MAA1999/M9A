import re
import time
from dataclasses import dataclass
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.define import OCRResult, RecognitionDetail
from maa.pipeline import JOCR, JRecognitionType
from utils.logger import logger
from utils.maa_types import is_hit, results_as
from utils.params import parse_params

__all__ = ["SwitchAccountSelect"]

# 账号列表里的掩码账号文本，例如 189****6002
_ACCOUNT_TEXT_PATTERN = r"[0-9]{3}\*{4}[0-9]{4}"


@dataclass
class _AccountRow:
    """账号列表中的一行，坐标取自该行掩码账号文本的 OCR 结果。"""

    box: tuple[int, int, int, int]
    text: str
    normalized_text: str

    @property
    def center(self) -> tuple[int, int]:
        x, y, w, h = self.box
        return x + w // 2, y + h // 2


@AgentServer.custom_action("SwitchAccountSelect")
class SwitchAccountSelect(CustomAction):
    """在账号列表中选择账号；未指定账号时选择列表底部最后一个。

    掩码账号文本直接在全屏 OCR 中识别，行位置一律由识别结果推导，不使用图标模板，
    也不写死任何 720p 窗口或行坐标，因此不受模拟器 DPI / 分辨率造成的界面缩放影响
    （该登录面板按 dp 绘制，会随 DPI 等比缩放）。
    """

    # MaaFW 约定 roi=(0,0,0,0) 为全屏识别：不预设列表窗口，任意界面缩放下都能读到行文本
    _FULL_SCREEN_ROI: tuple[int, int, int, int] = (0, 0, 0, 0)
    # 展开箭头位置由行文本推导：x = 文本右边缘 + 文字高 * 该系数（两套实机布局实测 3.03 / 3.17）
    _EXPAND_OFFSET_RATIO = 3.0
    _MAX_PAGES = 8
    _SWIPE_DURATION_MS = 600
    _SETTLE_SECONDS = 1.0
    # 复用管线的「登录按钮可见」节点判断收起态：收起态面板显示 登录 / 登录其他账号
    _LOGIN_PROBE_NODE = "SwitchLastAccountComplete"

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        params = parse_params(argv.custom_action_param)
        target_account = str(params.get("account", "") or "").strip()
        normalized_target = self._normalize_text(target_account)

        img = self._screencap(context)
        rows = self._read_rows(context, img)

        if len(rows) < 2 and self._login_visible(context, img):
            # 收起态：面板只显示当前账号与登录按钮，需要先点开下拉列表
            if not rows:
                logger.error("账号列表处于收起状态，但未读到当前账号行，无法定位展开箭头")
                return CustomAction.RunResult(success=False)

            logger.info(f"账号列表未展开（仅读到 {len(rows)} 行），点击展开箭头")
            self._click_expand_arrow(context, rows[0])
            rows = self._read_rows(context, self._screencap(context))
            if len(rows) < 2:
                logger.error(f"展开后仍只读到 {len(rows)} 个账号行，停止操作（避免误点）")
                return CustomAction.RunResult(success=False)

        if not rows:
            logger.error("未读到账号列表，请确认任务停在账号面板上")
            return CustomAction.RunResult(success=False)

        if len(rows) == 1:
            if normalized_target and not self._match_target(normalized_target, rows[0].normalized_text):
                logger.error(f"账号列表只有 {rows[0].text}，未找到目标账号: {target_account}")
                return CustomAction.RunResult(success=False)
            self._click_row(context, rows[0])
            logger.info(f"账号列表只有一个账号，直接选择: {rows[0].text}")
            self._remember_target(target_account, rows[0].text)
            return CustomAction.RunResult(success=True)

        seen_signatures: set[tuple[str, ...]] = set()

        for page_index in range(self._MAX_PAGES):
            self._log_visible_accounts(rows, page_index + 1)

            if normalized_target:
                for row in rows:
                    if self._match_target(normalized_target, row.normalized_text):
                        self._click_row(context, row)
                        logger.info(f"匹配到目标账号: {target_account}")
                        self._remember_target(target_account, row.text)
                        return CustomAction.RunResult(success=True)

            page_signature = self._page_signature(rows)
            if page_signature and page_signature in seen_signatures:
                if normalized_target:
                    logger.error(f"到达账号列表底部，未找到目标账号: {target_account}")
                    return CustomAction.RunResult(success=False)
                self._click_row(context, rows[-1])
                logger.info("选择列表底部最后一个账号")
                self._remember_target(target_account, rows[-1].text)
                return CustomAction.RunResult(success=True)

            if page_signature:
                seen_signatures.add(page_signature)

            if page_index >= self._MAX_PAGES - 1:
                break

            self._swipe_to_next_page(context, rows)
            rows = self._read_rows(context, self._screencap(context))
            if not rows:
                logger.error("翻页后读不到账号行，停止翻页（不再继续操作）")
                return CustomAction.RunResult(success=False)

        wanted = target_account or "列表底部"
        logger.error(f"达到最大翻页次数 {self._MAX_PAGES}，仍未选中账号: {wanted}")
        return CustomAction.RunResult(success=False)

    def _screencap(self, context: Context) -> Any:
        return context.tasker.controller.post_screencap().wait().get()

    def _remember_target(self, configured_target: str, selected_text: str) -> None:
        """记下这次切换的目标标识（**仅用于日志**）。

        账号归属现在只认游戏内真实 UID，不再需要把这个标识写进状态文件，
        所以这里只打一条 debug 日志，方便排查「切到了哪个账号」。
        """
        logger.debug(f"切换目标标识: {configured_target or '未配置'}（列表中选中的行: {selected_text}）")

    def _read_rows(self, context: Context, img: Any) -> list[_AccountRow]:
        """读取账号行：一次 OCR 直接得到行文本与行位置，不再依赖 × 图标模板。"""
        detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(roi=self._FULL_SCREEN_ROI, expected=[_ACCOUNT_TEXT_PATTERN], order_by="Vertical"),
            img,
        )
        if not is_hit(detail):
            self._log_unmatched_texts(detail)
            return []

        rows: list[_AccountRow] = []
        for result in results_as(detail, OCRResult):
            text = (result.text or "").strip()
            if not text:
                continue
            box = result.box
            rows.append(
                _AccountRow(
                    box=(int(box[0]), int(box[1]), int(box[2]), int(box[3])),
                    text=text,
                    normalized_text=self._normalize_text(text),
                )
            )

        rows.sort(key=lambda row: row.center[1])
        return rows

    def _login_visible(self, context: Context, img: Any) -> bool:
        return is_hit(context.run_recognition(self._LOGIN_PROBE_NODE, img))

    def _click_row(self, context: Context, row: _AccountRow) -> None:
        x, y = row.center
        context.tasker.controller.post_click(x, y).wait()
        time.sleep(self._SETTLE_SECONDS)

    def _click_expand_arrow(self, context: Context, row: _AccountRow) -> None:
        x, y, w, h = row.box
        context.tasker.controller.post_click(x + w + int(h * self._EXPAND_OFFSET_RATIO), y + h // 2).wait()
        time.sleep(self._SETTLE_SECONDS)

    def _swipe_to_next_page(self, context: Context, rows: list[_AccountRow]) -> None:
        """在列表内部翻页：起止点取已识别到的行，避免滑出面板把下拉列表关掉。"""
        x = rows[0].center[0]
        context.tasker.controller.post_swipe(
            x,
            rows[-1].center[1],
            x,
            rows[0].center[1],
            duration=self._SWIPE_DURATION_MS,
        ).wait()
        time.sleep(self._SETTLE_SECONDS)

    def _log_visible_accounts(self, rows: list[_AccountRow], page_index: int) -> None:
        visible = [row.text or "<empty>" for row in rows]
        logger.info(f"page {page_index}: {' | '.join(visible)}")
        logger.debug(f"page {page_index} 行坐标: {[row.box for row in rows]}")

    def _log_unmatched_texts(self, detail: RecognitionDetail | None) -> None:
        """读不到账号行时记录该区域的 OCR 原文，便于排查界面缩放不匹配。"""
        if detail is None:
            logger.debug("账号列表 OCR 未返回结果")
            return

        texts = [result.text for result in detail.all_results if isinstance(result, OCRResult) and result.text.strip()]
        logger.debug(f"账号列表区域 OCR 原文: {texts}")

    def _page_signature(self, rows: list[_AccountRow]) -> tuple[str, ...]:
        return tuple(row.normalized_text for row in rows if row.normalized_text)

    def _match_target(self, target: str, candidate: str) -> bool:
        if not target or not candidate:
            return False
        if target == candidate or target in candidate:
            return True
        if len(candidate) >= 4 and candidate in target:
            return True
        # 掩码文本只露出前 3 位与后 4 位，目标是完整手机号时按首尾比对
        return (
            len(candidate) >= 7
            and len(target) > len(candidate)
            and target.startswith(candidate[:3])
            and target.endswith(candidate[-4:])
        )

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"[\W_]+", "", text or "").lower()
