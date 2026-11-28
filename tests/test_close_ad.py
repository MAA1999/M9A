"""CloseAd 哨兵测试：两种按钮形态的命中/未命中契约，与渠道服的启用开关。

算法细节（多尺度 F1 匹配、边长扫描）不在此测——它由华为服实跑验证过；
这里防的是：识别名与 pipeline 节点漂移、渠道服漏开或官服误开、
纯「X」形态失效、阈值对非按钮画面的误配，以及 ROI / 边长参数的边界行为。
"""

import json
import math
import re
from pathlib import Path
from typing import Any, cast

import numpy as np
from maa.custom_recognition import CustomRecognition
from maa.define import Rect
from PIL import Image, ImageDraw

from agent.custom.reco.close_ad import CloseAd

ROOT = Path(__file__).resolve().parents[1]
NODE_ROI = Rect(800, 0, 480, 400)
ICON_CENTER = (1013, 113)


def _blank() -> Image.Image:
    return Image.new("RGB", (1280, 720), (40, 40, 44))


def _to_bgr(image: Image.Image) -> np.ndarray:
    return np.array(image)[:, :, ::-1].copy()  # RGB -> BGR


def _circle_x_screen(radius: int = 13) -> np.ndarray:
    """「圆圈 + X」：华为服实测的广告关闭按钮形态。"""
    cx, cy = ICON_CENTER
    image = _blank()
    draw = ImageDraw.Draw(image)
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=(255, 255, 255), width=2)
    offset = radius / math.sqrt(2.0)
    draw.line([cx - offset, cy - offset, cx + offset, cy + offset], fill=(255, 255, 255), width=2)
    draw.line([cx + offset, cy - offset, cx - offset, cy + offset], fill=(255, 255, 255), width=2)
    return _to_bgr(image)


def _bare_x_screen(radius: int = 13, width: int = 2) -> np.ndarray:
    """纯「X」：没有外圈的那种关闭按钮。"""
    cx, cy = ICON_CENTER
    image = _blank()
    draw = ImageDraw.Draw(image)
    draw.line([cx - radius, cy - radius, cx + radius, cy + radius], fill=(255, 255, 255), width=width)
    draw.line([cx + radius, cy - radius, cx - radius, cy + radius], fill=(255, 255, 255), width=width)
    return _to_bgr(image)


def _analyze(
    image: np.ndarray,
    *,
    roi: Rect = NODE_ROI,
    **param_overrides: object,
) -> CustomRecognition.AnalyzeResult:
    params: dict[str, object] = {"thresholds": {"circle_x": 0.65, "x": 0.7}}
    params.update(param_overrides)
    argv = CustomRecognition.AnalyzeArg(
        task_detail=cast(Any, None),
        node_name="CloseAd",
        custom_recognition_name="CloseAd",
        custom_recognition_param=json.dumps(params),
        image=image,
        roi=roi,
    )
    return CloseAd().analyze(cast(Any, None), argv)


def _pipeline(relative_path: str | Path) -> dict[str, object]:
    """读 pipeline（jsonc）。只支持整行 // 注释——写成行内注释会让这里以 JSON 解析错误的形式红。"""
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    return json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE))


def _assert_located(result: CustomRecognition.AnalyzeResult, shape: str) -> None:
    assert result.box is not None
    x, y, w, h = result.box
    cx, cy = ICON_CENTER
    assert abs(x + w / 2 - cx) <= 3, f"横向偏移过大: {result.box}"
    assert abs(y + h / 2 - cy) <= 3, f"纵向偏移过大: {result.box}"
    assert result.detail["shape"] == shape


def test_circle_icon_is_located() -> None:
    """「圆圈 + X」必须被定位到原位置附近，否则点击会落到弹窗外。"""
    _assert_located(_analyze(_circle_x_screen()), "circle_x")


def test_bare_x_is_located() -> None:
    """纯「X」没有外圈佐证，靠独立模板命中，形态要能区分出来。"""
    _assert_located(_analyze(_bare_x_screen()), "x")


def test_bare_x_is_located_at_small_size() -> None:
    """小一号的纯 X（20px）也要命中，否则小按钮会漏。"""
    _assert_located(_analyze(_bare_x_screen(radius=10)), "x")


def test_bare_x_with_thick_stroke_is_located() -> None:
    """真实按钮的笔画比模板比例更粗（样片实测约占边长 1/10），加粗后仍要命中。"""
    _assert_located(_analyze(_bare_x_screen(radius=13, width=3)), "x")


def test_roi_comes_from_framework_field() -> None:
    """识别区域取 argv.roi：节点 roi 之外不该命中，全屏 roi 应当命中。"""
    assert _analyze(_circle_x_screen(), roi=Rect(0, 0, 400, 300)).box is None
    _assert_located(_analyze(_circle_x_screen(), roi=Rect(0, 0, 1280, 720)), "circle_x")


def test_max_side_only_is_honoured() -> None:
    """只写 max_side=12 时按 12px 搜，不被默认下限 16 顶掉。"""
    result = _analyze(_circle_x_screen(), max_side=12)
    assert result.box is not None
    assert result.detail["side"] == 12


def test_invalid_side_param_is_treated_as_unset() -> None:
    """畸形 param（1e309 解析成 inf）不能让 analyze 抛异常，也不能顶掉另一侧的有效配置。"""
    assert _analyze(_to_bgr(_blank()), min_side=float("inf")).box is None
    assert _analyze(_circle_x_screen(), min_side=float("inf"), max_side=12).box is not None


def test_explicit_reversed_side_range_is_miss() -> None:
    """min_side 显式大于 max_side 属于配置写反，按未命中处理，而不是把上限抬上去。"""
    result = _analyze(_circle_x_screen(), min_side=40, max_side=20)
    assert result.box is None
    assert result.detail["reason"] == "边长区间非法"


def test_shapes_can_be_restricted_to_circle_only() -> None:
    """shapes 收窄到 circle_x 时，纯 X 不再命中——渠道要压误配时用这个开关。"""
    assert _analyze(_bare_x_screen(), shapes=["circle_x"]).box is None


def test_blank_screen_does_not_hit() -> None:
    """暗到没有笔画像素的画面在 screen_mask.any() 处就早退了，这里只锁早退路径。"""
    assert _analyze(_to_bgr(_blank())).box is None


def test_bright_clutter_does_not_hit() -> None:
    """亮色散点要走完整的 F1 评分与阈值判断后仍不命中——这才是纯 X 的误配边界。"""
    rng = np.random.default_rng(0)
    noise = rng.integers(60, 240, (720, 1280, 3), dtype=np.uint8)  # BGR，大量亮像素
    assert _analyze(noise).box is None


def test_base_defines_close_ad_disabled_and_wires_it_into_startup() -> None:
    """节点定义与 next 挂在 base，官服等无广告渠道靠 enabled:false 不参与轮询。"""
    base = _pipeline("resource/base/pipeline/startup.json")
    node = base["CloseAd"]
    param = node["recognition"]["param"]  # type: ignore[index]
    assert node["enabled"] is False  # type: ignore[index]
    assert param["custom_recognition"] == "CloseAd"
    # ROI 必须写在框架字段上：不写就是全屏，既慢又画不出调试图
    assert param["roi"] == [800, 0, 480, 400]
    assert "roi" not in param["custom_recognition_param"]
    assert set(param["custom_recognition_param"]["shapes"]) == {"circle_x", "x"}
    assert set(param["custom_recognition_param"]["thresholds"]) == {"circle_x", "x"}
    for parent in ("StartUp", "StartGame"):
        assert "[JumpBack]CloseAd" in base[parent]["next"], f"{parent}.next 未挂 CloseAd"  # type: ignore[index]


def test_close_ad_runs_after_reward_claim_nodes() -> None:
    """CloseAd 必须排在签到/奖励领取节点之后，否则先点掉 X 会导致奖励没领（905bc118）。"""
    base = _pipeline("resource/base/pipeline/startup.json")
    for parent in ("StartUp", "StartGame"):
        order = base[parent]["next"]  # type: ignore[index]
        for claim in ("[JumpBack]SignInReward", "[JumpBack]ClosePageFirst"):
            assert order.index("[JumpBack]CloseAd") > order.index(claim), f"{parent}.next: CloseAd 抢在 {claim} 前面"


def test_reward_page_close_button_is_a_known_false_positive() -> None:
    """签到/奖励页的关闭按钮会被纯 X 模板命中——这就是 CloseAd 必须排在后面的原因。

    模板取自仓库的 CloseRewardPage_2.2（green mask 还原成深色页面背景），实测 x 得分 0.939；
    它和广告的 X 同形，调阈值分不开，只能靠 next 顺序保证先领奖再关页。
    """
    template = Image.open(ROOT / "resource/base/image/StartUp/CloseButton/CloseRewardPage_2.2.png").convert("RGB")
    rgb = np.array(template).astype(int)
    green = rgb[:, :, 1] - np.maximum(rgb[:, :, 0], rgb[:, :, 2]) > 40
    rgb[green] = (23, 23, 25)  # green mask -> 深色页面背景
    canvas = Image.new("RGB", (1280, 720), (23, 23, 25))
    canvas.paste(Image.fromarray(rgb.astype(np.uint8)), (1000, 100))
    result = _analyze(_to_bgr(canvas))
    assert result.box is not None
    assert result.detail["shape"] == "x"


def test_only_expected_channels_enable_close_ad() -> None:
    """有启动广告的渠道各自开启；新增渠道要在这里补一条，避免悄悄扩到其他渠道。"""
    enabling = set()
    for startup in sorted((ROOT / "resource").glob("*/pipeline/startup.json")):
        node = _pipeline(startup.relative_to(ROOT)).get("CloseAd")
        if isinstance(node, dict) and node.get("enabled") is True:
            enabling.add(startup.parent.parent.name)
    assert enabling == {"huawei", "bilibili"}, f"实际开启的渠道：{sorted(enabling)}"
