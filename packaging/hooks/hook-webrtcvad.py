# Local override of pyinstaller-hooks-contrib's hook-webrtcvad.py.
# The stock hook does `copy_metadata('webrtcvad')`, which raises because this
# project installs the prebuilt fork `webrtcvad-wheels` (different dist name).
# The app only imports the `webrtcvad` C module — it never reads the metadata —
# so copying the real dist's metadata (best-effort) is enough.

from PyInstaller.utils.hooks import copy_metadata

try:
    datas = copy_metadata("webrtcvad-wheels")
except Exception:
    datas = []
