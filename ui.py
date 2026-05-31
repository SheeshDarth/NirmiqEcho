"""
ui.py - NirmiqEcho Phase 2 UI

Full production UI per Nirmiq Echo Design Summary spec:
- Custom dark draggable titlebar (#31354B) with settings/pin/minimize/close
- 48px circular Start/Stop MicButton (teal → red + pulse animation)
- 7-bar vertical VU meter with smooth per-bar decay
- Settings modal (sensitivity, language, hotkey, auto-run)
- System tray minimize via pystray (graceful fallback)
- Full keyboard shortcuts (F9, Ctrl+C/S/L, Esc, Ctrl+Q)
- Tooltips (500ms) on all interactive elements
- WCAG AA color palette throughout
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging
import queue
import random
import threading
from pathlib import Path

# pystray / Pillow — graceful fallback if not installed
try:
    import pystray
    from PIL import Image, ImageDraw
    _HAS_TRAY = True
except ImportError:
    _HAS_TRAY = False

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Design tokens — Nirmiq Echo Design Summary spec
# ─────────────────────────────────────────────────────────────────────

C = {
    "bg":       "#121212",   # main window bg
    "panel":    "#242423",   # toolbar / footer
    "panel2":   "#31354B",   # titlebar / header strips
    "tx_bg":    "#1F1F1F",   # transcript area bg
    "modal_bg": "#1A1A2E",   # settings modal bg

    "text":     "#ECEFF8",   # primary text  (~13.5:1 on panel)
    "text2":    "#9EA1AC",   # secondary text (~5.8:1)
    "dim":      "#565556",   # disabled / muted

    "teal":     "#0DB9D7",   # accent / mic idle / VU bars
    "blue":     "#6F7591",   # scrollbar thumb / hover
    "red":      "#F44336",   # stop / error
    "green":    "#4CAF50",   # ready / speaking
    "orange":   "#FF9800",   # loading / transcribing
    "focus":    "#5DC3F6",   # keyboard focus ring

    "sb_track": "#3F4140",
    "sb_thumb": "#6F7591",
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

# State key → (display label, colour)
STATUS_MAP = {
    "idle":             ("Idle — click ▶ or press F9 to start", C["text2"]),
    "loading":          ("Loading model…",                       C["orange"]),
    "ready":            ("Ready",                                C["green"]),
    "listening":        ("Listening…",                           C["teal"]),
    "listening_active": ("Speaking…",                            C["green"]),
    "transcribing":     ("Transcribing…",                        C["orange"]),
    "error":            ("Error — see console for details",      C["red"]),
}


# ─────────────────────────────────────────────────────────────────────
# Tooltip (500 ms delay, safe against widget destruction)
# ─────────────────────────────────────────────────────────────────────

class Tooltip:
    """Show a tooltip 500 ms after hovering; hide on leave."""

    def __init__(self, widget, text: str):
        self._w   = widget
        self._txt = text
        self._tip = None
        self._job = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._cancel,   add="+")

    def _schedule(self, _=None):
        self._cancel()
        try:
            self._job = self._w.after(500, self._show)
        except Exception:
            pass

    def _cancel(self, _=None):
        if self._job:
            try:
                self._w.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def _show(self):
        try:
            x = self._w.winfo_rootx() + 10
            y = self._w.winfo_rooty() + self._w.winfo_height() + 4
            self._tip = tk.Toplevel(self._w)
            self._tip.wm_overrideredirect(True)
            self._tip.wm_geometry(f"+{x}+{y}")
            tk.Label(
                self._tip, text=self._txt,
                bg=C["panel2"], fg=C["text"], relief="flat",
                font=F["small"], padx=6, pady=3,
            ).pack()
        except Exception:
            self._tip = None


# ─────────────────────────────────────────────────────────────────────
# MicButton — 56px circular canvas toggle
# ─────────────────────────────────────────────────────────────────────

class MicButton(tk.Canvas):
    """
    Circular toggle button.
    Idle  : teal ring + mic glyph
    Active: red fill + stop square; pulses when speaking is detected
    """

    SIZE = 56

    def __init__(self, parent, on_click, **kw):
        super().__init__(
            parent,
            width=self.SIZE, height=self.SIZE,
            bg=C["panel"], highlightthickness=0,
            cursor="hand2", **kw,
        )
        self._on_click    = on_click
        self._active      = False
        self._hover       = False   # MUST be set before first _draw()
        self._pulse_scale = 1.0
        self._pulse_dir   = 1
        self._pulse_job   = None
        self._destroyed   = False

        self._draw()
        self.bind("<ButtonRelease-1>", lambda e: self._on_click())
        self.bind("<Enter>",           self._hover_on)
        self.bind("<Leave>",           self._hover_off)
        self.bind("<Destroy>",         self._on_destroy)

    def _on_destroy(self, _=None):
        self._destroyed = True
        self._cancel_pulse()

    # ── Drawing ───────────────────────────────────────────────────────

    def _draw(self):
        if self._destroyed:
            return
        try:
            self.delete("all")
            cx = cy = self.SIZE // 2
            r = 22
            if self._active:
                # Red fill + stop square
                self.create_oval(cx-r, cy-r, cx+r, cy+r,
                                 fill=C["red"], outline="")
                sq = 10
                self.create_rectangle(cx-sq, cy-sq, cx+sq, cy+sq,
                                      fill=C["text"], outline="")
            else:
                # Teal ring + mic glyph
                self.create_oval(cx-r, cy-r, cx+r, cy+r,
                                 fill="#0A8F9A" if self._hover else "",
                                 outline=C["teal"], width=2)
                mw, mh = 8, 13
                # Mic body rect
                self.create_rectangle(cx-mw//2, cy-mh//2,
                                      cx+mw//2, cy+mh//2,
                                      fill=C["teal"], outline="")
                # Mic dome arc
                self.create_arc(cx-mw//2-1, cy-mh//2-1,
                                cx+mw//2+1, cy+mh//2+6,
                                start=0, extent=180,
                                fill=C["teal"], outline="")
                # Stand
                self.create_line(cx, cy+mh//2, cx, cy+mh//2+5,
                                 fill=C["teal"], width=2)
                self.create_arc(cx-6, cy+mh//2-2, cx+6, cy+mh//2+8,
                                start=180, extent=180,
                                outline=C["teal"], width=2, style="arc")
        except Exception:
            pass

    def _hover_on(self, _=None):
        self._hover = True
        self._draw()

    def _hover_off(self, _=None):
        self._hover = False
        self._draw()

    # ── Public ────────────────────────────────────────────────────────

    def set_active(self, val: bool):
        self._active = val
        self._draw()
        if val:
            self._start_pulse()
        else:
            self._stop_pulse()

    # ── Pulse animation ───────────────────────────────────────────────

    def _start_pulse(self):
        self._cancel_pulse()
        if not self._destroyed:
            self._pulse_job = self.after(80, self._pulse_tick)

    def _pulse_tick(self):
        if self._destroyed or not self._active:
            return
        try:
            self._pulse_scale += 0.015 * self._pulse_dir
            if self._pulse_scale >= 1.12:
                self._pulse_dir = -1
            elif self._pulse_scale <= 0.92:
                self._pulse_dir = 1

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
        except Exception:
            self._pulse_job = None

    def _stop_pulse(self):
        self._cancel_pulse()
        self._pulse_scale = 1.0
        self._pulse_dir   = 1
        self._draw()

    def _cancel_pulse(self):
        if self._pulse_job:
            try:
                self.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None


# ─────────────────────────────────────────────────────────────────────
# IconBtn — small labelled icon button
# ─────────────────────────────────────────────────────────────────────

class IconBtn(tk.Frame):
    """Icon + label button with hover highlight, tooltip, and enable state."""

    def __init__(self, parent, icon: str, label: str, cmd, tip: str = "", **kw):
        super().__init__(parent, bg=C["panel"], cursor="hand2", **kw)
        self._cmd     = cmd
        self._enabled = True

        self._icon_lbl = tk.Label(self, text=icon, font=F["emoji"],
                                   bg=C["panel"], fg=C["text"])
        self._icon_lbl.pack(side="top")
        self._txt_lbl  = tk.Label(self, text=label, font=F["badge"],
                                   bg=C["panel"], fg=C["text2"])
        self._txt_lbl.pack(side="top")

        for w in (self, self._icon_lbl, self._txt_lbl):
            w.bind("<Enter>",           lambda e: self._hi(True))
            w.bind("<Leave>",           lambda e: self._hi(False))
            w.bind("<ButtonRelease-1>", lambda e: self._fire())

        if tip:
            Tooltip(self, tip)

    def _hi(self, on: bool):
        if not self._enabled:
            return
        bg = "#31354B" if on else C["panel"]
        for w in (self, self._icon_lbl, self._txt_lbl):
            try:
                w.configure(bg=bg)
            except Exception:
                pass

    def _fire(self):
        if self._enabled:
            self._cmd()

    def set_enabled(self, yes: bool):
        self._enabled = yes
        fg  = C["text"]  if yes else C["dim"]
        cur = "hand2"    if yes else "arrow"
        self.configure(cursor=cur)
        self._icon_lbl.configure(fg=fg)
        self._txt_lbl.configure(fg=fg)


# ─────────────────────────────────────────────────────────────────────
# VUMeter — 7 vertical bars with smooth decay
# ─────────────────────────────────────────────────────────────────────

class VUMeter(tk.Canvas):
    """Animated vertical bar meter for real-time mic level feedback."""

    N_BARS = 7
    BAR_W  = 6
    GAP    = 3
    H      = 28

    def __init__(self, parent, **kw):
        w = self.N_BARS * self.BAR_W + (self.N_BARS - 1) * self.GAP
        super().__init__(parent, width=w, height=self.H,
                         bg=C["panel"], highlightthickness=0, **kw)
        self._peaks    = [0.0] * self.N_BARS
        self._target   = 0.0
        self._decay    = 0.08
        self._running  = True
        self._job      = None
        self.bind("<Destroy>", self._on_destroy)
        self._animate()

    def set_level(self, level: float):
        self._target = max(0.0, min(1.0, level))

    def _on_destroy(self, _=None):
        self._running = False
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def _animate(self):
        if not self._running:
            return
        changed = False
        for i in range(self.N_BARS):
            # Each bar gets a slightly randomised portion of the target
            factor   = 0.5 + 0.9 * random.random()
            target_i = min(1.0, self._target * factor)
            if self._peaks[i] < target_i:
                self._peaks[i] = min(target_i, self._peaks[i] + 0.15)
                changed = True
            elif self._peaks[i] > 0:
                self._peaks[i] = max(0.0, self._peaks[i] - self._decay)
                changed = True

        if changed:
            try:
                self._redraw()
            except Exception:
                pass

        try:
            self._job = self.after(50, self._animate)
        except Exception:
            self._running = False

    def _redraw(self):
        self.delete("all")
        for i, peak in enumerate(self._peaks):
            x1 = i * (self.BAR_W + self.GAP)
            x2 = x1 + self.BAR_W
            self.create_rectangle(x1, 0, x2, self.H,
                                  fill=C["panel2"], outline="")
            fh = int(self.H * peak)
            if fh > 1:
                color = C["teal"] if peak < 0.75 else C["orange"]
                self.create_rectangle(x1, self.H - fh, x2, self.H,
                                      fill=color, outline="")

    def stop(self):
        self._on_destroy()


# ─────────────────────────────────────────────────────────────────────
# Settings modal
# ─────────────────────────────────────────────────────────────────────

class SettingsModal:
    """Dark preferences dialog: VAD sensitivity, language, auto-run."""

    def __init__(self, parent, app):
        self._app = app
        self._win = tk.Toplevel(parent)
        self._win.title("Settings — NirmiqEcho")
        self._win.configure(bg=C["modal_bg"])
        self._win.resizable(False, False)
        self._win.grab_set()
        self._win.transient(parent)
        self._apply_dark_titlebar()
        self._build()
        self._win.update_idletasks()
        # Centre over parent
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        mw = self._win.winfo_width()
        mh = self._win.winfo_height()
        self._win.geometry(f"+{px + (pw-mw)//2}+{py + (ph-mh)//2}")

    def _apply_dark_titlebar(self):
        try:
            import ctypes
            hwnd = self._win.winfo_id()
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(ctypes.c_int(1)),
                ctypes.sizeof(ctypes.c_int))
        except Exception:
            pass

    def _lbl(self, parent, text):
        tk.Label(parent, text=text, font=F["small"],
                 bg=C["modal_bg"], fg=C["text2"], anchor="w"
                 ).pack(fill="x", pady=(8, 2))

    def _sep(self, parent):
        tk.Frame(parent, bg=C["panel2"], height=1).pack(fill="x", pady=6)

    def _build(self):
        body = tk.Frame(self._win, bg=C["modal_bg"])
        body.pack(fill="both", expand=True, padx=18, pady=4)

        tk.Label(body, text="⚙  Settings", font=F["title"],
                 bg=C["modal_bg"], fg=C["text"]).pack(anchor="w", pady=(8, 4))
        self._sep(body)

        # ── VAD Sensitivity ───────────────────────────────────────────
        self._lbl(body, "VAD Sensitivity  (0 = permissive · 3 = strict)")
        init_sens = (self._app.audio_handler.sensitivity
                     if self._app.audio_handler else 2)
        self._sens_var = tk.IntVar(value=init_sens)
        sens_row = tk.Frame(body, bg=C["modal_bg"])
        sens_row.pack(fill="x")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("S.TScale", background=C["modal_bg"],
                         troughcolor=C["panel"], sliderlength=14,
                         slidercolor=C["teal"])

        def _on_sens(v):
            iv = int(float(v))
            self._sens_var.set(iv)
            self._sens_lbl.config(text=str(iv))

        ttk.Scale(sens_row, from_=0, to=3, orient="horizontal",
                  variable=self._sens_var, style="S.TScale",
                  command=_on_sens).pack(side="left", fill="x", expand=True)
        self._sens_lbl = tk.Label(sens_row, text=str(init_sens),
                                   font=F["small"], bg=C["modal_bg"],
                                   fg=C["teal"], width=2)
        self._sens_lbl.pack(side="left")
        self._sep(body)

        # ── Language ──────────────────────────────────────────────────
        self._lbl(body, "Language  (blank = auto-detect)")
        init_lang = ""
        if self._app.transcription_engine:
            init_lang = self._app.transcription_engine.language or ""
        self._lang_var = tk.StringVar(value=init_lang)
        tk.Entry(body, textvariable=self._lang_var, font=F["toolbar"],
                 bg=C["panel"], fg=C["text"], insertbackground=C["teal"],
                 relief="flat", width=12).pack(anchor="w", pady=2)
        self._sep(body)

        # ── Hotkey ────────────────────────────────────────────────────
        self._lbl(body, "Global Toggle Hotkey")
        tk.Label(body, text="F9  (fixed in this release)",
                 font=F["small"], bg=C["modal_bg"],
                 fg=C["text2"]).pack(anchor="w")
        self._sep(body)

        # ── Auto-run ──────────────────────────────────────────────────
        self._autorun_var = tk.BooleanVar(value=getattr(self._app, "_autorun", False))
        tk.Checkbutton(body,
                       text=" Start listening automatically on launch",
                       variable=self._autorun_var,
                       font=F["small"],
                       bg=C["modal_bg"], fg=C["text"],
                       activebackground=C["modal_bg"], activeforeground=C["teal"],
                       selectcolor=C["panel"], relief="flat"
                       ).pack(anchor="w", pady=4)
        self._sep(body)

        # ── About ─────────────────────────────────────────────────────
        tk.Label(body, text="NirmiqEcho  ·  100% offline  ·  Whisper AI",
                 font=F["badge"], bg=C["modal_bg"], fg=C["text2"]
                 ).pack(anchor="w", pady=(0, 2))

        # ── Buttons ───────────────────────────────────────────────────
        btn_row = tk.Frame(body, bg=C["modal_bg"])
        btn_row.pack(fill="x", pady=(10, 8))

        def _save():
            self._app.set_sensitivity(self._sens_var.get())
            if self._app.transcription_engine:
                lang = self._lang_var.get().strip() or None
                self._app.transcription_engine.language = lang
            self._app._autorun = self._autorun_var.get()
            self._win.destroy()

        for txt, cmd, fg in [("Save", _save, C["teal"]),
                              ("Cancel", self._win.destroy, C["text2"])]:
            tk.Button(btn_row, text=txt, command=cmd, font=F["toolbar"],
                      bg=C["panel"], fg=fg,
                      activebackground=C["panel2"], activeforeground=C["text"],
                      relief="flat", padx=16, pady=4, cursor="hand2"
                      ).pack(side="left", padx=(0, 8))


# ─────────────────────────────────────────────────────────────────────
# System tray helper
# ─────────────────────────────────────────────────────────────────────

def _make_tray_icon():
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    d.ellipse([4, 4, size-4, size-4], fill=(13, 185, 215, 255))
    return img


# ─────────────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────────────

class NirmiqEchoUI:
    """
    NirmiqEcho main application window.
    All backend → UI updates happen via self.schedule() from any thread.
    UI mutations happen only on the main thread via root.after() tick.
    """

    MIN_W, MIN_H = 320, 200
    DEF_W, DEF_H = 420, 390
    TICK_MS = 50

    def __init__(self, app):
        self.app        = app
        self._q         = queue.Queue()
        self._lines     = []
        self._listening = False
        self._tray      = None
        self._cur_status_key = "idle"   # track current status key

        self._build()
        self._bind_shortcuts()
        self._tick()

    # ─────────────────────────── construction ────────────────────────

    def _build(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("NirmiqEcho")
        self.root.configure(bg=C["bg"])
        self.root.resizable(True, True)
        self.root.minsize(self.MIN_W, self.MIN_H)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.attributes("-topmost", True)

        # Custom titlebar (overrideredirect removes OS decoration)
        self.root.overrideredirect(True)
        self._apply_dark_titlebar(self.root)

        self._drag_x = self._drag_y = 0

        self._build_titlebar()
        self._build_toolbar()
        self._build_status_row()
        self._build_transcript()
        self._build_footer()
        self._build_resize_grip()

        # Center & show
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x  = (sw - self.DEF_W) // 2
        y  = (sh - self.DEF_H) // 2
        self.root.geometry(f"{self.DEF_W}x{self.DEF_H}+{x}+{y}")
        self.root.deiconify()

    @staticmethod
    def _apply_dark_titlebar(win):
        try:
            import ctypes
            hwnd = win.winfo_id()
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(ctypes.c_int(1)),
                ctypes.sizeof(ctypes.c_int))
        except Exception:
            pass

    # ─────────────────────────── titlebar ────────────────────────────

    def _build_titlebar(self):
        tb = tk.Frame(self.root, bg=C["panel2"], height=34)
        tb.pack(fill="x")
        tb.pack_propagate(False)

        # Drag from the whole bar
        for w in (tb,):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>",     self._drag_move)

        # Icon
        icon = tk.Label(tb, text="🎙", font=("Segoe UI Emoji", 13),
                        bg=C["panel2"], fg=C["teal"])
        icon.pack(side="left", padx=(10, 4))
        icon.bind("<ButtonPress-1>", self._drag_start)
        icon.bind("<B1-Motion>",     self._drag_move)

        # Title
        title = tk.Label(tb, text="Nirmiq Echo", font=F["title"],
                         bg=C["panel2"], fg=C["text"])
        title.pack(side="left")
        title.bind("<ButtonPress-1>", self._drag_start)
        title.bind("<B1-Motion>",     self._drag_move)

        # Right controls: close / minimize / settings (packed right→left)
        for sym, tip_txt, cmd in [
            ("✕", "Close  (Ctrl+Q)",  self._on_close),
            ("─", "Minimize to tray", self._minimize),
            ("⚙", "Settings",         self._open_settings),
        ]:
            b = tk.Label(tb, text=sym, font=("Segoe UI", 11),
                         bg=C["panel2"], fg=C["text2"],
                         cursor="hand2", padx=9)
            b.pack(side="right")
            b.bind("<Enter>",           lambda e, w=b: w.configure(fg=C["text"], bg="#4A4F6A"))
            b.bind("<Leave>",           lambda e, w=b: w.configure(fg=C["text2"], bg=C["panel2"]))
            b.bind("<ButtonRelease-1>", lambda e, fn=cmd: fn())
            Tooltip(b, tip_txt)

        # Pin toggle
        self._pin = tk.BooleanVar(value=True)
        pin = tk.Checkbutton(tb, text="📌", font=("Segoe UI Emoji", 11),
                              variable=self._pin,
                              command=lambda: self.root.attributes("-topmost", self._pin.get()),
                              bg=C["panel2"], fg=C["text2"],
                              activebackground=C["panel2"], activeforeground=C["teal"],
                              selectcolor=C["panel2"], relief="flat", cursor="hand2", bd=0)
        pin.pack(side="right")
        Tooltip(pin, "Toggle always-on-top")

    # ─────────────────────────── toolbar ─────────────────────────────

    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=C["panel"], pady=8)
        bar.pack(fill="x")

        # Mic column
        mic_col = tk.Frame(bar, bg=C["panel"])
        mic_col.pack(side="left", padx=14)
        self._mic_btn = MicButton(mic_col, on_click=self._toggle_listen)
        self._mic_btn.pack()
        tk.Label(mic_col, text="F9", font=F["badge"],
                 bg=C["panel"], fg=C["dim"]).pack()
        Tooltip(self._mic_btn, "Start / Stop Listening  (F9)")

        # Divider
        tk.Frame(bar, bg=C["panel2"], width=1).pack(side="left", fill="y", padx=8)

        # Action buttons
        for icon, lbl, cmd, tip in [
            ("⎘",  "Copy",  self._copy,  "Copy transcript  (Ctrl+C)"),
            ("💾", "Save",  self._save,  "Save transcript  (Ctrl+S)"),
            ("🗑", "Clear", self._clear, "Clear transcript  (Ctrl+L)"),
        ]:
            IconBtn(bar, icon, lbl, cmd, tip=tip).pack(side="left", padx=6)

        # VU meter
        vu_col = tk.Frame(bar, bg=C["panel"])
        vu_col.pack(side="right", padx=14)
        tk.Label(vu_col, text="MIC", font=F["badge"],
                 bg=C["panel"], fg=C["dim"]).pack()
        self._vu = VUMeter(vu_col)
        self._vu.pack()

    # ─────────────────────────── status row ──────────────────────────

    def _build_status_row(self):
        row = tk.Frame(self.root, bg=C["panel2"], pady=5)
        row.pack(fill="x")

        self._status_var = tk.StringVar(value=STATUS_MAP["idle"][0])
        self._status_lbl = tk.Label(
            row, textvariable=self._status_var,
            font=F["status"], bg=C["panel2"], fg=STATUS_MAP["idle"][1],
            anchor="w", padx=14)
        self._status_lbl.pack(side="left", fill="x", expand=True)

        self._model_lbl = tk.Label(
            row, text="Loading model…",
            font=F["badge"], bg=C["panel2"], fg=C["text2"],
            anchor="e", padx=14)
        self._model_lbl.pack(side="right")

    # ─────────────────────────── transcript ──────────────────────────

    def _build_transcript(self):
        hdr = tk.Frame(self.root, bg=C["panel2"], pady=3)
        hdr.pack(fill="x")
        tk.Label(hdr, text="TRANSCRIPT", font=F["badge"],
                 bg=C["panel2"], fg=C["dim"], padx=14).pack(side="left")
        self._wc_lbl = tk.Label(hdr, text="0 words", font=F["badge"],
                                  bg=C["panel2"], fg=C["dim"], padx=14)
        self._wc_lbl.pack(side="right")

        ta = tk.Frame(self.root, bg=C["tx_bg"])
        ta.pack(fill="both", expand=True)

        self._txt = tk.Text(
            ta, wrap="word", bg=C["tx_bg"], fg=C["text"],
            font=F["transcript"], relief="flat", padx=14, pady=10,
            insertbackground=C["teal"],
            selectbackground=C["blue"], selectforeground=C["text"],
            cursor="arrow")
        self._txt.pack(side="left", fill="both", expand=True)
        self._txt.config(state="disabled")

        sb = tk.Scrollbar(ta, command=self._txt.yview,
                          bg=C["sb_track"], troughcolor=C["sb_track"],
                          activebackground=C["sb_thumb"],
                          relief="flat", width=6, highlightthickness=0)
        sb.pack(side="right", fill="y")
        self._txt.config(yscrollcommand=sb.set)

    # ─────────────────────────── footer ──────────────────────────────

    def _build_footer(self):
        f = tk.Frame(self.root, bg=C["panel"], pady=4)
        f.pack(fill="x", side="bottom")
        tk.Label(f, text="100% offline · no APIs · Whisper AI",
                 font=F["badge"], bg=C["panel"], fg=C["dim"],
                 padx=14).pack(side="right")

    # ─────────────────────────── resize grip ─────────────────────────

    def _build_resize_grip(self):
        grip = tk.Label(self.root, text="⠿", font=("Segoe UI", 8),
                        bg=C["bg"], fg=C["dim"], cursor="size_nw_se")
        grip.place(relx=1.0, rely=1.0, anchor="se")
        grip.bind("<ButtonPress-1>", self._resize_start)
        grip.bind("<B1-Motion>",     self._resize_move)

    def _resize_start(self, e):
        self._rsx = e.x_root
        self._rsy = e.y_root
        self._rsw = self.root.winfo_width()
        self._rsh = self.root.winfo_height()

    def _resize_move(self, e):
        nw = max(self.MIN_W, self._rsw + e.x_root - self._rsx)
        nh = max(self.MIN_H, self._rsh + e.y_root - self._rsy)
        self.root.geometry(f"{nw}x{nh}")

    def _drag_start(self, e):
        self._drag_x = e.x_root - self.root.winfo_x()
        self._drag_y = e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    # ─────────────────────────── shortcuts ───────────────────────────

    def _bind_shortcuts(self):
        r = self.root
        r.bind("<F9>",        lambda e: self._toggle_listen())
        r.bind("<Escape>",    lambda e: self._stop_only())
        r.bind("<Control-c>", lambda e: self._copy())
        r.bind("<Control-s>", lambda e: self._save())
        r.bind("<Control-l>", lambda e: self._clear())
        r.bind("<Control-q>", lambda e: self._on_close())

    # ─────────────────────────── tick loop ───────────────────────────

    def _tick(self):
        # Drain the thread-safe command queue
        try:
            while True:
                item = self._q.get_nowait()
                cmd, *args = item
                fn = getattr(self, f"_do_{cmd}", None)
                if fn:
                    try:
                        fn(*args)
                    except Exception as exc:
                        logger.error("UI dispatch error [%s]: %s", cmd, exc)
        except queue.Empty:
            pass

        # Feed VU meter
        try:
            if self._listening and self.app.audio_handler:
                self._vu.set_level(self.app.audio_handler.audio_level)
            else:
                self._vu.set_level(0.0)
        except Exception:
            pass

        try:
            self.root.after(self.TICK_MS, self._tick)
        except Exception:
            pass

    def schedule(self, cmd: str, *args):
        """Thread-safe: enqueue a UI update from any background thread."""
        self._q.put((cmd, *args))

    # ─────────────────────────── dispatched handlers ─────────────────

    def _do_set_status(self, key: str):
        self._cur_status_key = key
        label, color = STATUS_MAP.get(key, STATUS_MAP["idle"])
        self._status_var.set(label)
        self._status_lbl.config(fg=color)

    def _do_append_transcript(self, text: str):
        self._lines.append(text)
        self._txt.config(state="normal")
        # Only insert newline if there's already content
        if self._txt.get("1.0", "end-1c"):
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

    # ─────────────────────────── actions ─────────────────────────────

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
        if not text:
            messagebox.showinfo("NirmiqEcho", "Transcript is empty.", parent=self.root)
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        # Brief status flash
        self._status_var.set("✓  Copied to clipboard!")
        self._status_lbl.config(fg=C["green"])
        self.root.after(1500, self._restore_status)

    def _restore_status(self):
        """Re-apply the current status after a transient flash."""
        try:
            self._do_set_status(self._cur_status_key)
        except Exception:
            pass

    def _save(self):
        text = self._get_text()
        if not text:
            messagebox.showinfo("NirmiqEcho", "Transcript is empty.", parent=self.root)
            return
        fp = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Transcript", initialfile="nirmiqecho_transcript.txt")
        if fp:
            try:
                Path(fp).write_text(text, encoding="utf-8")
                messagebox.showinfo("NirmiqEcho", f"Saved:\n{fp}", parent=self.root)
            except Exception as exc:
                messagebox.showerror("NirmiqEcho", f"Could not save:\n{exc}", parent=self.root)

    def _clear(self):
        if self._lines:
            if not messagebox.askyesno(
                    "Clear Transcript",
                    "Clear the transcript? This cannot be undone.",
                    parent=self.root):
                return
        self._lines.clear()
        self._txt.config(state="normal")
        self._txt.delete("1.0", "end")
        self._txt.config(state="disabled")
        self._update_wc()

    def _open_settings(self):
        SettingsModal(self.root, self.app)

    # ─────────────────────────── tray / window ───────────────────────

    def _minimize(self):
        if _HAS_TRAY:
            self.root.withdraw()
            self._start_tray()
        else:
            # No tray: temporarily restore OS frame so iconify works
            self.root.overrideredirect(False)
            self.root.iconify()
            # Re-apply custom titlebar when user restores
            self.root.bind("<Map>", self._on_map_after_iconify)

    def _on_map_after_iconify(self, _=None):
        self.root.unbind("<Map>")
        self.root.overrideredirect(True)

    def _start_tray(self):
        if self._tray is not None:
            return

        def _restore(icon, item):
            icon.stop()
            self._tray = None
            self.root.after(0, self.root.deiconify)

        def _exit(icon, item):
            icon.stop()
            self.root.after(0, self._on_close)

        menu = pystray.Menu(
            pystray.MenuItem("Show NirmiqEcho", _restore, default=True),
            pystray.MenuItem("Exit",            _exit),
        )
        img       = _make_tray_icon()
        self._tray = pystray.Icon("NirmiqEcho", img, "NirmiqEcho", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _on_close(self):
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
        try:
            self._vu.stop()
        except Exception:
            pass
        self.app.shutdown()
        try:
            self.root.destroy()
        except Exception:
            pass

    # ─────────────────────────── helpers ─────────────────────────────

    def _get_text(self) -> str:
        return self._txt.get("1.0", "end-1c").strip()

    def _update_wc(self):
        text = self._get_text()
        n    = len(text.split()) if text else 0
        self._wc_lbl.config(text=f"{n} word{'s' if n != 1 else ''}")

    def run(self):
        self.root.mainloop()
