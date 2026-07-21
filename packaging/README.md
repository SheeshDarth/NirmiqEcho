# Building NirmiqEcho (packaging)

> This directory holds the build scaffolding that must be **tracked in git**
> (the spec's hook overrides + these notes). It is deliberately NOT named
> `build/` or `dist/` — those are gitignored and are also where PyInstaller
> writes its own working + output trees.

Goal: freeze the app's native deps (faster-whisper/CTranslate2, sounddevice/
PortAudio, pycaw/COM, noisereduce, pystray) into a **onedir** build that launches
on a **clean, Python-free** Windows box, and see how Windows SmartScreen reacts.

## Prerequisites — build from a CLEAN venv

MS0 finding: building from a kitchen-sink system Python dragged in ~2.6 GB of
unrelated ML libs (bitsandbytes/CUDA, wandb, ...). Always build from a fresh
venv with ONLY the app's requirements:

```
py -3.12 -m venv .buildenv
.buildenv\Scripts\activate
pip install -r voiceflow_local\requirements.txt pyinstaller
```

## Optional: bundle a CPU model for a truly-offline first launch

```
# small.en int8 (~0.5 GB) — grab it once, then the spec bundles models_bundle/:
python -c "from faster_whisper import download_model; download_model('small.en', output_dir='models_bundle')"
```

## Build

```
pyinstaller nirmiqecho.spec
```

Output: `dist/NirmiqEcho/NirmiqEcho.exe` (console ON for the spike; MS3 flips it off).

## Test on THIS machine

1. Run the exe; watch the console for missing-DLL / `ModuleNotFoundError`. Fix by
   adding the name to `hiddenimports` (or a `collect_all(...)` package) in
   `nirmiqecho.spec`, then rebuild.
2. Tray icon appears; **F9** starts/stops listening; **F10** flips Command⟷Dictation.
3. Say one command ("what time is it") and dictate one phrase into Notepad.

## Test on a CLEAN box (the real gate — manual)

Copy `dist/NirmiqEcho/` to a Windows machine with **no Python**:

1. **SmartScreen:** does "Windows protected your PC" appear? Does "More info →
   Run anyway" launch it? (Unsigned + mic + keyboard-hook = likely flagged.)
2. **Defender:** any quarantine of the exe or the model download?
3. **Hotkey:** does F9/F10 work without admin? If not, record it (the app already
   falls back to tray-click when the global hook can't bind).
4. **Offline:** disable networking — does it still load a model and transcribe?
   (Requires `models_bundle/` bundled above.)

## Notes

- `upx=False` on purpose — UPX-compressed native DLLs trip antivirus heuristics.
- `excludes=["torch"]` — CPU CTranslate2 needs no torch; keeps the build small.
- Onedir (not onefile): onefile unpacks to temp each launch — slower start and
  worse AV optics for an app that hooks the keyboard.
- The `hooks/hook-webrtcvad.py` override is load-bearing: the stock PyInstaller
  hook crashes on the `webrtcvad-wheels` fork. Keep it tracked.
