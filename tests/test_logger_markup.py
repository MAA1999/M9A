from agent.utils.logger import _format_mxu_html_message


def test_mxu_restores_font_markup() -> None:
    """colorize_name 产出的 <font color> 标记在转义后应还原，供 MXU 日志面板渲染。"""
    line = '材料 <font color="#E5A32A">自走惊吓夜</font> 已达标'
    html = _format_mxu_html_message("INFO", line)
    assert '<font color="#E5A32A">自走惊吓夜</font>' in html
    assert "&lt;font" not in html


def test_mxu_keeps_other_markup_escaped() -> None:
    """白名单之外的 HTML（脚本、非法色值、残缺标签）必须保持转义。"""
    html = _format_mxu_html_message("INFO", '<script>alert("x")</script> <font color="red">x</font>')
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    assert "&lt;font color=&quot;red&quot;&gt;" in html


def test_mxu_wraps_each_line_in_level_span() -> None:
    html = _format_mxu_html_message("WARNING", "第一行\n第二行")
    lines = html.split("\n")
    assert lines == [
        '<span style="color:darkorange;">第一行</span>',
        '<span style="color:darkorange;">第二行</span>',
    ]
