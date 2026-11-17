"""GTA VI launch-day Twitch concurrency forecast: two-kernel analogue model.

Method
------
Hour 1's print is given by the case. For every later hour the model asks what the
comparable launches did between their own hour 1 and that same hour, and reads the
weighted quantiles of those log growth ratios back onto our hour 1.

Two kernels shape which comparables count, both computable from the case alone:

  * magnitude - a Gaussian on the log gap between a comparable's hour-1 audience and
    ours, so a launch that drew a comparable crowd outweighs one a hundred times
    smaller or larger. Without it a 164-viewer launch and an 875k-viewer launch would
    speak with the same voice.
  * hype - a Gaussian on the log gap between a comparable's own hype surge and ours,
    where the surge is hour 1's print over the mean of the last 24 hours before the
    release day. Two launches that open at the same size can still be travelling in
    opposite directions: a title whose pre-release audience was already large barely
    moves, while one that was quiet and then spiked carries a different first-day
    shape. Measured on leave-one-out over the comparables this second kernel is the
    single largest gain the model has, so it is not decoration.

Neighbouring hours are pooled into the sample with a decaying weight, because one
hour's print is noisy and the day's shape is smooth: an estimate at hour 10 borrows
strength from hours 7-13.

Determinism: standard library only, no clock, no random source. Two runs over the
same case write identical bytes.
"""

import json
import math
import os

IN_DIR = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
OUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
# Standard-normal quantiles at LEVELS: the fallback's shape is the house baseline's.
Z = (-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722)

MAG_BW = 1.0       # log-viewers bandwidth of the magnitude kernel
HYPE_BW = 0.3      # log-surge bandwidth of the hype kernel
HOUR_WIN = 4       # hours pooled either side of the target hour
HOUR_DECAY = 0.25  # neighbour weight = 1 / (1 + HOUR_DECAY * distance)
PRE_HOURS = 24     # hours of pre-release history the surge is measured over
MIN_PAIRS = 4      # fewer samples than this: fall back to the house shape
BASE_SIGMA = 0.15  # the house baseline's per-sqrt-hour log spread
FLOOR = 1e-9
CAP = 1e9


def hour_index(stamp):
    """1 for the release day's first hour, from an ISO 8601 'from'/'at' stamp."""
    try:
        return int(stamp[11:13]) + 1
    except (TypeError, ValueError, IndexError):
        return None


def positive(value):
    """A viewer count as a positive float, or None when it is missing or unusable."""
    if value is None:
        return None
    try:
        return max(1.0, float(value))
    except (TypeError, ValueError):
        return None


def launch_profile(comparable):
    """Release-day hours and the pre-release surge of one comparable."""
    day = str(comparable.get("day_start") or "")[:10]
    if not day:
        return None
    hours = {}
    earlier = []
    for row in comparable.get("hourly") or ():
        stamp = str(row.get("from") or "")
        if len(stamp) < 13:
            continue
        seen = positive(row.get("viewers"))
        if seen is None:
            continue
        if stamp[:10] == day:
            hour = hour_index(stamp)
            if hour is not None:
                hours[hour] = seen
        else:
            earlier.append((stamp, seen))
    earlier.sort()
    surge = None
    tail = [seen for _, seen in earlier[-PRE_HOURS:]]
    first = hours.get(1)
    if tail and first:
        mean = sum(tail) / len(tail)
        if mean > 0.0:
            surge = first / mean
    return {"hours": hours, "surge": surge}


def usable(comparable):
    """A comparable is a real launch day, not the category's own preview history."""
    text = (str(comparable.get("unlock") or "") + " " +
            str(comparable.get("tier") or "")).lower()
    return not ("not a launch" in text or "target-history" in text)


def case_surge(case, first):
    """Our own hype surge, measured the same way as the comparables'."""
    if not first:
        return None
    day = str(case.get("day_start") or "")[:10]
    tail = []
    for row in case.get("history_hourly") or ():
        stamp = str(row.get("from") or "")
        if len(stamp) < 13 or stamp[:10] >= day:
            continue
        seen = positive(row.get("viewers"))
        if seen is not None:
            tail.append((stamp, seen))
    if not tail:
        return None
    tail.sort()
    recent = [seen for _, seen in tail[-PRE_HOURS:]]
    mean = sum(recent) / len(recent)
    return (first / mean) if mean > 0.0 else None


def first_print(case):
    """Hour 1's print, with a fallback to the last recorded hourly point."""
    for row in case.get("known") or ():
        if row.get("hour") == 1:
            seen = positive(row.get("viewers"))
            if seen is not None:
                return seen
    for row in reversed(case.get("history_hourly") or ()):
        seen = positive(row.get("viewers"))
        if seen is not None:
            return seen
    return 1.0


def weighted_quantiles(samples):
    """Linear-interpolated quantiles of (value, weight) pairs at LEVELS."""
    if not samples:
        return None
    ordered = sorted(samples, key=lambda pair: pair[0])
    total = 0.0
    for _, weight in ordered:
        total += weight
    if not total > 0.0:
        middle = ordered[len(ordered) // 2][0]
        return [middle] * len(LEVELS)
    marks = []
    running = 0.0
    for _, weight in ordered:
        running += weight
        marks.append(running / total)
    out = []
    for level in LEVELS:
        if level <= marks[0]:
            out.append(ordered[0][0])
            continue
        if level >= marks[-1]:
            out.append(ordered[-1][0])
            continue
        for index in range(1, len(marks)):
            if level <= marks[index]:
                low, high = marks[index - 1], marks[index]
                span = high - low
                part = 0.0 if span <= 0.0 else (level - low) / span
                start = ordered[index - 1][0]
                out.append(start + part * (ordered[index][0] - start))
                break
    return out


def house_shape(first, hour):
    """The fallback: hour 1 held flat, the log spread widening as sqrt(hour - 1)."""
    scale = BASE_SIGMA * math.sqrt(max(hour - 1, 0))
    return [first * math.exp(z * scale) for z in Z]


def kernel(a, b, bandwidth):
    """Gaussian weight on the log gap of two positive quantities."""
    if not a or not b or a <= 0.0 or b <= 0.0:
        return 1.0
    gap = math.log(a / b) / bandwidth
    return math.exp(-0.5 * gap * gap)


def forecast_hour(first, hour, profiles, our_surge):
    """The five quantiles of `hour`'s audience."""
    samples = []
    for profile in profiles:
        hours = profile["hours"]
        begin = hours.get(1)
        if not begin or begin <= 0.0:
            continue
        weight = kernel(begin, first, MAG_BW)
        if our_surge and profile["surge"]:
            weight *= kernel(profile["surge"], our_surge, HYPE_BW)
        if weight <= 1e-12:
            continue
        for near in range(hour - HOUR_WIN, hour + HOUR_WIN + 1):
            later = hours.get(near)
            if not later or later <= 0.0:
                continue
            decay = 1.0 / (1.0 + HOUR_DECAY * abs(near - hour))
            samples.append((math.log(later / begin), weight * decay))
    if len(samples) < MIN_PAIRS:
        return house_shape(first, hour)
    ratios = weighted_quantiles(samples)
    if ratios is None:
        return house_shape(first, hour)
    return [first * math.exp(ratio) for ratio in ratios]


def tidy(values):
    """Clamp to (0, CAP], force non-decreasing, and round so the bytes are stable."""
    out = []
    previous = 0.0
    for value in values:
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = CAP
        if value != value:  # NaN can never be serialised
            value = CAP
        value = min(CAP, max(FLOOR, value))
        if value < previous:
            value = previous
        previous = value
        out.append(round(value, 6))
    return out


def forecast_case(case):
    first = first_print(case)
    our_surge = case_surge(case, first)
    profiles = []
    for comparable in case.get("comparables") or ():
        if not usable(comparable):
            continue
        profile = launch_profile(comparable)
        if profile is not None:
            profiles.append(profile)
    rows = []
    for row in case.get("forecast") or ():
        hour = int(row["hour"])
        rows.append({"hour": hour,
                     "q": tidy(forecast_hour(first, hour, profiles, our_surge))})
    return {"hours": rows}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    names = sorted(name for name in os.listdir(IN_DIR) if name.endswith(".in"))
    for name in names:
        with open(os.path.join(IN_DIR, name), "r", encoding="utf-8") as handle:
            case = json.load(handle)
        payload = json.dumps(forecast_case(case), separators=(",", ":"), allow_nan=False)
        target = os.path.join(OUT_DIR, name[:-3] + ".out")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")


if __name__ == "__main__":
    main()
