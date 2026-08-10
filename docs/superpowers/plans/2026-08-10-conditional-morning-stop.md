# Conditional Morning Stop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Smart-mode 08:30 stop conditional on useful room and house thermal headroom, while preserving all existing one-shot and safety behavior.

**Architecture:** Add a pure controller helper that returns the reason to skip or `None` when stopping is worthwhile. The Smart-mode gap branch consumes that decision; the existing evaluation/store path persists either a successful stop or a deliberate skip for the local day.

**Tech Stack:** Python 3 standard library, Home Assistant custom integration APIs, `unittest` regression harness.

## Global Constraints

- Do not change the house loop, its configured targets, or its 45-minute dwell.
- Room headroom is strictly greater than 1.0 C below `auto_start_room`.
- House headroom is strictly greater than 0.3 C below `auto_start_house`.
- The house average uses all valid configured house readings; individual missing
  readings are ignored. If no configured house reading is valid, the average is
  unavailable and the stop is skipped.
- Disabled daytime-start thresholds preserve legacy unconditional stopping.
- Never stop heating; treat `cool` and `dry` consistently.
- Release version is 1.12.5.

---

### Task 1: Specify conditional-stop behavior with failing regressions

**Files:**
- Modify: `test_regressions.py`

**Interfaces:**
- Consumes: `Controller._compute(datetime) -> Desired`, existing `_con_casa` and `_profilo_notte` test helpers.
- Produces: regression expectations for conditional stop, one-shot persistence, missing readings, and retained legacy behavior.

- [ ] **Step 1: Add a failing house-headroom test**

Add `test_morning_switch_off_is_skipped_when_house_would_restart_soon`: create an active cooling controller with `auto_start_house=26.0`, house average 25.8 C, room 24.0 C, evaluate at 08:31, and assert that HVAC is not `off` and the reason contains `fermo mattino saltato`.

```python
def test_morning_switch_off_is_skipped_when_house_would_restart_soon(self):
    ctrl = self._con_casa(room=24.0, altre=(25.8, 25.8), outdoor=31.0)
    ctrl.hass.states.values["climate.test"].state = "cool"
    desired = ctrl._compute(GIORNO.replace(hour=8, minute=31))
    self.assertNotEqual(desired.hvac, "off")
    self.assertIn("fermo mattino saltato", desired.reason)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python3 -I -m unittest test_regressions.ControllerTests.test_morning_switch_off_is_skipped_when_house_would_restart_soon -v`

Expected: FAIL because the current controller returns `hvac='off'`.

- [ ] **Step 3: Add the remaining failing boundary tests**

Add separate tests asserting: exact margin boundaries skip; sufficient room and house headroom still stop; an unavailable house average skips; disabled thresholds preserve the current stop; and a skipped stop is marked done so a later evaluation cannot turn the unit off that day.

```python
def test_morning_switch_off_skips_when_house_average_is_unavailable(self):
    ctrl = self._con_casa(room=24.0, altre=(25.0,), outdoor=31.0)
    ctrl.hass.states.values["climate.test"].state = "cool"
    ctrl.hass.states.values.pop("sensor.stanza0")
    desired = ctrl._compute(GIORNO.replace(hour=8, minute=31))
    self.assertNotEqual(desired.hvac, "off")

def test_morning_switch_off_skips_exact_headroom_boundaries(self):
    for room, altre in ((27.0, (25.0, 25.0)), (24.0, (25.7, 25.7))):
        with self.subTest(room=room, altre=altre):
            ctrl = self._con_casa(room=room, altre=altre, outdoor=31.0)
            ctrl.hass.states.values["climate.test"].state = "cool"
            desired = ctrl._compute(GIORNO.replace(hour=8, minute=31))
            self.assertNotEqual(desired.hvac, "off")

def test_morning_switch_off_still_happens_with_headroom(self):
    ctrl = self._con_casa(room=26.9, altre=(25.6, 25.6), outdoor=31.0)
    ctrl.hass.states.values["climate.test"].state = "cool"
    desired = ctrl._compute(GIORNO.replace(hour=8, minute=31))
    self.assertEqual(desired.hvac, "off")

def test_morning_switch_off_keeps_legacy_behavior_without_start_thresholds(self):
    ctrl = self._smart_controller(room=24.0)
    self._profilo_notte(ctrl)
    desired = ctrl._compute(GIORNO.replace(hour=8, minute=31))
    self.assertEqual(desired.hvac, "off")

def test_skipped_morning_switch_off_is_one_shot(self):
    ctrl = self._con_casa(room=24.0, altre=(25.8, 25.8), outdoor=31.0)
    ctrl.hass.states.values["climate.test"].state = "cool"
    ctrl._restore_event.set()

    async def succeeds(domain, service, data=None):
        return True

    ctrl._call = succeeds
    self._orologio(GIORNO.replace(hour=8, minute=31))
    asyncio.run(ctrl.async_evaluate("prova"))
    self.assertEqual(ctrl._morning_off_done_on, GIORNO.date())
    for entity_id in ("sensor.stanza0", "sensor.stanza1"):
        ctrl.hass.states.values[entity_id].state = "25.0"
    desired = ctrl._compute(GIORNO.replace(hour=8, minute=36))
    self.assertNotEqual(desired.hvac, "off")

def test_dry_uses_the_same_conditional_morning_stop(self):
    ctrl = self._con_casa(room=24.0, altre=(25.8, 25.8), outdoor=31.0)
    ctrl.hass.states.values["climate.test"].state = "dry"
    desired = ctrl._compute(GIORNO.replace(hour=8, minute=31))
    self.assertNotEqual(desired.hvac, "off")
```

- [ ] **Step 4: Run the focused group and verify failures are behavioral**

Run: `python3 -I -m unittest test_regressions.ControllerTests.test_morning_switch_off_is_skipped_when_house_would_restart_soon test_regressions.ControllerTests.test_morning_switch_off_skips_when_house_average_is_unavailable test_regressions.ControllerTests.test_morning_switch_off_skips_exact_headroom_boundaries test_regressions.ControllerTests.test_morning_switch_off_still_happens_with_headroom test_regressions.ControllerTests.test_morning_switch_off_keeps_legacy_behavior_without_start_thresholds test_regressions.ControllerTests.test_skipped_morning_switch_off_is_one_shot test_regressions.ControllerTests.test_dry_uses_the_same_conditional_morning_stop -v`

Expected: the new skip cases fail because the current code always stops an active cooling mode inside the morning window; retained-behavior cases pass.

### Task 2: Implement the minimum conditional-stop logic

**Files:**
- Modify: `const.py`
- Modify: `controller.py`
- Test: `test_regressions.py`

**Interfaces:**
- Produces: `Controller._morning_off_skip_reason(room: float | None, house: float | None) -> str | None` and ephemeral `_morning_off_skip_armed: bool`.
- Consumes: `CONF_AUTO_START_ROOM`, `CONF_AUTO_START_HOUSE`, `_house_average()`, and the existing persisted `morning_off_done_on` field.

- [ ] **Step 1: Add the two internal margins**

Add `MORNING_OFF_ROOM_HEADROOM = 1.0` and `MORNING_OFF_HOUSE_HEADROOM = 0.3` beside `MORNING_OFF_WINDOW_MINUTES` in `const.py`.

```python
MORNING_OFF_ROOM_HEADROOM = 1.0
MORNING_OFF_HOUSE_HEADROOM = 0.3
```

- [ ] **Step 2: Implement the pure headroom decision**

Add `_morning_off_skip_reason`. Check enabled house and room thresholds independently, return a concise Italian reason when a configured reading is missing or lies on/inside its margin, and return `None` only when all enabled signals have sufficient headroom or both are disabled.

```python
def _morning_off_skip_reason(
    self, room: float | None, house: float | None
) -> str | None:
    house_threshold = float(
        self._cfg(CONF_AUTO_START_HOUSE, DEFAULT_AUTO_START_HOUSE) or 0.0
    )
    if house_threshold > 0:
        if house is None:
            return "media casa non disponibile"
        if house >= house_threshold - MORNING_OFF_HOUSE_HEADROOM:
            return f"casa {house:.1f} vicina alla soglia {house_threshold:.1f}"

    room_threshold = float(
        self._cfg(CONF_AUTO_START_ROOM, DEFAULT_AUTO_START_ROOM) or 0.0
    )
    if room_threshold > 0:
        if room is None:
            return "temperatura camera non disponibile"
        if room >= room_threshold - MORNING_OFF_ROOM_HEADROOM:
            return f"camera {room:.1f} vicina alla soglia {room_threshold:.1f}"
    return None
```

- [ ] **Step 3: Integrate the decision into the Smart morning branch**

Compute the house average once. When `_morning_off_due` is true for `cool` or `dry`, preserve the current `turn_off` path if the helper returns `None`; otherwise arm the skip, continue into normal Smart daytime control, and include the skip reason in diagnostics.

```python
house = self._house_average()
morning_skip_reason = None
if self._morning_off_due(now) and cooling_active:
    morning_skip_reason = self._morning_off_skip_reason(room, house)
    if morning_skip_reason is None:
        self._morning_off_armed = True
        self.active_target = None
        return Desired(hvac=HVAC_OFF, reason="smart: spegnimento del mattino")
    self._morning_off_skip_armed = True
```

- [ ] **Step 4: Persist a deliberate skip as the day's decision**

Reset `_morning_off_skip_armed` at the start of each evaluation. After `_apply` completes, set `_morning_off_done_on` for either a deliberate skip or a successful armed stop. A failed stop command must remain retryable exactly as today.

```python
self._morning_off_armed = False
self._morning_off_skip_armed = False
# compute and apply
if self._morning_off_skip_armed:
    self._morning_off_done_on = now.date()
elif self._morning_off_armed and not self._apply_errors:
    self._morning_off_done_on = now.date()
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the focused command from Task 1 Step 4.

Expected: all focused tests PASS.

- [ ] **Step 6: Commit the behavioral change**

Run: `git add const.py controller.py test_regressions.py && git commit -m "fix: skip pointless morning climate stops"`

### Task 3: Version and verify the release candidate

**Files:**
- Modify: `manifest.json`

**Interfaces:**
- Produces: Clima Smart 1.12.5 release candidate.

- [ ] **Step 1: Update the manifest version**

Change `manifest.json` from `1.12.4` to `1.12.5`.

```json
"version": "1.12.5"
```

- [ ] **Step 2: Run complete verification**

Run: `python3 -I test_regressions.py`

Expected: all regression tests PASS.

Run: `python3 -m compileall -q .`

Expected: exit 0 and no output.

Run: `git diff --check`

Expected: exit 0 and no output.

- [ ] **Step 3: Commit release metadata**

Run: `git add manifest.json docs/superpowers/specs/2026-08-10-conditional-morning-stop-design.md docs/superpowers/plans/2026-08-10-conditional-morning-stop.md && git commit -m "chore: prepare Clima Smart 1.12.5"`

### Task 4: Review and live acceptance

**Files:**
- Review: `controller.py`, `const.py`, `test_regressions.py`, `manifest.json`
- Deploy after approval: `controller.py`, `const.py`, `manifest.json`

**Interfaces:**
- Consumes: reviewed commits and the existing Home Assistant/Samba deployment procedure.
- Produces: independently reviewed, backed-up, byte-verified, live-observed 1.12.5 installation.

- [ ] **Step 1: Obtain independent code review**

Request review specifically for exact-boundary behavior, missing sensors, daily one-shot persistence, failed-command retry, `dry`, heating safety, and unintended house-loop changes. Address every actionable finding and rerun Task 3 verification.

- [ ] **Step 2: Create live rollback points**

Create and verify a fresh full Home Assistant backup and a targeted archive of the currently installed `clima_smart` directory before uploading any file.

- [ ] **Step 3: Deploy only reviewed runtime files**

Upload `controller.py`, `const.py`, and `manifest.json` over Samba. Re-read them from Samba and verify byte equality plus SHA-256 against the reviewed worktree.

- [ ] **Step 4: Restart once and verify runtime**

Restart Home Assistant once. Poll until `/api/`, config entry state, Clima Smart entities, connectivity, version, and logs are healthy. Observe at least one five-minute `intervallo` evaluation and confirm no override or fault is active.

- [ ] **Step 5: Preserve evidence for the next morning**

Record the deployed commit/hash and the pre-deployment rollback path. The behavioral acceptance remains the next 08:30 decision: skip when close to a configured restart threshold, otherwise stop once and remain sensor-driven afterward.
