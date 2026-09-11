# -*- coding: utf-8 -*-
"""edge.py — 「拾遗」桌面悬浮窗:贴屏幕右缘,鼠标悬停展开,随手存一条。

用法:
    python edge.py [--edge right|left]

纯标准库(tkinter)。收起时只露 8px 粉色细条(无字),悬停滑入;移出
1 秒后滑出。面板四角圆角(SetWindowRgn 窗口区域裁剪)。右上角三个
无边框纯黑图标(图钉=钉住、减号=收、×=退),悬浮渐变为 #EFA3C8;
「退」退出(窗口无任务栏图标)。

配色与网页版同一套(奶油米色底、芥末黄、荧光浅绿、纯黑文字)。
小面板平时只有标题 + 两个按钮:

- 「+ 存一条」:点开才展开表单(文本框 + 理由 + 存入/清空)。
  粘贴或打字 → 点「存入」→ 后台调 DeepSeek 生成摘要与标签
  (不卡界面)→ 补一句理由(可留空,标「(待补)」)→ 直接写入
  notes/,格式与 ingest.py 一致。存完自动收回表单。
- 「打开网页版」:自动拉起 web.py(没在跑就先启动)并开浏览器,
  面板随即收起,不挡网页。

Esc:表单开着先收表单,再按收面板。浏览、搜索、回顾在网页版与 CLI。

窗口行为说明:

- 鼠标进出不用 Enter/Leave 事件(overrideredirect + 动画下不可靠),
  改为主循环每 120ms 轮询 winfo_pointerxy() 做状态机。
- 显式收起(Esc/「收」)后需要指针先离开细条区域,悬停才会再次展开,
  避免「按 Esc 收起 → 指针还在条上 → 又弹出来」。
- 仅主屏;DPI 感知在启动时声明,高分屏缩放不偏位。
"""

import argparse
import ctypes
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import traceback
import webbrowser

import common

# ---- 与网页版同一套配色 ----
CREAM = "#F6F1E7"      # 奶油米色(网页版 --cream)
PANEL_BG = "#FBF7EE"   # 文本框底(网页版 --panel)
MUSTARD = "#F0C94F"    # 芥末黄(细条 / 「+ 存一条」)
GREEN = "#C9E86C"      # 荧光浅绿(「打开网页版」)
INK = "#000000"        # 纯黑文字(网页版同款)
GREY = "#9C9484"       # 占位提示 / 次要文字(暖灰)
HOVER = "#EFA3C8"      # 右上角图标悬浮色
PINK = "#F3C7C1"       # 细条色(网页版 --pink,用户指定)
CORNER_R = 26          # 面板圆角半径

WEB_PORT = 8000        # web.py 默认端口

STRIP_W = 8            # 收起时露出宽度
PANEL_W = 280          # 小面板:不遮挡屏幕
COMPACT_H = 220        # 平时:标题 + 两个按钮 + 状态
FULL_H = 400           # 展开表单后
MARGIN = 30            # 展开态收起判定的缓冲边距
COLLAPSE_MS = 1000     # 移出后多久收起(用户要求 1 秒)
POLL_MS = 120
ANIM_STEPS = 7
ANIM_MS = 12

PLACEHOLDER_TEXT = "把要存的东西粘进来…(Ctrl+V)"
PLACEHOLDER_REASON = "为什么存它?(可留空)"
REASON_EMPTY = "(待补)"      # 与 ingest.py 一致

TITLE_MAX = 30         # 标题字段上限
STEM_MAX = 40          # 文件名主干上限
ILLEGAL_CHARS = '\\/:*?"<>|'

SERIF_CANDIDATES = ("Noto Serif SC", "Source Han Serif SC", "Songti SC",
                    "SimSun", "STSong", "Microsoft YaHei")
SANS_CANDIDATES = ("Microsoft YaHei", "PingFang SC", "SimHei", "Segoe UI")


def set_dpi_aware():
    """声明 DPI 感知,否则 125%/150% 缩放下坐标与物理像素错位。"""
    try:
        ctypes.windll.user32.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass  # 老系统没有也无妨,只是可能缩放错位


def declare_gdi_types():
    """64 位下不声明 argtypes/restype 会把句柄当 32 位 int 截断
    (高位丢光),DeleteObject 可能删错对象甚至崩溃;声明一次保平安。"""
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.GetParent.argtypes = [ctypes.c_void_p]
    user32.GetParent.restype = ctypes.c_void_p
    user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_int]
    user32.SetWindowRgn.restype = ctypes.c_int
    gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
    gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteObject.restype = ctypes.c_int


def round_rect(canvas, x1, y1, x2, y2, r, **kw):
    """tkinter 没有圆角矩形,用 smooth 多边形模拟。"""
    pts = (x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1)
    return canvas.create_polygon(pts, smooth=True, **kw)


def web_alive():
    """web.py 是否已在本机端口上响应。"""
    try:
        with socket.create_connection(("127.0.0.1", WEB_PORT), timeout=0.4):
            return True
    except OSError:
        return False


def blend_hex(c1, c2, t):
    """两个 #RRGGBB 颜色按比例 t 线性混合(图标悬浮过渡用)。"""
    a = (int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16))
    b = (int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16))
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t)
                                   for i in range(3))


class EdgeApp:
    def __init__(self, edge="right"):
        self.edge = edge
        self.state = "collapsed"   # collapsed / expanded / locked
        self.armed = True          # 显式收起后要等指针离开细条才允许再展开
        self.collapse_job = None
        self.anim_job = None
        self.busy = False          # 「存入」请求进行中
        self.web_opening = False   # 正在拉起网页版
        self.text_ph = True        # 文本框还停在占位提示
        self.reason_ph = True
        self.form_open = False     # 「+ 存一条」表单是否展开
        self.hover_slot = -1       # 当前悬停的图标槽位(-1=无)
        self.icon_colors = [INK, INK, INK]   # 各图标当前颜色(含过渡中)
        self.icon_fades = {}       # slot → after id(颜色过渡任务)
        self.panel_h = COMPACT_H
        self.region = None       # 圆角区域句柄(SetWindowRgn,重设后删旧)
        self.queue = queue.Queue()
        self.quitting = False    # 退出中:停止轮询续排,避免销毁竞态
        self.poll_job = None
        self.queue_job = None
        # 按钮文案(底部状态小字已删,反馈借按钮短暂闪现)
        self.add_btn_text = "+ 存一条"
        self.web_btn_text = "打开网页版"
        self.add_flash_job = None
        self.web_flash_job = None
        self.save_flash_job = None

        self.root = tk.Tk()
        self.root.withdraw()       # 无任务栏图标
        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()
        # 顶边固定:表单向下展开;并保证完整表单不超出屏幕
        self.y0 = min((self.screen_h - COMPACT_H) // 2,
                      self.screen_h - FULL_H - 30)

        fams = set(tkfont.families())
        self.serif = next((f for f in SERIF_CANDIDATES if f in fams),
                          SERIF_CANDIDATES[-1])
        self.sans = next((f for f in SANS_CANDIDATES if f in fams),
                         SANS_CANDIDATES[-1])

        # API key 在主线程取好;worker 线程里 load_api_key 的 sys.exit
        # 会作为 SystemExit 静默杀掉线程,结果永远回不来
        try:
            self.api_key = common.load_api_key()
        except SystemExit:
            self.api_key = None

        self._build_window()
        self._build_panel()
        self._apply_x(self._strip_x())
        self.poll_job = self.root.after(POLL_MS, self._poll)
        self.queue_job = self.root.after(150, self._poll_queue)

    # ---------- 窗口与几何 ----------

    def _build_window(self):
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=CREAM)
        self.win.protocol("WM_DELETE_WINDOW", self._quit)   # Alt+F4 也走整退
        self.win.bind("<Escape>", self._on_escape)
        self.win.bind("<Button-1>", lambda e: self.win.focus_force(), add="+")

    def _strip_x(self):
        return self.screen_w - STRIP_W if self.edge == "right" else 0

    def _panel_x(self):
        return self.screen_w - PANEL_W if self.edge == "right" else 0

    def _apply_x(self, x):
        # 注意:这里绝不碰 SetWindowRgn——移动过程中反复设区域会让
        # geometry() 失效(实机教训)。区域只在尺寸变化时单独设一次。
        self.win.geometry("%dx%d+%d+%d" % (PANEL_W, self.panel_h, x, self.y0))

    def _animate_to(self, target):
        if self.anim_job:
            self.root.after_cancel(self.anim_job)
        x0 = self.win.winfo_x()

        def step(i):
            try:
                if i >= ANIM_STEPS:
                    self.anim_job = None
                    self._apply_x(target)
                    return
                self._apply_x(x0 + (target - x0) * i // ANIM_STEPS)
            except Exception:
                self._log_error()
                if i >= ANIM_STEPS:
                    return   # 最后一步失败不再续排,交给轮询自愈
            self.anim_job = self.root.after(ANIM_MS, step, i + 1)
        step(0)

    # ---------- 展开/收起状态机 ----------

    def _expand(self):
        if self.state != "collapsed":
            return
        self.state = "expanded"
        self._cancel_collapse()
        self._animate_to(self._panel_x())
        self.win.focus_force()

    def _collapse(self):
        if self.state == "collapsed":
            return
        self.state = "collapsed"
        self.armed = False       # 等指针离开细条再允许悬停展开
        self._cancel_collapse()
        self._animate_to(self._strip_x())

    def _toggle_pin(self):
        if self.state == "locked":
            self.state = "expanded"
        else:
            self.state = "locked"
            self._cancel_collapse()
        self._update_pin_icon()

    def _schedule_collapse(self):
        if self.collapse_job:
            return
        self.collapse_job = self.root.after(COLLAPSE_MS,
                                            lambda: self._catch(self._collapse))

    def _catch(self, fn):
        """after 作业统一包一层,单个作业挂了不影响后续。"""
        try:
            fn()
        except Exception:
            self._log_error()

    def _cancel_collapse(self):
        if self.collapse_job:
            self.root.after_cancel(self.collapse_job)
            self.collapse_job = None

    def _strip_hit(self, px, py):
        x, y = self.win.winfo_x(), self.win.winfo_y()
        return (x - 4 <= px <= x + STRIP_W + 4 and y <= py <= y + self.panel_h)

    def _panel_hit(self, px, py):
        x, y = self.win.winfo_x(), self.win.winfo_y()
        return (x - MARGIN <= px <= x + PANEL_W + MARGIN and
                y - MARGIN <= py <= y + self.panel_h + MARGIN)

    def _log_error(self):
        """回调异常不掐断主循环:stderr + 项目里 edge_errors.log 各留一份。"""
        traceback.print_exc(file=sys.stderr)
        try:
            with open(os.path.join(common.BASE_DIR, "edge_errors.log"), "a",
                      encoding="utf-8") as f:
                f.write("%s\n%s\n" % (common.now_str(),
                                      traceback.format_exc()))
        except OSError:
            pass

    def _poll(self):
        try:
            if self.region is None:   # 启动时 wrapper 还没建好,窗口映射后补设圆角
                self._apply_x(self.win.winfo_x())
                self._apply_region()
            if self.state != "locked":
                px, py = self.win.winfo_pointerxy()
                if self.state == "collapsed":
                    hit = self._strip_hit(px, py)
                    if not hit:
                        self.armed = True
                    elif self.armed:
                        self._expand()
                else:  # expanded
                    if self._panel_hit(px, py):
                        self._cancel_collapse()
                    else:
                        self._schedule_collapse()
            # 自愈:动画已停但窗口还停在细条位置 → 状态纠正回收起
            if (self.state == "expanded" and self.anim_job is None
                    and abs(self.win.winfo_x() - self._strip_x()) <= 1):
                self.state = "collapsed"
        except Exception:
            self._log_error()
        if not self.quitting:
            self.poll_job = self.root.after(POLL_MS, self._poll)

    # ---------- 面板构建 ----------

    def _build_panel(self):
        self.panel = tk.Frame(self.win, bg=CREAM)
        self.panel.place(x=0, y=0, width=PANEL_W, height=FULL_H)

        # 收起时露出的粉色细条(无字),放在停靠那一边:窗口收起后该侧
        # 仍留在屏内(right 缘停在窗口 x=0,left 缘停在窗口右缘);
        # 角落由窗口区域裁掉,自然收圆
        self.strip_canvas = tk.Canvas(self.win, bg=PINK, highlightthickness=0)
        x = 0 if self.edge == "right" else PANEL_W - STRIP_W
        self.strip_canvas.place(x=x, y=0, width=STRIP_W, height=FULL_H)

        # 右上角图标:图钉 / 减号 / ×,无边框无背景,悬浮变 #EFA3C8
        self.icon_bar = tk.Canvas(self.panel, width=70, height=18,
                                  bg=CREAM, highlightthickness=0,
                                  cursor="hand2")
        self.icon_bar.place(relx=1.0, anchor="ne", x=-12, y=10)
        self._draw_icons()
        self.icon_bar.bind("<Motion>", self._on_icon_motion)
        self.icon_bar.bind("<Leave>", self._on_icon_leave)
        self.icon_bar.bind("<Button-1>", self._on_icon_click)

        # 标题行
        head = tk.Frame(self.panel, bg=CREAM)
        head.pack(fill="x", padx=20, pady=(12, 0))
        tk.Label(head, text="拾遗", bg=CREAM, fg=INK,
                 font=(self.serif, 20, "bold")).pack(side="left")

        # 主体:按钮区 / 表单二选一
        self.body = tk.Frame(self.panel, bg=CREAM)
        self.body.pack(fill="x", padx=16, pady=(6, 0))

        self.add_canvas = tk.Canvas(self.body, bg=CREAM, highlightthickness=0,
                                    height=106, cursor="hand2")
        self.add_canvas.pack(fill="x")
        self.add_canvas.bind("<Configure>", lambda e: self._draw_add_btn())

        self.form = tk.Frame(self.body, bg=CREAM)
        self.text_area = tk.Text(self.form, bg=PANEL_BG, fg=INK,
                                 relief="flat", bd=0, highlightthickness=0,
                                 wrap="char", font=(self.sans, 11), height=5,
                                 spacing1=2, spacing3=3, insertbackground=INK,
                                 undo=True)
        self.text_area.pack(fill="x")
        self.text_area.tag_configure("ph", foreground=GREY)
        self._set_text_placeholder()
        self.text_area.bind("<FocusIn>", self._on_text_focus_in)
        self.text_area.bind("<Control-Return>", lambda e: self._save())

        self.reason_entry = tk.Entry(self.form, font=(self.sans, 10), fg=GREY,
                                     bg="#FFFFFF", relief="flat", bd=0,
                                     highlightthickness=0,
                                     insertbackground=INK)
        self.reason_entry.pack(fill="x", pady=(8, 0), ipady=6)
        self._set_reason_placeholder()
        self.reason_entry.bind("<FocusIn>", self._on_reason_focus_in)
        self.reason_entry.bind("<Return>", lambda e: self._save())

        btns = tk.Frame(self.form, bg=CREAM)
        btns.pack(fill="x", pady=(8, 0))
        tk.Button(btns, text="‹ 返回", command=self._close_form,
                  font=(self.sans, 10), bg=CREAM, fg=INK, relief="flat", bd=0,
                  highlightthickness=0, activebackground=CREAM,
                  cursor="hand2").pack(side="left", ipady=4)
        tk.Button(btns, text="清空", command=self._clear, font=(self.sans, 9),
                  bg=CREAM, fg=INK, relief="flat", bd=0, highlightthickness=0,
                  activebackground=CREAM, cursor="hand2").pack(
                      side="right", padx=(0, 12), ipady=4)
        self.save_btn = tk.Button(btns, text="存入", command=self._save,
                                  font=(self.sans, 11, "bold"), bg=MUSTARD,
                                  fg=INK, relief="flat", bd=0,
                                  highlightthickness=0,
                                  activebackground=MUSTARD, cursor="hand2",
                                  padx=20)
        self.save_btn.pack(side="right", ipady=5)

    def _draw_add_btn(self):
        """两个圆角块:「+ 存一条」(展开表单)/「打开网页版」(拉起网页)。"""
        c = self.add_canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 20:
            return
        round_rect(c, 0, 0, w, 50, 16, fill=MUSTARD, outline="", tags="b1")
        c.create_text(w / 2, 25, text=self.add_btn_text, fill=INK,
                      font=(self.serif, 13, "bold"), tags="b1")
        round_rect(c, 0, 56, w, 106, 16, fill=GREEN, outline="", tags="b2")
        c.create_text(w / 2, 81, text=self.web_btn_text, fill=INK,
                      font=(self.sans, 10, "bold"), tags="b2")
        c.tag_bind("b1", "<Button-1>", lambda e: self._open_form())
        c.tag_bind("b2", "<Button-1>", lambda e: self._open_web())

    # ---------- 按钮闪现反馈(状态行小字已删) ----------

    def _flash_add_btn(self, text, ms=2500):
        self.add_btn_text = text
        self._draw_add_btn()
        if self.add_flash_job:
            self.root.after_cancel(self.add_flash_job)
        self.add_flash_job = self.root.after(ms, self._reset_add_btn)

    def _reset_add_btn(self):
        self.add_flash_job = None
        self.add_btn_text = "+ 存一条"
        self._draw_add_btn()

    def _flash_web_btn(self, text, ms=3000):
        self.web_btn_text = text
        self._draw_add_btn()
        if self.web_flash_job:
            self.root.after_cancel(self.web_flash_job)
        self.web_flash_job = self.root.after(ms, self._reset_web_btn)

    def _reset_web_btn(self):
        self.web_flash_job = None
        self.web_btn_text = "打开网页版"
        self._draw_add_btn()

    def _flash_save_btn(self, text, ms=2500):
        self.save_btn.configure(text=text)
        if self.save_flash_job:
            self.root.after_cancel(self.save_flash_job)
        self.save_flash_job = self.root.after(ms, self._reset_save_btn)

    def _reset_save_btn(self):
        self.save_flash_job = None
        if not self.busy:
            self.save_btn.configure(text="存入")

    # ---------- 右上角图标 ----------

    def _draw_icons(self):
        c = self.icon_bar
        c.delete("all")
        self.icon_items = [[], [], []]
        # 钉住:圆圈 + 竖线 + 底部短横
        cx = 9
        self.pin_circle = c.create_oval(cx - 3.5, 2, cx + 3.5, 9,
                                        outline=INK, fill=CREAM, width=1.5)
        self.icon_items[0] += [
            self.pin_circle,
            c.create_line(cx, 8, cx, 15, fill=INK, width=1.5),
            c.create_line(cx - 3, 12.5, cx + 3, 12.5, fill=INK, width=1.5),
        ]
        # 收:减号
        cx = 35
        self.icon_items[1] += [
            c.create_line(cx - 4.5, 9, cx + 4.5, 9, fill=INK, width=2,
                          capstyle="round"),
        ]
        # 退:×
        cx = 61
        self.icon_items[2] += [
            c.create_line(cx - 4, 5, cx + 4, 13, fill=INK, width=2,
                          capstyle="round"),
            c.create_line(cx + 4, 5, cx - 4, 13, fill=INK, width=2,
                          capstyle="round"),
        ]

    @staticmethod
    def _icon_slot(x):
        """槽位布局:三个 18px 宽、间隔 8px;间隙返回 -1。"""
        if x < 18:
            return 0
        if 26 <= x < 44:
            return 1
        if x >= 52:
            return 2
        return -1

    def _set_icon_color(self, slot, color):
        self.icon_colors[slot] = color
        for item in self.icon_items[slot]:
            if item == self.pin_circle:
                fill = color if self.state == "locked" else CREAM
                self.icon_bar.itemconfigure(item, outline=color, fill=fill)
            else:
                self.icon_bar.itemconfigure(item, fill=color)

    def _fade_icon(self, slot, target):
        """颜色过渡约 0.2s(5 步 × 40ms),模拟 CSS transition。"""
        if slot in self.icon_fades:
            self.root.after_cancel(self.icon_fades.pop(slot))
        start = self.icon_colors[slot]
        if start == target:
            return
        steps = 5

        def step(k):
            if k >= steps:
                self.icon_fades.pop(slot, None)
                self._set_icon_color(slot, target)
                return
            t = (k + 1) / steps
            self._set_icon_color(slot, blend_hex(start, target, t))
            self.icon_fades[slot] = self.root.after(40, step, k + 1)
        step(0)

    def _on_icon_motion(self, e):
        slot = self._icon_slot(e.x)
        if slot != self.hover_slot:
            old, self.hover_slot = self.hover_slot, slot
            if old != -1:
                self._fade_icon(old, INK)
            if slot != -1:
                self._fade_icon(slot, HOVER)

    def _on_icon_leave(self, e):
        if self.hover_slot != -1:
            self._fade_icon(self.hover_slot, INK)
            self.hover_slot = -1

    def _on_icon_click(self, e):
        slot = self._icon_slot(e.x)
        if slot == 0:
            self._toggle_pin()
        elif slot == 1:
            self._collapse()
        elif slot == 2:
            self._quit()

    # ---------- 表单展开 / 收起 ----------

    def _open_form(self):
        if self.form_open:
            return
        self.form_open = True
        self.add_canvas.pack_forget()
        self.form.pack(fill="x")
        self.panel_h = FULL_H
        self._apply_x(self.win.winfo_x())
        self._apply_region()   # 尺寸变了,圆角区域重设一次
        self.text_area.focus_set()   # 打开即想输入,顺便清掉占位提示

    def _close_form(self):
        if not self.form_open:
            return
        self.form_open = False
        self.form.pack_forget()
        self.add_canvas.pack(fill="x")
        self.panel_h = COMPACT_H
        self._apply_x(self.win.winfo_x())
        self._apply_region()   # 尺寸变了,圆角区域重设一次

    def _on_escape(self, e):
        if self.form_open:
            self._close_form()
        else:
            self._collapse()

    # ---------- 占位提示 ----------

    def _set_text_placeholder(self):
        self.text_area.delete("1.0", "end")
        self.text_area.insert("1.0", PLACEHOLDER_TEXT)
        self.text_area.tag_add("ph", "1.0", "end")
        self.text_ph = True

    def _on_text_focus_in(self, e):
        if self.text_ph:
            self.text_area.delete("1.0", "end")
            self.text_ph = False

    def _set_reason_placeholder(self):
        self.reason_entry.delete(0, "end")
        self.reason_entry.insert(0, PLACEHOLDER_REASON)
        self.reason_entry.configure(fg=GREY)
        self.reason_ph = True

    def _on_reason_focus_in(self, e):
        if self.reason_ph:
            self.reason_entry.delete(0, "end")
            self.reason_entry.configure(fg=INK)
            self.reason_ph = False

    def _clear(self):
        self._set_text_placeholder()
        self._set_reason_placeholder()

    # ---------- 存入流程 ----------

    def _save(self):
        if self.busy:
            return
        text = "" if self.text_ph else self.text_area.get("1.0", "end").strip()
        if not text:
            self._flash_save_btn("先粘贴内容")
            self.text_area.focus_set()
            return
        if not self.api_key:
            self._flash_save_btn("无 API key")
            return
        reason = "" if self.reason_ph else self.reason_entry.get().strip()
        self.busy = True
        self.save_btn.configure(state="disabled", text="生成中…")
        threading.Thread(target=self._summarize_worker,
                         args=(text, reason), daemon=True).start()

    def _summarize_worker(self, text, reason):
        """在后台线程调 API(Tk 非线程安全,结果只进队列)。"""
        try:
            result = common.summarize(text, self.api_key)
            self.queue.put(("ok", text, reason, result))
        except Exception as e:
            self.queue.put(("err", str(e)))

    def _poll_queue(self):
        try:
            while True:
                kind, *rest = self.queue.get_nowait()
                if kind == "ok":
                    self._finish_save(*rest)
                elif kind == "err":
                    self.busy = False
                    self.save_btn.configure(state="normal", text="存入")
                    self._flash_save_btn("调用失败,可重试")
                elif kind == "web_ok":
                    self.web_opening = False
                    self._collapse()
                else:  # web_err
                    self.web_opening = False
                    self._flash_web_btn("网页版启动失败")
        except queue.Empty:
            pass
        except Exception:
            self._log_error()
        if not self.quitting:
            self.queue_job = self.root.after(150, self._poll_queue)

    def _finish_save(self, text, reason, result):
        """写笔记:标题取首行,摘要/标签来自模型,格式与 ingest.py 一致。"""
        title = next((line.strip() for line in text.splitlines()
                      if line.strip()), "无标题")[:TITLE_MAX]
        meta = {
            "标题": title,
            "摘要": result["summary"],
            "标签": ", ".join(result["tags"]),
            "理由": reason or REASON_EMPTY,
            "保存时间": common.now_str(),
            "上次回顾": "",
        }
        stem = "".join(ch for ch in title
                       if ch not in ILLEGAL_CHARS).strip() or "笔记"
        stem = stem[:STEM_MAX].rstrip(". ")
        path = common.unique_path(common.NOTES_DIR, stem, ".md")
        common.write_text_file(path, common.build_note(meta, text))
        self.busy = False
        self.save_btn.configure(state="normal", text="存入")
        self._clear()
        self._close_form()
        self._flash_add_btn("已存 ✓")

    # ---------- 网页版 ----------

    def _open_web(self):
        if self.web_opening:
            return
        self.web_opening = True
        self._flash_web_btn("打开中…")
        threading.Thread(target=self._open_web_worker, daemon=True).start()

    def _open_web_worker(self):
        """网页版没在跑就无窗口拉起 web.py,起好了开浏览器。"""
        try:
            if not web_alive():
                subprocess.Popen(
                    [sys.executable, "-u", str(common.BASE_DIR / "web.py")],
                    cwd=str(common.BASE_DIR),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                for _ in range(25):   # 最多等约 5 秒
                    time.sleep(0.2)
                    if web_alive():
                        break
                else:
                    self.queue.put(("web_err",
                                    "网页版启动超时,可手动运行 python web.py"))
                    return
            webbrowser.open("http://127.0.0.1:%d" % WEB_PORT)
            self.queue.put(("web_ok",))
        except OSError as e:
            self.queue.put(("web_err", "启动网页版失败:%s" % e))

    # ---------- 杂项 ----------

    def _update_pin_icon(self):
        """图钉状态:锁定=圆圈实心。颜色跟随当前值(含悬停过渡中)。"""
        color = self.icon_colors[0]
        fill = color if self.state == "locked" else CREAM
        self.icon_bar.itemconfigure(self.pin_circle, outline=color, fill=fill)

    def _apply_region(self):
        """把窗口裁成圆角(CreateRoundRectRgn + SetWindowRgn,零依赖)。

        winfo_id() 给的是客户区 HWND(TkChild),真正的外层窗口是其父
        (TkTopLevel)——区域必须设在外层,否则裁不动。SetWindowRgn 成功后
        区域归系统所有(换区/窗口销毁时系统自会释放),绝不能 DeleteObject:
        双重释放会搞坏 GDI 句柄表,窗口连移动都会失效(实机教训)。
        """
        hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
        if not hwnd:
            return   # wrapper 还没创建;首次 _poll 会再补设一次
        r = 2 * CORNER_R
        hrgn = ctypes.windll.gdi32.CreateRoundRectRgn(
            0, 0, PANEL_W + 1, self.panel_h + 1, r, r)
        ctypes.windll.user32.SetWindowRgn(hwnd, hrgn, True)
        if hrgn:
            self.region = hrgn   # 只作「已设置」标记,句柄归系统不再碰

    def _quit(self):
        self.quitting = True
        for job in (self.poll_job, self.queue_job, self.collapse_job,
                    self.anim_job, self.add_flash_job, self.web_flash_job,
                    self.save_flash_job):
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    set_dpi_aware()
    declare_gdi_types()
    parser = argparse.ArgumentParser(description="拾遗桌面悬浮窗(随手存入)")
    parser.add_argument("--edge", choices=("right", "left"), default="right")
    args = parser.parse_args()
    print("拾遗悬浮窗已启动(%s缘)。悬停细条展开:「+ 存一条」随手存,"
          "「打开网页版」进网页;「退」退出。" % ("右" if args.edge == "right" else "左"))
    EdgeApp(edge=args.edge).run()


if __name__ == "__main__":
    main()
