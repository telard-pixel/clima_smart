# Clima Smart 1.12.3 trim-probe safety design

## Goal

Make the house-trim probe a bounded, explicit decision instead of state that can
remain pending across unrelated controller branches. Version 1.12.3 must close
the defect fixed only partially by 1.12.2, preserve the measured saturation and
daily-floor behaviour, and remain safe across restarts and transient store
failures.

The release changes only trim-probe evaluation, persistence retry, house-sensor
validation, regression tests and the manifest version. It does not change
schedules, configured targets, entity identifiers, fan control, HVAC modes or
Home Assistant settings.

## Confirmed failure modes

Two independent read-only reviews of `755e655..048fcb3` reproduced these cases:

1. A successful pending probe can still be overridden by the saturation brake,
   even though the direct measured verdict is meant to take precedence.
2. The deadband return and night phases can leave a probe pending for hours or
   across midnight, causing a stale baseline to create a floor on the next day.
3. A non-finite house reading can falsely fail and consume a probe.
4. `_async_save_memoria()` updates its in-memory saved snapshot before the
   asynchronous save succeeds, so a transient failure suppresses later retries.
5. Early returns for missing house data, disabled control, climate heat, season
   guards and mode guards can bypass probe expiry or night-window cancellation.
6. A stored ISO timestamp without an offset is accepted by `fromisoformat()` but
   later raises when subtracted from Home Assistant's timezone-aware clock.
7. A JSON-valid Store payload with a non-mapping top level, or corrupted scalar
   values such as NaN and truthy strings, can abort startup or poison decisions.
8. The real manual-override event queues an evaluation which returns while the
   override is active, before the only state-save call; the existing restart test
   hid this by invoking the private save method directly.

The existing 134-test suite passes but does not cover the 1.12.2 delta or these
failure modes.

## Probe state and lifetime

A probe consists of the house baseline, the attempted trim level and a dedicated
start timestamp. All three fields are persisted together. Loading an old or
partial snapshot without a valid timestamp discards the probe without learning a
floor; this is backward-compatible and prevents an unbounded 1.12.2 probe from
being judged after upgrade.

A probe is eligible for a verdict only when all of the following hold:

- baseline, attempted level and timestamp are present and finite;
- its timestamp belongs to the current local calendar day;
- its age has reached the existing dwell but has not exceeded twice the dwell;
- the controller is in a daytime phase where house trim is active.

Before the dwell expires, the controller keeps the probe pending and changes no
trim. After twice the dwell, at a day boundary, or on entry into sleep/wind-down,
the controller cancels it without creating a floor. A temporarily missing house
reading does not immediately cancel a valid probe; the age bound handles that
case without learning from missing data.

Lifetime housekeeping runs before every early return that can bypass house-trim
evaluation. It therefore expires probes even when the house average is missing,
the loop is disabled, the climate is heating, the season guard returns, or the
controller is off. Sleep and wind-down cancel a probe before those same guards.

Persisted datetimes are accepted only when timezone-aware. Probe age is computed
after normalizing both timestamps to UTC, avoiding DST and differing-offset
arithmetic. Naive, future and invalid timestamps cancel the probe without a
floor.

## Probe verdict and branch precedence

Probe evaluation returns an explicit tri-state result:

- no verdict: no probe exists, it is not yet due, or it was cancelled/expired;
- paid: the house average fell by at least `TRIM_PROBE_GAIN`;
- unpaid: the valid due probe failed to achieve that gain.

When a valid due probe is judged, it is consumed exactly once. An unpaid verdict
creates the existing daily floor and gives the attempted step back. A paid
verdict allows the next downward step when the house is still above the comfort
line. While a probe supplied either verdict, saturation may update its hysteresis
state but cannot override that direct verdict. With no probe verdict, the existing
saturation brake remains authoritative.

The due probe is evaluated before the deadband return. In the deadband a paid
probe is simply closed and the trim is held; an unpaid probe gives the step back
within the existing target/min/max limits. If the house is already below the
comfort band, the existing release branch remains authoritative after the probe
has been safely closed.

## Input validation

`_house_average()` accepts only converted Celsius readings that are finite and
within the existing plausible-temperature bounds. Invalid, infinite and NaN
values are skipped individually; valid sensors still contribute. If no valid
readings remain, it returns `None`, holds the current trim and never consumes a
probe from fabricated evidence.

Persisted numeric probe and floor fields receive the same finite/plausible checks
needed for their role. Invalid persisted probe state is discarded without
learning.

The Store top level must be a mapping. Any other JSON value is logged and treated
as an empty Store so startup continues. `house_trim` must be a finite plausible
temperature, `adaptive_extra` must be finite and non-boolean, and `saturated`
must be an actual boolean; invalid values fall back to clean defaults.

## Persistence retry

`_async_save_memoria()` compares the current snapshot with the last successfully
saved snapshot. It assigns `_stored` only after `async_save()` completes. On an
exception, `_stored` remains unchanged so the next controller pass retries the
same state. Save failures continue to be logged and must not stop evaluation.

When a real state-change event starts or updates a manual override, the queued
evaluation persists that state before returning through the `override_active`
guard. A failed save remains retryable on the next evaluation. Override expiry
continues through a normal evaluation and persists the cleared timestamp. The
restart regression must exercise event, evaluation, Store and a new controller;
it may not call `_async_save_memoria()` directly.

## Test-driven implementation

Production code is changed only after each regression test has been observed
failing for the expected reason. Tests cover:

1. pending unpaid probe plus active saturation gives the step back;
2. pending paid probe overrides saturation and earns the next step;
3. paid and unpaid probes are consumed correctly inside the deadband;
4. a probe is cancelled without a floor in sleep/wind-down, after midnight and
   after twice the dwell;
5. a restart reloads a complete valid probe, while legacy/partial probe state is
   discarded;
6. NaN, positive/negative infinity, implausible values and mixed valid/invalid
   house sensors cannot corrupt a verdict;
7. a fail-once store is retried and succeeds on the next save;
8. no-probe and repeated-evaluation paths remain idempotent.
9. missing house data and all early-return modes still expire or cancel probes;
10. naive, future and alternate-offset timestamps cannot break evaluation;
11. list/string/scalar Store payloads and corrupt persisted scalars fail cleanly;
12. a real manual event persists its override across a controller restart.

Final verification runs the complete standalone suite, Python compilation,
manifest/translation JSON parsing and `git diff --check`. Two fresh independent
read-only reviews must report no Critical or Important blockers before deployment.

## Versioning and deployment

The already-published `048fcb3` commit is not rewritten. The correction is a new
commit on `agent/clima-smart-1.12.3` with manifest version `1.12.3`.

Deployment remains gated on the verified Home Assistant backup `f3dc5d4d` and the
targeted 1.12.1 rollback copy. Only `const.py`, `controller.py` and
`manifest.json` are installed. The remote files are reread and compared before a
single Home Assistant restart. Success requires Home Assistant to return to
`RUNNING`, the loaded manifest to report 1.12.3, the `clima_smart` config entry to
be loaded, no new integration error in the log, and the climate entity to retain
its pre-restart operating state.
