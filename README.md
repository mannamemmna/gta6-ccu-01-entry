# gta6-ccu-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/mannamemmna/gta6-ccu-01-entry/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/mannamemmna/gta6-ccu-01-entry/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

An analogue forecaster for Grand Theft Auto VI's launch-day Twitch concurrency.

Hour 1 of the release day is given by the case. For every later hour the model asks
what the comparable launches did between their own first hour and that same hour, and
reads the weighted quantiles of those log growth ratios back onto this hour 1's print.
Two kernels decide which comparables count, both computable from the case alone:

- **magnitude** — a Gaussian on the log gap between a comparable's opening audience and
  ours, so a launch that drew a comparable crowd outweighs one a hundred times smaller
  or larger.
- **hype** — a Gaussian on the log gap between a comparable's pre-release surge and
  ours, where the surge is hour 1's print over the mean of the 24 hours before the
  release day. Two launches that open at the same size can still be travelling in
  opposite directions.

Neighbouring hours are pooled into the sample with a decaying weight, because a single
hour's print is noisy and the day's shape is smooth.

Pure Python standard library, no network, no clock, no randomness: two runs over one
case write identical bytes.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=y7cjn3nn&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
