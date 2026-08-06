import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger
from utils.maa_types import best_box, ocr_text


@AgentServer.custom_action("WarehouseInventoryScan")
class WarehouseInventoryScan(CustomAction):
    """仓库材料数量识别：扫描仓库素材页所有已配模板的材料，记录数量并落盘 JSON。

    与 BalancedFarmingAnalyze 的差异：
    - 不选关卡，只做"识别 + 保存"
    - 数据源为 data/combat/items.json 的完整材料表（按稀有度分组）
    - 输出到 data/combat/warehouse_inventory.json（可被未来功能复用）
    - 模板缺失的材料跳过并记录状态，预留未来扩展
    """

    # 材料表：全部可刷取材料（items.json，按稀有度分组）
    _ITEMS_PATH = "data/combat/items.json"
    # 输出文件：仓库数量快照（未来功能读取此文件）
    _OUTPUT_PATH = "data/combat/warehouse_inventory.json"
    # 仓库列表最多翻页次数（往返扫描：向下 6 屏 + 向上 6 屏，
    # 保证每个材料至少被读到 2-3 次，便于用众数纠正单次误读）
    _MAX_SCROLL_PAGES = 12

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        try:
            with open(self._ITEMS_PATH, encoding="utf-8") as f:
                items_by_rarity: dict[str, dict[str, dict[str, Any]]] = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"读取材料映射表失败: {self._ITEMS_PATH}, {e}")
            return CustomAction.RunResult(success=False)

        # 扁平化全部材料，记录来源稀有度分组
        materials: dict[str, dict[str, Any]] = {}
        for rarity, items in items_by_rarity.items():
            for item_id, info in items.items():
                materials[item_id] = {**info, "rarity": rarity}

        # 只保留有模板的材料（预留扩展：模板缺失的材料跳过，未来补模板即生效）
        with_template = {item_id: info for item_id, info in materials.items() if self._has_template(item_id)}
        if not with_template:
            logger.error(f"没有任何材料模板可用（{self._ITEMS_PATH} 与 image/Warehouse/ 不匹配）")
            return CustomAction.RunResult(success=False)

        # 每页都对全部材料做匹配，收集多次读数；
        # 单次读数可能被稀有度装饰条干扰（如 3→31、1→11、231→21），
        # 通过往返多轮扫描收集多次读数，用众数（出现最多的值）纠正。
        readings: dict[str, list[int]] = {item_id: [] for item_id in with_template}
        # 图标已找到但数量识别失败的材料，不能按 0 计，需排除出候选
        unreadable: set[str] = set()

        # 三段往返扫描：向下滚 → 向上滚 → 再向下滚，每个材料经过屏幕 2-3 次，
        # 收集多次读数后用众数消除单次误读。
        # 注意：先回到列表顶部再开始扫描，确保顶部材料被完整覆盖；
        # 固定扫描 12 屏：实测顶部材料（金/黄，列表最前）只经过 2 次屏幕，
        # 无法凑满 3 次，因此"全部材料 ≥3 次读数"的提前退出条件永不成立，
        # 故不做提前退出，跑满 12 屏保证覆盖与多次读数。
        logger.info("回滚到列表顶部")
        for _ in range(6):
            context.tasker.controller.post_swipe(640, 230, 640, 560, 1000).wait()
            time.sleep(0.8)
        segment = max(self._MAX_SCROLL_PAGES // 3, 2)
        for page in range(self._MAX_SCROLL_PAGES):
            logger.info(f"仓库扫描第 {page + 1}/{self._MAX_SCROLL_PAGES} 屏")
            img = context.tasker.controller.post_screencap().wait().get()
            for item_id in with_template:
                found, count = self._recognize_item(context, img, item_id)
                if not found:
                    continue
                if count is None:
                    unreadable.add(item_id)
                else:
                    readings[item_id].append(count)
            # 按方向滚动（三段：下 → 上 → 下）
            if page < segment:
                start_y, end_y = 560, 230  # 第一段向下
            elif page < segment * 2:
                start_y, end_y = 230, 560  # 第二段向上
            else:
                start_y, end_y = 560, 230  # 第三段向下
            logger.debug(f"第 {page + 1} 屏后滚动 ({start_y}->{end_y})")
            context.tasker.controller.post_swipe(640, start_y, 640, end_y, 1000).wait()
            time.sleep(1.5)

        counts: dict[str, int] = {}
        skipped: list[str] = []
        for item_id, values in readings.items():
            if values:
                counts[item_id] = self._best_count(values)
                if len(set(values)) > 1:
                    logger.warning(
                        f"材料 {with_template[item_id]['name']}({item_id}) "
                        f"多次读数不一致 {values}，取 {counts[item_id]}"
                    )
            elif item_id in unreadable:
                logger.warning(f"材料 {with_template[item_id]['name']}({item_id}) 数量识别失败，跳过")
                skipped.append(item_id)
            else:
                logger.warning(f"仓库中未找到材料 {with_template[item_id]['name']}({item_id})，按 0 计")
                counts[item_id] = 0

        if not counts:
            logger.error("没有任何材料识别成功，终止任务")
            return CustomAction.RunResult(success=False)

        # 落盘 JSON：包含数量快照 + 元信息，供未来功能读取。
        # 顺序与 data/combat/items.json 一致：按品质等级（金→黄→紫→蓝→绿）排列，
        # 同品级内按 items.json 中的条目顺序（with_template 保留了该插入顺序）。
        output = {
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "counts": {
                item_id: counts[item_id] for item_id in with_template if item_id in counts
            },
            "skipped": [item_id for item_id in with_template if item_id in skipped],
            "materials": {
                item_id: {
                    "name": with_template[item_id]["name"],
                    "rarity": with_template[item_id]["rarity"],
                }
                for item_id in with_template
            },
        }
        try:
            self._write_snapshot(output)
        except OSError as e:
            logger.error(f"写入仓库数量快照失败: {self._OUTPUT_PATH}, {e}")
            return CustomAction.RunResult(success=False)

        summary = ", ".join(
            f"{with_template[item_id]['name']}x{counts[item_id]}"
            for item_id in with_template
            if item_id in counts
        )
        logger.info(f"仓库材料数量已保存到 {self._OUTPUT_PATH}: {summary}")
        if skipped:
            logger.warning(f"本次跳过（数量识别失败）: {skipped}")

        return CustomAction.RunResult(success=True)

    def _write_snapshot(self, output: dict[str, Any]) -> None:
        """原子写入快照：先写同目录临时文件，成功后 os.replace 替换正式路径。

        避免中途失败（磁盘满/中断）在 _OUTPUT_PATH 留下损坏的部分 JSON；
        失败时清理临时文件并原样抛出。
        """
        out_path = Path(self._OUTPUT_PATH)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(out_path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, out_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _has_template(self, item_id: str) -> bool:
        """模板文件是否存在（image/Warehouse/Item-<id>.png）。"""
        return Path(f"resource/base/image/Warehouse/Item-{item_id}.png").exists()

    def _best_count(self, values: list[int]) -> int:
        """从多次读数中选最可信的数量。

        误读模式：稀有度装饰条可能被 OCR 并入数字（3→31、1→11），
        或数字被截断（231→21）。因此：
        1. 众数（出现最多的值）优先——真实读数通常重复出现；
        2. 无众数时取最长位数——截断误读（231→21）比真值短，
           而装饰条误读（3→31）虽然更长，但配合往返多轮扫描，
           真值更可能重复出现。
        """
        from collections import Counter

        counter = Counter(values)
        most_common = counter.most_common()
        if len(most_common) > 1 and most_common[0][1] > most_common[1][1]:
            return most_common[0][0]
        # 无众数：取最长位数（避免截断误读）
        return max(values, key=lambda v: (len(str(v)), v))

    def _recognize_item(self, context: Context, img: Any, item_id: str) -> tuple[bool, int | None]:
        """匹配单个材料图标并识别其下方数量。

        Returns:
            (是否找到图标, 数量)，图标找到但数量识别失败时数量为 None。
        """
        reco_detail = context.run_recognition(
            "BF_ItemIcon",
            img,
            {"BF_ItemIcon": {"recognition": {"param": {"template": f"Warehouse/Item-{item_id}.png"}}}},
        )
        box = best_box(reco_detail)
        if box is None:
            return False, None

        x, y, w, h = box
        # 数量数字在格子底部固定位置。实测（2026-08-06）：
        # - 高图标材料（金/紫/蓝，h≥80）：数字在「图标顶 +82~95px」
        # - 矮图标材料（绿/蓝，h<80）：数字在「图标底 +0~26px」
        # 按图标高度选择偏移组，避免跨组混读引入装饰条噪声。
        # 数量数字居中于图标；横向只取图标中部一半（数字区），
        # 避免把两侧装饰竖线卷入（金羊毛数字 1 + 装饰线会被 OCR 读成 11）。
        # 实测（2026-08-06）：50% 宽已覆盖 1~5 位数（如 test 材料 20023/1919）；
        # 放宽到 70% 会把金色装饰条卷入（金羊毛 1 读成 7、长青剑全空），不可取。
        dx = int(w * 0.25)
        dw = -int(w * 0.5)
        dh = 30
        if h >= 80:
            offsets = (82, 85, 90, 95)
        else:
            # 矮图标（h<80）：数字在图标底 +2~10px（实测 h=78 时 top+82 命中）
            offsets = (h + 2, h + 6, h + 10)
        candidates: list[int] = []
        for dy_top in offsets:
            if y + dy_top + dh > 718:
                continue
            count_roi = [x + dx, y + dy_top, w + dw, dh]
            count_detail = context.run_recognition(
                "BF_ItemCount",
                img,
                {"BF_ItemCount": {"recognition": {"param": {"roi": count_roi}}}},
            )
            text = ocr_text(count_detail)
            # 取最长数字组：真实数量位数多于边缘噪声误认的零散数字
            groups = re.findall(r"\d+", text.replace(",", ""))
            logger.debug(f"{item_id} box={list(box)} top={dy_top} text='{text}'")
            if groups:
                candidates.append(int(max(groups, key=len)))
        if not candidates:
            logger.warning(f"材料 {item_id} 图标已找到但数量识别失败")
            return True, None
        # 多个偏移读数取众数（出现最多的），无众数时取第一位
        from collections import Counter

        counter = Counter(candidates)
        most_common = counter.most_common()
        if len(most_common) > 1 and most_common[0][1] > most_common[1][1]:
            return True, most_common[0][0]
        return True, candidates[0]
