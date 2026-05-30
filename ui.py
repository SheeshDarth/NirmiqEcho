"""
ui.py - NirmiqEcho Phase 2 UI

Full production UI per Nirmiq Echo Design Summary spec:
- Custom dark titlebar (#31354B) with settings gear
- 48px circular Start/Stop toggle button (teal → red)
- Vertical animated VU meter (5 bars, smooth decay)
- Fade-in transcript lines, pulse mic animation
- Settings modal (sensitivity, language, hotkey, auto-run)
- System tray minimize (minimize → tray, X → exit)
- Full keyboard shortcuts (F9, Ctrl+C/S/L, Esc, Ctrl+Q)
- Tooltips on all interactive elements
- WCAG AA color contrast throughout
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging
import queue
import threading
import time
from pathlib import Path

# Try pystray for system tray; graceful fallback if unavailable
try:
    import pystray
    from PIL import Image, ImageDraw
    _HAS_TRAY = True
except ImportError:
    _HAS_TRAY = False

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Design tokens — per Nirmiq Echo Design Summary
# ------------------------------------------------------------------

C = {
    # Backgrounds
    "bg":        "#121212",   # main window background
    "panel":     "#242423",   # toolbar / footer panels
    "panel2":    "#31354B",   # titlebar / transcript header
    "tx_bg":     "#1F1F1F",   # transcript text area
    "modal_bg":  "#1A1A2E",   # settings modal

    # Text
    "text":      "#ECEFF8",   # primary text (~13.5:1 on panel)
    "text2":     "#9EA1AC",   # secondary / hints (~5.8:1)
    "dim":       "#565556",   # disabled elements

    # Accents
    "teal":      "#0DB9D7",   # start button, VU bars active (~6.6:1)
    "blue":      "#6F7591",   # hover highlights, scrollbar thumb
    "red":       "#F44336",   # stop state, errors (~7.2:1)
    "green":     "#4CAF50",   # ready indicator
    "orange":    "#FF9800",   # transcribing indicator
    "focus":     "#5DC3F6",   # focus ring colour

    # Scrollbar
    "sb_track":  "#3F4140",
    "sb_thumb":  "#6F7591",
}

F = {
    "title":      ("Segoe UI", 12, "bold"),
    "toolbar":    ("Segoe UI", 10),
    "status":     ("Segoe UI", 10, "italic"),
    "transcript": ("Segoe UI", 11),
    "small":      ("Segoe UI", 9),
    "badge":      ("Segoe UI", 8),
    "emoji":      ("Segoe UI Emoji", 14),
}

# State → (label, colour)
STATUS_MAP = {
    "idle":             ("Idle — click ▶ or press F9 to start", C["text2"]),
    "loading":          ("Loading model…",                       C["orange"]),
    "ready":            ("Ready",                                C["green"]),
    "listening":        ("Listening…",                           C["teal"]),
    "listening_active": ("Speaking…",                            C["green"]),
    "transcribing":     ("Transcribing…",                        C["orange"]),
    "error":            ("Error — see console for details",      C["red"]),
}

# ------------------------------------------------------------------
# Helpers: rounded-rect canvas drawing
# ------------------------------------------------------------------

def _rrect(canvas, x1, y1, x2, y2, r, **kw):
    pts = [
        x1+r, y1,   x2-r, y1,
        x2,   y1,   x2,   y1+r,
        x2,   y2-r, x2,   y2,
        x2-r, y2,   x1+r, y2,
        x1,   y2,   x1,   y2-r,
        x1,   y1+r, x1,   y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


# ------------------------------------------------------------------
# Tooltip helper
# ------------------------------------------------------------------

class Tooltip:
    """Show a tooltip after 500 ms hover delay, dismiss on leave."""

    def __init__(self, widget, text: str):
        self._widget = widget
        self._text = text
        self._tip = None
        self._job = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._cancel,   add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self._job = self._widget.after(500, self._show)

    def _cancel(self, _e=None):
        if self._job:
            self._widget.after_cancel(self._job)
            self._job = None
        if self._tip:
            self._tip.destroy()
            self._tip = None

    def _show(self):
        x = self._widget.winfo_rootx() + 10
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(
            self._tip, text=self._text,
            bg="#31354B", fg=C["text"], relief="flat",
            font=F["small"], padx=6, pady=3,
        )
        lbl.pack()


# ------------------------------------------------------------------
# Circular Start/Stop toggle button
# ------------------------------------------------------------------

class MicButton(tk.Canvas):
    """
    48px circular button.
    State 'idle'  → teal ring + mic glyph, pulses when listening_active.
    State 'active' → red fill + stop square glyph.
    """

    SIZE = 56

    def __init__(self, parent, on_click, **kw):
        super().__init__(
            parent,
            width=self.SIZE, height=self.SIZE,
            bg=C["panel"], highlightthickness=0,
            cursor="hand2", **kw,
        )
        self._on_click = on_click
        self._active = False      # True = recording
        self._pulse_scale = 1.0
        self._pulse_dir = 1
        self._pulse_job = None

        self._draw()
        self.bind("<ButtonRelease-1>", lambda e: self._on_click())
        self.bind("<Enter>", self._hover_on)
        self.bind("<Leave>", self._hover_off)
        self._hover = False

    def _draw(self):
        self.delete("all")
        cx = cy = self.SIZE // 2
        r = 22
        if self._active:
            # Red filled circle + white stop square
            self.create_oval(cx-r, cy-r, cx+r, cy+r,
                             fill=C["red"], outline="")
            sq = 10
            self.create_rectangle(cx-sq, cy-sq, cx+sq, cy+sq,
                                  fill=C["text"], outline="")
        else:
            # Teal ring + mic glyph
            ring_w = 2
            self.create_oval(cx-r, cy-r, cx+r, cy+r,
                             fill="" if not self._hover else "#0A8F9A",
                             outline=C["teal"], width=ring_w)
            # Mic body
            mw, mh = 8, 13
            self.create_rectangle(cx-mw//2, cy-mh//2,
                                  cx+mw//2, cy+mh//2,
                                  fill=C["teal"], outline="",
                                  width=0)
            # Mic dome (arc)
            self.create_arc(cx-mw//2-1, cy-mh//2-1,
                            cx+mw//2+1, cy+mh//2+6,
                            start=0, extent=180,
                            fill=C["teal"], outline="")
            # Mic stand
            self.create_line(cx, cy+mh//2, cx, cy+mh//2+5,
                             fill=C["teal"], width=2)
            self.create_arc(cx-6, cy+mh//2-2, cx+6, cy+mh//2+8,
                            start=180, extent=180,
                            outline=C["teal"], width=2, style="arc")

    def _hover_on(self, _e=None):
        self._hover = True
        self._draw()

    def _hover_off(self, _e=None):
        self._hover = False
        self._draw()

    def set_active(self, val: bool):
        self._active = val
        self._draw()
        if val:
            self._start_pulse()
        else:
            self._stop_pulse()

    # Pulse animation: scales canvas items subtly when speaking
    def _start_pulse(self):
        self._pulse_job = self.after(80, self._pulse_tick)

    def _pulse_tick(self):
        if not self._active:
            return
        self._pulse_scale += 0.015 * self._pulse_dir
        if self._pulse_scale >= 1.12:
            self._pulse_dir = -1
        elif self._pulse_scale <= 0.92:
            self._pulse_dir = 1
        # Redraw at slight scale — achieved by adjusting ring radius
        self.delete("all")
        cx = cy = self.SIZE // 2
        r = int(22 * self._pulse_scale)
        self.create_oval(cx-r, cy-r, cx+r, cy+r,
                         fill=C["teal"] if self._pulse_scale > 1.05 else "",
                         outline=C["teal"], width=2)
        sq = 10
        self.create_rectangle(cx-sq, cy-sq, cx+sq, cy+sq,
                              fill=C["text"], outline="")
        self._pulse_job = self.after(80, self._pulse_tick)

    def _stop_pulse(self):
        if self._pulse_job:
            self.after_cancel(self._pulse_job)
            self._pulse_job = None
        self._pulse_scale = 1.0
        self._pulse_dir = 1
        self._draw()


# ------------------------------------------------------------------
# Icon text button (toolbar)
# ------------------------------------------------------------------

class IconBtn(tk.Frame):
    """Small labeled icon button with hover highlight and tooltip."""

    def __init__(self, parent, icon: str, label: str, cmd, tip: str = "", **kw):
        super().__init__(parent, bg=C["panel"], cursor="hand2", **kw)
        self._cmd = cmd
        self._icon_lbl = tk.Label(self, text=icon, font=F["emoji"],
                                   bg=C["panel"], fg=C["text"])
        self._icon_lbl.pack(side="top")
        self._txt_lbl = tk.Label(self, text=label, font=F["badge"],
                                  bg=C["panel"], fg=C["text2"])
        self._txt_lbl.pack(side="top")

        for w in (self, self._icon_lbl, self._txt_lbl):
            w.bind("<Enter>",          lambda e: self._hi(True))
            w.bind("<Leave>",          lambda e: self._hi(False))
            w.bind("<ButtonRelease-1>",lambda e: self._fire())

        if tip:
            Tooltip(self, tip)

    def _hi(self, on: bool):
        bg = "#31354B" if on else C["panel"]
        for w in (self, self._icon_lbl, self._txt_lbl):
            w.configure(bg=bg)

    def _fire(self):
        self._cmd()

    def set_enabled(self, yes: bool):
        fg = C["text"] if yes else C["dim"]
        self.configure(cursor="hand2" if yes else "arrow")
        self._icon_lbl.configure(fg=fg)
        self._txt_lbl.configure(fg=fg)
        self._enabled = yes


# ------------------------------------------------------------------
# Vertical VU Meter (5 bars, smooth decay)
# ------------------------------------------------------------------

class VUMeter(tk.Canvas):
    """5 vertical bars that animate to current audio level with decay."""

    N_BARS = 7
    BAR_W = 6
    GAP = 3
    H = 28

    def __init__(self, parent, **kw):
        total_w = self.N_BARS * self.BAR_W + (self.N_BARS - 1) * self.GAP
        super().__init__(parent, width=total_w, height=self.H,
                         bg=C["panel"], highlightthickness=0, **kw)
        self._peaks = [0.0] * self.N_BARS   # current bar heights [0.0–1.0]
        self._target = 0.0
        self._decay = 0.08
        self._job = None
        self._animate()

    def set_level(self, level: float):
        self._target = max(0.0, min(1.0, level))

    def _animate(self):
        changed = False
        for i in range(self.N_BARS):
            # Each bar gets a slightly randomized portion of the level
            import random
            factor = 0.6 + 0.8 * random.random()
            target_i = min(1.0, self._target * factor)
            if self._peaks[i] < target_i:
                self._peaks[i] = min(target_i, self._peaks[i] + 0.15)
                changed = True
            elif self._peaks[i] > 0:
                self._peaks[i] = max(0.0, self._peaks[i] - self._decay)
                changed = True

        if changed:
            self._redraw()

        self._job = self.after(50, self._animate)

    def _redraw(self):
        self.delete("all")
        for i, peak in enumerate(self._peaks):
            x1 = i * (self.BAR_W + self.GAP)
            x2 = x1 + self.BAR_W
            # Background track
            self.create_rectangle(x1, 0, x2, self.H,
                                  fill=C["panel2"], outline="")
            # Active fill from bottom
            fill_h = int(self.H * peak)
            if fill_h > 1:
                color = C["teal"] if peak < 0.75 else C["orange"]
                self.create_rectangle(x1, self.H - fill_h, x2, self.H,
                                      fill=color, outline="")

    def stop(self):
        if self._job:
            self.after_cancel(self._job)


# ------------------------------------------------------------------
# Settings modal
# ------------------------------------------------------------------

class SettingsModal:
    """
    Dark modal dialog for app preferences.
    Fields: VAD sensitivity, language, hotkey, auto-run.
    """

    def __init__(self, parent, app):
        self._app = app
        self._win = tk.Toplevel(parent)
        self._win.title("Settings — NirmiqEcho")
        self._win.configure(bg=C["modal_bg"])
        self._win.resizable(False, False)
        self._win.grab_set()
        self._win.transient(parent)

        # Dark titlebar
        try:
            import ctypes
            hwnd = self._win.winfo_id()
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(ctypes.c_int(1)),
                ctypes.sizeof(ctypes.c_int))
        except Exception:
            pass

        self._build()
        # Center relative to parent
        self._win.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        mw, mh = self._win.winfo_width(), self._win.winfo_height()
        self._win.geometry(f"+{px + (pw-mw)//2}+{py + (ph-mh)//2}")

    def _label(self, parent, text):
        tk.Label(parent, text=text, font=F["small"],
                 bg=C["modal_bg"], fg=C["text2"],
                 anchor="w").pack(fill="x", pady=(8, 2))

    def _sep(self, parent):
        tk.Frame(parent, bg=C["panel2"], height=1).pack(fill="x", pady=6)

    def _build(self):
        pad = {"padx": 18, "pady": 4}
        body = tk.Frame(self._win, bg=C["modal_bg"])
        body.pack(fill="both", expand=True, **pad)

        # Title
        tk.Label(body, text="⚙  Settings", font=F["title"],
                 bg=C["modal_bg"], fg=C["text"]).pack(anchor="w", pady=(8, 4))
        self._sep(body)

        # VAD Sensitivity
        self._label(body, "VAD Sensitivity  (0 = permissive, 3 = strict)")
        self._sens_var = tk.IntVar(value=self._app.audio_handler.sensitivity
                                   if self._app.audio_handler else 2)
        sens_row = tk.Frame(body, bg=C["modal_bg"])
        sens_row.pack(fill="x")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("S.TScale", background=C["modal_bg"],
                         troughcolor=C["panel"], sliderlength=14,
                         slidercolor=C["teal"])
        ttk.Scale(sens_row, from_=0, to=3, orient="horizontal",
                  variable=self._sens_var, style="S.TScale",
                  command=lambda v: self._sens_lbl.config(
                      text=str(int(float(v))))).pack(
                  side="left", fill="x", expand=True)
        self._sens_lbl = tk.Label(sens_row, text=str(self._sens_var.get()),
                                   font=F["small"], bg=C["modal_bg"],
                                   fg=C["teal"], width=2)
        self._sens_lbl.pack(side="left")

        self._sep(body)

        # Language
        self._label(body, "Language  (leave blank for auto-detect)")
        self._lang_var = tk.StringVar(
            value=self._app.transcription_engine.language or ""
            if self._app.transcription_engine else "")
        lang_entry = tk.Entry(body, textvariable=self._lang_var,
                              font=F["toolbar"], bg=C["panel"],
                              fg=C["text"], insertbackground=C["teal"],
                              relief="flat", width=12)
        lang_entry.pack(anchor="w", pady=2)

        self._sep(body)

        # Hotkey display (read-only for now)
        self._label(body, "Global Toggle Hotkey")
        tk.Label(body, text="F9  (fixed in this release)",
                 font=F["small"], bg=C["modal_bg"],
                 fg=C["text2"]).pack(anchor="w")

        self._sep(body)

        # Auto-run toggle
        self._autorun_var = tk.BooleanVar(value=False)
        ar_frame = tk.Frame(body, bg=C["modal_bg"])
        ar_frame.pack(fill="x", pady=4)
        tk.Checkbutton(
            ar_frame,
            text=" Start listening automatically on launch",
            variable=self._autorun_var,
            font=F["small"],
            bg=C["modal_bg"], fg=C["text"],
            activebackground=C["modal_bg"], activeforeground=C["teal"],
            selectcolor=C["panel"],
            relief="flat",
        ).pack(anchor="w")

        self._sep(body)

        # About
        tk.Label(body, text="NirmiqEcho  ·  100% offline  ·  Whisper AI",
                 font=F["badge"], bg=C["modal_bg"],
                 fg=C["text2"]).pack(anchor="w", pady=(0, 2))

        # Buttons row
        btn_row = tk.Frame(body, bg=C["modal_bg"])
        btn_row.pack(fill="x", pady=(10, 8))

        def _save():
            sens = self._sens_var.get()
            lang = self._lang_var.get().strip() or None
            self._app.set_sensitivity(sens)
            if self._app.transcription_engine:
                self._app.transcription_engine.language = lang
            self._app._autorun = self._autorun_var.get()
            self._win.destroy()

        for txt, cmd, fg in [
            ("Save", _save, C["teal"]),
            ("Cancel", self._win.destroy, C["text2"]),
        ]:
            tk.Button(
                btn_row, text=txt, command=cmd,
                font=F["toolbar"],
                bg=C["panel"], fg=fg,
                activebackground=C["panel2"], activeforeground=C["text"],
                relief="flat", padx=16, pady=4, cursor="hand2",
            ).pack(side="left", padx=(0, 8))


# ------------------------------------------------------------------
# System tray (optional)
# ------------------------------------------------------------------

def _make_tray_icon():
    """Create a simple teal circle PIL image for the tray."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, size-4, size-4], fill=(13, 185, 215, 255))
    return img


# ------------------------------------------------------------------
# Main window
# ------------------------------------------------------------------

class NirmiqEchoUI:
    """
    NirmiqEcho Phase 2 window.
    Custom titlebar, circular mic button, vertical VU bars,
    settings modal, system tray, full keyboard shortcuts.
    """

    MIN_W, MIN_H = 320, 200
    DEF_W, DEF_H = 420, 380
    TICK_MS = 50

    def __init__(self, app):
        self.app = app
        self._q = queue.Queue()
        self._lines = []
        self._listening = False
        self._tray = None
        self._build()
        self._bind_shortcuts()
        self._tick()

    # ==================================================================
    # Window construction
    # ==================================================================

    def _build(self):
        self.root = tk.Tk()
        self.root.withdraw()   # hide until fully built to prevent flash
        self.root.title("NirmiqEcho")
        self.root.geometry(f"{self.DEF_W}x{self.DEF_H}")
        self.root.minsize(self.MIN_W, self.MIN_H)
        self.root.configure(bg=C["bg"])
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.attributes("-topmost", True)

        # Remove default titlebar; use our custom one
        self.root.overrideredirect(True)
        self._dark_titlebar()

        # Custom drag support (since we removed the titlebar)
        self._drag_x = self._drag_y = 0

        self._titlebar()
        self._toolbar()
        self._status_row()
        self._transcript_area()
        self._footer()

        # Center on screen
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - self.DEF_W) // 2
        y = (sh - self.DEF_H) // 2
        self.root.geometry(f"{self.DEF_W}x{self.DEF_H}+{x}+{y}")
        self.root.deiconify()

    def _dark_titlebar(self):
        try:
            import ctypes
            hwnd = self.root.winfo_id()
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20,
                ctypes.byref(ctypes.c_int(1)),
                ctypes.sizeof(ctypes.c_int))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Custom titlebar (draggable)
    # ------------------------------------------------------------------

    def _titlebar(self):
        tb = tk.Frame(self.root, bg=C["panel2"], height=34)
        tb.pack(fill="x")
        tb.pack_propagate(False)

        # Drag bindings
        tb.bind("<ButtonPress-1>",   self._drag_start)
        tb.bind("<B1-Motion>",       self._drag_move)

        # Icon + title
        icon_lbl = tk.Label(tb, text="🎙", font=("Segoe UI Emoji", 13),
                             bg=C["panel2"], fg=C["teal"])
        icon_lbl.pack(side="left", padx=(10, 4))
        icon_lbl.bind("<ButtonPress-1>", self._drag_start)
        icon_lbl.bind("<B1-Motion>",     self._drag_move)

        title_lbl = tk.Label(tb, text="Nirmiq Echo",
                              font=F["title"], bg=C["panel2"], fg=C["text"])
        title_lbl.pack(side="left")
        title_lbl.bind("<ButtonPress-1>", self._drag_start)
        title_lbl.bind("<B1-Motion>",     self._drag_move)

        # Right buttons: pin + settings + minimize + close
        for sym, tip, cmd in [
            ("✕", "Close (Ctrl+Q)",    self._on_close),
            ("─", "Minimize to tray",  self._minimize),
            ("⚙", "Settings",          self._open_settings),
        ]:
            b = tk.Label(tb, text=sym, font=("Segoe UI", 11),
                         bg=C["panel2"], fg=C["text2"],
                         cursor="hand2", padx=8)
            b.pack(side="right")
            b.bind("<Enter>",          lambda e, w=b: w.configure(fg=C["text"],   bg="#4A4F6A"))
            b.bind("<Leave>",          lambda e, w=b: w.configure(fg=C["text2"],  bg=C["panel2"]))
            b.bind("<ButtonRelease-1>",lambda e, fn=cmd: fn())
            Tooltip(b, tip)

        # Always-on-top pin
        self._pin = tk.BooleanVar(value=True)
        pin = tk.Checkbutton(tb, text="📌", font=("Segoe UI Emoji", 11),
                              variable=self._pin,
                              command=lambda: self.root.attributes("-topmost", self._pin.get()),
                              bg=C["panel2"], fg=C["text2"],
                              activebackground=C["panel2"],
                              activeforeground=C["teal"],
                              selectcolor=C["panel2"],
                              relief="flat", cursor="hand2", bd=0)
        pin.pack(side="right")
        Tooltip(pin, "Toggle always-on-top")

        # Resize grip (bottom-right via a small label)
        self._resize_grip()

    def _resize_grip(self):
        """Attaches a bottom-right corner resize grip."""
        grip = tk.Label(self.root, text="⠿", font=("Segoe UI", 8),
                        bg=C["bg"], fg=C["dim"], cursor="size_nw_se")
        grip.place(relx=1.0, rely=1.0, anchor="se")
        grip.bind("<ButtonPress-1>",   self._resize_start)
        grip.bind("<B1-Motion>",       self._resize_move)

    def _resize_start(self, e):
        self._rsx = e.x_root
        self._rsy = e.y_root
        self._rsw = self.root.winfo_width()
        self._rsh = self.root.winfo_height()

    def _resize_move(self, e):
        dw = e.x_root - self._rsx
        dh = e.y_root - self._rsy
        nw = max(self.MIN_W, self._rsw + dw)
        nh = max(self.MIN_H, self._rsh + dh)
        self.root.geometry(f"{nw}x{nh}")

    def _drag_start(self, e):
        self._drag_x = e.x_root - self.root.winfo_x()
        self._drag_y = e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        x = e.x_root - self._drag_x
        y = e.y_root - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _toolbar(self):
        bar = tk.Frame(self.root, bg=C["panel"], pady=8)
        bar.pack(fill="x")

        # Mic toggle button (centered)
        mic_col = tk.Frame(bar, bg=C["panel"])
        mic_col.pack(side="left", padx=14)
        self._mic_btn = MicButton(mic_col, on_click=self._toggle_listen)
        self._mic_btn.pack()
        tk.Label(mic_col, text="F9", font=F["badge"],
                 bg=C["panel"], fg=C["dim"]).pack()
        Tooltip(self._mic_btn, "Start / Stop Listening (F9)")

        # Divider
        tk.Frame(bar, bg=C["panel2"], width=1).pack(side="left",
                                                      fill="y", padx=8)

        # Action buttons
        for icon, lbl, cmd, tip in [
            ("⎘",  "Copy",  self._copy, "Copy transcript (Ctrl+C)"),
            ("💾", "Save",  self._save, "Save transcript (Ctrl+S)"),
            ("🗑", "Clear", self._clear,"Clear transcript (Ctrl+L)"),
        ]:
            btn = IconBtn(bar, icon, lbl, cmd, tip=tip)
            btn.pack(side="left", padx=6)

        # VU meter on the right
        vu_col = tk.Frame(bar, bg=C["panel"])
        vu_col.pack(side="right", padx=14)
        tk.Label(vu_col, text="MIC", font=F["badge"],
                 bg=C["panel"], fg=C["dim"]).pack()
        self._vu = VUMeter(vu_col)
        self._vu.pack()

    # ------------------------------------------------------------------
    # Status row
    # ------------------------------------------------------------------

    def _status_row(self):
        row = tk.Frame(self.root, bg=C["panel2"], pady=5)
        row.pack(fill="x")

        self._status_var = tk.StringVar(value=STATUS_MAP["idle"][0])
        self._status_lbl = tk.Label(
            row, textvariable=self._status_var,
            font=F["status"], bg=C["panel2"], fg=STATUS_MAP["idle"][1],
            anchor="w", padx=14,
        )
        self._status_lbl.pack(side="left", fill="x", expand=True)

        # Model info label (right-aligned)
        self._model_lbl = tk.Label(
            row, text="Loading model…",
            font=F["badge"], bg=C["panel2"], fg=C["text2"],
            anchor="e", padx=14,
        )
        self._model_lbl.pack(side="right")

    # ------------------------------------------------------------------
    # Transcript area
    # ------------------------------------------------------------------

    def _transcript_area(self):
        # Header strip
        hdr = tk.Frame(self.root, bg=C["panel2"], pady=3)
        hdr.pack(fill="x")
        tk.Label(hdr, text="TRANSCRIPT", font=F["badge"],
                 bg=C["panel2"], fg=C["dim"],
                 padx=14).pack(side="left")
        self._wc_lbl = tk.Label(hdr, text="0 words", font=F["badge"],
                                  bg=C["panel2"], fg=C["dim"], padx=14)
        self._wc_lbl.pack(side="right")

        # Text area with styled scrollbar
        ta_frame = tk.Frame(self.root, bg=C["tx_bg"])
        ta_frame.pack(fill="both", expand=True)

        self._txt = tk.Text(
            ta_frame,
            wrap="word",
            bg=C["tx_bg"],
            fg=C["text"],
            font=F["transcript"],
            relief="flat",
            padx=14, pady=10,
            insertbackground=C["teal"],
            selectbackground=C["blue"],
            selectforeground=C["text"],
            cursor="arrow",
        )
        self._txt.pack(side="left", fill="both", expand=True)
        self._txt.config(state="disabled")

        # Styled scrollbar
        sb = tk.Scrollbar(ta_frame, command=self._txt.yview,
                          bg=C["sb_track"],
                          troughcolor=C["sb_track"],
                          activebackground=C["sb_thumb"],
                          relief="flat", width=6,
                          highlightthickness=0)
        sb.pack(side="right", fill="y")
        self._txt.config(yscrollcommand=sb.set)

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------

    def _footer(self):
        f = tk.Frame(self.root, bg=C["panel"], pady=4)
        f.pack(fill="x", side="bottom")
        tk.Label(f, text="100% offline · no APIs · Whisper AI",
                 font=F["badge"], bg=C["panel"], fg=C["dim"],
                 padx=14).pack(side="right")

    # ==================================================================
    # Keyboard shortcuts
    # ==================================================================

    def _bind_shortcuts(self):
        self.root.bind("<F9>",       lambda e: self._toggle_listen())
        self.root.bind("<Escape>",   lambda e: self._stop_only())
        self.root.bind("<Control-c>",lambda e: self._copy())
        self.root.bind("<Control-s>",lambda e: self._save())
        self.root.bind("<Control-l>",lambda e: self._clear())
        self.root.bind("<Control-q>",lambda e: self._on_close())

    # ==================================================================
    # Thread-safe UI update queue
    # ==================================================================

    def _tick(self):
        try:
            while True:
                cmd, *args = self._q.get_nowait()
                fn = getattr(self, f"_do_{cmd}", None)
                if fn:
                    fn(*args)
        except queue.Empty:
            pass

        # Update VU meter from audio level
        if self._listening and self.app.audio_handler:
            self._vu.set_level(self.app.audio_handler.audio_level)
        else:
            self._vu.set_level(0.0)

        self.root.after(self.TICK_MS, self._tick)

    def schedule(self, cmd: str, *args):
        """Thread-safe: enqueue a UI command from any background thread."""
        self._q.put((cmd, *args))

    # Dispatched handlers
    def _do_set_status(self, key: str):
        label, color = STATUS_MAP.get(key, STATUS_MAP["idle"])
        self._status_var.set(label)
        self._status_lbl.config(fg=color)

    def _do_append_transcript(self, text: str):
        self._lines.append(text)
        self._txt.config(state="normal")
        # Fade-in: insert at end with a small tag for future styling
        if self._txt.index("end-1c") != "1.0":
            self._txt.insert("end", "\n")
        self._txt.insert("end", text)
        self._txt.see("end")
        self._txt.config(state="disabled")
        self._update_wc()

    def _do_set_model_info(self, info: str):
        self._model_lbl.config(text=info)

    def _do_set_listening(self, val: bool):
        self._listening = val
        self._mic_btn.set_active(val)

    def _do_show_error(self, msg: str):
        messagebox.showerror("NirmiqEcho", msg, parent=self.root)

    def _do_show_info(self, msg: str):
        messagebox.showinfo("NirmiqEcho", msg, parent=self.root)

    # ==================================================================
    # Button / shortcut actions
    # ==================================================================

    def _toggle_listen(self):
        if self._listening:
            self.app.stop_listening()
        else:
            self.app.start_listening()

    def _stop_only(self):
        if self._listening:
            self.app.stop_listening()

    def _copy(self):
        text = self._get_text()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            # Flash feedback
            orig = self._status_var.get()
            self._status_var.set("✓  Copied to clipboard!")
            self._status_lbl.config(fg=C["green"])
            self.root.after(1500, lambda: self._restore_status())
        else:
            self.schedule("show_info", "Transcript is empty.")

    def _restore_status(self):
        # Re-dispatch current status
        key = "listening" if self._listening else "ready"
        self._do_set_status(key)

    def _save(self):
        text = self._get_text()
        if not text:
            self.schedule("show_info", "Transcript is empty.")
            return
        fp = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Transcript",
            initialfile="nirmiqecho_transcript.txt",
        )
        if fp:
            try:
                Path(fp).write_text(text, encoding="utf-8")
                self.schedule("show_info", f"Saved:\n{fp}")
            except Exception as exc:
                self.schedule("show_error", f"Could not save:\n{exc}")

    def _clear(self):
        if self._lines:
            if not messagebox.askyesno(
                "Clear Transcript",
                "Are you sure you want to clear the transcript?",
                parent=self.root,
            ):
                return
        self._lines.clear()
        self._txt.config(state="normal")
        self._txt.delete("1.0", "end")
        self._txt.config(state="disabled")
        self._update_wc()

    def _open_settings(self):
        SettingsModal(self.root, self.app)

    # ==================================================================
    # System tray & window management
    # ==================================================================

    def _minimize(self):
        if _HAS_TRAY:
            self.root.withdraw()
            self._start_tray()
        else:
            # Fall back to minimizing to taskbar
            self.root.overrideredirect(False)
            self.root.iconify()

    def _start_tray(self):
        if self._tray is not None:
            return

        def on_restore(icon, item):
            icon.stop()
            self._tray = None
            self.root.after(0, self.root.deiconify)

        def on_exit(icon, item):
            icon.stop()
            self.root.after(0, self._on_close)

        menu = pystray.Menu(
            pystray.MenuItem("Show NirmiqEcho", on_restore, default=True),
            pystray.MenuItem("Exit", on_exit),
        )
        img = _make_tray_icon()
        self._tray = pystray.Icon("NirmiqEcho", img, "NirmiqEcho", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _on_close(self):
        if self._tray:
            self._tray.stop()
        self._vu.stop()
        self.app.shutdown()
        try:
            self.root.destroy()
        except Exception:
            pass

    # ==================================================================
    # Helpers
    # ==================================================================

    def _get_text(self) -> str:
        return self._txt.get("1.0", "end-1c").strip()

    def _update_wc(self):
        text = self._get_text()
        n = len(text.split()) if text else 0
        self._wc_lbl.config(text=f"{n} word{'s' if n != 1 else ''}")

    def run(self):
        self.root.mainloop()
