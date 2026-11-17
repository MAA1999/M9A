"""CloseAd 哨兵测试：掩码识别的命中/未命中契约，与渠道服的启用开关。

算法细节（多尺度 F1 匹配、尺度扫描）不在此测——它由华为服实跑验证过；
这里防的是：识别名与 pipeline 节点漂移、渠道服漏开或官服误开，
以及「圆圈+X」图标的定位能力回退。
"""

import json
import math
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

from agent.custom.reco.close_ad import CloseAd

ROOT = Path(__file__).resolve().parents[1]
ROI = [800, 0, 480, 400]


def _screen(icon: tuple[int, int, int] | None) -> np.ndarray:
    """造一张 1280x720 的 BGR 画面；给定 (cx, cy, r) 时画上「圆圈+X」。"""
    image = Image.new("RGB", (1280, 720), (40, 40, 44))
    if icon is not None:
        cx, cy, r = icon
        draw = ImageDraw.Draw(image)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255), width=2)
        offset = r / math.sqrt(2.0)
        draw.line([cx - offset, cy - offset, cx + offset, cy + offset], fill=(255, 255, 255), width=2)
        draw.line([cx + offset, cy - offset, cx - offset, cy + offset], fill=(255, 255, 255), width=2)
    return np.array(image)[:, :, ::-1].copy()  # RGB -> BGR


def _analyze(image: np.ndarray) -> object:
    param = json.dumps({"roi": ROI, "threshold": 0.65, "max_scale": 1.0})
    argv = SimpleNamespace(image=image, custom_recognition_param=param, node_name="CloseAd")
    return CloseAd().analyze(None, argv)  # type: ignore[arg-type]


def _pipeline(relative_path: str) -> dict[str, object]:
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    return json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE))  # pipeline 是 jsonc


def test_close_icon_is_located() -> None:
    """画的按钮必须被定位到原位置附近，否则点击会落到弹窗外。"""
    result = _analyze(_screen((1013, 113, 13)))
    assert result.box is not None  # type: ignore[attr-defined]
    x, y, w, h = result.box  # type: ignore[attr-defined]
    assert abs(x + w / 2 - 1013) <= 3
    assert abs(y + h / 2 - 113) <= 3
    assert result.detail["score"] >= 0.65  # type: ignore[attr-defined]


def test_blank_screen_does_not_hit() -> None:
    """无广告的画面不得命中，否则会在启动流程里乱点。"""
    assert _analyze(_screen(None)).box is None  # type: ignore[attr-defined]


def test_base_defines_close_ad_disabled_and_wires_it_into_startup() -> None:
    """节点定义与 next 挂在 base，官服等无广告渠道靠 enabled:false 不参与轮询。"""
    base = _pipeline("resource/base/pipeline/startup.json")
    node = base["CloseAd"]
    assert node["enabled"] is False  # type: ignore[index]
    assert node["recognition"]["param"]["custom_recognition"] == "CloseAd"  # type: ignore[index]
    for parent in ("StartUp", "StartGame"):
        assert "[JumpBack]CloseAd" in base[parent]["next"], f"{parent}.next 未挂 CloseAd"  # type: ignore[index]


def test_channel_resources_enable_close_ad() -> None:
    """有启动广告的渠道各自开启，新增渠道时在这里补一条。"""
    for channel in ("huawei", "bilibili"):
        node = _pipeline(f"resource/{channel}/pipeline/startup.json")["CloseAd"]
        assert node["enabled"] is True, f"{channel} 未开启 CloseAd"  # type: ignore[index]
