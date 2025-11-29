import os
import time
import json
import ast
from PIL import Image
import numpy as np

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from utils import logger


@AgentServer.custom_action("CCChessboard")
class CCChessboard(CustomAction):
    """
    翻斗棋：棋盘位置记录
    """

    board_rois = [
        [
            [359, 178, 66, 41],
            [495, 176, 66, 42],
            [631, 175, 66, 42],
            [767, 174, 66, 42],
            [903, 173, 66, 42],
        ],
        [
            [344, 287, 68, 43],
            [482, 286, 67, 43],
            [622, 285, 68, 44],
            [762, 286, 68, 44],
            [903, 285, 68, 44],
        ],
        [
            [324, 404, 68, 44],
            [470, 403, 67, 44],
            [613, 403, 68, 44],
            [760, 404, 68, 44],
            [905, 403, 68, 44],
        ],
    ]

    # 棋盘状态：None表示空位置，{'name': str, 'level': int}表示有棋子
    board: list[list[dict[str, str | int] | None]] = [
        [None, None, None, None, None],
        [None, None, None, None, None],
        [None, None, None, None, None],
    ]

    chess_types = [
        {"name": "Knight", "max_level": 8, "positions": [(0, 0), (2, 0)]},
        {"name": "Cat4", "max_level": 4, "positions": [(2, 1)]},
        {"name": "Cat3", "max_level": 4, "positions": [(2, 2)]},
        {"name": "Cat2", "max_level": 4, "positions": [(2, 3)]},
        {"name": "Cat1", "max_level": 4, "positions": [(2, 4)]},
        {"name": "Robot4", "max_level": 4, "positions": [(0, 1)]},
        {"name": "Robot3", "max_level": 4, "positions": [(0, 1)]},
        {"name": "Robot1", "max_level": 1, "positions": [(0, 4), (0, 3), (0, 2)]},
        {"name": "Robot2", "max_level": 1, "positions": [(0, 4), (0, 3), (0, 2)]},
        {"name": "Item3", "max_level": 1, "positions": [(1, 3)]},
        {"name": "Item1", "max_level": 1, "positions": [(1, 1)]},
        {"name": "Item2", "max_level": 1, "positions": [(1, 2)]},
    ]

    board_chesses = []

    @classmethod
    def board_reset(cls):
        cls.board = [
            [None, None, None, None, None],
            [None, None, None, None, None],
            [None, None, None, None, None],
        ]
        cls.board_chesses = []
        return cls.board

    @classmethod
    def get_chess_info(cls, name: str) -> dict:
        """获取指定棋子的信息"""
        for chess in cls.chess_types:
            if chess["name"] == name:
                return chess
        if name == "unknown_1":
            return {"name": "unknown_1", "max_level": 1, "positions": [(1, 0)]}
        elif name == "unknown_2":
            return {"name": "unknown_2", "max_level": 1, "positions": [(2, 0)]}
        return {}

    @classmethod
    def place_chess(cls, row: int, col: int, name: str, level: int = 1) -> bool:
        """在指定位置放置棋子"""
        if not cls._is_valid_position(row, col):
            return False

        chess_info = cls.get_chess_info(name)
        if not chess_info:
            return False

        # 检查是否可以放置在此位置
        if (row, col) not in chess_info["positions"]:
            return False

        # 检查位置是否为空
        if cls.board[row][col] is not None:
            return False

        cls.board[row][col] = {"name": name, "level": level}
        cls.board_chesses.append({"row": row, "col": col, "name": name, "level": level})
        return True

    @classmethod
    def upgrade_chess(cls, row: int, col: int) -> bool:
        """升级指定位置的棋子"""
        if not cls._is_valid_position(row, col):
            return False

        chess = cls.board[row][col]
        if chess is None:
            return False

        chess_info = cls.get_chess_info(chess["name"])
        if chess["level"] >= chess_info.get("max_level", 1):
            return False  # 已达最高等级

        chess["level"] += 1

        # 更新board_chesses中的记录
        for item in cls.board_chesses:
            if item["row"] == row and item["col"] == col:
                item["level"] = chess["level"]
                break

        return True

    @classmethod
    def remove_chess(cls, row: int, col: int) -> bool:
        """移除指定位置的棋子"""
        if not cls._is_valid_position(row, col):
            return False

        if cls.board[row][col] is None:
            return False

        cls.board[row][col] = None

        # 从board_chesses中移除
        cls.board_chesses = [
            item
            for item in cls.board_chesses
            if not (item["row"] == row and item["col"] == col)
        ]

        return True

    @classmethod
    def find_empty_position(cls, name: str) -> tuple[int, int] | None:
        """为指定棋子找到一个空位置"""
        chess_info = cls.get_chess_info(name)
        if not chess_info:
            return None

        for row, col in chess_info["positions"]:
            if cls.board[row][col] is None:
                return (row, col)
        return None

    @classmethod
    def _is_valid_position(cls, row: int, col: int) -> bool:
        """检查位置是否有效"""
        return 0 <= row < len(cls.board) and 0 <= col < len(cls.board[0])

    @classmethod
    def can_upgrade_existing(cls, card_name: str) -> bool:
        """检查是否有现有棋子可以升级"""
        chess_info = cls.get_chess_info(card_name)
        if not chess_info:
            return False

        max_level = chess_info["max_level"]
        for chess in cls.board_chesses:
            if chess["name"] == card_name and chess["level"] < max_level:
                return True
        return False

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("CCChessboardReset")
class CCChessboardReset(CustomAction):
    """
    翻斗棋：棋盘位置重置
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        CCChessboard.board_reset()

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("CCBuyCard")
class CCBuyCard(CustomAction):
    """
    翻斗棋：购买卡牌
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        # 策略已经在reco中制定，直接从argv.reco_detail获取结果
        detail_str = argv.reco_detail.raw_detail["best"]["detail"]
        box = argv.box

        detail_data = self._parse_detail(detail_str)
        if not detail_data:
            logger.debug("无法解析detail")
            return CustomAction.RunResult(success=False)

        action = detail_data.get("action")
        card_name = detail_data.get("name")
        if not card_name:
            logger.debug("detail中没有name")
            return CustomAction.RunResult(success=False)

        if action == 0:  # 部署
            empty_pos = CCChessboard.find_empty_position(card_name)
            if not empty_pos:
                logger.debug(f"没有空位置放置 {card_name}")
                return CustomAction.RunResult(success=False)

            row, col = empty_pos
            target_roi = CCChessboard.board_rois[row][col]

            # 执行拖拽操作，先滑动再更新内部棋盘状态以避免状态不一致
            img = context.tasker.controller.cached_image
            # 用 np 截取目标区域图片
            roi_array = img[
                target_roi[1] : target_roi[1] + target_roi[3],
                target_roi[0] : target_roi[0] + target_roi[2],
            ]
            # BGR2RGB
            rgb_array = roi_array[:, :, ::-1]
            # 转换为 PIL Image
            img = Image.fromarray(rgb_array)
            # 保存图片
            save_path = "tmp/ccdeploy.png"
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            img.save(save_path)
            logger.debug(f"已保存 CCDeploy 任务目标区域截图: {save_path}")
            context.run_task(
                "CCDeploy",
                {
                    "CCDeploy": {
                        "begin": list(box),
                        "end": target_roi,
                    },
                    "CCDeployFinished": {"roi": target_roi},
                },
            )
            # 尝试更新内部棋盘状态
            if CCChessboard.place_chess(row, col, card_name):
                logger.debug(f"成功放置 {card_name} 到位置 ({row}, {col})")
                return CustomAction.RunResult(success=True)
            else:
                logger.debug(
                    f"放置 {card_name} 失败（滑动已执行），请检查界面或识别结果"
                )
                return CustomAction.RunResult(success=False)

        elif action == 1:  # 升级
            # 找到一个可以升级的位置
            for chess in CCChessboard.board_chesses:
                if (
                    chess["name"] == card_name
                    and chess["level"]
                    < CCChessboard.get_chess_info(card_name)["max_level"]
                ):
                    row, col = chess["row"], chess["col"]
                    # 计算拖拽终点（棋盘位置中心）
                    target_roi = CCChessboard.board_rois[row][col]

                    # 执行拖拽操作，先滑动再更新内部棋盘状态以避免状态不一致
                    img = context.tasker.controller.cached_image
                    # 用 np 截取目标区域图片
                    roi_array = img[
                        box[1] : box[1] + box[3],
                        box[0] : box[0] + box[2],
                    ]
                    # BGR2RGB
                    rgb_array = roi_array[:, :, ::-1]
                    # 转换为 PIL Image
                    img = Image.fromarray(rgb_array)
                    # 保存图片
                    save_path = "tmp/ccupdate.png"
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    img.save(save_path)
                    logger.debug(f"已保存 CCUpdate 任务目标区域截图: {save_path}")
                    context.run_task(
                        "CCUpdate",
                        {
                            "CCUpdate": {
                                "begin": list(box),
                                "end": target_roi,
                            },
                            "CCUpdateFinished": {"roi": list(box)},
                        },
                    )
                    if CCChessboard.upgrade_chess(row, col):
                        logger.debug(f"成功升级 {card_name} 在位置 ({row}, {col})")
                        return CustomAction.RunResult(success=True)

            logger.debug(f"没有可以升级的 {card_name}")
            return CustomAction.RunResult(success=False)

        elif action == 2:  # 卖出
            # 计算拖拽起点（卡牌中心）
            # 根据卡牌类型确定卖出位置
            if card_name in ["Item1", "Item2", "Item3", "unknown_1"]:
                # Item类卖出到第二排第一列
                row, col = 1, 0
            else:
                # 卖到第三排第一列
                row, col = 2, 0
            target_roi = CCChessboard.board_rois[row][col]
            # 执行拖拽操作，先滑动再更新内部棋盘状态以避免状态不一致
            img = context.tasker.controller.cached_image
            # 用 np 截取目标区域图片
            roi_array = img[
                target_roi[1] : target_roi[1] + target_roi[3],
                target_roi[0] : target_roi[0] + target_roi[2],
            ]
            # BGR2RGB
            rgb_array = roi_array[:, :, ::-1]
            # 转换为 PIL Image
            img = Image.fromarray(rgb_array)
            # 保存图片
            save_path = "tmp/ccdeploy.png"
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            img.save(save_path)
            logger.debug(f"已保存 CCDeploy 任务目标区域截图: {save_path}")
            context.run_task(
                "CCDeploy",
                {
                    "CCDeploy": {
                        "begin": list(box),
                        "end": target_roi,
                    },
                    "CCDeployFinished": {"roi": target_roi},
                },
            )
            context.run_task(
                "CCSellCards",
                {
                    "CCSellCards": {"begin": target_roi},
                    "CCSellCardsFinished": {
                        "roi": target_roi,
                        "roi_offset": [-40, -30, 80, 60],
                    },
                },
            )
            logger.debug(f"成功卖出 {card_name}")
            return CustomAction.RunResult(success=True)
        else:
            logger.debug(f"未知action: {action}")
            return CustomAction.RunResult(success=False)

    def _parse_detail(self, detail) -> dict | None:
        """从detail中解析type和action"""
        try:
            # 如果是字符串，先用ast.literal_eval解析
            if isinstance(detail, str):
                detail = ast.literal_eval(detail)
            # 如果是dict，直接使用
            if isinstance(detail, dict):
                return detail
            # 如果是其他，尝试json.loads
            return json.loads(str(detail))
        except Exception as e:
            logger.debug(f"解析detail失败: {e}")
            return None


@AgentServer.custom_action("CCLevelUp")
class CCLevelUp(CustomAction):
    """
    翻斗棋：粘贴处升级识别，如升级则等待
    """

    level = 1

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        max_retries = 5
        times = 0
        while times < max_retries:
            reco_detail = context.run_recognition(
                "CCLevelRec", context.tasker.controller.cached_image
            )
            if reco_detail and reco_detail.hit:
                # 识别到文字，判断等级
                current_level = int(reco_detail.best_result.text)
                if current_level > self.level:
                    logger.debug(
                        f"检测到升级，从 {self.level} 升级到 {current_level}，等待中..."
                    )
                    self.level = current_level
                    time.sleep(5)  # 等待升级动画
                    break
                elif current_level == self.level:
                    logger.debug(f"当前等级仍为 {self.level}，无需等待")
                    break
            times += 1
        return CustomAction.RunResult(success=True)

    @classmethod
    def reset_level(cls):
        cls.level = 1


@AgentServer.custom_action("CCResetData")
class CCResetData(CustomAction):
    """
    翻斗棋：重置数据
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        CCChessboard.board_reset()
        CCLevelUp.reset_level()

        return CustomAction.RunResult(success=True)
