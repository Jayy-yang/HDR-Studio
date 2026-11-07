"""Draw docs/architecture.png for HDR Studio.

The diagram is intentionally built from plain Pillow primitives so it can be
regenerated without Graphviz, Mermaid CLI or a browser.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "architecture.png"

W, H = 1800, 1450
SCALE = 1  # coordinates below are authored for the final output size

BG = "#0B0F14"
PANEL = "#111820"
CARD = "#17212B"
CARD_ALT = "#1B2834"
BORDER = "#2A3946"
BORDER_SOFT = "#22303B"
TEXT = "#E6EDF3"
MUTED = "#91A0AE"
DIM = "#677685"
TEAL = "#4FD1C5"
TEAL_DARK = "#1F5E5B"
AMBER = "#F6C177"
AMBER_DARK = "#5A4324"
BLUE = "#7CB7FF"
BLUE_DARK = "#244A73"
GREEN = "#8BD49C"
GREEN_DARK = "#28533A"
PINK = "#F78DA7"

FONT = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"

_font_cache: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(FONT_BOLD if bold else FONT, size, index=0)
    return _font_cache[key]


def rr(draw: ImageDraw.ImageDraw, box, radius=12, fill=CARD, outline=BORDER, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def shadow(draw: ImageDraw.ImageDraw, box, radius=12):
    x, y, x2, y2 = box
    draw.rounded_rectangle((x + 3, y + 5, x2 + 3, y2 + 5), radius=radius, fill="#070A0E")


def t(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    size: int = 14,
    color: str = TEXT,
    bold: bool = False,
    anchor: str = "la",
):
    draw.text((x, y), text, font=font(size, bold), fill=color, anchor=anchor)


def mt(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    size: int = 14,
    color=TEXT,
    bold: bool = False,
    spacing: int = 4,
    anchor: str = "la",
):
    draw.multiline_text(
        (x, y),
        text,
        font=font(size, bold),
        fill=color,
        spacing=spacing,
        anchor=anchor,
    )


def pill(draw: ImageDraw.ImageDraw, x, y, w, h, text, color, fill=None, size=12):
    rr(draw, (x, y, x + w, y + h), radius=h // 2, fill=fill or CARD, outline=color, width=1)
    draw.ellipse((x + 13, y + h // 2 - 3, x + 19, y + h // 2 + 3), fill=color)
    t(draw, x + 27, y + h // 2, text, size=size, color=color, anchor="lm")


def arrow(
    draw: ImageDraw.ImageDraw,
    x1,
    y1,
    x2,
    y2,
    color=MUTED,
    width=2,
    dashed=False,
    double=False,
    head=9,
):
    """Straight arrow with an optional dashed shaft."""
    length = math.hypot(x2 - x1, y2 - y1)
    if length <= 0:
        return
    if dashed:
        dash, gap = 7, 5
        done = 0.0
        while done < length:
            end = min(done + dash, length)
            ax = x1 + (x2 - x1) * done / length
            ay = y1 + (y2 - y1) * done / length
            bx = x1 + (x2 - x1) * end / length
            by = y1 + (y2 - y1) * end / length
            draw.line((ax, ay, bx, by), fill=color, width=width)
            done += dash + gap
    else:
        draw.line((x1, y1, x2, y2), fill=color, width=width)

    angle = math.atan2(y2 - y1, x2 - x1)
    for px, py, direction in ((x2, y2, 1), (x1, y1, -1)):
        if direction == -1 and not double:
            continue
        a = angle if direction == 1 else angle + math.pi
        p1 = (px, py)
        p2 = (px - head * math.cos(a - 0.55), py - head * math.sin(a - 0.55))
        p3 = (px - head * math.cos(a + 0.55), py - head * math.sin(a + 0.55))
        draw.polygon((p1, p2, p3), fill=color)


def panel(draw, x, y, w, h, number, title, subtitle, accent):
    shadow(draw, (x, y, x + w, y + h), radius=18)
    rr(draw, (x, y, x + w, y + h), radius=18, fill=PANEL, outline=BORDER, width=1)
    draw.rounded_rectangle((x, y, x + 4, y + h), radius=2, fill=accent)
    t(draw, x + 24, y + 14, number, size=13, color=accent, bold=True)
    t(draw, x + 58, y + 12, title, size=17, color=TEXT, bold=True)
    t(draw, x + 58, y + 36, subtitle, size=12, color=MUTED)


def card(draw, x, y, w, h, title, body="", accent=TEAL, title_size=15, body_size=12):
    shadow(draw, (x, y, x + w, y + h), radius=12)
    rr(draw, (x, y, x + w, y + h), radius=12, fill=CARD, outline=BORDER_SOFT, width=1)
    draw.rounded_rectangle((x + 1, y + 12, x + 4, y + h - 12), radius=2, fill=accent)
    t(draw, x + 18, y + 12, title, size=title_size, color=TEXT, bold=True)
    if body:
        mt(draw, x + 18, y + 37, body, size=body_size, color=MUTED, spacing=4)


def chip(draw, x, y, w, h, title, body, accent=TEAL, title_size=13, body_size=10):
    rr(draw, (x, y, x + w, y + h), radius=9, fill=CARD_ALT, outline=BORDER_SOFT, width=1)
    draw.ellipse((x + 14, y + 15, x + 20, y + 21), fill=accent)
    t(draw, x + 29, y + 10, title, size=title_size, color=TEXT, bold=True)
    if body:
        t(draw, x + 29, y + 31, body, size=body_size, color=MUTED)


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # ---------------------------------------------------------------- header
    rr(d, (60, 38, 112, 90), radius=13, fill=CARD, outline=TEAL_DARK)
    t(d, 86, 64, "HDR", size=14, color=TEAL, bold=True, anchor="mm")
    t(d, 128, 34, "HDR Studio", size=34, color=TEXT, bold=True)
    t(d, 130, 80, "多曝光合成桌面应用 · 架构总览", size=15, color=MUTED)
    pill(d, 1302, 44, 250, 32, "本地处理 · 照片不上传", TEAL, fill="#102321")
    pill(d, 1567, 44, 150, 32, "v1.0 · Windows", BLUE, fill="#102033")
    d.line((60, 120, 1740, 120), fill=BORDER, width=1)

    # ---------------------------------------------------------------- entry
    panel(d, 60, 142, 1680, 138, "01", "启动与入口", "源码、打包产物与引导逻辑", AMBER)
    cards = [
        (80, 250, "启动HDR工具.bat", "源码入口 · 自提升 UAC", AMBER),
        (345, 270, "HDR Studio.exe", "文件夹版 · 开始菜单快捷方式", BLUE),
        (630, 500, "app.py", "UAC · 依赖检查 · 资源路径 · 自检", TEAL),
        (1145, 575, "tools/build_exe.ps1", "PyInstaller → exe + 快捷方式", AMBER),
    ]
    for x, w, title, body, accent in cards:
        card(d, x, 187, w, 64, title, body, accent=accent, title_size=14, body_size=11)
    arrow(d, 775, 251, 775, 315, color=TEAL, width=2)
    t(d, 790, 279, "main()", size=11, color=TEAL)

    # dashed build hint, routed above the cards
    arrow(d, 1432, 187, 1432, 170, color=AMBER, width=1, dashed=True, head=0)
    d.line((1432, 170, 480, 170), fill=AMBER, width=1)
    arrow(d, 480, 170, 480, 187, color=AMBER, width=1, dashed=True)
    t(d, 930, 156, "build → package", size=10, color=AMBER)

    # ---------------------------------------------------------------- gui
    panel(
        d,
        60,
        315,
        1110,
        390,
        "02",
        "表现层 · Tk 主线程",
        "HDRStudioApp：三栏界面、预览与交互状态",
        TEAL,
    )
    rr(d, (80, 382, 1150, 632), radius=14, fill="#0F161D", outline=BORDER_SOFT, width=1)

    # Column 1
    t(d, 100, 398, "曝光序列", size=15, color=AMBER, bold=True)
    mt(
        d,
        100,
        427,
        "拖入 / 选择 2–5 张照片\n"
        "缩略图 · 快门 · EXIF\n"
        "排序 · 删除 · 清空\n"
        "导入进度 / 队列状态",
        size=12,
        color=MUTED,
        spacing=7,
    )
    rr(d, (100, 548, 392, 606), radius=8, fill="#121C24", outline=BORDER_SOFT)
    t(d, 114, 558, "左侧列表", size=11, color=DIM)
    t(d, 114, 578, "每张照片一张卡片，导入完成后再重建", size=10, color=TEAL)

    # Column 2
    t(d, 430, 398, "合成预览", size=15, color=TEAL, bold=True)
    t(d, 430, 425, "合成结果 / 参考帧切换", size=12, color=MUTED)
    rr(d, (430, 451, 790, 562), radius=9, fill="#0B1117", outline=BORDER)
    t(d, 610, 506, "预览画布", size=13, color=DIM, anchor="mm")
    t(d, 430, 578, "进度 · 耗时 · 警告", size=11, color=MUTED)
    t(d, 430, 600, "预览 900px 缓存，导出全分辨率", size=10, color=BLUE)

    # Column 3
    t(d, 825, 398, "合成设置", size=15, color=PINK, bold=True)
    mt(
        d,
        825,
        427,
        "自然融合 / 真实 HDR\n"
        "亮度 · 饱和度 · 细节\n"
        "自动对齐 · 去除重影\n"
        "处理尺寸 · 记住尺寸",
        size=12,
        color=MUTED,
        spacing=7,
    )
    rr(d, (825, 548, 1128, 606), radius=8, fill="#121C24", outline=BORDER_SOFT)
    t(d, 839, 558, "实时调整", size=11, color=DIM)
    t(d, 839, 578, "滑杆变化只重渲染当前预览", size=10, color=PINK)

    # submodule chips
    for x, w, title, body, accent in [
        (80, 326, "widgets.py", "自绘按钮 / 滑杆 / 开关 / 列表 / 弹窗", TEAL),
        (421, 326, "theme.py", "深色主题 · 字体 · ttk 样式", BLUE),
        (762, 388, "drop_target.py", "WM_DROPFILES → 线程安全队列 → Tk", AMBER),
    ]:
        chip(d, x, 650, w, 40, title, body, accent=accent, title_size=11, body_size=9)

    # config side panel
    panel(
        d,
        1200,
        315,
        540,
        390,
        "03",
        "状态与配置",
        "GUI 与处理核心的数据契约",
        BLUE,
    )
    card(
        d,
        1220,
        382,
        500,
        115,
        "settings.py",
        "AppSettings · JSON 持久化\n%APPDATA% 优先，项目目录回退\n输出尺寸记忆 / 下次启动",
        accent=BLUE,
        title_size=14,
        body_size=11,
    )
    card(
        d,
        1220,
        512,
        500,
        162,
        "MergeSettings / MergeResult",
        "输入：mode · tone · align · deghost\n"
        "      max_dim · 亮度 / 饱和度 / 细节\n"
        "输出：image · base_ldr · radiance\n"
        "      reference · warnings · elapsed",
        accent=TEAL,
        title_size=13,
        body_size=10,
    )
    # GUI <-> config
    arrow(d, 1150, 480, 1200, 480, color=BLUE, width=1, dashed=True, double=True)
    t(d, 1162, 463, "读写", size=9, color=BLUE)

    # ---------------------------------------------------------------- background
    panel(
        d,
        60,
        735,
        1680,
        145,
        "04",
        "并发模型 · 单进程多线程",
        "所有耗时工作离开 Tk 主线程，结果经队列回来",
        BLUE,
    )
    bg_cards = [
        (80, 330, "Tk 主线程", "控件更新 / 事件循环\nroot.after() 轮询", TEAL),
        (425, 380, "hdr-import", "inspect_image / read_image_preview\n预览 + 缩略图 · import_token", BLUE),
        (820, 360, "hdr-merge", "process_bracket\n进度回调 · job_token", GREEN),
        (1195, 525, "queue.Queue + after()", "progress · done · error\n过期 token 直接丢弃", AMBER),
    ]
    for x, w, title, body, accent in bg_cards:
        card(d, x, 782, w, 78, title, body, accent=accent, title_size=13, body_size=10)

    arrow(d, 615, 705, 615, 735, color=BLUE, width=2, double=True)
    t(d, 628, 712, "任务 / 事件", size=9, color=BLUE)

    # import/merge -> queue bus
    d.line((615, 860, 615, 878), fill=AMBER, width=1)
    d.line((1000, 860, 1000, 878), fill=AMBER, width=1)
    d.line((615, 878, 1457, 878), fill=AMBER, width=1)
    arrow(d, 1457, 878, 1457, 860, color=AMBER, width=1, head=6)
    t(d, 1025, 888, "进度 / 结果 → 队列", size=9, color=AMBER)

    # ---------------------------------------------------------------- core
    panel(
        d,
        60,
        910,
        1680,
        360,
        "05",
        "处理核心 · 无 Tk 依赖",
        "core.py 驱动图像管线；alignment.py 负责几何与纹理",
        GREEN,
    )
    stages = [
        ("读取 / 缩放", "max_dim"),
        ("公共裁切", "最小公共区"),
        ("曝光时间", "EXIF / 亮度"),
        ("自动对齐", "alignment"),
        ("去重影", "≥ 3 张"),
        ("融合 / HDR", "Mertens / radiance"),
        ("色调 / 细节", "tone + sliders"),
        ("输出结果", "LDR / radiance"),
    ]
    sx, sy, sw, sh, gap = 80, 962, 190, 58, 12
    for i, (title, sub) in enumerate(stages):
        x = sx + i * (sw + gap)
        chip(d, x, sy, sw, sh, title, sub, accent=GREEN if i < 7 else TEAL, title_size=12, body_size=9)
        if i < len(stages) - 1:
            arrow(d, x + sw + 1, sy + sh // 2, x + sw + gap - 1, sy + sh // 2, color=DIM, width=1, head=5)

    # alignment card
    card(
        d,
        80,
        1042,
        760,
        195,
        "alignment.py　对齐策略",
        "先全局对齐，再在纹理上验证；只有评分提升才采用下一层",
        accent=GREEN,
        title_size=14,
        body_size=11,
    )
    align_items = [
        ("平移", "相位相关 / 整数裁切"),
        ("相似变换", "旋转 · 缩放"),
        ("单应", "透视 / 视差"),
        ("局部纹理", "7×9 位移场"),
    ]
    for i, (title, sub) in enumerate(align_items):
        x = 100 + i * 182
        rr(d, (x, 1102, x + 168, 1156), radius=8, fill=CARD_ALT, outline=BORDER_SOFT)
        t(d, x + 12, 1112, title, size=12, color=GREEN, bold=True)
        t(d, x + 12, 1134, sub, size=9, color=MUTED)
    t(
        d,
        100,
        1172,
        "纹理评分统一在 1200px；位移 > 12% 或有效区 < 60% 时回退",
        size=10,
        color=DIM,
    )
    t(d, 100, 1198, "纯平移：整数裁切或一次亚像素重采样；相似 / 单应：warp 后裁最大内接矩形", size=10, color=DIM)

    # result card
    card(
        d,
        860,
        1042,
        380,
        195,
        "MergeResult",
        "image · base_ldr · radiance\n"
        "reference · width/height\n"
        "times · time_source\n"
        "warnings · elapsed",
        accent=TEAL,
        title_size=14,
        body_size=11,
    )
    t(d, 878, 1192, "成功 → 预览 / 实时调整 / 导出", size=10, color=TEAL)

    # save card
    card(
        d,
        1260,
        1042,
        440,
        195,
        "save_result()",
        "JPG · PNG\n"
        "16-bit TIFF\n"
        "Radiance .hdr（真实 HDR）",
        accent=AMBER,
        title_size=14,
        body_size=11,
    )
    t(d, 1278, 1178, "导出使用全分辨率；预览只渲染 900px 缓存", size=10, color=DIM)
    t(d, 1278, 1200, "OpenCV 5：.hdr 经临时文件兼容非 ASCII 路径", size=9, color=DIM)

    # core -> platform
    arrow(d, 900, 1270, 900, 1300, color=GREEN, width=2)
    t(d, 914, 1276, "调用", size=9, color=GREEN)

    # ---------------------------------------------------------------- platform
    panel(
        d,
        60,
        1300,
        1680,
        105,
        "06",
        "平台与外部依赖",
        "本机资源；无网络请求",
        MUTED,
    )
    plats = [
        ("Tkinter / Tcl-Tk", "窗口、控件、事件循环", TEAL),
        ("OpenCV · NumPy · Pillow", "解码、融合、色调、编码", GREEN),
        ("Windows Shell / UAC", "提权、WM_DROPFILES", BLUE),
        ("本地文件系统", "照片 · exports · settings.json", AMBER),
    ]
    for i, (title, sub, accent) in enumerate(plats):
        x = 80 + i * 402
        chip(d, x, 1344, 390, 44, title, sub, accent=accent, title_size=11, body_size=9)

    # ---------------------------------------------------------------- footer
    d.line((60, 1422, 1740, 1422), fill=BORDER_SOFT, width=1)
    t(d, 60, 1432, "实线 = 进程内调用 / 数据流", size=10, color=MUTED)
    t(d, 300, 1432, "虚线 = 队列 / 事件 / 构建", size=10, color=MUTED)
    t(d, 1740, 1432, "HDR Studio · docs/architecture.png", size=10, color=DIM, anchor="ra")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT} ({W}x{H})")


if __name__ == "__main__":
    main()
