# nirmiqecho.spec — PyInstaller onedir build for NirmiqEcho (MS0 de-risk spike)
#
# Build:   pyinstaller nirmiqecho.spec         (see build/README.md)
# Output:  dist/NirmiqEcho/NirmiqEcho.exe
#
# This is the SPIKE build: console stays ON so we can see errors, and the goal
# is only "does PyInstaller freeze these native deps and launch". MS3 flips
# console off, resolves the writable-data-dir, and bundles the real model.

import os
from PyInstaller.utils.hooks import collect_all

APP_NAME = "NirmiqEcho"
HERE = os.path.abspath(SPECPATH)          # noqa: F821 (SPECPATH injected by PyInstaller)
SRC = os.path.join(HERE, "voiceflow_local")

# collect_all pulls datas + binaries + hiddenimports for packages whose native
# DLLs / data files PyInstaller's static analysis misses. These are the known
# troublemakers for this app.
datas, binaries, hiddenimports = [], [], []
for pkg in (
    "faster_whisper",   # + ctranslate2 tokenizer assets
    "ctranslate2",      # native inference DLLs
    "sounddevice",      # PortAudio DLL
    "noisereduce",
    "pycaw",            # Core Audio COM wrappers (mic auto-rescue)
    "comtypes",         # COM plumbing for pycaw + SAPI
    "pystray",          # tray backend
    "pyttsx3",          # SAPI TTS driver
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # a missing optional pkg shouldn't kill the spike build
        print(f"[spec] collect_all({pkg!r}) skipped: {exc}")

# Hidden imports the collectors still miss (lazy / string-based imports).
hiddenimports += [
    "pyttsx3.drivers",
    "pyttsx3.drivers.sapi5",
    "pystray._win32",
    "comtypes.stream",
]

# Bundle config template so first run can seed .env inside the frozen app.
if os.path.exists(os.path.join(HERE, ".env.example")):
    datas += [(os.path.join(HERE, ".env.example"), ".")]
if os.path.exists(os.path.join(HERE, "commands.example.yaml")):
    datas += [(os.path.join(HERE, "commands.example.yaml"), ".")]

# Optional: bundle a CPU Whisper model for a truly-offline first launch.
# Prepare ./models_bundle/ with small.en int8 (see build/README.md); kept out
# of git. MS3 wires transcription.py to load it by path with local_files_only.
if os.path.isdir(os.path.join(HERE, "models_bundle")):
    datas += [(os.path.join(HERE, "models_bundle"), "models_bundle")]

a = Analysis(
    [os.path.join(SRC, "main.py")],
    pathex=[SRC],               # flat intra-package imports (import audio_handler, ...)
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[os.path.join(HERE, "packaging", "hooks")],   # overrides broken contrib hook-webrtcvad.py
    runtime_hooks=[],
    excludes=["torch"],         # ponytail: CPU CTranslate2 needs no torch; drop the GBs
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    console=True,               # ponytail: spike keeps console; MS3 -> console=False
    disable_windowed_traceback=False,
    icon=None,                  # add assets/icon.ico in MS4
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,                  # UPX + native DLLs = AV false-positives; keep off
    name=APP_NAME,
)
