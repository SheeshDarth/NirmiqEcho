"""
units.py — offline unit conversion + simple date math for NirmiqEcho

100% offline, deterministic. No network, no API.

Conversions:
    "convert 5 km to miles"        -> 3.11 miles
    "10 kg in pounds"             -> 22.05 pounds
    "100 fahrenheit to celsius"   -> 37.78 celsius
    "5 feet in cm"                -> 152.4 cm
    "2 gb in mb"                  -> 2048 mb

Dates:
    "how many days until christmas"   -> N days
    "what's the date in 10 days"     -> <date>
    "what day is it in 3 days"        -> <weekday>
"""
import datetime
import re
from typing import Optional, Tuple

# ── Linear units: value-in-base. Base units: metre, gram, litre, mps, byte ──
_LENGTH = {
    "m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0,
    "km": 1000.0, "kilometer": 1000.0, "kilometers": 1000.0, "kilometre": 1000.0,
    "cm": 0.01, "centimeter": 0.01, "centimeters": 0.01,
    "mm": 0.001, "millimeter": 0.001, "millimeters": 0.001,
    "mile": 1609.344, "miles": 1609.344, "mi": 1609.344,
    "foot": 0.3048, "feet": 0.3048, "ft": 0.3048,
    "inch": 0.0254, "inches": 0.0254, "in": 0.0254,
    "yard": 0.9144, "yards": 0.9144, "yd": 0.9144,
}
_WEIGHT = {
    "g": 1.0, "gram": 1.0, "grams": 1.0,
    "kg": 1000.0, "kilogram": 1000.0, "kilograms": 1000.0, "kilo": 1000.0, "kilos": 1000.0,
    "mg": 0.001, "milligram": 0.001, "milligrams": 0.001,
    "pound": 453.592, "pounds": 453.592, "lb": 453.592, "lbs": 453.592,
    "ounce": 28.3495, "ounces": 28.3495, "oz": 28.3495,
    "ton": 1_000_000.0, "tons": 1_000_000.0, "tonne": 1_000_000.0, "tonnes": 1_000_000.0,
}
_VOLUME = {
    "l": 1.0, "liter": 1.0, "liters": 1.0, "litre": 1.0, "litres": 1.0,
    "ml": 0.001, "milliliter": 0.001, "milliliters": 0.001,
    "gallon": 3.78541, "gallons": 3.78541,
    "cup": 0.236588, "cups": 0.236588,
    "pint": 0.473176, "pints": 0.473176,
}
_SPEED = {
    "mps": 1.0, "kmh": 0.277778, "kph": 0.277778,
    "mph": 0.44704, "knot": 0.514444, "knots": 0.514444,
}
_DATA = {
    "byte": 1.0, "bytes": 1.0, "b": 1.0,
    "kb": 1024.0, "kilobyte": 1024.0, "kilobytes": 1024.0,
    "mb": 1024.0**2, "megabyte": 1024.0**2, "megabytes": 1024.0**2,
    "gb": 1024.0**3, "gigabyte": 1024.0**3, "gigabytes": 1024.0**3,
    "tb": 1024.0**4, "terabyte": 1024.0**4, "terabytes": 1024.0**4,
}
_LINEAR_TABLES = [_LENGTH, _WEIGHT, _VOLUME, _SPEED, _DATA]

_TEMP_ALIASES = {
    "celsius": "c", "centigrade": "c", "c": "c",
    "fahrenheit": "f", "f": "f",
    "kelvin": "k", "k": "k",
}

# Fixed holidays for "days until X" (month, day)
_HOLIDAYS = {
    "christmas": (12, 25), "new year": (1, 1), "new years": (1, 1),
    "valentines": (2, 14), "valentine's day": (2, 14), "halloween": (10, 31),
    "independence day": (8, 15),  # India
    "republic day": (1, 26), "diwali": None, "new year's": (1, 1),
}


def _fmt(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _find_table(unit: str):
    for tbl in _LINEAR_TABLES:
        if unit in tbl:
            return tbl
    return None


def _convert_temp(value: float, frm: str, to: str) -> float:
    # to celsius
    if frm == "c":
        c = value
    elif frm == "f":
        c = (value - 32) * 5 / 9
    else:  # k
        c = value - 273.15
    # from celsius
    if to == "c":
        return c
    if to == "f":
        return c * 9 / 5 + 32
    return c + 273.15


def convert(text: str) -> Optional[Tuple[str, str]]:
    """
    Parse + perform a unit conversion. Returns (result_str, spoken) or None.
    """
    t = text.lower().strip().rstrip("?.!")
    t = re.sub(r"^(?:convert|change|how many\b.*?\bis|what(?:'s| is))\s+", "", t)

    # number + from-unit + (to|in|into) + to-unit
    m = re.search(
        r"([-+]?\d+(?:\.\d+)?)\s*([a-z°]+)\s+(?:to|in|into|as)\s+([a-z°]+)", t)
    if not m:
        # "how many miles in 5 km"
        m2 = re.search(r"how many\s+([a-z°]+)\s+(?:in|are in)\s+"
                       r"([-+]?\d+(?:\.\d+)?)\s*([a-z°]+)", text.lower())
        if not m2:
            return None
        to_u, value_s, frm_u = m2.group(1), m2.group(2), m2.group(3)
        value = float(value_s)
    else:
        value, frm_u, to_u = float(m.group(1)), m.group(2), m.group(3)

    frm_u = frm_u.strip("°")
    to_u = to_u.strip("°")

    # Temperature
    if frm_u in _TEMP_ALIASES and to_u in _TEMP_ALIASES:
        out = _convert_temp(value, _TEMP_ALIASES[frm_u], _TEMP_ALIASES[to_u])
        r = _fmt(out)
        return (f"{r} {to_u}", f"{_fmt(value)} {frm_u} is {r} {to_u}.")

    # Linear (must be same category)
    frm_tbl = _find_table(frm_u)
    to_tbl = _find_table(to_u)
    if frm_tbl is not None and frm_tbl is to_tbl:
        base = value * frm_tbl[frm_u]
        out = base / to_tbl[to_u]
        r = _fmt(out)
        return (f"{r} {to_u}", f"{_fmt(value)} {frm_u} is {r} {to_u}.")

    return None


def date_query(text: str) -> Optional[Tuple[str, str]]:
    """Handle 'days until X' and 'date in N days'. Returns (result, spoken) or None."""
    t = text.lower().strip().rstrip("?.!")
    today = datetime.date.today()

    # "how many days until <holiday>" or "days until <month day>"
    m = re.search(r"(?:how many\s+)?days?\s+(?:until|till|to)\s+(.+)", t)
    if m:
        target_txt = m.group(1).strip()
        target = _parse_target_date(target_txt, today)
        if target:
            delta = (target - today).days
            if delta < 0:
                # next year
                target = target.replace(year=target.year + 1)
                delta = (target - today).days
            day_word = "day" if delta == 1 else "days"
            return (f"{delta} {day_word}",
                    f"{delta} {day_word} until {target_txt}.")

    # "what's the date in N days" / "date N days from now"
    m = re.search(r"date\s+(?:in\s+)?(\d+)\s+days?(?:\s+from now)?", t)
    if m:
        n = int(m.group(1))
        target = today + datetime.timedelta(days=n)
        s = target.strftime("%A, %d %B %Y")
        return (s, f"That will be {s}.")

    # "what day is it in N days"
    m = re.search(r"(?:what day.*?in|in)\s+(\d+)\s+days?", t)
    if m:
        n = int(m.group(1))
        target = today + datetime.timedelta(days=n)
        wd = target.strftime("%A")
        return (wd, f"That will be a {wd}.")

    return None


def _parse_target_date(txt: str, today: datetime.date) -> Optional[datetime.date]:
    txt = txt.strip()
    if txt in _HOLIDAYS and _HOLIDAYS[txt]:
        mo, da = _HOLIDAYS[txt]
        return datetime.date(today.year, mo, da)
    # "december 25" / "25 december"
    months = {m.lower(): i for i, m in enumerate(
        ["", "January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"])}
    m = re.search(r"([a-z]+)\s+(\d{1,2})", txt) or None
    if m and m.group(1) in months:
        return datetime.date(today.year, months[m.group(1)], int(m.group(2)))
    m = re.search(r"(\d{1,2})\s+([a-z]+)", txt)
    if m and m.group(2) in months:
        return datetime.date(today.year, months[m.group(2)], int(m.group(1)))
    return None


if __name__ == "__main__":
    conv_cases = {
        "convert 5 km to miles": "3.11 miles",
        "10 kg in pounds": "22.05 pounds",
        "100 fahrenheit to celsius": "37.78 celsius",
        "5 feet in cm": "152.4 cm",
        "2 gb in mb": "2048 mb",
        "1 mile in km": "1.61 km",
        "0 celsius to fahrenheit": "32 fahrenheit",
    }
    p = 0
    for phrase, want in conv_cases.items():
        got = convert(phrase)
        res = got[0] if got else None
        ok = res == want
        p += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {phrase!r:34} -> {res} (want {want})")
    print(f"{p}/{len(conv_cases)} conversions passed")
    assert convert("open chrome") is None
    print("non-conversion rejected")
    # date smoke test
    print("days until christmas ->", date_query("how many days until christmas"))
    print("date in 10 days ->", date_query("what's the date in 10 days"))
