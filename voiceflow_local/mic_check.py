"""
mic_check.py — NirmiqEcho microphone diagnostic

Run this whenever Echo seems deaf:
    python mic_check.py

Checks, in order:
  1. Input devices visible to sounddevice + which one is default
  2. Windows microphone privacy consent (registry)
  3. A 3-second live capture from the default device — reports RMS/peak
  4. webrtcvad reaction to the captured audio (is the VAD seeing speech?)
"""

import sys
import numpy as np


def list_devices():
    import sounddevice as sd
    print("=== 1. INPUT DEVICES ===")
    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = None
    found = False
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            found = True
            mark = "  <-- DEFAULT" if i == default_in else ""
            print(f"  [{i}] {d['name']}  "
                  f"({d['max_input_channels']}ch, {d['default_samplerate']:.0f} Hz){mark}")
    if not found:
        print("  NO INPUT DEVICES FOUND — check device manager / drivers")
    print()
    return found


def check_privacy():
    print("=== 2. WINDOWS MIC PRIVACY ===")
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion"
            r"\CapabilityAccessManager\ConsentStore\microphone",
        )
        val, _ = winreg.QueryValueEx(key, "Value")
        print(f"  Desktop-app microphone access: {val}")
        if str(val).lower() != "allow":
            print("  PROBLEM: Windows is BLOCKING desktop apps from the mic.")
            print("  Fix: Settings > Privacy & security > Microphone >")
            print("       enable 'Microphone access' AND 'Let desktop apps access'")
            return False
    except Exception as exc:
        print(f"  Could not read consent registry ({exc}) — check manually in Settings")
    print()
    return True


def check_mute():
    print("=== 2.5 WINDOWS MIC MUTE / LEVEL ===")
    try:
        from pycaw.pycaw import (IAudioEndpointVolume, IMMDeviceEnumerator,
                                 EDataFlow, ERole)
        from pycaw.constants import CLSID_MMDeviceEnumerator
        from comtypes import CLSCTX_ALL, CoCreateInstance

        enum = CoCreateInstance(CLSID_MMDeviceEnumerator,
                                IMMDeviceEnumerator, CLSCTX_ALL)
        dev = enum.GetDefaultAudioEndpoint(EDataFlow.eCapture.value,
                                           ERole.eConsole.value)
        vol = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL,
                           None).QueryInterface(IAudioEndpointVolume)
        muted = bool(vol.GetMute())
        level = vol.GetMasterVolumeLevelScalar() * 100
        print(f"  muted: {muted}   level: {level:.0f}%")
        if muted:
            vol.SetMute(0, None)
            print("  FIXED: microphone was muted — unmuted it now.")
            print("  (Tip: your laptop's mic-mute F-key toggles this.)")
        if level < 40:
            vol.SetMasterVolumeLevelScalar(0.80, None)
            print("  FIXED: input level was very low — raised to 80%.")
    except ImportError:
        print("  pycaw not installed — pip install pycaw comtypes")
    except Exception as exc:
        print(f"  could not check mute state: {exc}")
    print()


def capture_test(seconds: float = 3.0, samplerate: int = 16000):
    import sounddevice as sd
    print(f"=== 3. {seconds:.0f}-SECOND CAPTURE TEST ===")
    print("  Speak normally NOW...")
    try:
        rec = sd.rec(int(seconds * samplerate), samplerate=samplerate,
                     channels=1, dtype="int16")
        sd.wait()
    except Exception as exc:
        print(f"  CAPTURE FAILED: {exc}")
        print("  Another app may hold the mic exclusively, or the device is broken.")
        return None

    pcm = rec.flatten()
    f32 = pcm.astype(np.float32)
    rms = float(np.sqrt(np.mean(f32 ** 2)))
    peak = int(np.max(np.abs(pcm)))
    zero_pct = float(np.mean(pcm == 0)) * 100

    print(f"  RMS: {rms:.1f}   peak: {peak}   zero-samples: {zero_pct:.0f}%")
    if peak == 0:
        print("  VERDICT: PURE SILENCE — privacy block, muted device, or wrong default mic")
    elif rms < 5:
        print("  VERDICT: nearly dead — raise input level/boost in Sound settings,")
        print("           or the default device is the wrong mic (see list above)")
    elif rms < 50:
        print("  VERDICT: very quiet — usable, but raise the Windows input level")
    else:
        print("  VERDICT: mic capturing fine at OS level")
    print()
    return pcm


def vad_test(pcm):
    if pcm is None:
        return
    print("=== 4. WEBRTCVAD REACTION ===")
    try:
        import webrtcvad
    except ImportError:
        print("  webrtcvad not installed — pip install webrtcvad-wheels")
        return
    frame_len = 480  # 30 ms @ 16 kHz
    n = len(pcm) // frame_len
    for sens in (1, 2, 3):
        vad = webrtcvad.Vad(sens)
        voiced = sum(
            1 for i in range(n)
            if vad.is_speech(pcm[i * frame_len:(i + 1) * frame_len].tobytes(), 16000)
        )
        print(f"  sensitivity {sens}: {voiced}/{n} frames voiced ({voiced / n * 100:.0f}%)")
    print("  (If you spoke and sensitivity 1 shows ~0%, the signal is too quiet")
    print("   for VAD — raise the Windows mic level. If it shows >80% while you")
    print("   were silent, the environment is too noisy / mic gain too hot.)")


if __name__ == "__main__":
    ok = list_devices()
    if not ok:
        sys.exit(1)
    check_privacy()
    check_mute()
    pcm = capture_test()
    vad_test(pcm)
