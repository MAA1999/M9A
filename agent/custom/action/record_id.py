from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.pipeline import JOCR, JRecognitionType
from utils import logger


@AgentServer.custom_action("RecordID")
class RecordID(CustomAction):
    global_user_name: str = ""
    global_id: str = ""
    _user_name_roi: tuple[int, int, int, int] = (29, 99, 115, 20)
    _id_roi: tuple[int, int, int, int] = (54, 116, 92, 20)

    @classmethod
    def current_account_id(cls) -> str:
        return cls.global_id.strip()

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        img = context.tasker.controller.cached_image

        user_name = ""
        account_id = ""

        reco_detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(roi=self._user_name_roi, only_rec=True),
            img,
        )
        if reco_detail and reco_detail.hit:
            user_name = reco_detail.best_result.text.strip()
        else:
            logger.info("未识别到用户名文本")

        reco_detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(roi=self._id_roi, only_rec=True),
            img,
        )
        if reco_detail and reco_detail.hit:
            account_id = reco_detail.best_result.text.strip()
        else:
            logger.info("未识别到ID文本")

        if user_name != RecordID.global_user_name or account_id != RecordID.global_id:
            RecordID.global_user_name = user_name
            RecordID.global_id = account_id
            logger.info(f"欢迎: {user_name} - {account_id}")

        return CustomAction.RunResult(success=True)
