"""The smart controller brain for Clima Smart.

This ports the validated automation logic into Python. It does NOT create a
climate entity: it drives an existing one (e.g. the addhOn `climate.clima_camera`)
through normal service calls, exactly like the automation did.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryError
from homeassistant.const import UnitOfTemperature
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    COMMAND_SETTLE_SECONDS,
    CONF_AUTO_START_ROOM,
    CONF_AUTO_START_SLEEP,
    CONF_CLIMATE,
    CONF_DAY_START,
    CONF_ECO_BAND,
    CONF_ECO_OUTDOOR_OFF,
    CONF_ECO_OUTDOOR_ON,
    CONF_ECO_SWITCH,
    CONF_HUMIDITY,
    CONF_MORNING_OFF_START,
    CONF_MUTE_SWITCH,
    CONF_NIGHT_SWITCH,
    CONF_NIGHT_START,
    CONF_OUTDOOR,
    CONF_OUTDOOR_FALLBACK,
    CONF_OVERRIDE_MINUTES,
    CONF_PRESENCE,
    CONF_PRESENCE_HOME_STATE,
    CONF_SETPOINT_OFFSET,
    CONF_SLEEP_END,
    CONF_SLEEP_START,
    CONF_SUMMER_THRESHOLD,
    CONF_TARGET_AWAY,
    CONF_TARGET_HOME,
    CONF_TARGET_SLEEP,
    DEFAULT_AUTO_START_ROOM,
    DEFAULT_AUTO_START_SLEEP,
    DEFAULT_DAY_START,
    DEFAULT_ECO_BAND,
    DEFAULT_ECO_OUTDOOR_OFF,
    DEFAULT_ECO_OUTDOOR_ON,
    DEFAULT_MORNING_OFF_START,
    DEFAULT_NIGHT_START,
    DEFAULT_OVERRIDE_MINUTES,
    DEFAULT_PRESENCE_HOME_STATE,
    DEFAULT_SETPOINT_OFFSET,
    DEFAULT_SLEEP_END,
    DEFAULT_SLEEP_START,
    DEFAULT_SUMMER_THRESHOLD,
    DEFAULT_TARGET_AWAY,
    DEFAULT_TARGET_HOME,
    DEFAULT_TARGET_SLEEP,
    DOMAIN,
    DRY_DELTA_HYSTERESIS,
    EVENT_STARTED,
    DRY_HUMIDITY_OFF,
    DRY_HUMIDITY_ON,
    DRY_MAX_DELTA,
    FAN_BANDS,
    FAN_BANDS_SLEEP,
    FAN_HYSTERESIS,
    FAN_ORDER,
    HVAC_COOL,
    HVAC_DRY,
    HVAC_HEAT,
    HVAC_OFF,
    AUX_REFUSAL_BACKOFF_SECONDS,
    MIN_FAN_DWELL_SECONDS,
    MODE_AUTO,
    MODE_AWAY,
    MODE_COMFORT,
    MODE_NIGHT,
    MODE_OFF,
    MODE_SMART,
    MODES,
    MORNING_OFF_WINDOW_MINUTES,
    PHASE_DAY,
    PHASE_GAP,
    PHASE_NIGHT,
    PHASE_SLEEP,
    PHASE_WIND_DOWN,
    RESTORE_TIMEOUT_SECONDS,
    SERVICE_CALL_TIMEOUT_SECONDS,
    SLEEP_START_WINDOW_MINUTES,
    START_REASON_DAY,
    START_REASON_NIGHT,
    SUMMER_HYSTERESIS,
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
    # Both the configured value and the DEFAULT_* constant failed to parse -
    # only reachable if a default itself was edited to something invalid.
    # Silently collapsing to midnight would shrink a phase boundary with no
    # visible symptom, so make it loud instead.
    _LOGGER.warning(
        "Clima Smart: impossibile interpretare l'orario %r (fallback %r), uso 00:00",
        value,
        fallback,
    )
    return time(0, 0)


def _to_float(value) -> float | None:
    try:
        if value in _UNAVAILABLE:
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def _convert_temperature(
    value: float | None, from_unit: str | None, to_unit: str
) -> float | None:
    """Convert a temperature when the source entity declares a known unit."""
    if value is None or not from_unit or from_unit == to_unit:
        return value
    try:
        return TemperatureConverter.convert(value, from_unit, to_unit)
    except ValueError:
        return None


def _fan_band(delta: float, bands: tuple[tuple[float, str], ...]) -> str:
    """The fan step MODE_SMART wants for a given gap above the target."""
    for threshold, name in bands:
        if delta >= threshold:
            return name
    return bands[-1][1]


def _band_threshold(name: str, bands: tuple[tuple[float, str], ...]) -> float:
    """Lower edge of a fan band, used to hold a step until the gap really drops."""
    for threshold, band in bands:
        if band == name:
            return threshold
    return 0.0


def _snap_setpoint(value: float, attributes: dict) -> float:
    """Clamp a setpoint to the climate's limits and snap it to its own step.

    Shared by the decision and the apply path so the diagnostic target sensor
    and the value the unit actually receives can never disagree.
    """
    minimum = _to_float(attributes.get("min_temp"))
    maximum = _to_float(attributes.get("max_temp"))
    if minimum is not None:
        value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    step = _to_float(attributes.get("target_temp_step"))
    if step:
        base = minimum if minimum is not None else 0.0
        # round() halves to even (25.5 -> 26 but 16.5 -> 16): on a 1 degree step
        # the same half degree landed sometimes above and sometimes below the
        # request. Half-up keeps it predictable.
        value = base + math.floor((value - base) / step + 0.5) * step
        if minimum is not None:
            value = max(value, minimum)
        if maximum is not None:
            value = min(value, maximum)
    return value


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
        self._config_data_snapshot = dict(entry.data)
        self._unsubs: list = []
        self._lock = asyncio.Lock()
        self._stopped = False
        self._started = False
        self._restore_ready: set[str] = set()
        self._restore_event = asyncio.Event()
        self._restore_wait_timed_out = False
        self._override_cancel = None
        self._apply_errors: list[str] = []
        # True while an evaluation has been queued but has not started yet, so a
        # burst of state events collapses into one pass (see _queue_evaluate).
        self._evaluate_queued = False

        # Runtime state (surfaced/edited through entities)
        self.enabled: bool = False      # fail-safe until master restore completes
        self.mode: str = MODE_AUTO      # "Modo" select (restored on startup)
        self._override_until: datetime | None = None
        # Settle windows are tracked per command source, not as one shared
        # timestamp: an aux-switch command (eco/mute/night) must not mask
        # manual-action detection on the climate entity's hvac/setpoint, and
        # vice versa. See _maybe_flag_manual / _maybe_flag_manual_switch.
        self._settle_hvac_until: datetime | None = None
        self._settle_setpoint_until: datetime | None = None
        # Armed whenever we change the hvac mode: this unit moves the fan, the
        # setpoint and the aux switches as a side effect of a mode change, and
        # those knock-on changes carry no user context, so without this window
        # they were indistinguishable from someone reaching for the remote.
        self._settle_mode_change_until: datetime | None = None
        self._settle_fan_until: datetime | None = None
        self._settle_aux_until: dict[str, datetime] = {}
        self._last_setpoint_cmd: float | None = None
        self._last_hvac_cmd: str | None = None
        self._last_fan_cmd: str | None = None
        self._last_aux_cmd: dict[str, bool] = {}
        # Quando l'unita' ha rifiutato un nostro comando su uno switch ausiliario.
        self._aux_refused_at: dict[str, datetime] = {}
        # Fail safe to the last trustworthy presence value. At startup, an
        # unavailable tracker is treated as home instead of silently switching to
        # the away target.
        self._last_presence_home = True

        # MODE_SMART: the fan step we last decided and when, so a downgrade has to
        # wait out MIN_FAN_DWELL_SECONDS instead of chasing every tenth of a degree.
        self._last_fan_band: str | None = None
        self._last_fan_band_at: datetime | None = None
        self._dry_active = False
        # Giorno in cui lo spegnimento del mattino e' gia' stato eseguito, e flag
        # della passata in corso che lo ha deciso.
        self._morning_off_done_on = None
        self._morning_off_armed = False
        # Stessa coppia per l'avvio serale.
        self._sleep_start_done_on = None
        self._sleep_start_armed = False
        self._day_start_done_on = None
        self._start_reason: str | None = None

        # Diagnostics (read by sensors)
        self.current_phase: str | None = None
        self.active_target: float | None = None
        self.last_reason: str = "inizializzazione"
        # Fuori dallo stato del sensore: cambiano a ogni passata e riempirebbero
        # il recorder di righe identiche nel contenuto.
        self.last_trigger: str | None = None
        self.last_evaluated: datetime | None = None

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
    def config_data_changed(self) -> bool:
        """Return whether linked entities changed and subscriptions need a reload."""
        return dict(self.entry.data) != self._config_data_snapshot

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
    def target_sleep(self) -> float:
        return float(self._cfg(CONF_TARGET_SLEEP, DEFAULT_TARGET_SLEEP))

    @property
    def setpoint_offset(self) -> float:
        return float(self._cfg(CONF_SETPOINT_OFFSET, DEFAULT_SETPOINT_OFFSET))

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
        self._started = True
        watched = {self.climate_entity}
        if self.presence_entity:
            watched.add(self.presence_entity)
        for conf_key in (CONF_OUTDOOR, CONF_OUTDOOR_FALLBACK):
            if ent := self._cfg(conf_key):
                watched.add(ent)
        aux_config = {
            conf_key: self._cfg(conf_key)
            for conf_key in (CONF_ECO_SWITCH, CONF_MUTE_SWITCH, CONF_NIGHT_SWITCH)
            if self._cfg(conf_key)
        }
        if len(aux_config.values()) != len(set(aux_config.values())):
            raise ConfigEntryError(
                translation_domain=DOMAIN, translation_key="duplicate_aux_switch"
            )
        for conf_key, ent in aux_config.items():
            if ent:
                self._aux_entities[ent] = conf_key
                watched.add(ent)
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
        try:
            await asyncio.wait_for(
                self._restore_event.wait(), timeout=RESTORE_TIMEOUT_SECONDS
            )
        except TimeoutError:
            # One of the two restoring entities never arrived: it can be disabled in
            # the entity registry, which is an ordinary thing for a user to do. The
            # barrier opens anyway, or every later evaluation - interval, event,
            # options change - would bail out at the same check, for good and after
            # every restart. `enabled` stays False, so nothing is commanded until
            # the master switch says otherwise: degraded, not deaf.
            self._restore_wait_timed_out = True
            self._restore_event.set()
            self.enabled = False
            self.last_reason = (
                "entità master/modo non ripristinate: controllo fermo per sicurezza"
            )
            _LOGGER.warning(
                "Clima Smart: timeout nel ripristino iniziale (entità master/modo "
                "assenti o disabilitate), resto disattivato"
            )
            self._notify_entities()
            return
        await self.async_evaluate("avvio dopo ripristino")

    async def async_stop(self) -> None:
        self._stopped = True
        if self._override_cancel is not None:
            self._override_cancel()
            self._override_cancel = None
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        # Drain the lock: wait for any evaluation already in flight to finish
        # before unload completes, so the old controller cannot keep commanding
        # the climate while a reload brings up a new one (two brains fighting).
        # Newly queued tasks bail out at the _stopped check in async_evaluate.
        async with self._lock:
            pass

    async def async_pause(self) -> None:
        """Prevent new commands and drain the currently running evaluation."""
        self.enabled = False
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

    @callback
    def mark_restore_ready(self, entity: str) -> None:
        """Signal that one of the two RestoreEntity platforms is ready."""
        self._restore_ready.add(entity)
        if self._restore_ready >= {"master", "mode"}:
            self._restore_event.set()
            if self._started and self._restore_wait_timed_out and not self._stopped:
                self._restore_wait_timed_out = False
                self.entry.async_create_background_task(
                    self.hass,
                    self.async_evaluate("ripristino completato"),
                    "clima_smart_restore_evaluate",
                )

    # --------------------------------------------------------- state changes
    @callback
    def _queue_evaluate(self, trigger: str) -> None:
        """Queue one evaluation, collapsing bursts into a single pass.

        The Haier cloud publishes several attributes in a row: one task per event
        meant a queue of identical passes waiting on the lock. A pass that has
        not started yet can absorb everything that arrives meanwhile because it
        re-reads every state when it runs. Events arriving after it started still
        queue a fresh pass, so no update is lost.
        """
        if self._evaluate_queued:
            return
        self._evaluate_queued = True
        self.entry.async_create_background_task(
            self.hass, self.async_evaluate(trigger), "clima_smart_evaluate"
        )

    @callback
    def _on_interval(self, now: datetime) -> None:
        if self._stopped:
            return
        self._queue_evaluate("intervallo")

    @callback
    def _on_state_event(self, event: Event) -> None:
        if self._stopped:
            return
        entity_id = event.data.get("entity_id")
        if entity_id == self.climate_entity:
            self._maybe_flag_manual(event)
        elif entity_id in self._aux_entities:
            self._maybe_flag_manual_switch(self._aux_entities[entity_id], event)
        self._queue_evaluate("evento")

    @callback
    def _maybe_flag_manual(self, event: Event) -> None:
        """Detect a manual setpoint/hvac change on the controlled climate.

        Direct user contexts take precedence. For context-less cloud echoes, a
        short per-field settle window prevents false positives while the device
        catches up; after that window every relevant change is considered manual.
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
        new_fan = new_state.attributes.get("fan_mode")
        old_fan = old_state.attributes.get("fan_mode")
        fan_changed = new_fan != old_fan and new_fan is not None

        if not (hvac_changed or setpoint_changed or fan_changed):
            # current_temperature-only update: never a manual action.
            return

        now = dt_util.now()
        # Direct UI/service calls carry the user's id. They must win even during a
        # cloud settle window; otherwise a user action made just after one of our
        # commands would be silently reverted.
        user_initiated = new_state.context.user_id is not None
        if user_initiated:
            self._start_override("comando manuale rilevato")
            return

        # Attribute each changed field independently. Its own settle window may
        # still contain transient cloud echoes; an unrelated field's window must
        # never suppress detection here.
        manual = False
        hvac_echo = False
        # A mode change of ours drags other fields with it, in the same event or a
        # minute later. While that window is open, a setpoint or fan move without
        # user context is collateral of our own command, not a person.
        mode_change_settling = (
            self._settle_mode_change_until is not None
            and now < self._settle_mode_change_until
        )
        if hvac_changed:
            hvac_echo = (
                self._last_hvac_cmd is not None
                and new_state.state == self._last_hvac_cmd
            )
            hvac_settling = (
                self._settle_hvac_until is not None and now < self._settle_hvac_until
            )
            if not (hvac_settling and hvac_echo):
                manual = True
        # new_set None is a mode-driven attribute drop (e.g. our cool->off
        # clearing the target temperature), never something a user typed.
        if setpoint_changed and new_set is not None:
            # Tolerance matches _apply's quantization-noise tolerance so our
            # own echoed setpoint is never mistaken for a manual change.
            setpoint_echo = (
                self._last_setpoint_cmd is not None
                and abs(new_set - self._last_setpoint_cmd) <= 0.05
            )
            setpoint_settling = (
                self._settle_setpoint_until is not None
                and now < self._settle_setpoint_until
            )
            # Our own mode change carrying the setpoint with it: either seen in the
            # same event (hvac_echo) or arriving just after it.
            mode_driven = hvac_echo or mode_change_settling
            if not mode_driven and not (setpoint_settling and setpoint_echo):
                manual = True
        if fan_changed:
            fan_echo = self._last_fan_cmd is not None and new_fan == self._last_fan_cmd
            fan_settling = (
                self._settle_fan_until is not None and now < self._settle_fan_until
            )
            mode_driven_fan = hvac_echo or mode_change_settling
            if not mode_driven_fan and not (fan_settling and fan_echo):
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
        if new_state.context.user_id is not None:
            self._start_override(f"comando manuale su {conf_key}")
            return
        if (
            self._settle_mode_change_until is not None
            and now < self._settle_mode_change_until
        ):
            # Aux switches this unit drops or raises by itself when the mode
            # changes: our command moved them, not a hand.
            return
        settle_until = self._settle_aux_until.get(conf_key)
        want = new_state.state == "on"
        if settle_until is not None and now < settle_until:
            if self._last_aux_cmd.get(conf_key) == want:
                return
            # The opposite of what we just asked, right after asking it: the unit
            # refused the command. Measured twice, about 60-70 s later and always
            # without user context. Reading it as a manual action cost an hour of
            # control each time; re-sending it at the next pass would just repeat
            # the whole dance, so the switch is left alone for a while.
            self._aux_refused_at[conf_key] = now
            self.last_reason = f"{conf_key}: comando rifiutato dall'unita'"
            _LOGGER.info(
                "Clima Smart: %s ha rifiutato il comando (%s), non insisto per %d minuti",
                conf_key,
                "on" if self._last_aux_cmd.get(conf_key) else "off",
                AUX_REFUSAL_BACKOFF_SECONDS // 60,
            )
            self._notify_entities()
            return

        self._start_override(f"comando manuale su {conf_key}")

    def _start_override(self, reason: str) -> None:
        if self._override_cancel is not None:
            self._override_cancel()
            self._override_cancel = None
        minutes = self.override_minutes
        if minutes <= 0:
            # Override turned off by the user: keep control and say so. Setting
            # _override_until to "now" left override_active already false while
            # the reason line announced a handover until HH:MM that never was.
            self._override_until = None
            self.last_reason = f"{reason} → override disattivato (0 min)"
            _LOGGER.debug("Clima Smart: %s", self.last_reason)
            self._notify_entities()
            return
        self._override_until = dt_util.now() + timedelta(minutes=minutes)
        self.last_reason = f"{reason} → cedo fino a {self._override_until:%H:%M}"
        _LOGGER.debug("Clima Smart: %s", self.last_reason)
        self._override_cancel = async_call_later(
            self.hass,
            timedelta(minutes=minutes),
            self._on_override_expired,
        )
        self._notify_entities()

    @callback
    def _on_override_expired(self, now: datetime) -> None:
        self._override_cancel = None
        self._override_until = None
        if not self._stopped:
            self.entry.async_create_background_task(
                self.hass,
                self.async_evaluate("override scaduto"),
                "clima_smart_override_expired",
            )

    @callback
    def clear_override(self) -> None:
        if self._override_cancel is not None:
            self._override_cancel()
            self._override_cancel = None
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
            await self.async_pause()
            self.current_phase = None
            self.active_target = None
            self.last_reason = "controller disattivato (switch master OFF)"
            self._notify_entities()

    async def async_set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Modo Clima Smart non valido: {mode}")
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
                val = _convert_temperature(
                    val,
                    st.attributes.get("unit_of_measurement"),
                    UnitOfTemperature.CELSIUS,
                )
                if val is not None:
                    return val, True
        return None, False

    @property
    def _system_temperature_unit(self) -> str:
        """Unit used by climate state attributes and climate service payloads."""
        units = getattr(getattr(self.hass, "config", None), "units", None)
        return getattr(units, "temperature_unit", UnitOfTemperature.CELSIUS)

    def _reachable_target(self, target: float, climate) -> float:
        """The target the unit will really hold, expressed back in Celsius.

        active_target feeds the diagnostic sensor. Publishing the requested value
        instead of the quantized one made the sensor read 25.5 while a unit with
        a 1 degree step was holding 26.
        """
        unit = self._system_temperature_unit
        in_unit = _convert_temperature(target, UnitOfTemperature.CELSIUS, unit)
        if in_unit is None:
            return target
        snapped = _snap_setpoint(in_unit, climate.attributes)
        back = _convert_temperature(snapped, unit, UnitOfTemperature.CELSIUS)
        return target if back is None else back

    def _is_home(self) -> bool:
        ent = self.presence_entity
        if not ent:
            return True
        st = self.hass.states.get(ent)
        if st is None or st.state in _UNAVAILABLE:
            return self._last_presence_home
        home_state = self._cfg(CONF_PRESENCE_HOME_STATE, DEFAULT_PRESENCE_HOME_STATE)
        self._last_presence_home = st.state == home_state
        return self._last_presence_home

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
        sleep_start = _parse_time(
            self._cfg(CONF_SLEEP_START, DEFAULT_SLEEP_START), DEFAULT_SLEEP_START
        )
        sleep_end = _parse_time(
            self._cfg(CONF_SLEEP_END, DEFAULT_SLEEP_END), DEFAULT_SLEEP_END
        )
        # Checked first, and it normally wraps around midnight (23:30 -> 07:30), so
        # the two halves are tested separately; an unwrapped window still works.
        if sleep_start != sleep_end:
            if sleep_start > sleep_end:
                in_sleep = t >= sleep_start or t < sleep_end
            else:
                in_sleep = sleep_start <= t < sleep_end
            if in_sleep:
                return PHASE_SLEEP
            # From the end of the sleep window to the morning switch-off: still the
            # night target, but at the lowest fan step.
            if sleep_end <= t < morning:
                return PHASE_WIND_DOWN
        if morning <= t < day:
            return PHASE_GAP
        if day <= t < night:
            return PHASE_DAY
        return PHASE_NIGHT

    def _morning_off_due(self, now: datetime) -> bool:
        """Whether the one-shot morning switch-off still has to happen today.

        Bounded to a short window after its time, and marked once decided: a Home
        Assistant restart later in the morning must not switch off a unit the user
        has meanwhile turned back on.
        """
        if self._morning_off_done_on == now.date():
            return False
        start = _parse_time(
            self._cfg(CONF_MORNING_OFF_START, DEFAULT_MORNING_OFF_START),
            DEFAULT_MORNING_OFF_START,
        )
        begin = now.replace(
            hour=start.hour, minute=start.minute, second=0, microsecond=0
        )
        return begin <= now < begin + timedelta(minutes=MORNING_OFF_WINDOW_MINUTES)

    def _sleep_start_due(self, now: datetime) -> bool:
        """Whether the one-shot evening start still has to happen tonight.

        Same shape as the morning switch-off: bounded and marked once done, so a
        climate the user turns off at one in the morning is not switched back on at
        the next pass.
        """
        if not self._cfg(CONF_AUTO_START_SLEEP, DEFAULT_AUTO_START_SLEEP):
            return False
        if self._sleep_start_done_on == now.date():
            return False
        start = _parse_time(
            self._cfg(CONF_SLEEP_START, DEFAULT_SLEEP_START), DEFAULT_SLEEP_START
        )
        begin = now.replace(
            hour=start.hour, minute=start.minute, second=0, microsecond=0
        )
        return begin <= now < begin + timedelta(minutes=SLEEP_START_WINDOW_MINUTES)

    def _read_humidity(self) -> float | None:
        """Indoor relative humidity, if a sensor was configured (MODE_SMART only)."""
        ent = self._cfg(CONF_HUMIDITY)
        if not ent:
            return None
        st = self.hass.states.get(ent)
        if st is None:
            return None
        value = _to_float(st.state)
        # The Haier's own humidity sensor reports a flat 0.0 when it has nothing to
        # say, and 0% indoors is not a reading: treat it as missing.
        if value is None or value <= 0:
            return None
        return value

    def _fan_for(
        self,
        delta: float | None,
        cur_fan: str | None,
        now: datetime,
        fan_modes: list | None,
        bands: tuple[tuple[float, str], ...] = FAN_BANDS,
    ) -> str | None:
        """Fan step for MODE_SMART: harder the further the room is above target.

        Both directions need FAN_HYSTERESIS of margin past the band edge, because
        a unit that reports in half degrees sits exactly on an edge for minutes at
        a time: measured on the real unit, a room held at target touched the
        `medium` edge six times in 82 minutes and dragged the fan up every time.
        Downgrades additionally wait out MIN_FAN_DWELL_SECONDS.
        """
        if delta is None:
            return None
        wanted = _fan_band(delta, bands)

        # Compare against our own last decision; fall back to what the unit reports
        # so a restart doesn't jump the fan around before the first decision.
        reference = self._last_fan_band
        if reference not in FAN_ORDER:
            reference = cur_fan if cur_fan in FAN_ORDER else None
        # A step the current band table does not offer (e.g. `high` left over from
        # the day when the sleep window starts) is not a reference to hold on to.
        available = sorted({name for _, name in bands}, key=FAN_ORDER.index)
        if reference is not None and reference not in available:
            reference = None
        if reference in FAN_ORDER and wanted != reference:
            if FAN_ORDER.index(wanted) > FAN_ORDER.index(reference):
                # Upgrade: the gap has to be clearly inside the higher band, not
                # merely touching its edge. On a two-step jump, come down one step
                # at a time instead of collapsing back to the reference: falling
                # straight back to `low` meant the hotter the room, the slower the
                # fan, for every gap between a threshold and its margin.
                while (
                    available.index(wanted) > available.index(reference)
                    and delta < _band_threshold(wanted, bands) + FAN_HYSTERESIS
                ):
                    wanted = available[available.index(wanted) - 1]
            else:
                hold = delta > _band_threshold(reference, bands) - FAN_HYSTERESIS
                too_soon = (
                    self._last_fan_band_at is not None
                    and (now - self._last_fan_band_at).total_seconds()
                    < MIN_FAN_DWELL_SECONDS
                )
                if hold or too_soon:
                    wanted = reference

        if fan_modes and wanted not in fan_modes:
            # The unit does not offer this step: leave the fan alone rather than
            # sending something it would reject at every pass.
            return None
        if wanted != self._last_fan_band:
            self._last_fan_band = wanted
            self._last_fan_band_at = now
        return wanted

    def _program_for(
        self, delta: float | None, humidity: float | None, hvac_modes: list | None
    ) -> str:
        """Pick `dry` over `cool` when the room is muggy but already at temperature.

        Without a humidity sensor, or on a unit without `dry`, this always returns
        `cool`, which is exactly what the other modes do.
        """
        if humidity is None or delta is None:
            self._dry_active = False
            return HVAC_COOL
        if hvac_modes and HVAC_DRY not in hvac_modes:
            self._dry_active = False
            return HVAC_COOL
        # Two thresholds on the gap as well, not one hard edge: a unit reporting in
        # half degrees sits right on 1.0 for minutes, and a bare `>=` had the
        # compressor swapping between cool and dry at every pass.
        leave = DRY_MAX_DELTA + DRY_DELTA_HYSTERESIS if self._dry_active else DRY_MAX_DELTA
        if delta >= leave:
            # Too warm for dehumidifying to be the answer.
            self._dry_active = False
            return HVAC_COOL
        threshold = DRY_HUMIDITY_OFF if self._dry_active else DRY_HUMIDITY_ON
        self._dry_active = humidity > threshold
        return HVAC_DRY if self._dry_active else HVAC_COOL

    def _eco_decision(
        self, room: float | None, target: float, outdoor: float | None
    ) -> bool | None:
        """Asymmetric hysteresis: True=on, False=off, None=leave (dead band)."""
        if room is None:
            return None
        if room >= target + self.eco_band:
            return False
        if outdoor is None:
            return None
        if outdoor > self.eco_outdoor_off:
            return False
        if room <= target and outdoor < self.eco_outdoor_on:
            return True
        return None

    # ------------------------------------------------------------- decision
    def _compute(self, now: datetime) -> Desired:
        climate = self.hass.states.get(self.climate_entity)
        if climate is None or climate.state in _UNAVAILABLE:
            # Clear the diagnostics too: leaving them frozen on the last pass made
            # the sensors advertise a phase and a target we are no longer chasing.
            self.current_phase = None
            self.active_target = None
            return Desired(reason="clima non disponibile")

        cur_mode = climate.state
        climate_unit = self._system_temperature_unit
        room = _convert_temperature(
            _to_float(climate.attributes.get("current_temperature")),
            climate_unit,
            UnitOfTemperature.CELSIUS,
        )
        outdoor, outdoor_valid = self._read_outdoor()
        is_home = self._is_home()

        if outdoor_valid:
            summer = (
                outdoor > self.summer_threshold
                or (
                    cur_mode == HVAC_COOL
                    and outdoor > self.summer_threshold - SUMMER_HYSTERESIS
                )
            )
        else:
            # Outdoor sensors unavailable: fail closed. We may maintain a cooling
            # cycle already in progress, but never start one from an indoor-only
            # reading that could actually be caused by winter heating.
            summer = cur_mode == HVAC_COOL

        # Forced manual modes ignore presence/time.
        if self.mode == MODE_OFF:
            self.current_phase = None
            self.active_target = None
            return Desired(hvac=HVAC_OFF, reason="modo Spento")

        if self.mode in (MODE_COMFORT, MODE_AWAY, MODE_NIGHT):
            # Forced modes ignore presence/time, but still respect season and a
            # running heating cycle: never force cooling in winter or over heat.
            self.current_phase = None
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
            self.active_target = self._reachable_target(target, climate)
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

        # MODE_AUTO replicates the validated automation; MODE_SMART shares its
        # phases and season guards and only decides target, fan and program itself.
        phase = self._phase(now)
        self.current_phase = phase
        # The sleep window is a stretch of the night: same quiet behaviour, colder
        # target. Everything that keyed off "is it night" must include it.
        is_night = phase in (PHASE_NIGHT, PHASE_SLEEP)

        if phase == PHASE_GAP and self.mode == MODE_SMART:
            # For MODE_SMART the morning switch-off is one event, not a state held
            # for two hours: outside its window the phase behaves like the day, so a
            # unit the user turns back on in the morning is managed, not switched off.
            # Only what we drive gets switched off: `!= HVAC_OFF` also covered `heat`
            # and would have shut down a running heating cycle every winter morning,
            # the one thing the rest of this file promises never to do.
            if self._morning_off_due(now) and cur_mode in (HVAC_COOL, HVAC_DRY):
                # Marked only once the command has actually gone through, in
                # async_evaluate: marking here meant a failed turn_off was never
                # retried and the unit cooled all day.
                self._morning_off_armed = True
                self.active_target = None
                return Desired(hvac=HVAC_OFF, reason="smart: spegnimento del mattino")
        elif phase == PHASE_GAP:
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

        # MODE_SMART keeps one target whatever the presence says: it is the mode for
        # "I set 25 and you deal with the rest".
        smart = self.mode == MODE_SMART
        night_window = phase in (PHASE_SLEEP, PHASE_WIND_DOWN)
        if night_window:
            target = self.target_sleep
        else:
            target = self.target_home if (smart or is_home) else self.target_away
        self.active_target = self._reachable_target(target, climate)

        if smart:
            # MODE_SMART never starts the unit: the user decides when it runs, we
            # decide how it runs, and the only switch-off we do is the scheduled one.
            if cur_mode == HVAC_OFF:
                # L'unica eccezione alla regola "non accendo mai": l'avvio della
                # notte, se l'utente l'ha chiesto, e una volta sola.
                if phase == PHASE_SLEEP and self._sleep_start_due(now):
                    self._sleep_start_armed = True
                    self._start_reason = START_REASON_NIGHT
                    self.active_target = self._reachable_target(target, climate)
                    return Desired(
                        hvac=HVAC_COOL,
                        setpoint=target,
                        fan=_fan_band(
                            (room - target) if room is not None else 0.0,
                            FAN_BANDS_SLEEP,
                        ),
                        reason=f"smart {phase}: avvio della notte, target {target}",
                    )
                soglia = float(
                    self._cfg(CONF_AUTO_START_ROOM, DEFAULT_AUTO_START_ROOM) or 0.0
                )
                if (
                    phase == PHASE_DAY
                    and soglia > 0
                    and room is not None
                    and room >= soglia
                    and self._day_start_done_on != now.date()
                ):
                    self._sleep_start_armed = True
                    self._start_reason = START_REASON_DAY
                    self.active_target = self._reachable_target(target, climate)
                    return Desired(
                        hvac=HVAC_COOL,
                        setpoint=target,
                        fan=_fan_band(room - target, FAN_BANDS),
                        reason=(
                            f"smart {phase}: avvio, stanza {room:.1f} oltre {soglia:.1f}"
                        ),
                    )
                self.active_target = None
                return Desired(reason=f"smart {phase}: clima spento, non lo accendo io")

            delta = None if room is None else room - target
            humidity = self._read_humidity()
            hvac_modes = climate.attributes.get("hvac_modes")
            if phase == PHASE_WIND_DOWN:
                # The hour before the switch-off: dehumidify with the fan on auto,
                # which takes the edge off the room without cooling it further.
                program = (
                    HVAC_DRY if not hvac_modes or HVAC_DRY in hvac_modes else HVAC_COOL
                )
                fan = "auto"
            else:
                program = self._program_for(delta, humidity, hvac_modes)
                fan = self._fan_for(
                    delta,
                    climate.attributes.get("fan_mode"),
                    now,
                    climate.attributes.get("fan_modes"),
                    FAN_BANDS_SLEEP if phase == PHASE_SLEEP else FAN_BANDS,
                )
            detail = f"{program}, ventola {fan or 'invariata'}"
            if delta is not None:
                detail += f", scarto {delta:+.1f}"
            if humidity is not None:
                detail += f", umidità {humidity:.0f}%"
            return Desired(
                hvac=program,
                setpoint=target,
                fan=fan,
                eco=self._eco_decision(room, target, outdoor),
                mute=is_night,
                night=is_night,
                reason=f"smart {phase}: target {target}, {detail}",
            )

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
            # Release the coalescing slot only here. Background tasks start eagerly
            # in Home Assistant, and acquiring a free lock does not suspend, so
            # clearing it before this line ran inside _queue_evaluate itself: the
            # flag was already False when that call returned and nothing ever
            # coalesced. From here on the pass re-reads every state, so whatever
            # arrives now genuinely belongs to the next one.
            self._evaluate_queued = False
            if self._stopped:
                return
            if not self._restore_event.is_set():
                self.last_reason = "attendo ripristino entità master/modo"
                self._notify_entities()
                return
            if not self.enabled:
                self.current_phase = None
                self.active_target = None
                self.last_reason = "disattivato (switch master OFF)"
                self._notify_entities()
                return

            if self.override_active:
                self.last_reason = (
                    f"override manuale fino a {self._override_until:%H:%M}"
                )
                self.last_trigger = trigger
                self._notify_entities()
                return

            now = dt_util.now()
            try:
                self._morning_off_armed = False
                self._sleep_start_armed = False
                desired = self._compute(now)
                self._apply_errors.clear()
                await self._apply(desired)
                if self._morning_off_armed and not self._apply_errors:
                    # The switch-off went through: no second attempt today.
                    self._morning_off_done_on = now.date()
                if self._sleep_start_armed and not self._apply_errors:
                    if self._start_reason == START_REASON_DAY:
                        self._day_start_done_on = now.date()
                    else:
                        self._sleep_start_done_on = now.date()
                    # Chi vuole annunciarlo (per esempio a voce) ascolta questo.
                    self.hass.bus.async_fire(
                        EVENT_STARTED,
                        {
                            "entity_id": self.climate_entity,
                            "target": self.active_target,
                            "phase": self.current_phase,
                            "motivo": self._start_reason,
                        },
                    )
            except Exception as err:  # noqa: BLE001 - one bad pass must not wedge the loop silently
                _LOGGER.exception(
                    "Clima Smart: errore durante la valutazione (%s)", trigger
                )
                self.last_reason = f"errore interno: {err}"
                self.last_trigger = trigger
                self.last_evaluated = now
                self._notify_entities()
                return
            error_suffix = (
                f"; errori: {', '.join(self._apply_errors)}"
                if self._apply_errors
                else ""
            )
            self.last_reason = f"{desired.reason}{error_suffix}"
            self.last_trigger = trigger
            self.last_evaluated = now
            self._notify_entities()

    async def _apply(self, desired: Desired) -> None:
        climate = self.hass.states.get(self.climate_entity)
        if climate is None or climate.state in _UNAVAILABLE:
            return
        cur_mode = climate.state
        cur_set = _to_float(climate.attributes.get("temperature"))
        cur_fan = climate.attributes.get("fan_mode")
        climate_unit = self._system_temperature_unit
        hvac_modes = climate.attributes.get("hvac_modes")
        hvac_blocked = (
            desired.hvac not in (None, HVAC_OFF)
            and hvac_modes
            and desired.hvac not in hvac_modes
        )
        if hvac_blocked:
            # Record it and skip only the hvac/setpoint/fan/eco part: mute and night
            # do not depend on the hvac mode, and returning here left them frozen on
            # yesterday's phase for as long as the mismatch lasted.
            self._apply_errors.append(f"modalità HVAC non supportata: {desired.hvac}")
        # A command issued in a PREVIOUS pass may still be propagating through the
        # cloud (the read-back lags); don't re-send an identical value meanwhile.
        # Each field has its own settle window (see __init__) so an unrelated
        # command doesn't suppress a legitimate resend of a different field.
        now = dt_util.now()
        hvac_settle_active = (
            self._settle_hvac_until is not None and now < self._settle_hvac_until
        )
        setpoint_settle_active = (
            self._settle_setpoint_until is not None
            and now < self._settle_setpoint_until
        )
        fan_settle_active = (
            self._settle_fan_until is not None and now < self._settle_fan_until
        )

        # 1) HVAC mode
        if (
            not hvac_blocked
            and desired.hvac is not None
            and desired.hvac != cur_mode
            and not (hvac_settle_active and desired.hvac == self._last_hvac_cmd)
        ):
            # Bail before arming if we're being torn down, so we never leave the
            # settle window armed for a command we didn't actually send.
            if self._stopped or not self.enabled:
                return
            # Record the command and arm the settle window BEFORE issuing it, so an
            # optimistic state write during the await is not mistaken for a manual
            # action by _maybe_flag_manual.
            prev = self._last_hvac_cmd
            self._last_hvac_cmd = desired.hvac
            self._arm_settle("_settle_hvac_until")
            # The unit rearranges fan, setpoint and aux switches around a mode
            # change; give those knock-on moves the same grace.
            self._arm_settle("_settle_mode_change_until")
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
                self._settle_hvac_until = None
                self._settle_mode_change_until = None
                # Un comando che non e' andato a buon fine non va registrato come
                # fatto, altrimenti oggi non lo si ritenta piu'.
                self._morning_off_armed = False
                self._sleep_start_armed = False
                return
            # Treat the unit as already in the target mode for the rest of this pass.
            cur_mode = desired.hvac

        # Setpoint / fan / eco only make sense while we intend the unit to cool or
        # dehumidify (MODE_SMART's `dry` still takes a setpoint and a fan step).
        if not hvac_blocked and desired.hvac in (HVAC_COOL, HVAC_DRY):
            # 2) Setpoint. Snap the desired value to the climate's own step
            # first (a unit that quantizes, e.g. to whole degrees, would report
            # back a value that never equals ours and we would re-send at every
            # pass); the small tolerance absorbs float noise in the reported
            # state. _last_setpoint_cmd stores the snapped value, so the manual
            # detection compares against what the device will actually echo.
            # The offset shifts what the unit is asked for, never the target we aim
            # the room at: active_target and the eco decision keep using the real
            # goal, so the diagnostics do not start lying to compensate a machine.
            want_set = desired.setpoint
            if want_set is not None:
                want_set += self.setpoint_offset
                want_set = _convert_temperature(
                    want_set, UnitOfTemperature.CELSIUS, climate_unit
                )
            if want_set is not None:
                want_set = _snap_setpoint(want_set, climate.attributes)
            if (
                want_set is not None
                and (cur_set is None or abs(cur_set - want_set) > 0.05)
                and not (setpoint_settle_active and want_set == self._last_setpoint_cmd)
            ):
                if self._stopped or not self.enabled:
                    return
                prev = self._last_setpoint_cmd
                self._last_setpoint_cmd = want_set
                self._arm_settle("_settle_setpoint_until")
                if not await self._call(
                    "climate", "set_temperature", {"temperature": want_set}
                ):
                    self._last_setpoint_cmd = prev
                    self._settle_setpoint_until = None

            # 3) Fan, unless the unit is in quiet mode. Measured on the real unit:
            # with `muto` on it puts the fan back to `auto` about a minute after our
            # command, and that contextless divergence is exactly what
            # _maybe_flag_manual treats as a manual action, handing over control for
            # override_minutes. Fighting it costs an hour of control every time.
            fan_modes = climate.attributes.get("fan_modes")
            if (
                desired.fan is not None
                and not self._quiet_mode_on(desired)
                and (not fan_modes or desired.fan in fan_modes)
                and cur_fan != desired.fan
                and not (fan_settle_active and desired.fan == self._last_fan_cmd)
            ):
                if self._stopped or not self.enabled:
                    return
                prev = self._last_fan_cmd
                self._last_fan_cmd = desired.fan
                self._arm_settle("_settle_fan_until")
                if not await self._call(
                    "climate", "set_fan_mode", {"fan_mode": desired.fan}
                ):
                    self._last_fan_cmd = prev
                    self._settle_fan_until = None

            # 4) Eco
            await self._apply_switch(CONF_ECO_SWITCH, desired.eco)

        # Mute / night quietness follow the day/night phase independently of
        # hvac mode (see _compute's heat branch in MODE_AUTO).
        await self._apply_switch(CONF_MUTE_SWITCH, desired.mute)
        await self._apply_switch(CONF_NIGHT_SWITCH, desired.night)

    def _quiet_mode_on(self, desired: Desired) -> bool:
        """Whether the unit is in (or is being put into) quiet mode this pass.

        With no mute switch linked there is nothing to conflict with, so the fan
        stays ours to command: `desired.mute` alone must not block it.
        """
        entity_id = self._cfg(CONF_MUTE_SWITCH)
        if not entity_id:
            return False
        if desired.mute:
            return True
        st = self.hass.states.get(entity_id)
        return st is not None and st.state == "on"

    def _arm_settle(self, field: str) -> None:
        setattr(self, field, dt_util.now() + timedelta(seconds=COMMAND_SETTLE_SECONDS))

    async def _apply_switch(self, conf_key: str, want: bool | None) -> bool:
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
        now = dt_util.now()
        refused_at = self._aux_refused_at.get(conf_key)
        if (
            refused_at is not None
            and (now - refused_at).total_seconds() < AUX_REFUSAL_BACKOFF_SECONDS
        ):
            self._apply_errors.append(f"{conf_key}: rifiutato dall'unita', riprovo dopo")
            return False
        settle_until = self._settle_aux_until.get(conf_key)
        settle_active = settle_until is not None and now < settle_until
        if settle_active and self._last_aux_cmd.get(conf_key) == want:
            return False
        if self._stopped or not self.enabled:
            return False
        had_prev = conf_key in self._last_aux_cmd
        prev = self._last_aux_cmd.get(conf_key)
        self._last_aux_cmd[conf_key] = want
        self._settle_aux_until[conf_key] = now + timedelta(
            seconds=COMMAND_SETTLE_SECONDS
        )
        if not await self._call_target(
            "switch", "turn_on" if want else "turn_off", entity_id
        ):
            # Restore so the failed switch command is retried next pass.
            if had_prev:
                self._last_aux_cmd[conf_key] = prev
            else:
                self._last_aux_cmd.pop(conf_key, None)
            self._settle_aux_until.pop(conf_key, None)
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
            self._apply_errors.append(f"{domain}.{service}: {err}")
            _LOGGER.warning(
                "Clima Smart: errore su %s.%s(%s): %s", domain, service, entity_id, err
            )
            return False
