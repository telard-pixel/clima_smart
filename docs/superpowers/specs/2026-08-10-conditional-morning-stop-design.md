# Conditional Morning Stop Design

## Goal

Prevent Clima Smart from performing a scheduled morning stop when the configured
daytime-start sensors already show that the unit is likely to restart after the
30-minute guard. Preserve the existing stop when the room and the rest of the
house have useful thermal headroom.

## Evidence and scope

Between 5 and 10 August, the 08:30 stop was followed several times by a restart
after only 30-40 minutes. The change is intentionally limited to the morning
one-shot in Smart mode. It does not alter the house loop, its 45-minute dwell,
the 26.0 C house line, the new 23.0 C minimum trim, seasonal handling, or manual
override behavior.

## Decision rule

The stop remains eligible only when every enabled daytime-start signal has
headroom:

- configured room threshold: the room must be strictly below the threshold by
  more than 1.0 C;
- configured house threshold: the house average must be strictly below the
  threshold by more than 0.3 C;
- the house average is available when at least one configured house sensor has a
  valid reading; individual missing or invalid sensors are ignored;
- when no configured house sensor has a valid reading, the house average is
  unavailable and the stop is skipped;
- a disabled threshold is ignored;
- when both thresholds are disabled, preserve the legacy unconditional stop.

The thresholds remain the user's existing `auto_start_room` and
`auto_start_house` options. The margins are internal hysteresis constants, not
new configuration fields.

## State and diagnostics

If the stop is skipped, mark the morning decision as completed for the local
calendar day and persist it through the existing store. This prevents a later
five-minute evaluation from stopping the unit after temperatures happen to fall.
The diagnostic reason must say that the morning stop was skipped and identify the
signal that lacked headroom.

If the stop is eligible, retain the existing semantics: arm the one-shot, issue
`climate.turn_off`, mark it completed only after a successful command, and retry
inside the existing window after a failed command.

## Safety and compatibility

- Smart mode only; Auto and Off mode behavior is unchanged.
- Never switch off a running heater.
- Continue treating both `cool` and `dry` as cooling modes.
- Do not start the unit as part of this decision.
- Preserve old behavior for installations without daytime auto-start thresholds.
- Release as version 1.12.5.

## Verification

Regression tests must prove: skip near the house threshold, skip when the house
average has no valid reading, preserve the stop with sufficient headroom, preserve
legacy behavior with thresholds disabled, persist the skipped one-shot, and keep
the failed-command retry behavior. Run the complete regression suite, compileall,
and `git diff --check`; then obtain an independent review before any live upload.

Live deployment requires a fresh full Home Assistant backup, a targeted rollback
archive, Samba byte/hash verification of only changed runtime files, one restart,
API/config-entry/log checks, and observation of a periodic controller evaluation.
