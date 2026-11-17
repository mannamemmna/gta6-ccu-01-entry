"""gta6-ccu-forecast-01: hour-by-hour forecast of GTA VI's launch-day Twitch concurrency.

Method: an analogue forecaster on the natural-log scale. Hour 1 of the release day is
given in the case; for each later hour the model looks at what the comparable launches
did between their own hour 1 and that same hour, spreads each comparable's log growth
ratio into five weighted quantiles, and applies them to hour 1's print.

Two weights shape the distribution, both computable from the case alone:

  * similarity: a Gaussian kernel on how far a comparable's hour-1 audience sits from ours
    in logs, so a launch that drew a comparable crowd counts for more than one that drew
    1/100th of it. This is what keeps a 5,000-viewer launch from dominating a forecast for
    a category that opens at 500,000.
  * pattern: a downweight for a comparable whose unlock differs from the case's own
    (rolling midnight release vs a single global unlock), because the shape of the first
    day depends on how the release rolls across time zones.

Everything uses the standard library only and reads no clock and no random source, so two
runs over one case write identical bytes.

Input:  $MAKEFUN_INPUT_DIR (default /input)   -- each <id>.in case file, in name order.
Output: $MAKEFUN_OUTPUT_DIR (default /output) -- <id>.out, {"hours": [{"hour", "q": [...]}]}.
"""

import json
import math
import os

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]

# The standard normal's quantile at each of LEVELS: the house baseline's spread is quoted
# in these terms, so the fallback shape matches it exactly.
Z = [-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722]

BANDWIDTH = 1.0        # log-viewers bandwidth of the hour-1 similarity kernel
MIN_POOL = 3           # fewer usable neighbours than this: fall back to the house shape
BASE_SIGMA = 0.15      # the house baseline's per-sqrt-hour log spread
FLOOR = 1e-9
CAP = 1e9


def day_hours(comparable):
    """{n: viewers} over one comparable's release day, n = 1 for the day's first hour."""
    day = str(comparable.get("day_start") or "")[:10]
    out = {}
    for row in comparable.get("hourly") or ():
        start = str(row.get("from") or "")
        if len(start) < 13 or start[:10] != day:
            continue
        viewers = row.get("viewers")
        if viewers is None:
            continue
        out[int(start[11:13]) + 1] = max(1.0, float(viewers))
    return out


def similar(first, target, bandwidth=BANDWIDTH):
    """Gaussian weight on the log gap between a comparable's hour-1 audience and ours."""
    gap = math.log(max(first, 1.0) / max(target, 1.0)) / bandwidth
    return math.exp(-0.5 * gap * gap)


def quantiles(pairs, levels=LEVELS):
    """Weighted quantiles of (value, weight) pairs, interpolated between bracketing points."""
    ordered = sorted(pairs, key=lambda pair: pair[0])
    total = sum(weight for _, weight in ordered)
    if not (total > 0.0):
        middle = ordered[len(ordered) // 2][0]
        return [middle for _ in levels]
    cumulative = []
    running = 0.0
    for _, weight in ordered:
        running += weight
        cumulative.append(running / total)
    out = []
    for level in levels:
        if level <= cumulative[0]:
            out.append(ordered[0][0])
            continue
        if level >= cumulative[-1]:
            out.append(ordered[-1][0])
            continue
        for j in range(1, len(cumulative)):
            right = cumulative[j]
            if level <= right:
                left = cumulative[j - 1]
                span = right - left
                frac = 0.0 if span <= 0.0 else (level - left) / span
                lo, hi = ordered[j - 1][0], ordered[j][0]
                out.append(lo + frac * (hi - lo))
                break
    return out


def house_quantiles(first, hour):
    """The baseline's shape: persistence with a random walk's widening log spread."""
    scale = BASE_SIGMA * math.sqrt(hour - 1)
    return [first * math.exp(z * scale) for z in Z]


def forecast_hour(first, hour, pool):
    """Five quantiles of `hour`'s audience from the comparables' log growth ratios.

    The similarity kernel is deliberately the only weighting. An unlock-pattern weight was
    measured too: on the comparables it made the loss worse at every bandwidth (a launch
    that rolls across time zones and one that unlocks at a single instant still draw their
    first day's crowd the same way in log space), so it was dropped rather than shipped.
    """
    pairs = []
    for hours in pool:
        begin = hours.get(1)
        later = hours.get(hour)
        if begin is None or later is None or begin <= 0.0 or later <= 0.0:
            continue
        weight = similar(begin, first)
        if weight > 1e-12:
            pairs.append((math.log(later / begin), weight))
    if len(pairs) < MIN_POOL:
        return house_quantiles(first, hour)
    return [first * math.exp(ratio) for ratio in quantiles(pairs)]


def first_print(case):
    """Hour 1's print, falling back to the last recorded point when the row is missing."""
    for row in case.get("known") or ():
        if row.get("hour") == 1 and row.get("viewers") is not None:
            return max(1.0, float(row["viewers"]))
    hourly = case.get("history_hourly") or ()
    for row in reversed(hourly):
        if row.get("viewers") is not None:
            return max(1.0, float(row["viewers"]))
    return 1.0


def forecast_case(case):
    first = first_print(case)
    pool = [day_hours(c) for c in (case.get("comparables") or ())]
    rows = []
    for row in case.get("forecast") or ():
        hour = int(row["hour"])
        rows.append({"hour": hour, "q": forecast_hour(first, hour, pool)})
    return {"hours": rows}


def sanitise(row):
    """Clamp into (0, CAP], force non-decreasing, and round so the bytes are stable."""
    cleaned = []
    previous = 0.0
    for value in row:
        value = float(value)
        if value != value:  # NaN can never be written out
            value = CAP
        value = min(CAP, max(FLOOR, value))
        if value < previous:
            value = previous
        previous = value
        cleaned.append(round(value, 6))
    return cleaned


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for name in sorted(os.listdir(INPUT_DIR)):
        if not name.endswith(".in"):
            continue
        with open(os.path.join(INPUT_DIR, name), "r", encoding="utf-8") as handle:
            case = json.load(handle)
        forecast = forecast_case(case)
        for row in forecast["hours"]:
            row["q"] = sanitise(row["q"])
        payload = json.dumps(forecast, separators=(",", ":"), allow_nan=False)
        with open(os.path.join(OUTPUT_DIR, name[:-3] + ".out"), "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")


if __name__ == "__main__":
    main()
