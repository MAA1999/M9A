"""`utils.uid_sampler` 的采样规则与错误处理。"""

from __future__ import annotations

from typing import Any

import pytest

from agent.utils import uid_sampler


class _FakeJob:
    def wait(self) -> _FakeJob:
        return self

    def get(self) -> Any:
        return _FAKE_IMAGE


class _FakeController:
    def post_screencap(self) -> _FakeJob:
        return _FakeJob()


class _FakeTasker:
    controller = _FakeController()


class _FakeDetail:
    """最小可用的识别结果：ocr_text 走 est_result → OCRResult.text。"""

    def __init__(self, text: str) -> None:
        from maa.define import OCRResult, Rect

        self.text = text
        self.hit = bool(text)
        self.box = Rect(10, 20, 30, 40) if text else None
        self.best_result = OCRResult(box=Rect(10, 20, 30, 40), text=text, score=0.99) if text else None
        self.all_results: list[object] = []
        self.filtered_results: list[object] = []


_FAKE_IMAGE = object()


class _Ctx:
    """可配置的假 Context。"""

    tasker = _FakeTasker()

    def __init__(self, texts: list[str], *, raises: type[BaseException] | None = None) -> None:
        self._texts = list(texts)
        self._raises = raises
        self.calls = 0

    def run_recognition_direct(self, *_a: object, **_k: object) -> _FakeDetail:
        self.calls += 1
        if self._raises is not None:
            raise self._raises("boom")
        return _FakeDetail(self._texts.pop(0) if self._texts else "")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """采样间隔 1 秒 × 6 次会把测试拖到 5 秒，去掉等待。"""
    monkeypatch.setattr(uid_sampler.time, "sleep", lambda _s: None)


def test_first_round_all_equal_returns_early() -> None:
    """第一轮 3 次全一致 → 立即采信，不再读第二轮。"""
    ctx = _Ctx(["ID:123456789"] * 3)
    assert uid_sampler.sample_uid(ctx) == "123456789"  # type: ignore[arg-type]
    assert ctx.calls == 3, "第一轮就一致，不该读第二轮"


def test_six_all_equal_returns_value() -> None:
    """第一轮不一致、6 次全一致 → 采信。"""
    ctx = _Ctx(["ID:A", "ID:A", "ID:B", "ID:C", "ID:C", "ID:C"])
    # 第一轮 A A B 不一致；第二轮 C C C —— 六次不全一致 → 读不到
    assert uid_sampler.sample_uid(ctx) == ""  # type: ignore[arg-type]


def test_two_mismatches_is_rejected() -> None:
    """4:2 也算读不到（用户明确要求：任何不一致都判读不到）。"""
    ctx = _Ctx(["ID:A", "ID:A", "ID:B", "ID:A", "ID:A", "ID:B"])
    assert uid_sampler.sample_uid(ctx) == ""  # type: ignore[arg-type]


def test_one_mismatch_is_rejected() -> None:
    """5:1 也算读不到 —— 比「多数表决」严格，宁可这轮不记录。"""
    ctx = _Ctx(["ID:A", "ID:A", "ID:B", "ID:A", "ID:A", "ID:A"])
    assert uid_sampler.sample_uid(ctx) == ""  # type: ignore[arg-type]


def test_all_empty_is_rejected() -> None:
    """全空（不在主页 / OCR 读不到）→ 返回空串。"""
    ctx = _Ctx(["", "", "", "", "", ""])
    assert uid_sampler.sample_uid(ctx) == ""  # type: ignore[arg-type]


def test_interface_error_is_not_swallowed() -> None:
    """接口不存在这类**程序错误**必须抛出，不能被降级成「读不到」。

    回归防护（2026-11-14 真机）：早前把所有异常都记 debug 再返回空串，
    结果采样稳定返回空、记录永不落盘，日志里却只有 debug 级线索。
    """
    ctx = _Ctx([], raises=AttributeError)
    with pytest.raises(AttributeError):
        uid_sampler.sample_uid(ctx)  # type: ignore[arg-type]


def test_id_roi_includes_id_label() -> None:
    """采样 ROI 必须比 `RecordID._id_roi` 更宽，把 `ID:` 前缀框进来。

    回归防护（2026-11-14 真机）：用源码的 `(54,116,92,20)` 只读到 `107354242`，
    没有 `ID` 标签，按新规则会被判成读不到 → 采样稳定返回空串。
    """
    roi = uid_sampler._id_roi()
    assert roi == uid_sampler._ID_ROI
    # 必须比源码 ROI 更靠左、更宽
    assert roi[0] < 54, "起点要在 ID: 左边"
    assert roi[0] + roi[2] > 54 + 92, "右边界要覆盖整个数字串"


# ---------------------------------------------------------------- 只取数字
def test_extract_digits_takes_after_id_label() -> None:
    """有 `ID:` 标签时只取冒号后面的数字。

    用户 2026-11-14：「有 ID 就取 ID 字符和冒号后的」。
    """
    assert uid_sampler.extract_digits("ID:118404470") == "118404470"
    assert uid_sampler.extract_digits("小径 ID:118404470") == "118404470"
    assert uid_sampler.extract_digits("ID：118404470") == "118404470"  # 中文冒号
    assert uid_sampler.extract_digits("id:118404470") == "118404470"  # 小写


def test_extract_digits_rejects_player_name_digits() -> None:
    """玩家名里的数字不能被拼进 UID。

    回归防护（CodeRabbit 本地审查，major）：早前是「剥离所有非数字字符」，
    `Player123 ID:118404470` 会变成 `123118404470`（13 位），
    而它正好落在 6~12 位之外才侥幸被拦；若玩家名是 `1` 位数字就会拼成 10 位
    并通过长度校验 —— 三帧一致后写进**错误的账号桶**。
    """
    assert uid_sampler.extract_digits("Player123 ID:118404470") == "118404470"


def test_extract_digits_requires_id_label() -> None:
    """没有 `ID` 标签 → 判读不到（返回空串）。

    用户 2026-11-14：「没有 ID 直接当成读不到 UID，不记录只顺延」。
    """
    assert uid_sampler.extract_digits("118404470") == ""
    assert uid_sampler.extract_digits("PlayerName 118404470") == ""


def test_extract_digits_ignores_fullwidth() -> None:
    """全角数字不是游戏 UID 会出现的字符，不能当数字收下。"""
    assert uid_sampler.extract_digits("１１８４０４４７０") == ""


def test_extract_digits_empty() -> None:
    assert uid_sampler.extract_digits("") == ""
    assert uid_sampler.extract_digits("LV.73") == ""


def test_read_once_rejects_level_and_stamina() -> None:
    """`LV.73 46040/46300` 这种等级/体力文本必须被拒。

    真机实测（2026-11-14）：主页左上角等级行的 OCR 结果是
    `LV.73` + `46040/46300`，拼起来是 `734604046300`（12 位）。
    如果只做「取数字 + 长度校验」，它会刚好落在 6~12 位区间里被误当成 UID。
    所以必须在取数字**之后**再确认原始文本里没有 `LV`。
    """
    ctx = _Ctx(["LV.73 46040/46300"] * 6)
    assert uid_sampler.sample_uid(ctx) == ""  # type: ignore[arg-type]


def test_read_once_accepts_id_prefixed_text() -> None:
    """`ID:118404470` 这种形式（带前缀）要能取出来。"""
    ctx = _Ctx(["柿柿柿柿柿子 ID:107354242"] * 3)
    assert uid_sampler.sample_uid(ctx) == "107354242"  # type: ignore[arg-type]


def test_uid_length_bounds() -> None:
    """太短/太长的数字串都不算 UID。"""
    assert not uid_sampler._looks_like_uid("12345")  # 5 位，太短
    assert uid_sampler._looks_like_uid("118404470")  # 9 位，正常
    assert not uid_sampler._looks_like_uid("1234567890123")  # 13 位，太长


def test_extract_digits_rejects_letters_inside_uid() -> None:
    """UID 里混入字母 → 整帧作废，不能删掉字母凑出一个数字。

    回归防护（CodeRabbit 本地复查，major）：
    ID:1184O4470（字母 O 冒充 0）如果只是删掉非数字，会得到 11844470（8 位），
    正好通过长度校验 → 三帧一致把错误 UID 确认下来 → 记录写进错误的账号桶。
    """
    assert uid_sampler.extract_digits("ID:1184O4470") == ""
    assert uid_sampler.extract_digits("ID:1184044O70") == ""
    assert uid_sampler.extract_digits("ID:1184-4470") == ""


def test_sample_rejects_malformed_readings() -> None:
    """三帧都带字母 → 采样仍然读不到（不会把错的值确认下来）。"""
    ctx = _Ctx(["ID:1184O4470"] * 6)
    assert uid_sampler.sample_uid(ctx) == ""  # type: ignore[arg-type]


class _BrokenController:
    """模拟接口签名不兼容：`post_screencap` 不接受调用方传的参数。"""

    def post_screencap(self, *args: object, **kwargs: object) -> object:
        raise TypeError("post_screencap() got an unexpected keyword argument")


class _BrokenTasker:
    controller = _BrokenController()


class _BrokenContext:
    tasker = _BrokenTasker()


def test_read_once_reraises_interface_type_error() -> None:
    """截图接口签名不匹配（`TypeError`）必须抛出，不能降级成「本次没读到」。

    回归防护（CodeRabbit）：`_read_once()` 曾经用一个 `except Exception` 把
    `AttributeError` / `TypeError` 也吞掉、返回空串。那样 MaaFW 升级改了接口之后，
    6 次采样会稳定返回空 → 所有按账号分桶的记录都不再落盘，而用户只看到
    「未能读取游戏内 UID」，日志里只有一堆 warning 级别的「取帧失败」，
    完全看不出是接口不兼容。

    识别块早就按这个原则分成两类，截图块当时漏了。
    """
    import pytest

    with pytest.raises(TypeError):
        uid_sampler._read_once(_BrokenContext())  # type: ignore[arg-type]


class _MissingMethodController:
    """模拟接口不存在：控制器上根本没有 `post_screencap`。"""

    pass


class _MissingMethodTasker:
    controller = _MissingMethodController()


class _MissingMethodContext:
    tasker = _MissingMethodTasker()


def test_read_once_reraises_missing_interface_attribute_error() -> None:
    """截图接口不存在（`AttributeError`）同样必须抛出。"""
    import pytest

    with pytest.raises(AttributeError):
        uid_sampler._read_once(_MissingMethodContext())  # type: ignore[arg-type]


class _FlakyController:
    """模拟截图偶发失败：抛一个普通运行时错误。"""

    def post_screencap(self) -> object:
        raise RuntimeError("画面还没准备好")


class _FlakyTasker:
    controller = _FlakyController()


class _FlakyContext:
    tasker = _FlakyTasker()


def test_read_once_returns_empty_on_transient_capture_failure() -> None:
    """偶发失败仍然返回空串（让采样继续），不能改成抛异常。"""
    assert uid_sampler._read_once(_FlakyContext()) == ""  # type: ignore[arg-type]
