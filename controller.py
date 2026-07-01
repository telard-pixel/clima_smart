"""The smart controller brain for Clima Smart.

This ports the validated automation logic into Python. It does NOT create a
climate entity: it drives an existing one (e.g. the addhOn `climate.clima_camera`)
through normal service calls, exactly like the automation did.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    COMMAND_SETTLE_SECONDS,
    CONF_CLIMATE,
    CONF_DAY_START,
    CONF_ECO_BAND,
    CONF_ECO_OUTDOOR_OFF,
    CONF_ECO_OUTDOOR_ON,
    CONF_ECO_SWITCH,
    CONF_MORNING_OFF_START,
    CONF_MUTE_SWITCH,
    CONF_NIGHT_SWITCH,
    CONF_NIGHT_START,
    CONF_OUTDOOR,
    CONF_OUTDOOR_FALLBACK,
    CONF_OVERRIDE_MINUTES,
    CONF_PRESENCE,
    CONF_PRESENCE_HOME_STATE,
    CONF_SUMMER_THRESHOLD,
    CONF_TARGET_AWAY,
    CONF_TARGET_HOME,
    DEFAULT_DAY_START,
    DEFAULT_ECO_BAND,
    DEFAULT_ECO_OUTDOOR_OFF,
    DEFAULT_ECO_OUTDOOR_ON,
    DEFAULT_MORNING_OFF_START,
    DEFAULT_NIGHT_START,
    DEFAULT_OVERRIDE_MINUTES,
    DEFAULT_PRESENCE_HOME_STATE,
    DEFAULT_SUMMER_THRESHOLD,
    DEFAULT_TARGET_AWAY,
    DEFAULT_TARGET_HOME,
    HVAC_COOL,
    HVAC_HEAT,
    HVAC_OFF,
    MODE_AUTO,
    MODE_AWAY,
    MODE_COMFORT,
    MODE_NIGHT,
    MODE_OFF,
    PHASE_DAY,
    PHASE_GAP,
    PHASE_NIGHT,
    SERVICE_CALL_TIMEOUT_SECONDS,
    UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

_UNAVAILABLE = ("unavailable", "unknown", None)


def _parse_time(value: str, fallback: str) -> time:
    """Parse 'HH:MM' into a time, falling back on bad input."""
    for candidate in (value, fallback):
        try:
            hh, mm = str(candidate).split(":")[:2]
            return time(int(hh), int(mm))
        except (ValueError, AttributeError):
            continue
    return time(0, 0)


def _to_float(value) -> float | None:
    try:
        if value in _UNAVAILABLE:
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


@dataclass
class Desired:
    """What the controller wants the climate to be on this evaluation.

    A field set to None means "don't touch it" (idempotent / leave as-is).
    """

    hvac: str | None = None          # 'cool' / 'off' / None
    setpoint: float | None = None    # target temperature / None
    fan: str | None = None           # 'auto' / None
    eco: bool | None = None          # True=on, False=off, None=leave
    mute: bool | None = None
    night: bool | None = None
    reason: str = ""


class ClimaSmartController:
    """Holds runtime state and applies the control logic to the target climate."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._unsubs: list = []
        self._lock = asyncio.Lock()
        self._stopped = False

        # Runtime state (surfaced/edited through entities)
        self.enabled: bool = True       # master switch (restored on startup)
        self.mode: str = MODE_AUTO      # "Modo" select (restored on startup)
        self._override_until: datetime | None = None
        self._settle_until: datetime | None = None
        self._last_setpoint_cmd: float | None = None
        self._last_hvac_cmd: str | None = None
        self._last_fan_cmd: str | None = None
        self._last_aux_cmd: dict[str, bool] = {}

        # Diagnostics (read by sensors)
        self.current_phase: str | None = None
        self.active_target: float | None = None
        self.last_reason: str = "inizializzazione"

        # entity_id -> conf_key for the eco/mute/night aux switches, resolved in
        # async_start() so manual toggles on them get the same override grace
        # period as manual hvac/setpoint changes on the climate entity.
        self._aux_entities: dict[str, str] = {}

        # Entity refresh callbacks
        self._update_callbacks: list = []

    # ------------------------------------------------------------------ config
    def _cfg(self, key: str, default=None):
        """Option overrides data; data is the immutable initial config."""
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key, default)

    @property
    def climate_entity(self) -> str:
        return self.entry.data[CONF_CLIMATE]

    @property
    def presence_entity(self) -> str | None:
        return self._cfg(CONF_PRESENCE) or None

    @property
    def target_home(self) -> float:
        return float(self._cfg(CONF_TARGET_HOME, DEFAULT_TARGET_HOME))

    @property
    def target_away(self) -> float:
        return float(self._cfg(CONF_TARGET_AWAY, DEFAULT_TARGET_AWAY))

    @property
    def eco_band(self) -> float:
        return float(self._cfg(CONF_ECO_BAND, DEFAULT_ECO_BAND))

    @property
    def eco_outdoor_on(self) -> float:
        return float(self._cfg(CONF_ECO_OUTDOOR_ON, DEFAULT_ECO_OUTDOOR_ON))

    @property
    def eco_outdoor_off(self) -> float:
        return float(self._cfg(CONF_ECO_OUTDOOR_OFF, DEFAULT_ECO_OUTDOOR_OFF))

    @property
    def summer_threshold(self) -> float:
        return float(self._cfg(CONF_SUMMER_THRESHOLD, DEFAULT_SUMMER_THRESHOLD))

    @property
    def override_minutes(self) -> int:
        return int(self._cfg(CONF_OVERRIDE_MINUTES, DEFAULT_OVERRIDE_MINUTES))

    # ------------------------------------------------------------- lifecycle
    async def async_start(self) -> None:
        watched = [self.climate_entity]
        if self.presence_entity:
            watched.append(self.presence_entity)
        for conf_key in (CONF_ECO_SWITCH, CONF_MUTE_SWITCH, CONF_NIGHT_SWITCH):
            ent = self._cfg(conf_key)
            if ent:
                self._aux_entities[ent] = conf_key
                watched.append(ent)
        self._unsubs.append(
            async_track_state_change_event(self.hass, watched, self._on_state_event)
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._on_interval,
                timedelta(seconds=UPDATE_INTERVAL_SECONDS),
            )
        )
        await self.async_evaluate("avvio")

    async def async_stop(self) -> None:
        self._stopped = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        # Drain the lock: wait for any evaluation already in flight to finish
        # before unload completes, so the old controller cannot keep commanding
        # the climate while a reload brings up a new one (two brains fighting).
        # Newly queued tasks bail out at the _stopped check in async_evaluate.
        async with self._lock:
            pass

    # --------------------------------------------------------- entity wiring
    @callback
    def register_update_callback(self, cb) -> None:
        self._update_callbacks.append(cb)

    @callback
    def unregister_update_callback(self, cb) -> None:
        if cb in self._update_callbacks:
            self._update_callbacks.remove(cb)

    @callback
    def _notify_entities(self) -> None:
        for cb in list(self._update_callbacks):
            cb()

    # --------------------------------------------------------- state changes
    @callback
    def _on_interval(self, now: datetime) -> None:
        if self._stopped:
            return
        self.entry.async_create_background_task(
            self.hass, self.async_evaluate("intervallo"), "clima_smart_evaluate"
        )

    @callback
    def _on_state_event(self, event: Event) -> None:
        if self._stopped:
            return
        entity_id = event.data.get("entity_id")
        if entity_id == self.climate_entity:
            self._maybe_flag_manual(event)
        elif entity_id in self._aux_entities:
            self._maybe_flag_manual_switch(self._aux_entities[entity_id], event)
        self.entry.async_create_background_task(
            self.hass, self.async_evaluate("evento"), "clima_smart_evaluate"
        )

    @callback
    def _maybe_flag_manual(self, event: Event) -> None:
        """Detect a manual setpoint/hvac change on the controlled climate.

        We compare against the last values WE commanded rather than relying on
        event context (the underlying integration may refresh state with its own
        context after a cloud round-trip). A short settle window after our own
        command prevents false positives while the cloud catches up.
        """
        if not self.enabled:
            return
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None or old_state is None:
            return
        # A transition to/from unavailable/unknown (a cloud hiccup) is never a
        # manual user action: don't cede control for override_minutes over it.
        if new_state.state in _UNAVAILABLE or old_state.state in _UNAVAILABLE:
            return

        hvac_changed = new_state.state != old_state.state
        new_set = _to_float(new_state.attributes.get("temperature"))
        old_set = _to_float(old_state.attributes.get("temperature"))
        setpoint_changed = new_set != old_set

        if not (hvac_changed or setpoint_changed):
            # current_temperature-only update: never a manual action.
            return

        now = dt_util.now()
        if self._settle_until and now < self._settle_until:
            # Our own command still propagating.
            return

        # Attribute each CHANGED field independently: it is "ours" only if it
        # matches a value we actually commanded. A changed field we never set
        # (e.g. a manual setpoint while hvac stayed 'cool') counts as manual.
        manual = False
        if hvac_changed and not (
            self._last_hvac_cmd is not None and new_state.state == self._last_hvac_cmd
        ):
            manual = True
        # new_set None is a mode-driven attribute drop (e.g. our cool->off
        # clearing the target temperature), never something a user typed: if the
        # state event lands after the settle window it must not flag manual.
        if (
            setpoint_changed
            and new_set is not None
            and not (
                self._last_setpoint_cmd is not None
                and new_set == self._last_setpoint_cmd
            )
        ):
            manual = True

        if manual:
            self._start_override("comando manuale rilevato")

    @callback
    def _maybe_flag_manual_switch(self, conf_key: str, event: Event) -> None:
        """Same idea as _maybe_flag_manual, for the eco/mute/night aux switches.

        Without this, a manual toggle of one of these switches from the
        dashboard had no override protection at all (only the climate entity
        was watched) and got silently reverted on the next evaluation pass.
        """
        if not self.enabled:
            return
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None or old_state is None:
            return
        if new_state.state in _UNAVAILABLE or old_state.state in _UNAVAILABLE:
            return
        if new_state.state == old_state.state:
            return

        now = dt_util.now()
        if self._settle_until and now < self._settle_until:
            return

        want = new_state.state == "on"
        if self._last_aux_cmd.get(conf_key) == want:
            return

        self._start_override(f"comando manuale su {conf_key}")

    def _start_override(self, reason: str) -> None:
        self._override_until = dt_util.now() + timedelta(minutes=self.override_minutes)
        self.last_reason = f"{reason} → cedo fino a {self._override_until:%H:%M}"
        _LOGGER.debug("Clima Smart: %s", self.last_reason)
        self._notify_entities()

    @callback
    def clear_override(self) -> None:
        self._override_until = None

    @property
    def override_active(self) -> bool:
        return self._override_until is not None and dt_util.now() < self._override_until

    @property
    def override_until(self) -> datetime | None:
        return self._override_until

    # ----------------------------------------------------------- public API
    async def async_set_enabled(self, value: bool) -> None:
        self.enabled = value
        if value:
            self.clear_override()
            await self.async_evaluate("switch master ON")
        else:
            self.last_reason = "controller disattivato (switch master OFF)"
            self._notify_entities()

    async def async_set_mode(self, mode: str) -> None:
        self.mode = mode
        self.clear_override()
        await self.async_evaluate(f"modo → {mode}")

    @callback
    def async_options_updated(self) -> None:
        self.entry.async_create_background_task(
            self.hass, self.async_evaluate("opzioni aggiornate"), "clima_smart_evaluate"
        )

    # -------------------------------------------------------------- helpers
    def _read_outdoor(self) -> tuple[float | None, bool]:
        for key in (CONF_OUTDOOR, CONF_OUTDOOR_FALLBACK):
            ent = self._cfg(key)
            if not ent:
                continue
            st = self.hass.states.get(ent)
            if st is None:
                continue
            val = _to_float(st.state)
            if val is not None:
                return val, True
        return None, False

    def _is_home(self) -> bool:
        ent = self.presence_entity
        if not ent:
            return True
        st = self.hass.states.get(ent)
        if st is None:
            return True
        home_state = self._cfg(CONF_PRESENCE_HOME_STATE, DEFAULT_PRESENCE_HOME_STATE)
        return st.state == home_state

    def _phase(self, now: datetime) -> str:
        t = now.time()
        morning = _parse_time(
            self._cfg(CONF_MORNING_OFF_START, DEFAULT_MORNING_OFF_START),
            DEFAULT_MORNING_OFF_START,
        )
        day = _parse_time(self._cfg(CONF_DAY_START, DEFAULT_DAY_START), DEFAULT_DAY_START)
        night = _parse_time(
            self._cfg(CONF_NIGHT_START, DEFAULT_NIGHT_START), DEFAULT_NIGHT_START
        )
        if morning <= t < day:
            return PHASE_GAP
        if day <= t < night:
            return PHASE_DAY
        return PHASE_NIGHT

    def _eco_decision(
        self, room: float | None, target: float, outdoor: float | None
    ) -> bool | None:
        """Asymmetric hysteresis: True=on, False=off, None=leave (dead band)."""
        if room is None:
            return None
        out = outdoor if outdoor is not None else 0.0
        if room <= target and out < self.eco_outdoor_on:
            return True
        if room >= target + self.eco_band or out > self.eco_outdoor_off:
            return False
        return None

    # ------------------------------------------------------------- decision
    def _compute(self, now: datetime) -> Desired:
        climate = self.hass.states.get(self.climate_entity)
        if climate is None or climate.state in _UNAVAILABLE:
            return Desired(reason="clima non disponibile")

        cur_mode = climate.state
        room = _to_float(climate.attributes.get("current_temperature"))
        outdoor, outdoor_valid = self._read_outdoor()
        is_home = self._is_home()

        if outdoor_valid:
            summer = (
                outdoor > self.summer_threshold
                or (cur_mode == HVAC_COOL and outdoor > self.summer_threshold - 2)
            )
        else:
            # Outdoor sensors unavailable: never fail open (a dead sensor in
            # winter would start cooling out of season). Keep controlling a unit
            # that is already cooling; otherwise resume only on clear indoor
            # heat (room at/over the home target). The heat guard below still
            # protects a heating cycle either way.
            summer = cur_mode == HVAC_COOL or (
                room is not None and room >= self.target_home
            )

        # Forced manual modes ignore presence/time.
        if self.mode == MODE_OFF:
            self.current_phase = "—"
            self.active_target = None
            return Desired(hvac=HVAC_OFF, reason="modo Spento")

        if self.mode in (MODE_COMFORT, MODE_AWAY, MODE_NIGHT):
            # Forced modes ignore presence/time, but still respect season and a
            # running heating cycle: never force cooling in winter or over heat.
            self.current_phase = "—"
            if cur_mode == HVAC_HEAT:
                self.active_target = None
                return Desired(
                    reason=f"modo {self.mode}: clima in heat, non intervengo"
                )
            if not summer:
                self.active_target = None
                if cur_mode == HVAC_COOL:
                    return Desired(
                        hvac=HVAC_OFF,
                        reason=f"modo {self.mode}: fuori stagione, spengo cool",
                    )
                return Desired(
                    reason=f"modo {self.mode}: fuori stagione, non tocco"
                )
            target = self.target_away if self.mode == MODE_AWAY else self.target_home
            self.active_target = target
            night = self.mode == MODE_NIGHT
            return Desired(
                hvac=HVAC_COOL,
                setpoint=target,
                fan=None if night else "auto",
                eco=self._eco_decision(room, target, outdoor),
                mute=night,
                night=night,
                reason=f"modo {self.mode}",
            )

        # MODE_AUTO: replicate the validated automation.
        phase = self._phase(now)
        self.current_phase = phase
        is_night = phase == PHASE_NIGHT

        if phase == PHASE_GAP:
            self.active_target = None
            # Turn off, but only if cooling (never touch heating).
            if cur_mode == HVAC_COOL:
                return Desired(hvac=HVAC_OFF, reason="fascia 08-10: spengo")
            return Desired(reason="fascia 08-10: clima gia spento")

        if not summer:
            self.active_target = None
            if cur_mode == HVAC_COOL:
                return Desired(hvac=HVAC_OFF, reason="fuori stagione: spengo cool")
            return Desired(reason="fuori stagione: non tocco il riscaldamento")

        if cur_mode == HVAC_HEAT:
            # Never touch hvac/setpoint over a running heat cycle, but muto/notte
            # still follow the day/night phase (the original automation toggled
            # them whenever it was "summer and not gap", regardless of hvac mode).
            self.active_target = None
            return Desired(
                mute=is_night,
                night=is_night,
                reason="clima in heat: non tocco hvac/setpoint, aggiorno muto/notte",
            )

        target = self.target_home if is_home else self.target_away
        self.active_target = target
        return Desired(
            hvac=HVAC_COOL,
            setpoint=target,
            fan=None if is_night else "auto",
            eco=self._eco_decision(room, target, outdoor),
            mute=is_night,
            night=is_night,
            reason=f"auto {phase}: target {target}{' (fuori)' if not is_home else ''}",
        )

    # ---------------------------------------------------------------- apply
    async def async_evaluate(self, trigger: str) -> None:
        # Serialize: interval + state events must not run the logic concurrently
        # (equivalent of the automation's mode: single).
        async with self._lock:
            if self._stopped:
                return
            if not self.enabled:
                self.last_reason = "disattivato (switch master OFF)"
                self._notify_entities()
                return

            if self.override_active:
                self.last_reason = (
                    f"override manuale fino a {self._override_until:%H:%M} ({trigger})"
                )
                self._notify_entities()
                return

            now = dt_util.now()
            desired = self._compute(now)
            await self._apply(desired)
            self.last_reason = f"{desired.reason} [{trigger} {now:%H:%M}]"
            self._notify_entities()

    async def _apply(self, desired: Desired) -> None:
        climate = self.hass.states.get(self.climate_entity)
        if climate is None or climate.state in _UNAVAILABLE:
            return
        cur_mode = climate.state
        cur_set = _to_float(climate.attributes.get("temperature"))
        cur_fan = climate.attributes.get("fan_mode")
        # A command issued in a PREVIOUS pass may still be propagating through the
        # cloud (the read-back lags); don't re-send an identical value meanwhile.
        settle_active = (
            self._settle_until is not None and dt_util.now() < self._settle_until
        )

        # 1) HVAC mode
        if (
            desired.hvac is not None
            and desired.hvac != cur_mode
            and not (settle_active and desired.hvac == self._last_hvac_cmd)
        ):
            # Bail before arming if we're being torn down, so we never leave the
            # settle window armed for a command we didn't actually send.
            if self._stopped:
                return
            # Record the command and arm the settle window BEFORE issuing it, so an
            # optimistic state write during the await is not mistaken for a manual
            # action by _maybe_flag_manual.
            prev = self._last_hvac_cmd
            self._last_hvac_cmd = desired.hvac
            self._arm_settle()
            if desired.hvac == HVAC_OFF:
                ok = await self._call("climate", "turn_off", {})
            else:
                ok = await self._call(
                    "climate", "set_hvac_mode", {"hvac_mode": desired.hvac}
                )
            if not ok:
                # Command failed: undo the bookkeeping so the next pass retries it
                # instead of the settle guard suppressing the resend for ~180s.
                self._last_hvac_cmd = prev
                return
            # Treat the unit as already in the target mode for the rest of this pass.
            cur_mode = desired.hvac

        # Setpoint / fan / eco only make sense while we intend the unit to cool.
        if desired.hvac == HVAC_COOL:
            # 2) Setpoint. Snap the desired value to the climate's own step
            # first (a unit that quantizes, e.g. to whole degrees, would report
            # back a value that never equals ours and we would re-send at every
            # pass); the small tolerance absorbs float noise in the reported
            # state. _last_setpoint_cmd stores the snapped value, so the manual
            # detection compares against what the device will actually echo.
            want_set = desired.setpoint
            if want_set is not None:
                step = _to_float(climate.attributes.get("target_temp_step"))
                if step:
                    want_set = round(want_set / step) * step
            if (
                want_set is not None
                and (cur_set is None or abs(cur_set - want_set) > 0.05)
                and not (settle_active and want_set == self._last_setpoint_cmd)
            ):
                if self._stopped:
                    return
                prev = self._last_setpoint_cmd
                self._last_setpoint_cmd = want_set
                self._arm_settle()
                if not await self._call(
                    "climate", "set_temperature", {"temperature": want_set}
                ):
                    self._last_setpoint_cmd = prev

            # 3) Fan
            if (
                desired.fan is not None
                and cur_fan != desired.fan
                and not (settle_active and desired.fan == self._last_fan_cmd)
            ):
                if self._stopped:
                    return
                prev = self._last_fan_cmd
                self._last_fan_cmd = desired.fan
                self._arm_settle()
                if not await self._call(
                    "climate", "set_fan_mode", {"fan_mode": desired.fan}
                ):
                    self._last_fan_cmd = prev

            # 4) Eco
            await self._apply_switch(CONF_ECO_SWITCH, desired.eco, settle_active)

        # Mute / night quietness follow the day/night phase independently of
        # hvac mode (see _compute's heat branch in MODE_AUTO).
        await self._apply_switch(CONF_MUTE_SWITCH, desired.mute, settle_active)
        await self._apply_switch(CONF_NIGHT_SWITCH, desired.night, settle_active)

    def _arm_settle(self) -> None:
        self._settle_until = dt_util.now() + timedelta(seconds=COMMAND_SETTLE_SECONDS)

    async def _apply_switch(
        self, conf_key: str, want: bool | None, settle_active: bool
    ) -> bool:
        if want is None:
            return False
        entity_id = self._cfg(conf_key)
        if not entity_id:
            return False
        st = self.hass.states.get(entity_id)
        if st is None or st.state in _UNAVAILABLE:
            return False
        is_on = st.state == "on"
        if want == is_on:
            return False
        if settle_active and self._last_aux_cmd.get(conf_key) == want:
            return False
        if self._stopped:
            return False
        had_prev = conf_key in self._last_aux_cmd
        prev = self._last_aux_cmd.get(conf_key)
        self._last_aux_cmd[conf_key] = want
        self._arm_settle()
        if not await self._call_target(
            "switch", "turn_on" if want else "turn_off", entity_id
        ):
            # Restore so the failed switch command is retried next pass.
            if had_prev:
                self._last_aux_cmd[conf_key] = prev
            else:
                self._last_aux_cmd.pop(conf_key, None)
            return False
        return True

    async def _call(self, domain: str, service: str, data: dict) -> bool:
        return await self._call_target(domain, service, self.climate_entity, data)

    async def _call_target(
        self, domain: str, service: str, entity_id: str, data: dict | None = None
    ) -> bool:
        payload = {"entity_id": entity_id}
        if data:
            payload.update(data)
        try:
            await asyncio.wait_for(
                self.hass.services.async_call(
                    domain, service, payload, blocking=True
                ),
                timeout=SERVICE_CALL_TIMEOUT_SECONDS,
            )
            return True
        except Exception as err:  # noqa: BLE001 - never let one bad call kill the loop
            _LOGGER.warning(
                "Clima Smart: errore su %s.%s(%s): %s", domain, service, entity_id, err
            )
            return False
