from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context
import json
from maa.pipeline import JClick  

@AgentServer.custom_action("FrameArtAction")
class FrameArtAction(CustomAction):
    """
    点击不同位置的主题，判断是否匹配预期主题
    """
    def run(self, context: Context, argv):
        # 读取参数
        params = json.loads(argv.custom_action_param)
        
        # 四个不同的主题位置 (ROI格式: x, y, w, h)
        click_rois = [[1122,137,46,30],[1136,250,36,32],[1128,351,50,25],[1132,449,50,26]]
        
        # 获取OCR识别参数
        expected_text = params.get("expected_text", "")
        
        # 遍历点击位置
        for roi in click_rois:
            # 点击主题位置
            context.run_action_direct("Click",JClick(target=roi))
            context.wait_freezes(100,tuple(roi))
            
            # 获取当前截图
            img = context.tasker.controller.post_screencap().wait().get()
            
            # 进行OCR识别，判断是否匹配预期文本
            ocr_result = context.run_recognition(
                "frame_art_expected",
                img,
                {
                    "frame_art_expected":{
                    "expected": expected_text
                    }
                  
                }
                )
            if ocr_result and ocr_result.hit:
                context.run_task("frame_art_switch")
                return CustomAction.RunResult(success=True)
       
        
        # 所有位置都点击后仍未匹配，报错
        return CustomAction.RunResult(success=False)
