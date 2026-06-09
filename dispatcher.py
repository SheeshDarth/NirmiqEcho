"""Routes parsed intents to handler functions. All calls are synchronous."""
from __future__ import annotations

import datetime

from handlers.apps    import open_app, close_app, minimize_app
from handlers.whatsapp import whatsapp_message, whatsapp_call, whatsapp_video_call
from handlers.media   import play_music, pause_music, stop_music, next_track, prev_track, set_volume, toggle_mute
from handlers.files   import open_file, search_file, open_folder
from handlers.typer   import type_text, press_key
from handlers.system  import shutdown, restart, sleep_pc, lock_screen, screenshot, cancel_shutdown, get_battery, get_wifi
from handlers.browser import web_search, open_url


def execute(intent: dict) -> str:
    name = intent.get("intent", "UNKNOWN")
    p    = intent.get("params", {})

    def s(key, default=""):
        return str(p.get(key, default)).strip()

    try:
        match name:
            # Apps
            case "OPEN_APP":            return open_app(s("app"))
            case "CLOSE_APP":           return close_app(s("app"))
            case "MINIMIZE_APP":        return minimize_app(s("app"))

            # WhatsApp
            case "WHATSAPP_MESSAGE":    return whatsapp_message(s("contact"), s("message"))
            case "WHATSAPP_CALL":       return whatsapp_call(s("contact"))
            case "WHATSAPP_VIDEO_CALL": return whatsapp_video_call(s("contact"))

            # Phone
            case "CALL_CONTACT":
                import subprocess
                subprocess.run(f'start tel:{s("contact")}', shell=True)
                return f"Calling {s('contact')}."

            # Typing
            case "TYPE_TEXT":           return type_text(s("text"))
            case "PRESS_KEY":           return press_key(s("key"))

            # Music
            case "PLAY_MUSIC":          return play_music(s("query"))
            case "PAUSE_MUSIC":         return pause_music()
            case "STOP_MUSIC":          return stop_music()
            case "NEXT_TRACK":          return next_track()
            case "PREV_TRACK":          return prev_track()
            case "VOLUME_UP":           return set_volume("up")
            case "VOLUME_DOWN":         return set_volume("down")
            case "TOGGLE_MUTE":         return toggle_mute()
            case "SET_VOLUME":          return set_volume("set", int(p.get("level", 50)))

            # Files
            case "OPEN_FILE":           return open_file(s("filename"))
            case "SEARCH_FILE":         return search_file(s("query"), s("location"))
            case "OPEN_FOLDER":         return open_folder(s("folder"))

            # Browser
            case "WEB_SEARCH":          return web_search(s("query"))
            case "OPEN_URL":            return open_url(s("url"))

            # System
            case "SHUTDOWN":            return shutdown()
            case "RESTART":             return restart()
            case "SLEEP":               return sleep_pc()
            case "LOCK":                return lock_screen()
            case "SCREENSHOT":          return screenshot()
            case "CANCEL_SHUTDOWN":     return cancel_shutdown()
            case "GET_BATTERY":         return get_battery()
            case "GET_WIFI":            return get_wifi()

            # Info
            case "GET_TIME":
                t = datetime.datetime.now().strftime("%I:%M %p")
                return f"It's {t}."
            case "GET_DATE":
                d = datetime.datetime.now().strftime("%A, %B %d, %Y")
                return f"Today is {d}."

            case _:
                raw = p.get("raw", name)
                return f"I didn't understand: {raw}"

    except Exception as exc:
        return f"Something went wrong: {exc}"
