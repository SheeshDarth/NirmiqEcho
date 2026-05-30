"""
ui.py - NirmiqEcho main application window

Minimal dark floating overlay built with tkinter.
All UI mutations are dispatched from the main thread via after() scheduling.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging
import queue
from pathlib import Path

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Design system
# ------------------------------------------------------------------

C = {
    "bg":          "#0d0d10",
    "surface":     "#16161b",
    "surface2":    "#1e1e25",
    "border":      "#2a2a35",
    "accent":      "#6c63ff",
    "accent_h":    "#8b85ff",
    "accent_dim":  "#3d3780",
    "green":       "#20c954",
    "red":         "#f44",
    "orange":      "#f97316",
    "text":        "#e2e2ec",
    "muted":       "#7a7a95",
    "dim":         "#44445a",
}

F = {
    "title":  ("Segoe UI", 12, "bold"),
    "body":   ("Segoe UI", 10),
    "small":  ("Segoe UI", 9),
    "mono":   ("Consolas", 10),
    "badge":  ("Segoe UI", 8),
}

STATUS = {
    "idle":             ("●  Idle",          C["dim"]),
    "loading":          ("●  Loading…",      C["orange"]),
    "ready":            ("●  Ready",         C["green"]),
    "listening":        ("●  Listening",     C["accent"]),
    "listening_active": ("◉  Speaking",      C["green"]),
    "transcribing":     ("●  Transcribing…", C["orange"]),
    "error":            ("●  Error",         C["red"]),
}


# ------------------------------------------------------------------
# Rounded canvas button
# ------------------------------------------------------------------

class RoundBtn(tk.Canvas):
    """Canvas-based button with rounded corners and hover animation."""

    def __init__(self, parent, text, command,
                 w=80, h=32, bg=None, bg_h=None, fg="#fff",
                 radius=8, font=None, **kw):
        bg = bg or C["accent"]
        bg_h = bg_h or C["accent_h"]
        font = font or F["body"]
        super().__init__(parent, width=w, height=h,
                         bg=C["bg"], highlightthickness=0,
                         cursor="hand2", **kw)
        self._norm, self._hover_c = bg, bg_h
        self._fg, self._r = fg, radius
        self._text, self._font = text, font
        self._cmd = command
        self._cur = bg
        self._off = False
        self._draw()
        self.bind("<Enter>",          lambda e: self._set(self._hover_c))
        self.bind("<Leave>",          lambda e: self._set(self._norm))
        self.bind("<ButtonPress-1>",  lambda e: self._set(C["accent_dim"]))
        self.bind("<ButtonRelease-1>",lambda e: (self._set(self._hover_c), self._cmd()))

    def _poly(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r,y1, x2-r,y1, x2,y1, x2,y1+r,
               x2,y2-r, x2,y2, x2-r,y2, x1+r,y2,
               x1,y2, x1,y2-r, x1,y1+r, x1,y1]
        self.create_polygon(pts, smooth=True, **kw)

    def _draw(self):
        self.delete("all")
        w, h = int(self["width"]), int(self["height"])
        self._poly(0, 0, w, h, self._r, fill=self._cur, outline="")
        self.create_text(w//2, h//2, text=self._text,
                         fill=self._fg, font=self._font, anchor="center")

    def _set(self, color):
        if not self._off:
            self._cur = color
            self._draw()

    def disable(self, yes: bool):
        self._off = yes
        self._cur = C["border"] if yes else self._norm
        self._fg_saved = self._fg
        self._fg = C["dim"] if yes else "#fff"
        self._draw()

    def relabel(self, text: str):
        self._text = text
        self._draw()


# ------------------------------------------------------------------
# Audio VU level meter
# ------------------------------------------------------------------

class LevelMeter(tk.Canvas):
    """Slim horizontal bar reflecting real-time mic input level."""

    def __init__(self, parent, w=200, h=5, **kw):
        super().__init__(parent, width=w, height=h,
                         bg=C["bg"], highlightthickness=0, **kw)
        self._w, self._h = w, h
        self._level = 0.0
        self._redraw(0.0)

    def set_level(self, level: float):
        level = max(0.0, min(1.0, level))
        if abs(level - self._level) > 0.015:
            self._level = level
            self._redraw(level)

    def _poly(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r,y1, x2-r,y1, x2,y1, x2,y1+r,
               x2,y2-r, x2,y2, x2-r,y2, x1+r,y2,
               x1,y2, x1,y2-r, x1,y1+r, x1,y1]
        self.create_polygon(pts, smooth=True, **kw)

    def _redraw(self, level: float):
        self.delete("all")
        self._poly(0, 0, self._w, self._h, 2, fill=C["border"], outline="")
        fw = int(self._w * level)
        if fw > 3:
            color = C["green"] if level < 0.72 else C["orange"]
            self._poly(0, 0, fw, self._h, 2, fill=color, outline="")


# ------------------------------------------------------------------
# Main window
# ------------------------------------------------------------------

class NirmiqEchoUI:
    """
    The NirmiqEcho application window.
    Receives updates from backend threads via a thread-safe queue
    drained every 50 ms on the main thread.
    """

    TITLE    = "NirmiqEcho"
    GEOMETRY = "420x540"
    TICK_MS  = 50

    def __init__(self, app):
        self.app = app
        self._q = queue.Queue()
        self._lines = []
        self._listening = False
        self._build()
        self._tick()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build(self):
        self.root = tk.Tk()
        self.root.title(self.TITLE)
        self.root.geometry(self.GEOMETRY)
        self.root.resizable(True, True)
        self.root.minsize(360, 460)
        self.root.configure(bg=C["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.attributes("-topmost", True)
        self._dark_titlebar()

        self._header()
        self._status_bar()
        self._meter_row()
        self._transcript_area()
        self._controls()
        self._footer()

    def _dark_titlebar(self):
        try:
            import ctypes
            hwnd = self.root.winfo_id()
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20,
                ctypes.byref(ctypes.c_int(1)),
                ctypes.sizeof(ctypes.c_int)
            )
        except Exception:
            pass

    def _header(self):
        f = tk.Frame(self.root, bg=C["bg"], padx=14, pady=10)
        f.pack(fill="x")

        tk.Label(f, text="🎙", font=("Segoe UI Emoji", 18),
                 bg=C["bg"], fg=C["accent"]).pack(side="left", padx=(0, 8))

        info = tk.Frame(f, bg=C["bg"])
        info.pack(side="left")
        tk.Label(info, text="NirmiqEcho", font=F["title"],
                 bg=C["bg"], fg=C["text"]).pack(anchor="w")
        self._model_lbl = tk.Label(info, text="Loading model…",
                                   font=F["small"], bg=C["bg"], fg=C["muted"])
        self._model_lbl.pack(anchor="w")

        # Always-on-top pin toggle
        self._pin = tk.BooleanVar(value=True)
        tk.Checkbutton(f, text="📌", variable=self._pin,
                       command=lambda: self.root.attributes("-topmost", self._pin.get()),
                       bg=C["bg"], fg=C["muted"], activebackground=C["bg"],
                       activeforeground=C["accent"], selectcolor=C["bg"],
                       relief="flat", cursor="hand2",
                       font=("Segoe UI Emoji", 12), bd=0).pack(side="right")

    def _status_bar(self):
        bar = tk.Frame(self.root, bg=C["surface"], padx=14, pady=7)
        bar.pack(fill="x", padx=10, pady=(0, 6))

        self._status_var = tk.StringVar(value="●  Idle")
        self._status_lbl = tk.Label(bar, textvariable=self._status_var,
                                    font=("Segoe UI", 9, "bold"),
                                    bg=C["surface"], fg=C["dim"])
        self._status_lbl.pack(side="left")

        tk.Label(bar, text="F9 to toggle", font=F["badge"],
                 bg=C["surface"], fg=C["dim"]).pack(side="right")

    def _meter_row(self):
        f = tk.Frame(self.root, bg=C["bg"], padx=10)
        f.pack(fill="x", pady=(0, 4))
        tk.Label(f, text="MIC", font=F["badge"],
                 bg=C["bg"], fg=C["dim"]).pack(side="left", padx=(0, 5))
        self._meter = LevelMeter(f, h=5)
        self._meter.pack(side="left", fill="x", expand=True)

    def _transcript_area(self):
        outer = tk.Frame(self.root, bg=C["bg"], padx=10)
        outer.pack(fill="both", expand=True, pady=(6, 0))

        tk.Label(outer, text="TRANSCRIPT", font=F["badge"],
                 bg=C["bg"], fg=C["dim"]).pack(anchor="w", pady=(0, 3))

        border = tk.Frame(outer, bg=C["border"], padx=1, pady=1)
        border.pack(fill="both", expand=True)

        inner = tk.Frame(border, bg=C["surface"])
        inner.pack(fill="both", expand=True)

        self._txt = tk.Text(inner, wrap="word", bg=C["surface"], fg=C["text"],
                            font=F["mono"], relief="flat", padx=10, pady=10,
                            insertbackground=C["accent"],
                            selectbackground=C["accent_dim"],
                            selectforeground=C["text"],
                            cursor="arrow")
        self._txt.pack(side="left", fill="both", expand=True)
        self._txt.config(state="disabled")

        sb = tk.Scrollbar(inner, command=self._txt.yview,
                          bg=C["surface"], troughcolor=C["surface"],
                          activebackground=C["border"], relief="flat", width=5)
        sb.pack(side="right", fill="y")
        self._txt.config(yscrollcommand=sb.set)

    def _controls(self):
        cf = tk.Frame(self.root, bg=C["bg"], padx=10, pady=8)
        cf.pack(fill="x")

        # Row 1: Start / Stop
        r1 = tk.Frame(cf, bg=C["bg"])
        r1.pack(fill="x", pady=(0, 5))

        self._start_btn = RoundBtn(r1, "▶  Start", self._start,
                                   w=176, h=34, bg=C["accent"], bg_h=C["accent_h"])
        self._start_btn.pack(side="left", padx=(0, 5))

        self._stop_btn = RoundBtn(r1, "■  Stop", self._stop,
                                  w=176, h=34, bg="#2a1010", bg_h=C["red"])
        self._stop_btn.pack(side="left")

        # Row 2: utility buttons
        r2 = tk.Frame(cf, bg=C["bg"])
        r2.pack(fill="x", pady=(0, 6))

        self._copy_btn = RoundBtn(r2, "⎘ Copy", self._copy,
                                  w=108, h=28, bg=C["surface2"], bg_h=C["surface"],
                                  font=F["small"])
        self._copy_btn.pack(side="left", padx=(0, 4))

        self._save_btn = RoundBtn(r2, "💾 Save", self._save,
                                  w=108, h=28, bg=C["surface2"], bg_h=C["surface"],
                                  font=F["small"])
        self._save_btn.pack(side="left", padx=(0, 4))

        self._clr_btn = RoundBtn(r2, "🗑 Clear", self._clear,
                                 w=108, h=28, bg=C["surface2"], bg_h="#2a1010",
                                 font=F["small"])
        self._clr_btn.pack(side="left")

        # VAD sensitivity slider
        sf = tk.Frame(cf, bg=C["bg"])
        sf.pack(fill="x")
        tk.Label(sf, text="VAD Sensitivity", font=F["small"],
                 bg=C["bg"], fg=C["muted"]).pack(side="left")
        self._sens = tk.IntVar(value=2)
        ttk.Style().configure("H.TScale", background=C["bg"],
                              troughcolor=C["surface2"])
        ttk.Scale(sf, from_=0, to=3, orient="horizontal",
                  variable=self._sens, style="H.TScale",
                  command=self._sens_changed).pack(side="left", fill="x",
                                                   expand=True, padx=6)
        self._sens_lbl = tk.Label(sf, text="2", font=F["small"],
                                  bg=C["bg"], fg=C["muted"], width=2)
        self._sens_lbl.pack(side="left")

    def _footer(self):
        f = tk.Frame(self.root, bg=C["bg"], padx=10, pady=5)
        f.pack(fill="x")
        self._wc_lbl = tk.Label(f, text="0 words", font=F["badge"],
                                 bg=C["bg"], fg=C["dim"])
        self._wc_lbl.pack(side="left")
        tk.Label(f, text="100% offline · no APIs", font=F["badge"],
                 bg=C["bg"], fg=C["dim"]).pack(side="right")

    # ------------------------------------------------------------------
    # Thread-safe update queue
    # ------------------------------------------------------------------

    def _tick(self):
        """Drain the UI queue and update the audio meter every TICK_MS."""
        try:
            while True:
                cmd, *args = self._q.get_nowait()
                fn = getattr(self, f"_do_{cmd}", None)
                if fn:
                    fn(*args)
        except queue.Empty:
            pass

        # Update mic level meter
        if self._listening and self.app.audio_handler:
            self._meter.set_level(self.app.audio_handler.audio_level)
        else:
            self._meter.set_level(0.0)

        self.root.after(self.TICK_MS, self._tick)

    def schedule(self, cmd: str, *args):
        """Thread-safe: enqueue a UI command from any background thread."""
        self._q.put((cmd, *args))

    # Dispatched handlers
    def _do_set_status(self, key: str):
        label, color = STATUS.get(key, STATUS["idle"])
        self._status_var.set(label)
        self._status_lbl.config(fg=color)

    def _do_append_transcript(self, text: str):
        self._lines.append(text)
        self._txt.config(state="normal")
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
        self._start_btn.disable(val)
        self._stop_btn.disable(not val)

    def _do_show_error(self, msg: str):
        messagebox.showerror("NirmiqEcho", msg, parent=self.root)

    def _do_show_info(self, msg: str):
        messagebox.showinfo("NirmiqEcho", msg, parent=self.root)

    # ------------------------------------------------------------------
    # Button callbacks
    # ------------------------------------------------------------------

    def _start(self): self.app.start_listening()
    def _stop(self):  self.app.stop_listening()

    def _copy(self):
        text = self._get_text()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._copy_btn.relabel("✓ Copied!")
            self.root.after(1400, lambda: self._copy_btn.relabel("⎘ Copy"))
        else:
            self.schedule("show_info", "Transcript is empty.")

    def _save(self):
        text = self._get_text()
        if not text:
            self.schedule("show_info", "Transcript is empty.")
            return
        fp = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Transcript", initialfile="nirmiqecho_transcript.txt",
        )
        if fp:
            try:
                Path(fp).write_text(text, encoding="utf-8")
                self.schedule("show_info", f"Saved to:\n{fp}")
            except Exception as exc:
                self.schedule("show_error", f"Could not save file:\n{exc}")

    def _clear(self):
        self._lines.clear()
        self._txt.config(state="normal")
        self._txt.delete("1.0", "end")
        self._txt.config(state="disabled")
        self._update_wc()

    def _sens_changed(self, val: str):
        v = int(float(val))
        self._sens.set(v)
        self._sens_lbl.config(text=str(v))
        self.app.set_sensitivity(v)

    def _close(self):
        self.app.shutdown()
        self.root.destroy()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_text(self) -> str:
        return self._txt.get("1.0", "end-1c").strip()

    def _update_wc(self):
        text = self._get_text()
        n = len(text.split()) if text else 0
        self._wc_lbl.config(text=f"{n} word{'s' if n != 1 else ''}")

    def run(self):
        self.root.mainloop()
