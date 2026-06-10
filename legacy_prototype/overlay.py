"""
NirmiqEcho Floating Overlay
═══════════════════════════
Minimal always-on-top tkinter window.
  • Shows current state (idle / listening / processing)
  • Pulses orb ring while listening
  • Displays transcript and response text
  • Draggable by clicking anywhere
  • Hides to tray on close button
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import font as tkfont


BG         = "#080c14"
ACCENT     = "#00d4ff"
ACCENT2    = "#7b61ff"
MUTED      = "#475569"
TEXT       = "#e2e8f0"
SUCCESS    = "#22d3a5"
DANGER     = "#ff4d6d"

ORB_IDLE       = "#0d1a3a"
ORB_LISTENING  = "#00d4ff"
ORB_PROCESSING = "#7b61ff"
ORB_MUTED      = "#1e293b"


class EchoOverlay:
    def __init__(self, on_close_to_tray: callable | None = None):
        self._on_close = on_close_to_tray
        self._root: tk.Tk | None = None
        self._state  = "loading"
        self._drag_x = 0
        self._drag_y = 0
        self._pulse_job = None
        self._pulse_phase = 0
        self._built = False

    # ── public API ───────────────────────────────────────────────────

    def show(self):
        if self._root:
            self._root.deiconify()
            self._root.lift()

    def hide(self):
        if self._root:
            self._root.withdraw()

    def set_state(self, state: str):
        """state: 'loading' | 'idle' | 'listening' | 'processing' | 'muted'"""
        self._state = state
        if self._built:
            self._root.after(0, self._update_state)

    def set_transcript(self, text: str):
        if self._built:
            self._root.after(0, lambda: self._transcript_var.set(f'"{text}"'))

    def set_response(self, text: str):
        if self._built:
            self._root.after(0, lambda: self._response_var.set(text))

    def run(self):
        """Blocks — call from dedicated thread or main thread."""
        self._build()
        self._root.mainloop()

    def schedule(self, fn):
        if self._root:
            self._root.after(0, fn)

    # ── build ─────────────────────────────────────────────────────────

    def _build(self):
        root = tk.Tk()
        self._root = root

        root.title("NirmiqEcho")
        root.overrideredirect(True)          # no titlebar
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.96)
        root.configure(bg=BG)
        root.resizable(False, False)

        # Position bottom-right corner
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = 320, 200
        root.geometry(f"{w}x{h}+{sw - w - 24}+{sh - h - 60}")

        # ── drag ────────────────────────────────────────────────────
        root.bind("<ButtonPress-1>",   self._drag_start)
        root.bind("<B1-Motion>",       self._drag_motion)

        # ── top bar ─────────────────────────────────────────────────
        top = tk.Frame(root, bg=BG, height=26)
        top.pack(fill="x", padx=0, pady=0)
        top.bind("<ButtonPress-1>", self._drag_start)
        top.bind("<B1-Motion>",     self._drag_motion)

        brand = tk.Label(top, text="NIRMIQ  ECHO", bg=BG,
                         fg=ACCENT, font=("Segoe UI", 8, "bold"),
                         letterSpacing=4)
        brand.pack(side="left", padx=12, pady=4)

        close_btn = tk.Label(top, text="×", bg=BG, fg=MUTED,
                              font=("Segoe UI", 14), cursor="hand2")
        close_btn.pack(side="right", padx=10, pady=2)
        close_btn.bind("<Button-1>", lambda _: self._handle_close())

        # ── orb canvas ───────────────────────────────────────────────
        self._canvas = tk.Canvas(root, width=80, height=80, bg=BG,
                                  highlightthickness=0)
        self._canvas.pack(pady=(4, 0))

        # outer ring
        self._ring = self._canvas.create_oval(
            8, 8, 72, 72,
            outline=ACCENT, width=1.5, fill=ORB_IDLE
        )
        # inner core
        self._core = self._canvas.create_oval(
            18, 18, 62, 62,
            outline="", fill=ORB_IDLE
        )
        # dot
        self._canvas.create_oval(38, 38, 42, 42, fill=ACCENT, outline="")

        # ── state label ──────────────────────────────────────────────
        self._state_var = tk.StringVar(value="Loading model…")
        self._state_lbl = tk.Label(
            root, textvariable=self._state_var,
            bg=BG, fg=MUTED,
            font=("Segoe UI", 8), pady=0
        )
        self._state_lbl.pack()

        # ── transcript ───────────────────────────────────────────────
        self._transcript_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self._transcript_var,
                 bg=BG, fg="#94a3b8",
                 font=("Segoe UI", 9, "italic"),
                 wraplength=290, justify="center").pack(pady=(2, 0))

        # ── response ─────────────────────────────────────────────────
        self._response_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self._response_var,
                 bg=BG, fg=ACCENT,
                 font=("Segoe UI", 9, "bold"),
                 wraplength=290, justify="center").pack(pady=(2, 6))

        self._built = True
        self._update_state()
        self._pulse_loop()

    # ── state → visuals ───────────────────────────────────────────────

    def _update_state(self):
        c = self._canvas
        s = self._state

        state_colors = {
            "loading":    (ORB_MUTED,      MUTED,      "Loading model…"),
            "idle":       (ORB_IDLE,        MUTED,      "Ready — say something"),
            "listening":  (ORB_LISTENING,   ACCENT,     "Listening…"),
            "processing": (ORB_PROCESSING,  ACCENT2,    "Processing…"),
            "muted":      (ORB_MUTED,        DANGER,    "Muted"),
        }
        fill, outline, label = state_colors.get(s, (ORB_IDLE, MUTED, s))
        c.itemconfig(self._core, fill=fill)
        c.itemconfig(self._ring, outline=outline)
        self._state_var.set(label)

    def _pulse_loop(self):
        """Animate ring opacity when listening."""
        if not self._built or self._root is None:
            return
        if self._state == "listening":
            self._pulse_phase = (self._pulse_phase + 0.12) % (2 * 3.14159)
            import math
            alpha = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(self._pulse_phase))
            r = int(0 + (0x0 - 0) * (1 - alpha))
            g = int(180 + (0xd4 - 180) * alpha)
            b = int(200 + (0xff - 200) * alpha)
            color = f"#{r:02x}{g:02x}{b:02x}"
            self._canvas.itemconfig(self._ring, outline=color, width=2.0)
        self._pulse_job = self._root.after(50, self._pulse_loop)

    # ── drag ─────────────────────────────────────────────────────────

    def _drag_start(self, event):
        self._drag_x = event.x_root - self._root.winfo_x()
        self._drag_y = event.y_root - self._root.winfo_y()

    def _drag_motion(self, event):
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self._root.geometry(f"+{x}+{y}")

    def _handle_close(self):
        self.hide()
        if self._on_close:
            self._on_close()
