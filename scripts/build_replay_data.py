"""
Build a compact, replay-ready copy of the SWaT TEST split (the part with
attacks) so the Replay Engine doesn't have to load/sort the 290 MB combined CSV
at startup.

Output: data/replay_test.csv.gz  (test rows only, all columns, gzip ~tens of MB)
Run:    python scripts/build_replay_data.py
"""

import pandas as pd

CSV = "data/swat_combined.csv"
SPLIT = "2015-12-28 00:00:00"
OUT = "data/replay_test.csv.gz"


def main():
    print("[replay-data] reading combined CSV (one pass) ...")
    df = pd.read_csv(CSV, parse_dates=["Timestamp"])
    df = df.sort_values("Timestamp").reset_index(drop=True)
    test = df[df["Timestamp"] >= pd.Timestamp(SPLIT)].reset_index(drop=True)
    print(f"[replay-data] test rows: {len(test):,}  "
          f"attack rows: {int((test['label'] != 0).sum()):,}")
    test.to_csv(OUT, index=False, compression="gzip")
    print(f"[replay-data] wrote {OUT}")


if __name__ == "__main__":
    main()
