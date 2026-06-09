"""
NirmiqEcho System Tray
═══════════════════════
pystray icon in the notification area.
  Left-click  → show / hide overlay
  Right-click → context menu
Icon is generated with Pillow — no external .ico needed.
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw


# ── icon generation ───────────────────────────────────────────────────

def _make_icon(state: str = "idle") -> Image.Image:
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    colors = {
        "idle":       ("#0d1a3a", "#00d4ff"),
        "listening":  ("#001a2e", "#00d4ff"),
        "processing": ("#0d001a", "#7b61ff"),
        "muted":      ("#1e293b", "#475569"),
        "loading":    ("#0d1a3a", "#7b61ff"),
    }
    bg_col, ring_col = colors.get(state, colors["idle"])

    # Background circle
    draw.ellipse([2, 2, 62, 62], fill=bg_col)
    # Ring
    draw.ellipse([2, 2, 62, 62], outline=ring_col, width=4)
    # Center dot
    draw.ellipse([26, 26, 38, 38], fill=ring_col)

    return img


# ── tray class ────────────────────────────────────────────────────────

class EchoTray:
    def __init__(
        self,
        on_toggle_listen: callable,
        on_toggle_mute:   callable,
        on_show_overlay:  callable,
        on_quit:          callable,
    ):
        self._toggle_listen  = on_toggle_listen
        self._toggle_mute    = on_toggle_mute
        self._show_overlay   = on_show_overlay
        self._quit           = on_quit
        self._icon           = None
        self._state          = "loading"

    def set_state(self, state: str):
        self._state = state
        if self._icon:
            self._icon.icon = _make_icon(state)
            tooltips = {
                "idle":       "NirmiqEcho — Ready",
                "listening":  "NirmiqEcho — Listening…",
                "processing": "NirmiqEcho — Processing…",
                "muted":      "NirmiqEcho — Muted",
                "loading":    "NirmiqEcho — Loading model…",
            }
            self._icon.title = tooltips.get(state, "NirmiqEcho")

    def run(self):
        """Blocks — must be called from main thread on Windows."""
        import pystray

        def _on_click(icon, item):
            label = str(item)
            if label == "Show Overlay":
                self._show_overlay()
            elif label in ("Mute", "Unmute"):
                self._toggle_mute()
            elif label == "Quit":
                icon.stop()
                self._quit()

        def _left_click(icon, item):
            self._show_overlay()

        menu = pystray.Menu(
            pystray.MenuItem("Show Overlay",  _on_click, default=True),
            pystray.MenuItem(
                lambda _: "Unmute" if self._state == "muted" else "Mute",
                _on_click,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", _on_click),
        )

        self._icon = pystray.Icon(
            name="NirmiqEcho",
            icon=_make_icon("loading"),
            title="NirmiqEcho — Loading model…",
            menu=menu,
        )
        self._icon.run()
