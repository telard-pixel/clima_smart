# Clima Smart 1.12.3 Trim-Probe Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every house-trim probe bounded, persistable and authoritative over the saturation hint, while preserving safe retries and rejecting invalid sensor evidence.

**Architecture:** Keep the existing single-controller design and add one persisted probe timestamp plus small private lifecycle helpers. Probe evaluation returns `bool | None`: `True` and `False` are direct paid/unpaid verdicts; `None` means that no valid due verdict exists, so the existing saturation rule may decide. Store retry and input validation remain separate changes with focused regression tests.

**Tech Stack:** Python 3 standard library, Home Assistant custom-integration APIs, `unittest` standalone stubs, JSON manifest/translations, SMB and Home Assistant REST/WebSocket APIs for deployment.

## Global Constraints

- Base the work on commit `048fcb3b9d62f12dd4149a56e3f35999f27c0075` and do not rewrite it.
- Work only on `agent/clima-smart-1.12.3` until the finishing workflow selects integration.
- Do not change schedules, configured targets, entity identifiers, fan control, HVAC modes or Home Assistant settings.
- Write each regression test before its production change and observe the expected failure.
- A valid probe may be judged from one to two `HOUSE_TRIM_DWELL_SECONDS` after it starts; older, cross-day or night-window probes are cancelled without learning.
- A direct paid/unpaid verdict takes precedence over saturation; saturation decides only when there is no verdict.
- Do not deploy until two independent read-only reviewers report no Critical or Important issues.
- Preserve backup `f3dc5d4d` and `/root/code/backups/clima_smart_pre_1_12_2_20260808_2212.tar.gz` for rollback.

---

### Task 1: Retry failed state saves and reject invalid house readings

**Files:**
- Modify: `controller.py:928-938`
- Modify: `controller.py:1402-1417`
- Test: `test_regressions.py:500-530`
- Test: `test_regressions.py:785-825`

**Interfaces:**
- Consumes: existing `ClimaSmartController._memoria() -> dict`, `_plausible(float) -> bool`, `_convert_temperature(value, from_unit, to_unit) -> float | None`.
- Produces: `_async_save_memoria()` whose `_stored` value means “last successful save”; `_house_average() -> float | None` containing only finite, plausible Celsius readings.

- [ ] **Step 1: Add a failing fail-once store retry test**

Add this test beside the existing store tests:

```python
def test_a_failed_store_save_is_retried(self):
    ctrl = self._smart_controller(room=27.0)
    ctrl.adaptive_extra = 1.0
    calls = []

    async def fail_once(data):
        calls.append(dict(data))
        if len(calls) == 1:
            raise RuntimeError("temporary save failure")

    ctrl._store.async_save = fail_once
    asyncio.run(ctrl._async_save_memoria())
    asyncio.run(ctrl._async_save_memoria())
    self.assertEqual(len(calls), 2)
    self.assertEqual(ctrl._stored, ctrl._memoria())
```

- [ ] **Step 2: Run the retry test and verify RED**

Run:

```bash
python3 -m unittest test_regressions.ControllerRegressionTests.test_a_failed_store_save_is_retried -v
```

Expected: FAIL because `len(calls)` is `1`; the failed first call incorrectly updated `_stored`.

- [ ] **Step 3: Move the successful-snapshot assignment after `async_save()`**

Implement the minimum ordering change:

```python
async def _async_save_memoria(self) -> None:
    adesso = self._memoria()
    if adesso == self._stored:
        return
    try:
        await self._store.async_save(adesso)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Clima Smart: non sono riuscito a salvare lo stato")
    else:
        self._stored = adesso
```

- [ ] **Step 4: Verify the retry test is GREEN**

Run the command from Step 2. Expected: PASS with exactly two save attempts.

- [ ] **Step 5: Add failing invalid/mixed house-sensor tests**

Add focused assertions using `_con_anello()` and direct sensor state replacement:

```python
def test_house_average_skips_non_finite_and_implausible_values(self):
    ctrl = self._con_anello(altre=(26.0, 26.5, 27.0))
    ctrl.hass.states.values["sensor.stanza0"].state = "nan"
    ctrl.hass.states.values["sensor.stanza1"].state = "inf"
    ctrl.hass.states.values["sensor.stanza2"].state = "26.0"
    self.assertEqual(ctrl._house_average(), 26.0)

def test_house_average_returns_none_without_valid_evidence(self):
    ctrl = self._con_anello(altre=(26.0, 26.5, 27.0))
    for entity, value in zip(
        ("sensor.stanza0", "sensor.stanza1", "sensor.stanza2"),
        ("nan", "-inf", "999"),
    ):
        ctrl.hass.states.values[entity].state = value
    self.assertIsNone(ctrl._house_average())
```

- [ ] **Step 6: Run the new sensor tests and verify RED**

Run:

```bash
python3 -m unittest \
  test_regressions.ControllerRegressionTests.test_house_average_skips_non_finite_and_implausible_values \
  test_regressions.ControllerRegressionTests.test_house_average_returns_none_without_valid_evidence -v
```

Expected: FAIL because `nan` contaminates the first average and invalid numbers produce a non-`None` result.

- [ ] **Step 7: Filter converted readings at the source**

Import `math` and append only acceptable readings:

```python
if (
    value is not None
    and math.isfinite(value)
    and _plausible(value)
):
    letture.append(value)
```

- [ ] **Step 8: Verify Task 1 and commit**

Run the three focused tests, then:

```bash
python3 -I test_regressions.py
git diff --check
git add controller.py test_regressions.py
git commit -m "Retry state saves and validate house readings"
```

Expected: complete suite PASS; the test count increases from 134 to 137.

---

### Task 2: Persist a bounded trim-probe lifecycle

**Files:**
- Modify: `controller.py:325-342`
- Modify: `controller.py:838-925`
- Modify: `controller.py:1237-1267`
- Test: `test_regressions.py:490-535`
- Test: `test_regressions.py:895-965`

**Interfaces:**
- Consumes: `HOUSE_TRIM_DWELL_SECONDS`, `TRIM_PROBE_GAIN`, `_plausible(float)`, `_memoria()`, `_async_load_memoria()`.
- Produces: `_trim_probe_started_at: datetime | None`, `_clear_trim_probe() -> None`, `_last_step_paid(casa: float, passo: float, now: datetime) -> bool | None`.

- [ ] **Step 1: Add failing persistence and legacy-state tests**

Add tests that create a real probe, save, restart, and inspect all fields:

```python
def test_a_complete_probe_survives_a_restart(self):
    ctrl = self._con_anello()
    self._casa(ctrl, 28.0)
    ctrl._compute(GIORNO)
    started = GIORNO + timedelta(seconds=controller_module.HOUSE_TRIM_DWELL_SECONDS + 60)
    ctrl._compute(started)
    asyncio.run(ctrl._async_save_memoria())
    after = self._riavvia(ctrl)
    self.assertEqual(after._trim_probe_casa, 28.0)
    self.assertEqual(after._trim_probe_level, 24.0)
    self.assertEqual(after._trim_probe_started_at, started)

def test_a_legacy_probe_without_timestamp_is_discarded(self):
    ctrl = self._con_anello()
    ctrl._store._dati[ctrl._store.key] = {
        "trim_probe_casa": 28.0,
        "trim_probe_level": 24.0,
    }
    asyncio.run(ctrl._async_load_memoria())
    self.assertIsNone(ctrl._trim_probe_casa)
    self.assertIsNone(ctrl._trim_probe_level)
    self.assertIsNone(ctrl._trim_probe_started_at)
```

- [ ] **Step 2: Verify the persistence tests are RED**

Run:

```bash
python3 -m unittest \
  test_regressions.ControllerRegressionTests.test_a_complete_probe_survives_a_restart \
  test_regressions.ControllerRegressionTests.test_a_legacy_probe_without_timestamp_is_discarded -v
```

Expected: ERROR/FAIL because `_trim_probe_started_at` does not exist and the old pair is currently loaded.

- [ ] **Step 3: Add the timestamp and atomic clear helper**

Initialize the field and centralize clearing:

```python
self._trim_probe_started_at: datetime | None = None

def _clear_trim_probe(self) -> None:
    self._trim_probe_casa = None
    self._trim_probe_level = None
    self._trim_probe_started_at = None
```

Add `trim_probe_started_at` to `_memoria()` using the existing `giorno()` serializer. Load it with `istante_di()`. Accept numeric probe fields only if `math.isfinite()` and `_plausible()` return true; require all three fields or call `_clear_trim_probe()`.

- [ ] **Step 4: Record the timestamp when a downward step creates a probe**

At the existing probe creation site set all three values together:

```python
self._trim_probe_casa = casa
self._trim_probe_level = nuovo
self._trim_probe_started_at = now
```

- [ ] **Step 5: Verify persistence tests are GREEN**

Run the two focused tests. Expected: PASS; a complete probe round-trips and a partial legacy probe is cleared.

- [ ] **Step 6: Add failing cross-day and maximum-age tests**

Add direct lifecycle tests:

```python
def test_a_previous_day_probe_expires_without_learning(self):
    ctrl = self._con_anello()
    ctrl._trim_probe_casa = 28.0
    ctrl._trim_probe_level = 24.0
    ctrl._trim_probe_started_at = GIORNO
    result = ctrl._last_step_paid(28.0, 1.0, GIORNO + timedelta(days=1))
    self.assertIsNone(result)
    self.assertIsNone(ctrl._trim_floor_today)
    self.assertIsNone(ctrl._trim_probe_casa)

def test_an_overdue_probe_expires_without_learning(self):
    ctrl = self._con_anello()
    ctrl._trim_probe_casa = 28.0
    ctrl._trim_probe_level = 24.0
    ctrl._trim_probe_started_at = GIORNO
    result = ctrl._last_step_paid(
        28.0,
        1.0,
        GIORNO + timedelta(seconds=2 * controller_module.HOUSE_TRIM_DWELL_SECONDS + 1),
    )
    self.assertIsNone(result)
    self.assertIsNone(ctrl._trim_floor_today)
```

- [ ] **Step 7: Verify expiration tests are RED**

Expected: current code returns `False`, creates a floor and cannot clear the timestamp.

- [ ] **Step 8: Implement bounded tri-state evaluation**

Change `_last_step_paid()` to:

```python
def _last_step_paid(self, casa: float, passo: float, now: datetime) -> bool | None:
    self._reset_trim_floor(now)
    if self._trim_probe_casa is None:
        return None
    started = self._trim_probe_started_at
    if started is None or started.date() != now.date():
        self._clear_trim_probe()
        return None
    age = (now - started).total_seconds()
    if age < HOUSE_TRIM_DWELL_SECONDS:
        return None
    if age > 2 * HOUSE_TRIM_DWELL_SECONDS:
        self._clear_trim_probe()
        return None
    reso = casa <= self._trim_probe_casa - TRIM_PROBE_GAIN
    livello = self._trim_probe_level
    self._clear_trim_probe()
    if not reso and livello is not None:
        passo = passo if passo and passo > 0 else 1.0
        candidato = livello + passo
        self._trim_floor_today = (
            candidato if self._trim_floor_today is None
            else max(self._trim_floor_today, candidato)
        )
    return reso
```

- [ ] **Step 9: Verify Task 2 and commit**

Run all Task 2 tests and the complete suite, then:

```bash
git diff --check
git add controller.py test_regressions.py
git commit -m "Persist and bound trim probe lifetime"
```

Expected: complete suite PASS; test count is at least 141.

---

### Task 3: Make direct probe verdicts authoritative in every daytime branch

**Files:**
- Modify: `controller.py:1280-1390`
- Test: `test_regressions.py:800-965`

**Interfaces:**
- Consumes: `_last_step_paid(casa, passo, now) -> bool | None`, `_saturation_brake(casa, room) -> bool`, `_clear_trim_probe()`.
- Produces: daytime trim ordering where `False` gives a step back, `True` permits progress, and `None` delegates to saturation.

- [ ] **Step 1: Add a failing paid-probe-plus-saturation test**

```python
def test_a_paid_probe_overrides_the_saturation_brake(self):
    ctrl = self._con_anello(ripresa=27.5)
    ctrl.entry.options = dict(ctrl.entry.options, trim_min=22.0)
    self._casa(ctrl, 28.0)
    ctrl._compute(GIORNO)
    first = GIORNO + timedelta(seconds=controller_module.HOUSE_TRIM_DWELL_SECONDS + 60)
    self.assertEqual(ctrl._compute(first).setpoint, 24.0)
    self._casa(ctrl, 27.85)
    ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 25.0
    second = first + timedelta(seconds=controller_module.HOUSE_TRIM_DWELL_SECONDS + 60)
    self.assertEqual(ctrl._compute(second).setpoint, 23.0)
```

- [ ] **Step 2: Verify RED**

Expected: FAIL with setpoint `25.0` because `saturo or not pagato` overrides the paid verdict.

- [ ] **Step 3: Add failing saturation, deadband and idempotence tests**

Cover these exact outcomes:

```python
def test_an_unpaid_probe_is_given_back_while_saturated(self):
    ctrl = self._con_anello(ripresa=27.5)
    ctrl.entry.options = dict(ctrl.entry.options, trim_min=22.0)
    self._casa(ctrl, 28.0)
    ctrl._compute(GIORNO)
    first = GIORNO + timedelta(seconds=controller_module.HOUSE_TRIM_DWELL_SECONDS + 60)
    self.assertEqual(ctrl._compute(first).setpoint, 24.0)
    ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 25.0
    second = first + timedelta(seconds=controller_module.HOUSE_TRIM_DWELL_SECONDS + 60)
    self.assertEqual(ctrl._compute(second).setpoint, 25.0)
    self.assertEqual(ctrl._trim_floor_today, 25.0)

def test_a_paid_probe_is_closed_inside_the_deadband(self):
    ctrl = self._con_anello(altre=(26.9, 26.9, 26.9))
    ctrl._compute(GIORNO)
    first = GIORNO + timedelta(seconds=controller_module.HOUSE_TRIM_DWELL_SECONDS + 60)
    self.assertEqual(ctrl._compute(first).setpoint, 24.0)
    self._casa(ctrl, 26.7)
    second = first + timedelta(seconds=controller_module.HOUSE_TRIM_DWELL_SECONDS + 60)
    self.assertEqual(ctrl._compute(second).setpoint, 24.0)
    self.assertIsNone(ctrl._trim_probe_casa)
    self.assertIsNone(ctrl._trim_floor_today)

def test_an_unpaid_probe_is_given_back_inside_the_deadband(self):
    ctrl = self._con_anello(altre=(26.8, 26.8, 26.8))
    ctrl._compute(GIORNO)
    first = GIORNO + timedelta(seconds=controller_module.HOUSE_TRIM_DWELL_SECONDS + 60)
    self.assertEqual(ctrl._compute(first).setpoint, 24.0)
    self._casa(ctrl, 26.74)
    second = first + timedelta(seconds=controller_module.HOUSE_TRIM_DWELL_SECONDS + 60)
    self.assertEqual(ctrl._compute(second).setpoint, 25.0)
    self.assertEqual(ctrl._trim_floor_today, 25.0)

def test_probe_verdict_is_consumed_only_once(self):
    ctrl = self._con_anello()
    ctrl._trim_probe_casa = 28.0
    ctrl._trim_probe_level = 24.0
    ctrl._trim_probe_started_at = GIORNO
    due = GIORNO + timedelta(seconds=controller_module.HOUSE_TRIM_DWELL_SECONDS + 60)
    self.assertFalse(ctrl._last_step_paid(28.0, 1.0, due))
    floor = ctrl._trim_floor_today
    self.assertIsNone(ctrl._last_step_paid(28.0, 1.0, due))
    self.assertEqual(ctrl._trim_floor_today, floor)
```

Use `_con_anello()`, `_casa()`, fixed `GIORNO` and `HOUSE_TRIM_DWELL_SECONDS + 60`; assert setpoint, floor and all three cleared probe fields.

- [ ] **Step 4: Verify all four new tests are RED for their stated reason**

Run each named test separately. Do not proceed on fixture errors or unrelated failures.

- [ ] **Step 5: Reorder dwell, verdict, deadband and saturation decisions**

Keep the existing bounds and give-back calculation, but use this decision order:

```python
if casa is None:
    return self.house_trim
if (
    self._trim_changed_at is not None
    and (now - self._trim_changed_at).total_seconds() < HOUSE_TRIM_DWELL_SECONDS
):
    return self.house_trim

passo = passo if passo and passo > 0 else 1.0
verdetto = self._last_step_paid(casa, passo, now)
saturo = errore > 0 and self._saturation_brake(casa, room)

deve_restituire = verdetto is False or (verdetto is None and saturo)
if abs(errore) <= HOUSE_TRIM_DEADBAND:
    if verdetto is not False:
        return self.house_trim
elif errore <= 0:
    deve_restituire = False

if errore > 0 and deve_restituire:
    tetto = min(massimo, max(self.target_home, minimo))
    nuovo = (
        min(self.house_trim + passo, tetto)
        if self.house_trim < tetto
        else self.house_trim
    )
elif errore > 0:
    if comodino is not None:
        pavimento = float(self._cfg(CONF_ROOM_FLOOR, DEFAULT_ROOM_FLOOR) or 0.0)
        if pavimento > 0 and comodino <= pavimento:
            return self.house_trim
    self._reset_trim_floor(now)
    if self._trim_floor_today is not None:
        minimo = max(minimo, self._trim_floor_today)
    nuovo = max(self.house_trim - passo, minimo)
    if nuovo < self.house_trim:
        self._trim_probe_casa = casa
        self._trim_probe_level = nuovo
        self._trim_probe_started_at = now
else:
    nuovo = min(self.house_trim + passo, massimo)
```

Do not duplicate the give-back bounds; keep one branch for saturation and unpaid verdicts.

- [ ] **Step 6: Verify Task 3 and commit**

Run every new focused test, all existing trim-loop tests, then the complete suite:

```bash
python3 -I test_regressions.py
git diff --check
git add controller.py test_regressions.py
git commit -m "Make trim probe verdicts authoritative"
```

Expected: complete suite PASS and no existing target/fan/schedule regression.

---

### Task 4: Cancel probes outside their control phase and publish version 1.12.3

**Files:**
- Modify: `controller.py:1678-1740`
- Modify: `manifest.json:4`
- Test: `test_regressions.py:780-965`

**Interfaces:**
- Consumes: `_clear_trim_probe()`, `_phase(now)`, `PHASE_SLEEP`, `PHASE_WIND_DOWN`.
- Produces: phase transition that cancels stale daytime evidence without creating a floor; manifest version `1.12.3`.

- [ ] **Step 1: Add failing sleep and wind-down cancellation tests**

```python
def test_sleep_cancels_a_daytime_probe_without_learning(self):
    ctrl = self._con_anello()
    ctrl._trim_probe_casa = 28.0
    ctrl._trim_probe_level = 24.0
    ctrl._trim_probe_started_at = GIORNO
    ctrl._compute(GIORNO.replace(hour=2))
    self.assertIsNone(ctrl._trim_probe_casa)
    self.assertIsNone(ctrl._trim_floor_today)

def test_wind_down_cancels_a_daytime_probe_without_learning(self):
    ctrl = self._con_anello()
    self._orari(ctrl, target_sleep=22.0)
    ctrl._trim_probe_casa = 28.0
    ctrl._trim_probe_level = 24.0
    ctrl._trim_probe_started_at = GIORNO
    ctrl._compute(NOW.replace(hour=7, minute=45))
    self.assertIsNone(ctrl._trim_probe_casa)
    self.assertIsNone(ctrl._trim_floor_today)
```

- [ ] **Step 2: Verify phase tests are RED**

Expected: FAIL because night windows bypass `_house_trim()` and leave probe fields intact.

- [ ] **Step 3: Cancel before selecting the night target**

At the `night_window` branch:

```python
if night_window:
    self._clear_trim_probe()
    target = self.target_sleep
else:
    trim = self._house_trim(now, casa, passo, comodino, outdoor, room)
    if trim is not None:
        target = trim
    else:
        target = self.target_home
        compensazione = self._adaptive_extra(outdoor, now, passo)
        target += compensazione
```

- [ ] **Step 4: Verify phase tests and full suite are GREEN**

Run both phase tests and `python3 -I test_regressions.py`.

- [ ] **Step 5: Bump and validate the manifest**

Change only:

```json
"version": "1.12.3"
```

Run:

```bash
python3 -m json.tool manifest.json >/dev/null
python3 -m compileall -q .
git diff --check
```

- [ ] **Step 6: Commit Task 4**

```bash
git add controller.py test_regressions.py manifest.json
git commit -m "Release Clima Smart 1.12.3"
```

---

### Task 5: Harden early returns, stored timestamps and override persistence

**Files:**
- Modify: `controller.py:860-950`
- Modify: `controller.py:1260-1310`
- Modify: `controller.py:1688-1775`
- Modify: `controller.py:1918-2005`
- Test: `test_regressions.py:480-590`
- Test: `test_regressions.py:880-1080`

**Interfaces:**
- Consumes: `_clear_trim_probe()`, `_async_save_memoria()`, Home Assistant-aware `dt_util.now()`.
- Produces: `_trim_probe_age(now: datetime) -> float | None`, fail-safe Store parsing and a durably persisted real override path.

- [ ] **Step 1: Write failing lifetime and timezone tests**

Add tests proving that an overdue probe is cleared with `casa=None`, sleep clears
it even while climate is `heat`, a naive stored timestamp is rejected, a future
timestamp is cancelled, and a valid different-offset timestamp is compared by
elapsed UTC time.

- [ ] **Step 2: Run each test separately and verify RED**

Run:

```bash
python3 -m unittest \
  test_regressions.ControllerRegressionTests.test_an_overdue_probe_expires_even_without_house_reading \
  test_regressions.ControllerRegressionTests.test_sleep_cancels_probe_even_while_heating \
  test_regressions.ControllerRegressionTests.test_a_naive_stored_probe_timestamp_is_discarded \
  test_regressions.ControllerRegressionTests.test_a_future_probe_expires_without_learning \
  test_regressions.ControllerRegressionTests.test_probe_age_uses_elapsed_utc_across_offsets -v
```

Expected failures must be the retained probe or the naive/aware `TypeError`,
never a fixture error.

- [ ] **Step 3: Centralize probe-age housekeeping**

Implement `_trim_probe_age(now)` to reject missing/naive/future/cross-day/overdue
timestamps, compare aware values in UTC, and clear invalid probes without a
floor. Call it before `_house_trim()` early returns and near the start of
`_compute()`; cancel sleep/wind-down immediately after phase calculation and
before mode/season/HVAC early returns. `_last_step_paid()` consumes the returned
age and judges only after one dwell.

- [ ] **Step 4: Verify lifetime/timezone tests GREEN and run the full suite**

Expected: all new cases pass and the existing 148 tests remain green.

- [ ] **Step 5: Write failing corrupt-Store tests**

Cover top-level list/string/scalar payloads, naive datetime strings,
`house_trim` as NaN/inf/bool, `adaptive_extra` as NaN/inf/bool and `saturated`
as non-boolean. Assert `_async_load_memoria()` never raises and leaves clean,
finite defaults.

Name the tests `test_non_mapping_store_payload_is_ignored` and
`test_corrupt_persisted_scalars_are_ignored`.

- [ ] **Step 6: Implement fail-safe Store validation and verify GREEN**

Require a dict top level. Make `istante_di()` return only aware datetimes.
Introduce a finite non-boolean numeric parser, add plausibility only for
temperatures, and accept `saturated` only when `isinstance(value, bool)`.

- [ ] **Step 7: Write the failing real override persistence test**

Drive `_maybe_flag_manual()` with a user-context climate event, prepare the
controller restore barrier and service stubs, call `async_evaluate("evento")`,
then create/reload a new controller. Do not call `_async_save_memoria()` in the
test. Expected RED: Store save count is zero or the restarted controller has no
active override.

Name the test `test_a_real_manual_event_persists_override_before_early_return`.

- [ ] **Step 8: Persist at the override early-return boundary**

Inside `async_evaluate()`, await `_async_save_memoria()` before returning from
the `override_active` guard. This keeps the state durable and retains fail-once
retry semantics without spawning a competing save task.

- [ ] **Step 9: Verify Task 5 and commit**

Run all new focused tests, `python3 -I test_regressions.py`, compile/JSON checks
and `git diff --check`, then commit controller, tests, specification and plan as:

```bash
git commit -m "Harden persisted controller state"
```

---

### Task 6: Verify, independently review, integrate and deploy

**Files:**
- Verify: `controller.py`, `const.py`, `manifest.json`, `test_regressions.py`, `translations/*.json`
- Runtime write: `/config/custom_components/clima_smart/{const.py,controller.py,manifest.json}`
- Rollback: `/root/code/backups/clima_smart_pre_1_12_2_20260808_2212/`

**Interfaces:**
- Consumes: completed branch commits, backup ID `f3dc5d4d`, Home Assistant token `/root/code/.ha_token`, Samba credentials `/root/code/.smbcredentials`.
- Produces: reviewed branch with no Important/Critical findings and a verified live Home Assistant installation on 1.12.3.

- [ ] **Step 1: Run fresh complete verification**

```bash
python3 -I test_regressions.py
python3 -m compileall -q .
python3 -m json.tool manifest.json >/dev/null
python3 -m json.tool hacs.json >/dev/null
for file in translations/*.json; do python3 -m json.tool "$file" >/dev/null; done
git diff --check 048fcb3..HEAD
git status --short
```

Expected: all tests PASS, JSON and compilation exit `0`, no whitespace errors, clean working tree.

- [ ] **Step 2: Dispatch two fresh read-only reviews**

Reviewer A checks probe semantics, branch precedence, timing and bounds. Reviewer B checks persistence, restart compatibility, invalid readings, test quality and Home Assistant production risk. Both review `048fcb3..HEAD`, run the full suite and return severity-ranked findings.

Expected: no Critical or Important findings. If either reviewer finds one, verify it, add a failing test and repeat the relevant TDD task before requesting fresh reviews.

- [ ] **Step 3: Use the finishing workflow for branch integration**

Invoke `superpowers:finishing-a-development-branch`. Do not rewrite `048fcb3`. Re-run verification after any merge/rebase and record the exact integrated SHA. Do not push or merge without the option selected in that workflow.

- [ ] **Step 4: Revalidate the backup and pre-deploy live state**

Verify WebSocket `backup/info` still reports `f3dc5d4d` complete and idle, and Samba reports `f3dc5d4d.tar` with size `162078720`. Record API config, live manifest 1.12.1, config entry state, climate state/setpoint/current temperature and a pre-deploy error-log snapshot.

- [ ] **Step 5: Upload only the three approved files over SMB**

Use the exact integrated checkout:

```bash
smbclient //192.168.0.170/config -A /root/code/.smbcredentials -m SMB3 \
  -c 'cd custom_components/clima_smart; put const.py const.py; put controller.py controller.py; put manifest.json manifest.json'
```

Run from the integrated checkout. Do not upload tests, docs or unrelated files.

- [ ] **Step 6: Reread and compare every remote file before restart**

Download the three remote files into a new `/tmp/clima-smart-1.12.3-verify/` directory and run:

```bash
cmp -s const.py /tmp/clima-smart-1.12.3-verify/const.py
cmp -s controller.py /tmp/clima-smart-1.12.3-verify/controller.py
cmp -s manifest.json /tmp/clima-smart-1.12.3-verify/manifest.json
```

Expected: all three exit `0`; parsed remote manifest reports `1.12.3`. If any comparison fails, restore all three rollback files and stop before restart.

- [ ] **Step 7: Restart once and poll conditionally**

Call `POST /api/services/homeassistant/restart` with the local token. Poll authenticated `GET /api/` for up to ten minutes without fixed long sleeps. Continue only after it returns `{"message":"API running."}` and `/api/config` reports `RUNNING`.

- [ ] **Step 8: Verify loaded integration and unchanged operating intent**

Use WebSocket `manifest/list` and `config_entries/get` to confirm `clima_smart` version 1.12.3 and a loaded entry. Re-read `climate.clima_camera` and confirm its HVAC state and requested setpoint match the pre-restart intent. Fetch `/api/error_log`; reject new `clima_smart` import/setup/traceback errors.

- [ ] **Step 9: Roll back on any failed acceptance check**

Upload the three files from `/root/code/backups/clima_smart_pre_1_12_2_20260808_2212/`, compare remote bytes, restart once, then prove manifest 1.12.1, loaded entry and prior climate intent. Report the failed 1.12.3 check and rollback evidence.

- [ ] **Step 10: Report exact evidence**

Report integrated commit SHA, test count, reviewer verdicts, backup ID/size, remote byte comparisons, restart completion, loaded manifest/entry, climate state and log result. Do not call the deployment complete without all of them.
