import re
import time
from dataclasses import dataclass

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.pipeline import JOCR, JRecognitionType
from utils import logger
from utils.params import parse_params

__all__ = ["SwitchAccountSelect"]


@dataclass
class _VisibleAccount:
    row_roi: tuple[int, int, int, int]
    text: str
    normalized_text: str


@AgentServer.custom_action("SwitchAccountSelect")
class SwitchAccountSelect(CustomAction):
    _list_left = 437
    _list_top = 340
    _list_bottom = 640
    _max_swipes = 8
    _swipe_from = (620, 600)
    _swipe_to = (620, 390)

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        params = parse_params(argv.custom_action_param)
        target_account = str(params.get("account", "") or "").strip()
        normalized_target = self._normalize_text(target_account)
        seen_signatures: set[tuple[str, ...]] = set()

        for page_index in range(self._max_swipes):
            img = context.tasker.controller.post_screencap().wait().get()
            accounts = self._get_visible_accounts(context, img)
            if not accounts:
                logger.error(
                    "SwitchAccountSelect failed to recognize any visible accounts"
                )
                return CustomAction.RunResult(success=False)

            self._log_visible_accounts(accounts, page_index + 1)

            if normalized_target:
                for account in accounts:
                    if self._match_target(normalized_target, account.normalized_text):
                        self._click_account_row(context, account.row_roi)
                        logger.info(f"匹配到目标账号: {target_account}")
                        return CustomAction.RunResult(success=True)

            page_signature = self._build_page_signature(accounts)
            if page_signature and page_signature in seen_signatures:
                if not normalized_target:
                    self._click_account_row(context, accounts[-1].row_roi)
                    logger.info("选择列表底部最后一个账号")
                    return CustomAction.RunResult(success=True)
                logger.error(f"到达账号列表底部，未找到目标账号: {target_account}")
                return CustomAction.RunResult(success=False)

            if page_signature:
                seen_signatures.add(page_signature)

            if page_index >= self._max_swipes - 1:
                break

            self._swipe_to_next_page(context)

        if not normalized_target:
            logger.error("达到最大滑动次数")
            return CustomAction.RunResult(success=False)

        logger.error(f"未找到目标账号: {target_account}")
        return CustomAction.RunResult(success=False)

    def _get_visible_accounts(self, context: Context, img) -> list[_VisibleAccount]:
        anchors = self._get_row_anchors(context, img)
        if not anchors:
            return []

        centers = [int(box[1] + box[3] / 2) for box in anchors]
        accounts: list[_VisibleAccount] = []

        for index, anchor in enumerate(anchors):
            center = centers[index]
            top = (
                max(self._list_top, int((centers[index - 1] + center) / 2))
                if index > 0
                else max(self._list_top, center - 45)
            )
            bottom = (
                min(self._list_bottom, int((center + centers[index + 1]) / 2))
                if index < len(anchors) - 1
                else min(self._list_bottom, center + 45)
            )
            right = max(self._list_left + 120, int(anchor[0]) - 20)
            row_roi = (
                self._list_left,
                top,
                right - self._list_left,
                max(40, bottom - top),
            )
            row_text = self._read_row_text(context, img, row_roi)
            accounts.append(
                _VisibleAccount(
                    row_roi=row_roi,
                    text=row_text,
                    normalized_text=self._normalize_text(row_text),
                )
            )

        return accounts

    def _get_row_anchors(
        self, context: Context, img
    ) -> list[tuple[int, int, int, int]]:
        for node_name in ("SwitchAccountRowAnchor", "SwitchAccountRowAnchor_1440p"):
            reco_detail = context.run_recognition(node_name, img)
            anchors = self._extract_boxes(reco_detail)
            if anchors:
                return anchors
        return []

    def _extract_boxes(self, reco_detail) -> list[tuple[int, int, int, int]]:
        if reco_detail is None or not reco_detail.hit:
            return []

        boxes: list[tuple[int, int, int, int]] = []
        for result in getattr(reco_detail, "filtered_results", []) or []:
            box = getattr(result, "box", None)
            if box:
                boxes.append((int(box[0]), int(box[1]), int(box[2]), int(box[3])))

        if not boxes:
            best = getattr(reco_detail, "best_result", None)
            box = getattr(best, "box", None) if best is not None else None
            if box:
                boxes.append((int(box[0]), int(box[1]), int(box[2]), int(box[3])))

        boxes.sort(key=lambda box: box[1] + box[3] / 2)

        deduped: list[tuple[int, int, int, int]] = []
        for box in boxes:
            if (
                deduped
                and abs((deduped[-1][1] + deduped[-1][3] / 2) - (box[1] + box[3] / 2))
                < 20
            ):
                continue
            deduped.append(box)
        return deduped

    def _read_row_text(
        self, context: Context, img, row_roi: tuple[int, int, int, int]
    ) -> str:
        reco_detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(roi=row_roi, order_by="Vertical"),
            img,
        )
        if reco_detail is None or not reco_detail.hit:
            return ""

        texts: list[str] = []
        for result in getattr(reco_detail, "filtered_results", []) or []:
            text = (getattr(result, "text", "") or "").strip()
            if text:
                texts.append(text)

        if not texts:
            best = getattr(reco_detail, "best_result", None)
            text = (getattr(best, "text", "") or "").strip() if best is not None else ""
            if text:
                texts.append(text)

        return " ".join(texts)

    def _click_account_row(
        self, context: Context, row_roi: tuple[int, int, int, int]
    ) -> None:
        x, y, w, h = row_roi
        context.tasker.controller.post_click(x + w // 2, y + h // 2).wait()
        time.sleep(1)

    def _swipe_to_next_page(self, context: Context) -> None:
        context.tasker.controller.post_swipe(
            self._swipe_from[0],
            self._swipe_from[1],
            self._swipe_to[0],
            self._swipe_to[1],
            duration=600,
        ).wait()
        time.sleep(1)

    def _log_visible_accounts(
        self, accounts: list[_VisibleAccount], page_index: int
    ) -> None:
        visible = [account.text or "<empty>" for account in accounts]
        logger.info(f"page {page_index}: {' | '.join(visible)}")

    def _build_page_signature(self, accounts: list[_VisibleAccount]) -> tuple[str, ...]:
        return tuple(
            account.normalized_text for account in accounts if account.normalized_text
        )

    def _match_target(self, target: str, candidate: str) -> bool:
        if not target or not candidate:
            return False
        if target == candidate or target in candidate:
            return True
        return len(candidate) >= 4 and candidate in target

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"[\W_]+", "", text or "").lower()
