"""
replay/engine.py — controllable "live stream" over the SWaT test set.

Treats the recorded test data as a seekable real-time feed: play / pause,
variable speed (1x..500x), and jump-to-next-attack. Each streamed reading is
scored by a dedicated CT-MIF scorer; a *debounced rising edge* of the detector
triggers the full 4-agent reasoning + persistence, so isolated false positives
don't spawn events and a single attack fires exactly one event.

Demo-quality touches (kept OUT of the verified core detector, where they belong):
  - silent warm-up after a jump, so temporal buffers are primed before the
    visible window starts (avoids cold-start false positives);
  - confirm-after-k / clear-after-m debounce around event creation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from typing import Any, Awaitable, Callable

import pandas as pd

from agents.graph import run_reasoning
from api import db
from api.config import settings
from core.ctmif import CTMIFScorer, quick_severity

BASE_INTERVAL = 1.0     # SWaT is sampled at 1 Hz -> 1 row == 1 second
MIN_TICK = 0.02         # don't sleep shorter than this; batch rows instead
WARMUP_SILENT = 60      # rows fed to the scorer silently to prime buffers
PRE_CONTEXT = 60        # visible rows shown before an attack after a jump
CONFIRM_HITS = 3        # consecutive anomalies needed to open an event
CLEAR_MISSES = 20       # consecutive normals needed to close an event
EMIT_MIN_INTERVAL = 0.04  # cap normal-reading emits at ~25/s (anomalies always emit)
SLEEP_CHUNK = 0.05      # max single sleep; lets controls take effect within ~50ms

Emit = Callable[[dict[str, Any]], Awaitable[None]]


def _load_dataframe(path: str) -> pd.DataFrame:
    """Load replay rows from a .json sample fixture or a (gz) CSV."""
    if path.endswith(".json"):
        with open(path) as f:
            return pd.DataFrame(json.load(f)["rows"])
    return pd.read_csv(path)  # compression inferred from .gz


class ReplayEngine:
    def __init__(self, dataset_path: str | None = None, artifacts_dir: str | None = None):
        path = dataset_path or settings.replay_dataset_path
        if not os.path.exists(path):
            # fall back to the lightweight sample fixture
            fallback = "data/sample_readings.json"
            if os.path.exists(fallback):
                print(f"[replay] '{path}' missing; using {fallback}")
                path = fallback
            else:
                raise FileNotFoundError(
                    f"No replay data at '{path}' (run scripts/build_replay_data.py "
                    "or scripts/extract_sample.py)."
                )
        self.path = path
        self.df = _load_dataframe(path)
        self.n = len(self.df)
        self.scorer = CTMIFScorer(artifacts_dir)
        self.sensor_cols = [c for c in self.scorer.sensor_cols if c in self.df.columns]

        lab = (self.df["label"].values != 0).astype(int) if "label" in self.df else \
            [0] * self.n
        self.labels = list(map(int, lab))
        self.segments = self._compute_segments()          # [(start, end), ...]
        self.attack_starts = [s for s, _ in self.segments]
        # Demo-critical: jump targets the next DETECTED attack, not the next
        # ground-truth one. Recall < 1, so some labelled attacks never fire and
        # jumping to one would show an empty pipeline. Computed once, cached.
        self.detected_attack_starts = self._compute_detected_starts()

        # control state
        self.current_idx = 0
        self.speed = float(settings.replay_default_speed)
        self.paused = False
        self._jump_requested = False
        self._seek_requested = False
        self._status_dirty = False
        self._last_emit = 0.0
        self._gen = 0
        self._stop = False
        self._running = False
        self._reset_event_state()

    # ── control surface (called from REST endpoints or WS commands) ────────
    def play(self) -> None:
        self.paused = False
        self._status_dirty = True

    def pause(self) -> None:
        self.paused = True
        self._status_dirty = True

    def set_speed(self, multiplier: float) -> None:
        self.speed = max(0.1, min(float(multiplier), 1000.0))
        self._status_dirty = True

    def request_jump(self) -> None:
        self._jump_requested = True
        self._status_dirty = True

    def seek(self, idx: int) -> None:
        self.current_idx = max(0, min(int(idx), self.n - 1))
        self._seek_requested = True  # warm up at this position (NOT a next-attack jump)
        self._status_dirty = True

    def stop(self) -> None:
        self._stop = True

    def begin_session(self) -> int:
        """Start a new streaming session; any older run loop sees the changed
        generation and exits, so the newest connection owns the engine."""
        self._gen += 1
        self._stop = False
        return self._gen

    def status(self) -> dict[str, Any]:
        return {
            "type": "status",
            "idx": int(self.current_idx),
            "total": self.n,
            "speed": self.speed,
            "paused": self.paused,
            "running": self._running,
            "attacks": len(self.attack_starts),
            "detected_attacks": len(self.detected_attack_starts),
            "supabase": settings.supabase_enabled,
        }

    # ── internals ──────────────────────────────────────────────────────────
    def _compute_segments(self) -> list[tuple[int, int]]:
        """Contiguous (start, end) attack spans from the label column."""
        segs, in_s, s = [], False, 0
        for i, v in enumerate(self.labels):
            if v and not in_s:
                in_s, s = True, i
            elif not v and in_s:
                in_s = False
                segs.append((s, i))
        if in_s:
            segs.append((s, self.n))
        return segs

    def _compute_detected_starts(self) -> list[int]:
        """Starts of attack segments the detector actually fires on (>=1 hit).
        Cached to artifacts/detected_attacks.json keyed by dataset + row count
        so it's computed only once per dataset."""
        if not self.segments:
            return []
        cache = os.path.join(self.scorer.artifacts_dir, "detected_attacks.json")
        sig = f"{os.path.basename(self.path)}:{self.n}"
        if os.path.exists(cache):
            try:
                with open(cache) as f:
                    d = json.load(f)
                if d.get("sig") == sig:
                    return [int(s) for s in d.get("starts", [])]
            except Exception:
                pass
        print(f"[replay] scoring {self.n:,} rows to find detected attacks ...")
        preds = self.scorer.predict_dataframe(self.df)
        starts = [int(s) for (s, e) in self.segments if bool(preds[s:e].any())]
        try:
            with open(cache, "w") as f:
                json.dump({"sig": sig, "starts": starts}, f)
        except Exception:
            pass
        print(f"[replay] {len(starts)}/{len(self.segments)} attack segments detected")
        return starts

    def _reset_event_state(self) -> None:
        self._in_event = False
        self._hit_streak = 0
        self._miss_streak = 0

    def _warm_up(self) -> None:
        """Silently feed the rows preceding current_idx to prime the scorer."""
        self.scorer.reset()
        n = min(WARMUP_SILENT, self.current_idx)
        for j in range(self.current_idx - n, self.current_idx):
            self.scorer.score(self.df.iloc[j].to_dict())
        self._reset_event_state()

    def _do_jump(self) -> None:
        # Prefer detected attacks; fall back to ground-truth if none detected.
        targets = self.detected_attack_starts or self.attack_starts
        upcoming = [i for i in targets if i > self.current_idx + PRE_CONTEXT]
        target = upcoming[0] if upcoming else (targets[0] if targets else self.current_idx)
        self.current_idx = max(0, target - PRE_CONTEXT)
        self._warm_up()

    def _reading_msg(self, idx: int, row: dict, det: dict) -> dict[str, Any]:
        return {
            "type": "reading",
            "idx": int(idx),
            "t": str(row.get("Timestamp", idx)),
            "sensors": {c: round(float(row.get(c, 0.0)), 3) for c in self.sensor_cols},
            "score": det["anomaly_score"],
            "threshold": det["threshold"],
            "is_anomaly": det["is_anomaly"],
            "label": int(row.get("label", 0) != 0),
        }

    def _process_event_sync(self, row: dict, det: dict) -> tuple[dict, str, str | None]:
        """Heavy work for a confirmed event: agent reasoning + persistence."""
        report = run_reasoning(row, det)
        severity = (report.get("assessor") or {}).get("severity") \
            or quick_severity(det["score_ratio"])
        reading_row = db.insert_reading(row, str(row.get("Timestamp")), None)
        ev = db.insert_anomaly_event(
            reading_id=reading_row["id"] if reading_row else None,
            anomaly_score=det["anomaly_score"],
            is_anomaly=True,
            severity=severity,
            agent_report=report,
        )
        return report, severity, (ev["id"] if ev else None)

    async def _fire_event(self, idx: int, row: dict, det: dict, emit: Emit) -> None:
        # immediate cue so the UI can show "analyzing…"
        await emit({"type": "event_start", "idx": int(idx),
                    "severity": quick_severity(det["score_ratio"]), "detector": det})
        loop = asyncio.get_event_loop()
        report, severity, event_id = await loop.run_in_executor(
            None, self._process_event_sync, row, det
        )
        await emit({"type": "event", "idx": int(idx), "event_id": event_id,
                    "severity": severity, "agent_report": report})

    def _step(self, idx: int) -> tuple[dict, dict]:
        row = self.df.iloc[idx].to_dict()
        det = self.scorer.score(row)
        # debounce bookkeeping
        if det["is_anomaly"]:
            self._hit_streak += 1
            self._miss_streak = 0
        else:
            self._miss_streak += 1
            self._hit_streak = 0
            if self._miss_streak >= CLEAR_MISSES:
                self._in_event = False
        return row, det

    # ── main loop ───────────────────────────────────────────────────────────
    async def _control_tick(self, emit: Emit) -> bool:
        """Apply any pending control flag (jump / seek / speed / pause / play)
        and emit fresh status. Single status sender -> no concurrent WS writes.
        Returns True if it handled something (caller should re-loop)."""
        if self._jump_requested:
            self._jump_requested = False
            self._status_dirty = False
            self._do_jump()
            await emit(self.status())
            return True
        if self._seek_requested:
            self._seek_requested = False
            self._status_dirty = False
            self._warm_up()
            await emit(self.status())
            return True
        if self._status_dirty:
            self._status_dirty = False
            await emit(self.status())
            return True
        return False

    async def _interruptible_sleep(self, total: float, session: int) -> None:
        """Sleep up to `total`s, waking early when a control flag flips so
        pause/jump/speed register within ~SLEEP_CHUNK at any speed."""
        end = time.monotonic() + total
        while True:
            remaining = end - time.monotonic()
            if (remaining <= 0 or self._stop or self._gen != session or self.paused
                    or self._jump_requested or self._seek_requested
                    or self._status_dirty):
                return
            await asyncio.sleep(min(SLEEP_CHUNK, remaining))

    async def run(self, emit: Emit, session: int | None = None) -> None:
        if session is None:
            session = self.begin_session()
        self._running = True
        self._last_emit = 0.0
        self._warm_up()
        await emit(self.status())
        try:
            while not self._stop and self._gen == session and self.current_idx < self.n:
                # Controls take priority and work whether or not we're paused.
                if await self._control_tick(emit):
                    continue
                if self.paused:
                    await asyncio.sleep(SLEEP_CHUNK)
                    continue

                delay = BASE_INTERVAL / max(self.speed, 1e-6)
                if delay >= MIN_TICK:
                    batch, sleep_for = 1, delay
                else:
                    batch = max(1, round(MIN_TICK / delay))
                    sleep_for = MIN_TICK

                for _ in range(batch):
                    if (self._stop or self._gen != session or self.paused
                            or self._jump_requested or self._seek_requested
                            or self.current_idx >= self.n):
                        break
                    idx = self.current_idx
                    row, det = self._step(idx)
                    # Throttle normal-reading emits at high speed so the client
                    # isn't flooded; anomalies are always shown. Scoring + event
                    # detection still run on every row.
                    now = time.monotonic()
                    if det["is_anomaly"] or (now - self._last_emit) >= EMIT_MIN_INTERVAL:
                        await emit(self._reading_msg(idx, row, det))
                        self._last_emit = now
                    if not self._in_event and self._hit_streak >= CONFIRM_HITS:
                        self._in_event = True
                        await self._fire_event(idx, row, det, emit)
                    self.current_idx += 1

                await self._interruptible_sleep(sleep_for, session)

            if self.current_idx >= self.n:
                await emit({"type": "replay_complete", "idx": int(self.current_idx)})
        finally:
            self._running = False


# process-wide singleton (single-client demo)
_engine: ReplayEngine | None = None


def get_engine() -> ReplayEngine:
    global _engine
    if _engine is None:
        _engine = ReplayEngine()
    return _engine
