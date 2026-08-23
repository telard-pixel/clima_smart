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
from datetime import date, datetime, time, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryError
from homeassistant.const import UnitOfTemperature
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    AUX_REFUSAL_BACKOFF_SECONDS,
    COMMAND_SETTLE_SECONDS,
    ADAPTIVE_MIN_DWELL_SECONDS,
    ADAPTIVE_QUANTUM,
    CONF_ADAPTIVE_MAX,
    CONF_ADAPTIVE_SLOPE,
    CONF_ADAPTIVE_START,
    CONF_AUTO_START_HOUSE,
    CONF_AUTO_START_OUTDOOR,
    CONF_AUTO_START_ROOM,
    CONF_AUTO_START_SLEEP,
    CONF_CLIMATE,
    CONF_DAY_START,
    CONF_ECO_BAND,
    CONF_ECO_OUTDOOR_OFF,
    CONF_ECO_OUTDOOR_ON,
    CONF_ECO_SWITCH,
    CONF_HOUSE_SENSORS,
    CONF_WINTER_ROOM_START,
    CONF_WINTER_ROOM_TARGET,
    CONF_WINTER_HOUSE_CEILING,
    CONF_HOT_OUTDOOR,
    CONF_HOUSE_TARGET,
    CONF_HUMIDITY,
    CONF_MORNING_OFF_ENABLED,
    CONF_MORNING_OFF_START,
    CONF_MUTE_SWITCH,
    CONF_NIGHT_START,
    CONF_NIGHT_MILD_OUTDOOR,
    CONF_NIGHT_START_OUTDOOR,
    CONF_NIGHT_SWITCH,
    CONF_OUTDOOR,
    CONF_OUTDOOR_FALLBACK,
    CONF_ROOM_SENSOR,
    CONF_ROOM_FLOOR,
    CONF_TRIM_MAX,
    CONF_TRIM_MIN,
    CONF_TRIM_MIN_HOT,
    CONF_OVERRIDE_MINUTES,
    CONF_SETPOINT_OFFSET,
    CONF_PRESENCE_ENTITY,
    CONF_SLEEP_END,
    CONF_SLEEP_START,
    CONF_SUMMER_THRESHOLD,
    CONF_TARGET_HOME,
    CONF_TARGET_SLEEP,
    CONF_TARGET_SLEEP_MILD,
    CONF_VANE_DAY_H,
    CONF_VANE_DAY_V,
    CONF_VANE_H,
    CONF_VANE_SLEEP,
    CONF_VANE_V,
    CONF_START_APPROVAL,
    DEFAULT_ADAPTIVE_MAX,
    DEFAULT_HOT_OUTDOOR,
    DEFAULT_HOUSE_TARGET,
    DEFAULT_ROOM_FLOOR,
    DEFAULT_TRIM_MAX,
    DEFAULT_TRIM_MIN,
    DEFAULT_TRIM_MIN_HOT,
    DEFAULT_ADAPTIVE_SLOPE,
    DEFAULT_ADAPTIVE_START,
    DEFAULT_AUTO_START_HOUSE,
    DEFAULT_AUTO_START_OUTDOOR,
    DEFAULT_AUTO_START_ROOM,
    DEFAULT_AUTO_START_SLEEP,
    DEFAULT_START_APPROVAL,
    DEFAULT_DAY_START,
    DEFAULT_ECO_BAND,
    DEFAULT_ECO_OUTDOOR_OFF,
    DEFAULT_ECO_OUTDOOR_ON,
    DEFAULT_MORNING_OFF_ENABLED,
    DEFAULT_MORNING_OFF_START,
    DEFAULT_NIGHT_START,
    DEFAULT_NIGHT_MILD_OUTDOOR,
    DEFAULT_NIGHT_START_OUTDOOR,
    DEFAULT_WINTER_ROOM_START,
    DEFAULT_WINTER_ROOM_TARGET,
    DEFAULT_WINTER_HOUSE_CEILING,
    DEFAULT_OVERRIDE_MINUTES,
    DEFAULT_PRESENCE_ENTITY,
    DEFAULT_SETPOINT_OFFSET,
    DEFAULT_SLEEP_END,
    DEFAULT_SLEEP_START,
    DEFAULT_SUMMER_THRESHOLD,
    DEFAULT_TARGET_HOME,
    DEFAULT_TARGET_SLEEP,
    DEFAULT_TARGET_SLEEP_MILD,
    DEFAULT_VANE_DAY,
    DEFAULT_VANE_SLEEP,
    DOMAIN,
    DRY_DELTA_HYSTERESIS,
    DRY_HUMIDITY_OFF,
    DRY_HUMIDITY_ON,
    DRY_MAX_DELTA,
    COLD_NIGHT_HYSTERESIS,
    NIGHT_MILD_HYSTERESIS,
    EVENT_APPROVAL_NEEDED,
    EVENT_COOL_OFF,
    EVENT_STARTED,
    FAN_BANDS,
    FAN_BANDS_SLEEP,
    FAN_HYSTERESIS_DOWN,
    FAN_HYSTERESIS_SLEEP,
    FAN_HYSTERESIS_UP,
    FAN_ORDER,
    HOT_OUTDOOR_HYSTERESIS,
    HOUSE_TRIM_DEADBAND,
    HOUSE_TRIM_DWELL_SECONDS,
    HVAC_COOL,
    HVAC_DRY,
    HVAC_HEAT,
    HVAC_OFF,
    MIN_FAN_DWELL_SECONDS,
    MODES,
    MODE_OFF,
    MODE_SMART,
    MORNING_OFF_WINDOW_MINUTES,
    PHASE_DAY,
    PHASE_GAP,
    PHASE_NIGHT,
    PHASE_SLEEP,
    PHASE_WIND_DOWN,
    RESTORE_TIMEOUT_SECONDS,
    SATURATION_GAP,
    SATURATION_HYSTERESIS,
    SERVICE_CALL_TIMEOUT_SECONDS,
    PLAUSIBLE_MAX_C,
    PLAUSIBLE_MIN_C,
    SEASON_EXIT_CONFIRM_SECONDS,
    SLEEP_BOOST_MIN_DELTA,
    STORAGE_VERSION,
    TRIM_PROBE_GAIN,
    SLEEP_BOOST_MINUTES,
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


def _plausible(celsius: float) -> bool:
    """Whether a reading can be a real temperature at all.

    A sensor that fails by publishing a number instead of `unavailable` walked
    straight past the fail-safe path, which only ever looked for the unavailable
    state. This is the cheap guard that puts it back on that path.
    """
    return PLAUSIBLE_MIN_C <= celsius <= PLAUSIBLE_MAX_C


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
    vane_h: str | None = None        # posizione chiesta all'aletta orizzontale
    vane_v: str | None = None        # e a quella verticale
    reason: str = ""


class ClimaSmartController:
    """Holds runtime state and applies the control logic to the target climate."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._config_data_snapshot = dict(entry.data)
        self._unsubs: list = []
        self._lock = asyncio.Lock()
        self._save_lock = asyncio.Lock()
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
        self.mode: str = MODE_SMART     # "Modo" select (restored on startup)
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
        # MODE_SMART: the fan step we last decided and when, so a downgrade has to
        # wait out MIN_FAN_DWELL_SECONDS instead of chasing every tenth of a degree.
        self._last_fan_band: str | None = None
        self._last_fan_band_at: datetime | None = None
        self._dry_active = False
        # Da quando la condizione "non e' piu' stagione calda" e' vera senza
        # interruzioni: None finche' siamo in stagione.
        self._not_summer_since: datetime | None = None
        # Anello esterno: il target della camera scelto per tenere le altre stanze
        # sulla linea di comfort. Vive fra un riavvio e l'altro come gli altri
        # contrassegni, perche' ci mette ore ad assestarsi e ripartire da capo
        # ogni volta significherebbe non assestarsi mai.
        self.house_trim: float | None = None
        self._trim_changed_at: datetime | None = None
        # Il vincolo legato all'esterna e' acceso o spento: ha isteresi, perche'
        # la stazione riporta gradi interi e balla sulla soglia.
        self._hot_outdoor = False
        # Il freno della saturazione e' inserito o no: anche questo con isteresi,
        # perche' guarda l'aria di ripresa, che si muove a mezzo grado per volta.
        self._saturated = False
        # Notte fredda: il vincolo esterna+comodino e' inserito o no, con la
        # stessa isteresi degli altri due. E se e' inserito e ha appena spento la
        # macchina, cosi' un riavvio a riposo sa che la ripresa non ha finestra
        # oraria: e' un rientro dal riposo, non l'avvio serale.
        self._cold_night = False
        self._cold_night_resting = False
        # Notte mite: dentro o fuori dalla banda dell'isteresi. Persistito come
        # _cold_night e per lo stesso motivo - un riavvio a meta' notte non deve
        # far ripartire il target da capo e rimbalzare di un grado.
        self._night_mild = False
        # Aiuto invernale: acceso o spento, con le due soglie configurate
        # (avvio/tetto) come propria isteresi - stesso schema di
        # _cold_night, stessa ragione di persistenza.
        self._winter_heating = False
        # Il giudizio del passo in giu': la media di casa al momento in cui e'
        # stato fatto, il livello a cui ha portato, e il pavimento che i passi
        # bocciati hanno lasciato per la giornata in corso.
        self._trim_probe_casa: float | None = None
        self._trim_probe_level: float | None = None
        self._trim_probe_started_at: datetime | None = None
        self._trim_floor_today: float | None = None
        self._trim_floor_day: date | None = None
        # Cio' che non deve morire con il processo: i contrassegni "gia' fatto
        # oggi" e la resa manuale. Senza, un riavvio dopo che l'utente ha spento
        # a mano riaccendeva la macchina, e l'avvio diurno poteva farlo ore dopo
        # perche' non ha finestra oraria.
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._stored: dict | None = None
        # Giorno in cui lo spegnimento del mattino e' gia' stato eseguito, e flag
        # della passata in corso che lo ha deciso.
        self._morning_off_done_on = None
        self._morning_off_armed = False
        # Stessa coppia per l'avvio serale.
        self._sleep_start_done_on = None
        self._sleep_start_armed = False
        # I dati dell'evento di richiesta, armati da `_compute` e lanciati da
        # `async_evaluate`: stesso schema degli altri contrassegni, ma qui non
        # c'e' nessun comando da mandare all'unita', quindi non dipende
        # dall'esito di `_apply`.
        self._approval_armed: dict | None = None
        self._day_start_done_on = None
        # E per lo spegnimento di una mattina fresca: come lo spegnimento del
        # mattino, un tentativo al giorno, cosi' un riavvio non lo ritenta
        # all'infinito ne' spegne un'unita' che l'utente ha appena riacceso.
        self._morning_cool_off_done_on = None
        self._morning_cool_off_armed = False
        self._vane_restored_on = None
        self._start_reason: str | None = None

        # Diagnostics (read by sensors)
        self.current_phase: str | None = None
        self.active_target: float | None = None
        # Quanto il target e' stato alzato per via del caldo esterno, e quando e'
        # cambiato l'ultima volta.
        self.adaptive_extra: float = 0.0
        self._adaptive_changed_at: datetime | None = None
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
    def target_home(self) -> float:
        return float(self._cfg(CONF_TARGET_HOME, DEFAULT_TARGET_HOME))

    @property
    def target_sleep(self) -> float:
        return float(self._cfg(CONF_TARGET_SLEEP, DEFAULT_TARGET_SLEEP))

    def _sleep_target(self, outdoor: float | None) -> float:
        """Il target della notte fonda, pieno o mite a seconda dell'esterna.

        Sotto `night_mild_outdoor` i muri smettono di spingere calore dentro e
        inseguire il target pieno costa senza rendere; sopra, la notte e' calda
        e i gradi vanno presi davvero. Con isteresi sull'esterna, perche' una
        notte assestata a ridosso della soglia rimbalzerebbe fra i due target.

        Il mite vale solo se e' **sopra** il pieno: un valore incrociato sarebbe
        una configurazione senza senso, e la si tratta come non configurata
        invece di raffreddare di piu' proprio quando fuori e' fresco.
        """
        pieno = self.target_sleep
        soglia = float(
            self._cfg(CONF_NIGHT_MILD_OUTDOOR, DEFAULT_NIGHT_MILD_OUTDOOR) or 0.0
        )
        mite = float(
            self._cfg(CONF_TARGET_SLEEP_MILD, DEFAULT_TARGET_SLEEP_MILD) or 0.0
        )
        if soglia <= 0 or mite <= pieno:
            self._night_mild = False
            return pieno
        if outdoor is None:
            # Una lettura che manca non e' la prova che la notte sia diventata
            # calda: si tiene il regime in corso. Senza questo, un buco della
            # stazione riportava il target da mite a pieno - tre gradi di
            # setpoint - e la macchina ripartiva a inseguire i 22, cioe' i
            # 460-580 W che questa funzione esiste per evitare. E' la stessa
            # difesa che hanno gia' _saturation_brake e _adaptive_extra.
            return mite if self._night_mild else pieno
        if self._night_mild:
            self._night_mild = outdoor < soglia + NIGHT_MILD_HYSTERESIS
        else:
            self._night_mild = outdoor < soglia
        return mite if self._night_mild else pieno

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
        await self._async_load_memoria()
        watched = {self.climate_entity}
        for conf_key in (CONF_OUTDOOR, CONF_OUTDOOR_FALLBACK):
            if ent := self._cfg(conf_key):
                watched.add(ent)
        # La presenza: cosi' l'uscita e - piu' importante - il rientro fanno
        # rivalutare subito, senza aspettare il tick periodico. Al rientro la notte
        # fonda deve ripartire in fretta, non con dieci minuti di ritardo.
        if presenza := self._presence_entity():
            watched.add(presenza)
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
        # Le alette seguono la stessa strada: sorvegliate, cosi' un tuo intervento
        # su di esse vale come su qualunque altro comando.
        for conf_key in (CONF_VANE_H, CONF_VANE_V):
            ent = self._cfg(conf_key)
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
        # Switches are remembered as booleans, the air-direction selects as the
        # option string: compare like with like.
        atteso = self._last_aux_cmd.get(conf_key)
        want = new_state.state == "on" if isinstance(atteso, bool) else new_state.state
        if settle_until is not None and now < settle_until:
            if atteso == want:
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
    def _fan_delta(
        self,
        phase: str,
        room: float | None,
        target: float,
        compensazione: float,
    ) -> float | None:
        """The signal the fan decision reads.

        **Misurato il 5 agosto, e costato caro.** La media di casa era stata messa
        qui come segnale diurno, perche' e' il carico vero e la ventola non lo
        muove. Ma le due grandezze non stanno sullo stesso livello: lo scarto sulla
        ripresa oscilla intorno a +1.0, quello sulla media di casa sta stabilmente
        fra +1.6 e +2.2, perche' il resto della casa e' piu' caldo della camera in
        cui vive la macchina. Con le stesse soglie la ventola e' salita a `high` e
        non e' piu' scesa, e siccome la portata d'aria e' il **tetto** del
        compressore, l'unita' ha potuto salire a 71 Hz e 1090 W invece di
        strozzarsi sui 40. Risultato su una finestra di un'ora e tre quarti, a
        parita' di raffrescamento consegnato e con l'esterna piu' fresca:
        **2.002 kWh contro 1.334 e 1.288 dei due giorni prima, il 50% in piu'.**

        Quindi di giorno si torna alla ripresa. Non e' un bel segnale - e' quello
        che la ventola stessa sposta di un grado - ma quell'oscillazione costava
        0.8 centesimi al giorno, misurati, e questa ne costava decine di volte
        tanti. Il rimedio all'oscillazione e' l'isteresi larga (`FAN_HYSTERESIS`),
        non un segnale diverso con le soglie di un altro.
        """
        if room is None:
            return None
        if phase == PHASE_SLEEP:
            # La notte resta sulla camera, perche' `low` non e' solo una portata:
            # e' il silenzio, ed e' il motivo per cui il muto e' scollegato. Cambia
            # pero' il riferimento: il setpoint che la macchina tiene davvero, non
            # il target nominale. Col target nominale si scendeva a `low` esattamente
            # quando la macchina arrivava - la patologia che queste bande esistono
            # per impedire, vista sul campo il 5 agosto alle 05:53.
            return room - (target + self.setpoint_offset)
        return room - target

    def _memoria(self) -> dict:
        """Snapshot of everything that must outlive the process."""

        def giorno(value):
            return value.isoformat() if value is not None else None

        return {
            "morning_off_done_on": giorno(self._morning_off_done_on),
            "sleep_start_done_on": giorno(self._sleep_start_done_on),
            "day_start_done_on": giorno(self._day_start_done_on),
            "morning_cool_off_done_on": giorno(self._morning_cool_off_done_on),
            "vane_restored_on": giorno(self._vane_restored_on),
            "override_until": giorno(self._override_until),
            "adaptive_extra": self.adaptive_extra,
            "house_trim": self.house_trim,
            # Il freno viaggia insieme al target che ha prodotto: senza, un riavvio
            # riparte staccato e l'anello ricomincia a spingere da dove era
            # arrivato. E' successo il 7 agosto 2026 alle 19:30.
            "saturated": self._saturated,
            # Il gemello del freno di saturazione: anche il vincolo "esterna calda"
            # ha isteresi, quindi al riavvio dentro la banda (es. 27.5 con soglia 28
            # e isteresi 1.0) va ripreso dal disco, altrimenti riparte spento e il
            # pavimento trim_min_hot sparisce - stessa lezione del 7 agosto.
            "hot_outdoor": self._hot_outdoor,
            # Il terzo della famiglia: come gli altri due, senza questo un riavvio
            # dentro il riposo per notte fredda lo perde e riparte come se la
            # macchina fosse sempre stata spenta per conto suo, non a riposo.
            "cold_night": self._cold_night,
            "cold_night_resting": self._cold_night_resting,
            "night_mild": self._night_mild,
            "winter_heating": self._winter_heating,
            # Anche il giudizio sul passo deve sopravvivere a un riavvio: senza,
            # l'anello dimentica la lezione e ricomincia a spingere. Misurato l'8
            # agosto 2026: riavvio alle 18:48, e alle 18:49 ha rifatto il passo che
            # aveva gia' bocciato alle 16:13.
            "trim_probe_casa": self._trim_probe_casa,
            "trim_probe_level": self._trim_probe_level,
            "trim_probe_started_at": giorno(self._trim_probe_started_at),
            "trim_floor_today": self._trim_floor_today,
            "trim_floor_day": giorno(self._trim_floor_day),
            "trim_changed_at": giorno(self._trim_changed_at),
            "adaptive_changed_at": giorno(self._adaptive_changed_at),
            # Il dwell della ventola: senza, un riavvio faceva ripartire la ventola
            # da zero e poteva cambiarla subito invece di aspettare i 30 minuti di
            # MIN_FAN_DWELL. Salvato insieme alla banda che lo ha aperto.
            "last_fan_band": self._last_fan_band,
            "last_fan_band_at": giorno(self._last_fan_band_at),
        }

    async def _async_load_memoria(self) -> None:
        """Bring back the one-shot marks and the manual override after a restart.

        Without this, a restart in the wrong minute undid a decision the user had
        just taken by hand: the daytime start is the worst of the three, because
        unlike the other two it has no time window and could fire again hours
        later, on any hot afternoon.
        """
        try:
            dati = await self._store.async_load()
        except Exception:  # noqa: BLE001 - un archivio illeggibile non deve fermare l'avvio
            _LOGGER.exception("Clima Smart: archivio di stato illeggibile, riparto pulito")
            return
        if not dati:
            return
        if not isinstance(dati, dict):
            _LOGGER.error(
                "Clima Smart: archivio di stato non valido (%s), riparto pulito",
                type(dati).__name__,
            )
            return

        def data_di(chiave):
            grezzo = dati.get(chiave)
            try:
                return date.fromisoformat(grezzo) if grezzo else None
            except (TypeError, ValueError):
                return None

        def istante_di(chiave):
            # `fromisoformat` e non l'aiutante di Home Assistant: il valore l'abbiamo
            # scritto noi con `isoformat`, quindi il giro si chiude nella libreria
            # standard e la logica resta provabile senza HA installato.
            grezzo = dati.get(chiave)
            try:
                valore = datetime.fromisoformat(grezzo) if grezzo else None
            except (TypeError, ValueError):
                return None
            if valore is None or valore.tzinfo is None or valore.utcoffset() is None:
                return None
            return valore

        self._morning_off_done_on = data_di("morning_off_done_on")
        self._sleep_start_done_on = data_di("sleep_start_done_on")
        self._day_start_done_on = data_di("day_start_done_on")
        self._morning_cool_off_done_on = data_di("morning_cool_off_done_on")
        self._vane_restored_on = data_di("vane_restored_on")
        self._override_until = istante_di("override_until")
        self._adaptive_changed_at = istante_di("adaptive_changed_at")
        self._trim_changed_at = istante_di("trim_changed_at")
        self._last_fan_band_at = istante_di("last_fan_band_at")
        banda = dati.get("last_fan_band")
        self._last_fan_band = banda if banda in FAN_ORDER else None
        adesso = dt_util.now()

        def dopo(a: datetime, b: datetime) -> bool:
            return a.astimezone(timezone.utc) > b.astimezone(timezone.utc)

        limite_override = adesso + timedelta(minutes=max(0, self.override_minutes))
        if (
            self._override_until is not None
            and (
                not dopo(self._override_until, adesso)
                or dopo(self._override_until, limite_override)
            )
        ):
            self._override_until = None
        if self._adaptive_changed_at is not None and dopo(
            self._adaptive_changed_at, adesso
        ):
            self._adaptive_changed_at = None
        if self._trim_changed_at is not None and dopo(self._trim_changed_at, adesso):
            self._trim_changed_at = None
        # Un timestamp del dwell ventola nel futuro (orologio spostato) non deve
        # bloccare la ventola per sempre: si scarta e la banda riparte libera.
        if self._last_fan_band_at is not None and dopo(self._last_fan_band_at, adesso):
            self._last_fan_band_at = None
            self._last_fan_band = None

        def numero_finito(chiave):
            valore = dati.get(chiave)
            if isinstance(valore, bool) or not isinstance(valore, (int, float)):
                return None
            valore = float(valore)
            return valore if math.isfinite(valore) else None

        def temperatura_di(chiave):
            valore = numero_finito(chiave)
            return valore if valore is not None and _plausible(valore) else None

        minimo_trim = float(
            self._cfg(CONF_TRIM_MIN, DEFAULT_TRIM_MIN) or DEFAULT_TRIM_MIN
        )
        massimo_trim = float(
            self._cfg(CONF_TRIM_MAX, DEFAULT_TRIM_MAX) or DEFAULT_TRIM_MAX
        )

        def livello_trim_di(chiave):
            valore = temperatura_di(chiave)
            if valore is None or not minimo_trim <= valore <= massimo_trim:
                return None
            return valore

        self.house_trim = livello_trim_di("house_trim")
        saturato = dati.get("saturated", False)
        self._saturated = saturato if isinstance(saturato, bool) else False
        freddo_notte = dati.get("cold_night", False)
        self._cold_night = freddo_notte if isinstance(freddo_notte, bool) else False
        riposo_notte = dati.get("cold_night_resting", False)
        self._cold_night_resting = (
            riposo_notte if isinstance(riposo_notte, bool) else False
        )
        notte_mite = dati.get("night_mild", False)
        self._night_mild = notte_mite if isinstance(notte_mite, bool) else False
        scaldo_inverno = dati.get("winter_heating", False)
        self._winter_heating = (
            scaldo_inverno if isinstance(scaldo_inverno, bool) else False
        )
        caldo_esterno = dati.get("hot_outdoor", False)
        self._hot_outdoor = caldo_esterno if isinstance(caldo_esterno, bool) else False

        self._trim_probe_casa = temperatura_di("trim_probe_casa")
        self._trim_probe_level = livello_trim_di("trim_probe_level")
        self._trim_probe_started_at = istante_di("trim_probe_started_at")
        self._trim_floor_today = livello_trim_di("trim_floor_today")
        if (
            self._trim_probe_casa is None
            or self._trim_probe_level is None
            or self._trim_probe_started_at is None
        ):
            self._clear_trim_probe()
        self._trim_floor_day = data_di("trim_floor_day")
        valore = numero_finito("adaptive_extra")
        massimo_adattivo = float(
            self._cfg(CONF_ADAPTIVE_MAX, DEFAULT_ADAPTIVE_MAX) or 0.0
        )
        if valore is not None and 0.0 <= valore <= max(0.0, massimo_adattivo):
            self.adaptive_extra = valore
        self._stored = self._memoria()
        if self.override_active:
            _LOGGER.debug(
                "Clima Smart: ripristinata la resa manuale fino a %s",
                self._override_until,
            )

    async def _async_save_memoria(self) -> None:
        """Persist the snapshot, but only when something actually moved."""
        async with self._save_lock:
            adesso = self._memoria()
            if adesso == self._stored:
                return
            try:
                await self._store.async_save(adesso)
            except Exception:  # noqa: BLE001 - un salvataggio fallito non deve fermare il ciclo
                _LOGGER.exception("Clima Smart: non sono riuscito a salvare lo stato")
            else:
                self._stored = adesso

    def _season_confirmed(self, summer: bool, now: datetime) -> bool:
        """Hold the warm season until "it is not summer" has lasted a while.

        Entering the season stays immediate: if it really is hot, we want to cool
        at once. It is the exit that has to be earned, because it switches the
        unit off for the rest of the day and a single bad sample used to be
        enough.
        """
        if summer:
            self._not_summer_since = None
            return True
        if self._not_summer_since is None:
            self._not_summer_since = now
        elapsed = (now - self._not_summer_since).total_seconds()
        if elapsed >= SEASON_EXIT_CONFIRM_SECONDS:
            return False
        # Not confirmed yet: carry on as if it were still summer.
        return True

    def _fan_hysteresis(self, phase: str) -> tuple[float, float]:
        """How much margin the fan decision needs before it moves.

        Sized to what the number can actually do. On the return air the margin has
        to be as wide as the loop gain, because a fan step moves that reading by a
        whole degree - the fan would otherwise chase itself. On a thermometer the
        fan does not move, the margin goes back to being what a margin should be:
        tolerance for sensor noise, and nothing more.
        """
        if phase == PHASE_SLEEP:
            return FAN_HYSTERESIS_SLEEP, FAN_HYSTERESIS_SLEEP
        return FAN_HYSTERESIS_UP, FAN_HYSTERESIS_DOWN

    def _read_bedside(self) -> float | None:
        """Il termometro della camera, se collegato. **Serve da limite, non da
        riferimento del controllo.**

        Errore commesso il 6 agosto e corretto lo stesso giorno: era stato messo al
        posto della temperatura di ripresa in tutto il calcolo, e siccome legge
        3.1-3.5 gradi meno - sta al comodino, in basso, mentre la ripresa e' in alto
        e in un getto d'aria - lo scarto diventava sempre piccolo. Con uno scarto
        piccolo la ventola non saliva mai, e con la ventola bassa il compressore
        resta inchiodato: il setpoint e' stato abbassato di due gradi e per due ore
        la macchina non si e' mossa da 46 Hz, la ripresa da 27.0 e la casa da 26.9.

        Un anello che chiede e una macchina che non esegue. Quindi il controllo
        resta sulla ripresa, che e' cio' che la macchina stessa insegue, e questo
        numero fa una cosa sola: dire quando la camera ha dato abbastanza.
        """
        ent = self._cfg(CONF_ROOM_SENSOR)
        if not ent:
            return None
        st = self.hass.states.get(ent)
        if st is None:
            return None
        valore = _to_float(st.state)
        if valore is None:
            return None
        valore = _convert_temperature(
            valore,
            st.attributes.get("unit_of_measurement"),
            UnitOfTemperature.CELSIUS,
        )
        if valore is None or not _plausible(valore):
            return None
        return valore

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
                if val is not None and _plausible(val):
                    return val, True
                if val is not None:
                    _LOGGER.warning(
                        "Clima Smart: lettura implausibile da %s (%s °C), la ignoro",
                        ent,
                        val,
                    )
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

    def _morning_off_enabled(self) -> bool:
        """Se lo spegnimento del mattino (e la gap) sono attivi.

        Disattivandolo, dopo la notte fonda si va diretti alla gestione di giorno,
        senza spegnere alle 08:30: su questa casa il calore entra fra le 07:30 e le
        10:00, quindi quello stop lasciava scaldare la casa nel momento peggiore.
        """
        value = self._cfg(CONF_MORNING_OFF_ENABLED, DEFAULT_MORNING_OFF_ENABLED)
        return bool(value) if value is not None else DEFAULT_MORNING_OFF_ENABLED

    def _phase(self, now: datetime) -> str:
        t = now.time()
        enabled = self._morning_off_enabled()
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
            # night target, but at the lowest fan step. Solo se lo spegnimento del
            # mattino e' attivo: senza, wind_down e gap collassano e dopo la notte
            # si passa diretti al giorno.
            if enabled and sleep_end <= t < morning:
                return PHASE_WIND_DOWN
        # Con lo spegnimento disattivato il giorno comincia alla fine della notte
        # fonda, e non esiste ne' wind_down ne' gap.
        day_begin = day if enabled else sleep_end
        if enabled and morning <= t < day:
            return PHASE_GAP
        if day_begin <= t < night:
            return PHASE_DAY
        return PHASE_NIGHT

    def _morning_off_due(self, now: datetime) -> bool:
        """Whether the one-shot morning switch-off still has to happen today.

        Bounded to a short window after its time, and marked once decided: a Home
        Assistant restart later in the morning must not switch off a unit the user
        has meanwhile turned back on.
        """
        if not self._morning_off_enabled():
            return False
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

    def _adaptive_extra(
        self, outdoor: float | None, now: datetime, step: float | None = None
    ) -> float:
        """How much to raise the target because it is very hot outside.

        Proportional above the threshold, capped, quantised to half degrees. The
        quantisation alone was not enough: the station reports whole degrees and
        swings across the threshold, so the compensation flipped every few minutes
        and every flip was a setpoint command to the unit - beep included. Going up
        is immediate, because if it really is getting hotter the target must
        follow; coming down needs a whole quantum of margin, meaning the outdoor
        has to fall back below the value that raised it; and either way a change
        waits out ADAPTIVE_MIN_DWELL_SECONDS.

        One single path, on purpose: the early return for "below the threshold"
        used to bypass both defences, so at exactly the threshold the compensation
        collapsed anyway.
        """
        inizio = float(self._cfg(CONF_ADAPTIVE_START, DEFAULT_ADAPTIVE_START) or 0.0)
        pendenza = float(self._cfg(CONF_ADAPTIVE_SLOPE, DEFAULT_ADAPTIVE_SLOPE) or 0.0)
        massimo = float(self._cfg(CONF_ADAPTIVE_MAX, DEFAULT_ADAPTIVE_MAX) or 0.0)
        if inizio <= 0 or pendenza <= 0 or massimo <= 0:
            self.adaptive_extra = 0.0
            return 0.0
        if outdoor is None:
            # Nessuna informazione nuova: si tiene quella di prima invece di
            # cambiare il target perche' un sensore ha battuto le palpebre.
            return self.adaptive_extra

        # Il quanto e' quello della macchina, non un mezzo grado deciso a tavolino.
        # Misurato su questa unita', che ha passo 1.0: mezzo grado di compensazione
        # diventava 24.5 comandati, che lo snap portava a 25.0, cioe' un grado
        # pieno. Il 4 agosto l'esterna ha attraversato la soglia dieci volte e il
        # setpoint l'ha seguita dieci volte, trascinandosi dietro anche la ventola,
        # perche' un grado di setpoint e' un grado di scarto e quindi un cambio di
        # banda. Quantizzando sul passo vero, uno scatto avviene solo quando puo'
        # davvero arrivare alla macchina, e l'isteresi sotto diventa larga quanto
        # serve: con pendenza 0.25 si sale a 35 gradi esterni e si torna giu' solo
        # sotto 33, due gradi pieni di banda morta.
        quanto = step if step and step > 0 else ADAPTIVE_QUANTUM
        # Il tetto va portato su un multiplo del quanto prima di arrotondare:
        # altrimenti un massimo di 1.5 con passo 1.0 diventerebbe 2.0, sforandolo.
        # Su una macchina a gradi interi un tetto di mezzo grado vale zero, ed e'
        # corretto cosi': quel mezzo grado non saprebbe dove andare.
        tetto = math.floor(massimo / quanto) * quanto
        grezzo = max(0.0, min((outdoor - inizio) * pendenza, massimo))
        nuovo = min(math.floor(grezzo / quanto + 0.5) * quanto, tetto)
        corrente = self.adaptive_extra
        if nuovo == corrente:
            return corrente
        if nuovo < corrente and grezzo > corrente - quanto:
            return corrente
        if (
            self._adaptive_changed_at is not None
            and (now - self._adaptive_changed_at).total_seconds()
            < ADAPTIVE_MIN_DWELL_SECONDS
        ):
            return corrente
        self._adaptive_changed_at = now
        self.adaptive_extra = nuovo
        return nuovo

    def _cold_night_off(
        self,
        outdoor: float | None,
        comodino: float | None,
        obiettivo: float | None = None,
    ) -> bool:
        """Se la notte fonda deve riposare perche' fuori sta gia' facendo il lavoro.

        Sotto `night_start_outdoor` l'aria di ripresa non basta piu' a dire se in
        stanza si sta gia' bene: legge il condotto, non il letto. Si media con il
        comodino, che legge la stanza vera, e si lascia riposare la macchina
        quando quella media e' gia' al target di notte fonda o sotto. Non e' un
        secondo target: `target_sleep` resta l'unico, questo dice solo quando
        raggiungerlo da soli costa niente farlo fare all'aria di fuori.

        Con isteresi sulla stessa media, per lo stesso motivo di sempre: le
        letture ballano sulla soglia.

        `obiettivo` e' il target di notte fonda **effettivo** di questa passata,
        che dalla 1.19.0 puo' essere quello pieno o quello mite. Misurare sempre
        contro il pieno faceva lavorare la macchina per un traguardo che l'aria
        di fuori aveva gia' superato. Assente, si torna al pieno: serve alle
        prove che chiamano questa funzione da sola.
        """
        soglia = float(
            self._cfg(CONF_NIGHT_START_OUTDOOR, DEFAULT_NIGHT_START_OUTDOOR) or 0.0
        )
        if soglia <= 0 or outdoor is None or outdoor >= soglia or comodino is None:
            self._cold_night = False
            return False
        riferimento = (outdoor + comodino) / 2
        obiettivo = self.target_sleep if obiettivo is None else obiettivo
        if self._cold_night:
            self._cold_night = riferimento <= obiettivo + COLD_NIGHT_HYSTERESIS
        else:
            self._cold_night = riferimento <= obiettivo
        return self._cold_night

    def _morning_cool_off_due(self, now: datetime, outdoor: float | None) -> bool:
        """Se una mattina troppo fresca deve fermare una macchina gia' accesa.

        Simmetrico alla guardia dell'avvio diurno (`_day_start_due`), ma al
        contrario: quella impedisce di accendere in una mattina fresca, questa
        spegne chi era gia' acceso - dalla notte fonda, o perche' l'utente l'ha
        riacceso a mano. Un solo tentativo al giorno, nella finestra fra la fine
        della notte fonda e l'inizio del giorno pieno: fuori da li' decide il
        resto dell'algoritmo, non questa guardia.
        """
        if self._morning_cool_off_done_on == now.date():
            return False
        guard = float(
            self._cfg(CONF_AUTO_START_OUTDOOR, DEFAULT_AUTO_START_OUTDOOR) or 0.0
        )
        if guard <= 0 or outdoor is None or outdoor >= guard:
            return False
        sleep_end = _parse_time(
            self._cfg(CONF_SLEEP_END, DEFAULT_SLEEP_END), DEFAULT_SLEEP_END
        )
        day_start = _parse_time(
            self._cfg(CONF_DAY_START, DEFAULT_DAY_START), DEFAULT_DAY_START
        )
        t = now.time()
        return sleep_end <= t < day_start

    def _hot_outdoor_floor(self, outdoor: float | None) -> float | None:
        """Il minimo che l'esterna impone al target della camera, se lo impone.

        Non e' un secondo regolatore: non sposta l'obiettivo, dice solo fin dove ha
        senso spingere. Sopra la soglia la macchina e' al limite, e chiedere di piu'
        alla camera non porta gradi in casa - porta frequenza. Misurato: il
        rendimento migliore sta fra 28 e 45 Hz (12-13 W/Hz) e peggiora sopra i 56
        (15 W/Hz a 71).

        Con isteresi, perche' l'esterna riporta gradi interi e balla sulla soglia.
        """
        soglia = float(self._cfg(CONF_HOT_OUTDOOR, DEFAULT_HOT_OUTDOOR) or 0.0)
        if soglia <= 0 or outdoor is None:
            self._hot_outdoor = False
            return None
        if self._hot_outdoor:
            self._hot_outdoor = outdoor >= soglia - HOT_OUTDOOR_HYSTERESIS
        else:
            self._hot_outdoor = outdoor >= soglia
        if not self._hot_outdoor:
            return None
        return float(self._cfg(CONF_TRIM_MIN_HOT, DEFAULT_TRIM_MIN_HOT) or 0.0) or None

    def _saturation_brake(self, casa: float | None, room: float | None) -> bool:
        """Se la camera e' gia' cosi' sotto la casa che chiedere di piu' non rende.

        Non e' un limite di comfort ne' un limite di macchina: e' il punto in cui
        il collo di bottiglia smette di essere il freddo prodotto e diventa l'aria
        che deve passare da una stanza all'altra. Da li' in poi abbassare ancora
        il setpoint raffredda solo la camera.

        Misurato su 36 finestre di un'ora, pomeriggi 2-7 agosto 2026, tenendo
        conto dell'esterna: un grado in piu' di divario costa **40 W** e porta
        **+0.006 C/h** di calo alla casa, con errore tipico 0.136 - cioe' il
        beneficio sta sotto la soglia di rilevabilita' mentre il costo si vede
        benissimo. Vedi SATURATION_GAP per la giornata che lo ha reso evidente.

        Con isteresi, come il vincolo dell'esterna: la banda deve restare piu'
        larga del passo del segnale, e l'aria di ripresa si muove a mezzo grado.
        """
        if SATURATION_GAP <= 0:
            self._saturated = False
            return False
        if casa is None or room is None:
            # **Non si azzera**: una lettura che manca non e' la prova che il freno
            # vada tolto, e il vincolo dell'esterna qui non fa testo, perche' li'
            # perdere il limite significa solo tornare liberi. Qui significa
            # ricominciare a spingere.
            #
            # Misurato il 7 agosto 2026: alle 19:30 Home Assistant si e' riavviato,
            # il freno e' ripartito staccato, il divario era 1.38 - sotto la soglia
            # d'innesco ma dentro l'isteresi - e l'anello ha rimesso il target a
            # 22.0 con la ventola alta. Cinquanta minuti a 695 W invece di 585.
            return self._saturated
        divario = casa - room
        if self._saturated:
            self._saturated = divario >= SATURATION_GAP - SATURATION_HYSTERESIS
        else:
            self._saturated = divario >= SATURATION_GAP
        return self._saturated

    def _reset_trim_floor(self, now: datetime) -> None:
        """Il pavimento imparato vale per la giornata, non per sempre.

        Una casa che oggi non risponde puo' rispondere domani: cambia il sole,
        cambia il vento, cambiano le finestre aperte. Quindi la lezione si azzera
        a mezzanotte, come gli altri contrassegni "gia' fatto oggi"."""
        if self._trim_floor_day != now.date():
            self._trim_floor_day = now.date()
            self._trim_floor_today = None

    def _clear_trim_probe(self) -> None:
        """Discard every part of the current measurement as one atomic state."""
        self._trim_probe_casa = None
        self._trim_probe_level = None
        self._trim_probe_started_at = None

    def _trim_probe_age(self, now: datetime) -> float | None:
        """Return elapsed probe seconds, clearing state that can no longer speak."""
        if self._trim_probe_casa is None:
            return None
        started = self._trim_probe_started_at
        if (
            started is None
            or started.tzinfo is None
            or started.utcoffset() is None
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            self._clear_trim_probe()
            return None
        if started.astimezone(now.tzinfo).date() != now.date():
            self._clear_trim_probe()
            return None
        age = (
            now.astimezone(timezone.utc) - started.astimezone(timezone.utc)
        ).total_seconds()
        if age < 0 or age > 2 * HOUSE_TRIM_DWELL_SECONDS:
            self._clear_trim_probe()
            return None
        return age

    def _last_step_paid(
        self, casa: float, passo: float, now: datetime
    ) -> bool | None:
        """Se l'ultimo passo in giu' ha davvero mosso la casa.

        E' il criterio che il divario non sa dare. Il divario si stringe **proprio
        quando la macchina lavora bene**: usarlo come freno significa mollare la
        presa nel momento sbagliato, ed e' quello che e' successo l'8 agosto 2026,
        target da 25 a 22 in due ore e mezza e macchina a 55 Hz.

        Qui invece si guarda il risultato: dopo un'attesa piena, la media di casa
        e' scesa di almeno TRIM_PROBE_GAIN? Se si', il passo ha reso e si puo'
        continuare. Se no, il passo va restituito e **quel livello non si riprova
        per il resto della giornata**: senza il pavimento, l'anello lo
        ritenterebbe fra tre quarti d'ora e si metterebbe a oscillare.

        Sui passi registrati fra il 5 e l'8 agosto uno solo su cinque aveva reso.
        """
        self._reset_trim_floor(now)
        age = self._trim_probe_age(now)
        if age is None:
            return None                     # nessun passo valido da giudicare
        if age < HOUSE_TRIM_DWELL_SECONDS:
            return None
        reso = casa <= self._trim_probe_casa - TRIM_PROBE_GAIN
        livello = self._trim_probe_level
        casa_partenza = self._trim_probe_casa
        self._clear_trim_probe()
        if not reso and livello is not None and casa <= casa_partenza:
            # Il pavimento si mette solo se la casa NON stava salendo. Se invece e'
            # salita (casa > casa_partenza) il passo non e' "inutile": il calore
            # sta entrando - la finestra 07:30-10:00 su questa casa - e il passo lo
            # contrasta. Bloccare il livello li' vorrebbe dire rinunciare a
            # raffreddare proprio prima del picco. Segnalato il 12 agosto 2026:
            # l'anello e' rimasto inchiodato a 25 tutto il giorno perche' il
            # pavimento era scattato la mattina mentre la casa saliva col sole.
            passo = passo if passo and passo > 0 else 1.0
            candidato = livello + passo
            self._trim_floor_today = (
                candidato if self._trim_floor_today is None
                else max(self._trim_floor_today, candidato)
            )
        return reso

    def _house_trim(
        self,
        now: datetime,
        casa: float | None,
        passo: float,
        comodino: float | None,
        outdoor: float | None = None,
        room: float | None = None,
    ) -> float | None:
        """Il target della camera che serve per tenere le altre stanze sulla linea.

        Di giorno l'obiettivo non e' la camera ma salotto, cucina e ingresso: la
        camera e' lo strumento, e sta piu' fredda perche' e' la sorgente di freddo
        di tutto il trilocale. Quindi questo anello guarda la media delle altre
        stanze e da quella ricava il setpoint da chiedere alla camera.

        Si muove **piano e di un passo macchina alla volta**: misurato, il
        pomeriggio piu' efficace ha tolto 0.72 gradi alla media in otto ore. Una
        correzione ogni tre quarti d'ora e' gia' piu' rapida di quanto la casa
        sappia rispondere; piu' in fretta si rincorrerebbe solo il rumore.
        """
        self._trim_probe_age(now)
        linea = float(self._cfg(CONF_HOUSE_TARGET, DEFAULT_HOUSE_TARGET) or 0.0)
        if linea <= 0:
            return None                      # anello disattivato: target fisso di prima
        minimo = float(self._cfg(CONF_TRIM_MIN, DEFAULT_TRIM_MIN) or DEFAULT_TRIM_MIN)
        massimo = float(self._cfg(CONF_TRIM_MAX, DEFAULT_TRIM_MAX) or DEFAULT_TRIM_MAX)
        caldo = self._hot_outdoor_floor(outdoor)
        if caldo is not None:
            minimo = max(minimo, caldo)

        if self.house_trim is None:
            # Si parte dal target di casa configurato, che e' l'ultima volonta'
            # esplicita dell'utente, e da li' l'anello corregge. La prima correzione
            # aspetta comunque la sua attesa piena: senza, la prima valutazione dopo
            # un riavvio salterebbe di un grado all'istante.
            self.house_trim = min(max(self.target_home, minimo), massimo)
            self._trim_changed_at = now
        if self.house_trim < minimo:
            # Il vincolo si e' appena acceso e siamo gia' sotto: si risale subito.
            # Chiedere meno e' la direzione sicura, non ha senso aspettare.
            self.house_trim = minimo
            self._trim_changed_at = now
        if casa is None:
            return self.house_trim           # nessuna media: si tiene quello che c'e'

        errore = casa - linea
        if (
            self._trim_changed_at is not None
            and (now - self._trim_changed_at).total_seconds() < HOUSE_TRIM_DWELL_SECONDS
        ):
            return self.house_trim

        passo = passo if passo and passo > 0 else 1.0
        # La prova in sospeso si giudica SEMPRE, non solo nel ramo che spinge in
        # giu': altrimenti resta appesa finche' non ricapita la stessa
        # condizione, e quando infine viene giudicata confronta la casa di adesso
        # con una base di ore prima invece che di tre quarti d'ora prima. E'
        # innocuo chiamarla a vuoto - senza una prova in sospeso non fa nulla.
        #
        # Misurato l'8 agosto 2026: col freno di saturazione inserito il verdetto
        # restava sospeso per ore, perche' il ramo che lo giudicava non veniva
        # nemmeno raggiunto.
        pagato = self._last_step_paid(casa, passo, now)
        saturo = errore > 0 and self._saturation_brake(casa, room)
        deve_restituire = pagato is False or (pagato is None and saturo)
        if abs(errore) <= HOUSE_TRIM_DEADBAND and pagato is not False:
            # Anche dentro la banda una prova ormai matura va chiusa. Se ha reso
            # si tiene il passo; se non ha reso, il ramo sotto lo restituisce.
            return self.house_trim
        if errore > 0 and deve_restituire:
            # Casa sopra la linea, ma spingere non rende piu': o la camera e'
            # gia' molto piu' fredda della casa (il divario compra solo
            # frequenza), o l'ultimo passo non ha mosso la casa (il verdetto
            # diretto, che quando c'e' vince sul divario). Si **restituisce** un
            # passo invece di limitarsi a fermare la discesa, perche' fermarsi
            # soltanto lascerebbe inchiodato un target che ci e' gia' arrivato -
            # com'e' successo il 7 agosto, target a 22.0 dalle dieci del mattino
            # alle sei di sera.
            #
            # Restituendo un passo alla volta, con la stessa attesa di tutto
            # l'anello, il target si assesta da solo attorno al divario utile:
            # scende finche' rende, risale appena smette. E l'isteresi tiene
            # l'assestamento lento invece di farlo oscillare.
            #
            # Restituisce **fino al target di giorno e non oltre**. Serve
            # un'ancora: rigiocando il 7 agosto senza, il target risaliva di un
            # passo ogni tre quarti d'ora fino al tetto del trim e ci restava,
            # perche' il divario si chiude solo quando la camera si scalda e in un
            # replay quella retroazione non c'e'. Ma un freno che puo' svuotare
            # tutto l'anello e' sbagliato comunque: questo dice "non piu' freddo di
            # quanto renda", non "smetti di raffreddare". Salire **sopra** il
            # target di giorno resta mestiere dell'altro ramo, quello che molla la
            # presa quando la casa sta gia' bene.
            tetto = min(massimo, max(self.target_home, minimo))
            nuovo = (
                min(self.house_trim + passo, tetto)
                if self.house_trim < tetto
                else self.house_trim
            )
        elif errore > 0:
            # Casa sopra la linea: si chiede di piu' alla camera.
            if comodino is not None:
                pavimento = float(self._cfg(CONF_ROOM_FLOOR, DEFAULT_ROOM_FLOOR) or 0.0)
                if pavimento > 0 and comodino <= pavimento:
                    # La camera ha gia' dato quello che poteva: serve la casa, ma
                    # resta una stanza in cui si dorme.
                    return self.house_trim
            self._reset_trim_floor(now)
            if self._trim_floor_today is not None:
                minimo = max(minimo, self._trim_floor_today)
            nuovo = max(self.house_trim - passo, minimo)
            if nuovo < self.house_trim:
                # Si segna da dove si parte, per poter giudicare fra un'attesa.
                self._trim_probe_casa = casa
                self._trim_probe_level = nuovo
                self._trim_probe_started_at = now
        else:
            nuovo = min(self.house_trim + passo, massimo)

        if nuovo != self.house_trim:
            self.house_trim = nuovo
            self._trim_changed_at = now
        return self.house_trim

    def _presence_entity(self) -> str | None:
        ent = self._cfg(CONF_PRESENCE_ENTITY, DEFAULT_PRESENCE_ENTITY)
        return ent or None

    def _fuori_casa(self) -> bool:
        """True solo se il sensore di presenza dice esplicitamente che sono fuori.

        `home` e' a casa; qualunque altra zona reale (`not_home`, il nome di una
        zona) e' fuori. Uno stato rotto - assente, `unknown`, `unavailable` - o
        l'entita' non configurata valgono "a casa": un GPS guasto non deve togliere
        la notte fonda a chi sta dormendo.
        """
        ent = self._presence_entity()
        if not ent:
            return False
        st = self.hass.states.get(ent)
        if st is None:
            return False
        return st.state not in ("home", "unknown", "unavailable", "none", "")

    def _house_average(self) -> float | None:
        """Average of the other rooms' thermometers, in Celsius.

        Sensors that are missing, unavailable or not numeric are simply skipped;
        with none left there is no average and the house condition cannot fire.
        """
        entities = self._cfg(CONF_HOUSE_SENSORS) or []
        if isinstance(entities, str):
            entities = [entities]
        letture = []
        for ent in entities:
            st = self.hass.states.get(ent)
            if st is None:
                continue
            value = _to_float(st.state)
            if value is None:
                continue
            value = _convert_temperature(
                value,
                st.attributes.get("unit_of_measurement"),
                UnitOfTemperature.CELSIUS,
            )
            if value is not None and math.isfinite(value) and _plausible(value):
                letture.append(value)
        if not letture:
            return None
        return sum(letture) / len(letture)

    def _start_approval(self) -> bool:
        """Se l'avvio deve passare da una persona invece di scattare da solo."""
        valore = self._cfg(CONF_START_APPROVAL, DEFAULT_START_APPROVAL)
        return bool(valore) if valore is not None else DEFAULT_START_APPROVAL

    def _day_start_due(
        self, now: datetime, room: float | None, outdoor: float | None
    ) -> str | None:
        """Why the unit should be started now, or None to leave it off.

        Two independent signals, because they answer different questions: the
        bedroom being hot means it is already uncomfortable, the house average
        being hot means it is about to be. Both are gated on the outdoor reading,
        so a cool day never triggers a start.
        """
        if self._day_start_done_on == now.date():
            return None
        guard = float(
            self._cfg(CONF_AUTO_START_OUTDOOR, DEFAULT_AUTO_START_OUTDOOR) or 0.0
        )
        if guard > 0 and (outdoor is None or outdoor < guard):
            return None

        soglia_stanza = float(
            self._cfg(CONF_AUTO_START_ROOM, DEFAULT_AUTO_START_ROOM) or 0.0
        )
        if soglia_stanza > 0 and room is not None and room >= soglia_stanza:
            return f"stanza {room:.1f} oltre {soglia_stanza:.1f}"

        soglia_casa = float(
            self._cfg(CONF_AUTO_START_HOUSE, DEFAULT_AUTO_START_HOUSE) or 0.0
        )
        if soglia_casa > 0:
            casa = self._house_average()
            if casa is not None and casa >= soglia_casa:
                return f"casa {casa:.1f} oltre {soglia_casa:.1f}"
        return None

    def _vane_day_due(self, now: datetime) -> bool:
        """Whether the vanes still have to be put back for the day."""
        return self._vane_restored_on != now.date()

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

    def _morning_off_window_closed(self, now: datetime) -> bool:
        """Whether the morning switch-off has had its say and is behind us.

        The only reason the daytime start waits at all: without it, the unit could
        be switched off at 08:30 and started again at 08:31 by the very same house
        average that was already above threshold - a pointless switch-off, and a
        compressor stopped and restarted inside a minute.
        """
        if not self._morning_off_enabled():
            # Nessuno spegnimento del mattino: non c'e' finestra da attendere.
            return True
        start = _parse_time(
            self._cfg(CONF_MORNING_OFF_START, DEFAULT_MORNING_OFF_START),
            DEFAULT_MORNING_OFF_START,
        )
        chiusura = now.replace(
            hour=start.hour, minute=start.minute, second=0, microsecond=0
        ) + timedelta(minutes=MORNING_OFF_WINDOW_MINUTES)
        return now >= chiusura

    def _sleep_boost_active(self, now: datetime) -> bool:
        """The opening minutes of the sleep window, where the fan goes to `high`.

        Read from the clock rather than from a remembered transition, so a restart
        at 23:05 still knows the boost is running - and, just as important, one at
        01:00 knows it is long over.
        """
        if SLEEP_BOOST_MINUTES <= 0:
            return False
        start = _parse_time(
            self._cfg(CONF_SLEEP_START, DEFAULT_SLEEP_START), DEFAULT_SLEEP_START
        )
        elapsed = (now.hour * 60 + now.minute) - (start.hour * 60 + start.minute)
        if elapsed < 0:
            # The window normally wraps around midnight (23:00 -> 07:30).
            elapsed += 24 * 60
        return elapsed < SLEEP_BOOST_MINUTES

    def _boost_fan(self, delta: float | None, fan_modes: list | None, now: datetime) -> str | None:
        """`high` while the boost lasts, or None to leave the decision to the bands."""
        if delta is None or delta < SLEEP_BOOST_MIN_DELTA:
            return None
        if fan_modes and "high" not in fan_modes:
            return None
        if self._last_fan_band != "high":
            self._last_fan_band = "high"
            self._last_fan_band_at = now
        return "high"

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
        hysteresis: tuple[float, float] = (FAN_HYSTERESIS_UP, FAN_HYSTERESIS_DOWN),
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
                    and delta < _band_threshold(wanted, bands) + hysteresis[0]
                ):
                    wanted = available[available.index(wanted) - 1]
            else:
                hold = delta > _band_threshold(reference, bands) - hysteresis[1]
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
        self._trim_probe_age(now)
        phase = self._phase(now)
        if phase in (PHASE_SLEEP, PHASE_WIND_DOWN):
            self._clear_trim_probe()
        climate = self.hass.states.get(self.climate_entity)
        if climate is None or climate.state in _UNAVAILABLE:
            # Clear the diagnostics too: leaving them frozen on the last pass made
            # the sensors advertise a phase and a target we are no longer chasing.
            self.current_phase = None
            self.active_target = None
            return Desired(reason="clima non disponibile")

        cur_mode = climate.state
        cooling_active = cur_mode in (HVAC_COOL, HVAC_DRY)
        # Il giudizio sulla deumidificazione rispecchia la macchina, non si
        # accumula. `_program_for` e' l'unico posto che azzerava `_dry_active`, e
        # non viene raggiunto quando l'unita' e' spenta, in `gap`, in `wind_down`,
        # fuori stagione o a riposo: il flag restava acceso per ore e alla
        # riaccensione faceva usare la soglia d'USCITA (55) al posto di quella
        # d'INGRESSO (60). Osservato il 22 agosto 2026: rientro in `dry` con
        # umidita' al 56%. Le due soglie servono a non ballare **dentro** un ciclo
        # continuo, non a portarsi dietro la decisione di dodici ore prima.
        #
        # Si azzera a macchina **ferma**, non "quando non e' gia' in dry": fra il
        # comando e il momento in cui l'unita' lo esegue passano delle passate in
        # cui lo stato riportato e' ancora `cool`, e azzerare li' impedirebbe alla
        # deumidificazione di entrare del tutto. Le prove lo hanno dimostrato.
        if not cooling_active:
            self._dry_active = False
        climate_unit = self._system_temperature_unit
        ripresa = _convert_temperature(
            _to_float(climate.attributes.get("current_temperature")),
            climate_unit,
            UnitOfTemperature.CELSIUS,
        )
        # L'aria di ripresa passa dal vaglio di plausibilita' come tutti gli altri
        # termometri: un glitch numerico dal cloud (assurdo o NaN) non deve entrare
        # in delta, eco e saturazione. Senza, un NaN portava la ventola a `low`.
        room = (
            ripresa
            if ripresa is not None and math.isfinite(ripresa) and _plausible(ripresa)
            else None
        )
        comodino = self._read_bedside()
        outdoor, outdoor_valid = self._read_outdoor()

        if outdoor_valid:
            summer = (
                outdoor > self.summer_threshold
                or (
                    cooling_active
                    and outdoor > self.summer_threshold - SUMMER_HYSTERESIS
                )
            )
            summer = self._season_confirmed(summer, now)
        else:
            # Outdoor sensors unavailable: fail closed. We may maintain a cooling
            # cycle already in progress, but never start one from an indoor-only
            # reading that could actually be caused by winter heating.
            summer = cooling_active

        if self.mode == MODE_OFF:
            self.current_phase = None
            self.active_target = None
            return Desired(hvac=HVAC_OFF, reason="modo Spento")

        # Da qui in poi c'e' un solo percorso: fasce orarie, guardie di stagione, e
        # le decisioni prese dai sensori.
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

        # Mattina fresca: simmetrico alla guardia dell'avvio diurno, ma per una
        # macchina gia' accesa - dalla notte fonda, o perche' l'utente l'ha
        # riaccesa a mano. Se quella mattina non fa abbastanza caldo per
        # giustificare l'anello di giorno, si spegne; _day_start_due la fara'
        # ripartire da sola piu' tardi lo stesso giorno se l'esterna sale sopra
        # soglia, perche' questo ramo non tocca il suo contrassegno.
        if (
            cur_mode in (HVAC_COOL, HVAC_DRY)
            and self._morning_cool_off_due(now, outdoor)
        ):
            # Marcato solo quando lo spegnimento e' andato a segno davvero, in
            # async_evaluate: stessa cautela dello spegnimento del mattino.
            self._morning_cool_off_armed = True
            self.active_target = None
            return Desired(
                hvac=HVAC_OFF, reason="smart: mattina fresca, non serve raffrescare"
            )

        if not summer:
            if cooling_active:
                self.active_target = None
                return Desired(
                    hvac=HVAC_OFF, reason="fuori stagione: spengo raffrescamento"
                )
            soglia_avvio = float(
                self._cfg(CONF_WINTER_ROOM_START, DEFAULT_WINTER_ROOM_START) or 0.0
            )
            target_inverno = float(
                self._cfg(CONF_WINTER_ROOM_TARGET, DEFAULT_WINTER_ROOM_TARGET) or 0.0
            )
            if soglia_avvio <= 0 or target_inverno <= 0 or target_inverno <= soglia_avvio:
                # Aiuto invernale non configurato (o soglie incrociate/uguali,
                # che farebbero accendere e spegnere il compressore a ogni
                # passata): comportamento di sempre.
                self.active_target = None
                self._winter_heating = False
                return Desired(reason="fuori stagione: non tocco il riscaldamento")
            in_sonno = phase in (PHASE_SLEEP, PHASE_WIND_DOWN)
            if in_sonno:
                # Il sonno resta escluso: un ciclo gia' avviato si interrompe
                # se la notte fonda entra prima del tetto, non aspetta - per
                # questo qui si spegne attivamente, non ci si limita a
                # smettere di seguirlo (hvac=None lascerebbe la pompa di
                # calore accesa e incustodita per tutta la notte).
                self.active_target = None
                self._winter_heating = False
                if cur_mode == HVAC_HEAT:
                    return Desired(
                        hvac=HVAC_OFF,
                        reason="fuori stagione: entra il sonno, mi fermo",
                    )
                return Desired(
                    reason="fuori stagione: non tocco il riscaldamento (sonno)"
                )
            if room is None:
                # Sensore assente: non ne parte uno nuovo, ma non si
                # interrompe nemmeno un ciclo gia' in corso su un dato
                # transitorio mancante - stessa cautela della guardia
                # sull'esterna qui sopra.
                self.active_target = None
                return Desired(reason="fuori stagione: non tocco il riscaldamento")
            if self._winter_heating:
                self._winter_heating = room < target_inverno
            else:
                tetto_casa = float(
                    self._cfg(CONF_WINTER_HOUSE_CEILING, DEFAULT_WINTER_HOUSE_CEILING)
                    or 0.0
                )
                casa = self._house_average()
                # Fail closed: un tetto configurato senza una media di casa
                # leggibile blocca la partenza, non la lascia passare.
                casa_libera = tetto_casa <= 0 or (
                    casa is not None and casa < tetto_casa
                )
                self._winter_heating = room < soglia_avvio and casa_libera
            if not self._winter_heating:
                self.active_target = None
                if cur_mode == HVAC_HEAT:
                    return Desired(
                        hvac=HVAC_OFF, reason="inverno: camera al tetto, mi fermo"
                    )
                return Desired(reason="fuori stagione: non tocco il riscaldamento")
            self.active_target = self._reachable_target(target_inverno, climate)
            return Desired(
                hvac=HVAC_HEAT,
                setpoint=target_inverno,
                reason=f"inverno: aiuto i caloriferi, target {target_inverno}",
            )

        self._winter_heating = False

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

        fuori = self._fuori_casa()
        # La notte fonda vera - target piu' freddo e spinta iniziale della ventola -
        # vale solo se sono a casa. Fuori, in fascia sleep, il clima resta nel regime
        # di comfort di prima (come la fascia notte fino alle 23:30): niente crollo a
        # target_sleep, niente spinta, fasce ventola normali. Non ha senso inseguire i
        # gradi e spingere la ventola per una stanza vuota. Al rientro riprende da solo.
        notte_fonda = phase == PHASE_SLEEP and not fuori
        passo = _to_float(climate.attributes.get("target_temp_step"))
        casa = self._house_average()
        trim = None
        compensazione = 0.0
        if phase == PHASE_WIND_DOWN or notte_fonda:
            # Di notte la porta e' chiusa: la casa esce dal quadro e comanda la
            # camera, con il suo target. Anche la prova diurna esce dal quadro:
            # conservarla fino al giorno dopo la trasformerebbe in una misura di
            # ore invece che dei tre quarti d'ora per cui e' stata aperta.
            self._clear_trim_probe()
            target = self._sleep_target(outdoor)
        elif phase == PHASE_SLEEP:
            # Fascia notte fonda ma sono fuori: la salto. Non il freddo profondo, ma
            # nemmeno l'anello di giorno - quello spinge la camera piu' in basso per
            # raffreddare le altre stanze, l'ultima cosa da fare per una casa vuota.
            # Solo comfort: il target fisso col ritocco sull'esterna, come la fascia
            # notte prima delle 23:30. Al rientro riprende la notte fonda vera.
            self._clear_trim_probe()
            target = self.target_home
            compensazione = self._adaptive_extra(outdoor, now, passo)
            target += compensazione
        else:
            # Di giorno comanda la linea di comfort delle altre stanze, e la camera
            # e' lo strumento per ottenerla.
            trim = self._house_trim(
                now, casa, passo, comodino, outdoor, room
            )
            if trim is not None:
                target = trim
                # L'adattivo qui non si applica, e non e' una dimenticanza: alza il
                # target quando fuori fa caldo, cioe' fa il contrario dell'obiettivo
                # proprio nelle ore in cui la casa fatica di piu'.
            else:
                target = self.target_home
                compensazione = self._adaptive_extra(outdoor, now, passo)
                target += compensazione
        self.active_target = self._reachable_target(target, climate)

        # Notte fredda: sotto night_start_outdoor la media esterna/comodino puo'
        # dire che la stanza e' gia' al target di notte fonda mentre l'aria di
        # ripresa legge ancora caldo. In quel caso la macchina riposa - non e'
        # un'eccezione alla regola "non spengo mai mio conto": e' la stessa
        # regola letta al contrario di quella della mattina fresca qui sopra.
        freddo = notte_fonda and self._cold_night_off(outdoor, comodino, target)
        if not notte_fonda:
            self._cold_night_resting = False
        if freddo and cur_mode in (HVAC_COOL, HVAC_DRY):
            self._cold_night_resting = True
            return Desired(
                hvac=HVAC_OFF,
                reason=f"smart {phase}: fuori sotto soglia, la camera riposa",
            )

        # MODE_SMART never starts the unit: the user decides when it runs, we
        # decide how it runs, and the only switch-off we do is the scheduled one.
        if cur_mode == HVAC_OFF:
            if notte_fonda and freddo:
                # Ancora sotto la soglia fredda: resto spento senza consumare il
                # tentativo unico dell'avvio serale, che deve restare libero per
                # quando (se) la notte fonda tornera' a chiederlo sul serio. Marco
                # comunque il riposo: anche se non ho mai acceso stanotte, il
                # rientro sopra soglia non deve dipendere dalla finestra
                # dell'avvio delle 23, che a quel punto puo' essere gia' chiusa.
                self._cold_night_resting = True
                return Desired(
                    reason=f"smart {phase}: fuori sotto soglia, resto spento"
                )
            # Si riparte per due motivi distinti: l'avvio della notte, se
            # l'utente l'ha chiesto e una volta sola, oppure il rientro dal
            # riposo per notte fredda, che non ha finestra oraria perche' puo'
            # capitare a qualunque ora - la temperatura non guarda l'orologio.
            # Se sono fuori la notte fonda non parte affatto: non accendo per
            # una stanza vuota.
            riparte_dal_riposo = notte_fonda and self._cold_night_resting
            if notte_fonda and (riparte_dal_riposo or self._sleep_start_due(now)):
                # La ripresa dal riposo per notte fredda non chiede il
                # permesso: non e' un avvio nuovo, e' il rientro da una pausa
                # decisa dal controller su un'unita' gia' accesa col consenso
                # dell'utente.
                if self._start_approval() and not riparte_dal_riposo:
                    self._start_reason = START_REASON_NIGHT
                    self._approval_armed = {
                        "motivo": f"notte fonda, target {target}",
                        "fase": phase,
                        "casa": casa,
                        "camera": room,
                        "esterna": outdoor,
                        "target": self._reachable_target(target, climate),
                    }
                    self.active_target = None
                    return Desired(
                        reason=f"smart {phase}: chiedo il permesso, notte fonda"
                    )
                self._sleep_start_armed = True
                self._start_reason = START_REASON_NIGHT
                self._cold_night_resting = False
                self.active_target = self._reachable_target(target, climate)
                scarto = (room - target) if room is not None else 0.0
                # L'avvio cade sempre dentro la spinta iniziale, e una stanza che
                # arriva dal target del giorno e' proprio il caso per cui esiste.
                # Al rientro dal riposo invece la stanza e' gia' al target: la
                # spinta non ha senso, bastano le bande normali.
                partenza = (
                    self._boost_fan(scarto, climate.attributes.get("fan_modes"), now)
                    if self._sleep_boost_active(now) and not riparte_dal_riposo
                    else None
                )
                motivo = (
                    "sopra la soglia fredda, riparto"
                    if riparte_dal_riposo
                    else f"avvio della notte, target {target}"
                )
                return Desired(
                    hvac=HVAC_COOL,
                    setpoint=target,
                    fan=partenza or _fan_band(scarto, FAN_BANDS_SLEEP),
                    reason=f"smart {phase}: {motivo}",
                )
            # Anche nella fascia fra lo spegnimento del mattino e l'inizio del
            # giorno: quell'attesa era un orario fisso ereditato dai valori
            # predefiniti, non una decisione. Dopo lo spegnimento decidono i
            # sensori, che e' il punto di tutto il modo adattivo.
            puo_partire = phase == PHASE_DAY or (
                phase == PHASE_GAP and self._morning_off_window_closed(now)
            )
            perche = (
                self._day_start_due(now, room, outdoor) if puo_partire else None
            )
            if perche is not None:
                if self._start_approval():
                    self._start_reason = START_REASON_DAY
                    self._approval_armed = {
                        "motivo": perche,
                        "fase": phase,
                        "casa": casa,
                        "camera": room,
                        "esterna": outdoor,
                        "target": self._reachable_target(target, climate),
                    }
                    self.active_target = None
                    return Desired(
                        reason=f"smart {phase}: chiedo il permesso, {perche}"
                    )
                self._sleep_start_armed = True
                self._start_reason = START_REASON_DAY
                self.active_target = self._reachable_target(target, climate)
                return Desired(
                    hvac=HVAC_COOL,
                    setpoint=target,
                    fan=_fan_band(
                        (room - target) if room is not None else 0.0, FAN_BANDS
                    ),
                    reason=f"smart {phase}: avvio, {perche}",
                )
            self.active_target = None
            return Desired(reason=f"smart {phase}: clima spento, non lo accendo io")

        delta = None if room is None else room - target
        humidity = self._read_humidity()
        hvac_modes = climate.attributes.get("hvac_modes")
        spinta = False
        scarto_ventola = None
        if phase == PHASE_WIND_DOWN:
            # L'ora prima dello spegnimento, in `cool` con la ventola su `auto`.
            #
            # Qui c'era `dry`, sull'idea che togliesse l'afa senza raffreddare oltre.
            # **Misurato il 5 agosto sull'energia dell'ora intera**, che e' il numero
            # che conta, e non sulla potenza istantanea:
            #
            #   02/08  dry   23.5 -> 24.5  (+1.0)  esterna 26.0   0.396 kWh
            #   05/08  cool  23.5 -> 24.5  (+1.0)  esterna 28.0   0.364 kWh
            #
            # Stessa partenza, stessa deriva della camera, due gradi in piu' fuori, e
            # ha speso meno. Il confronto e' su una sola mattina, ma e' pulito.
            program = HVAC_COOL
            fan = "auto"
        else:
            program = self._program_for(delta, humidity, hvac_modes)
            scarto_ventola = self._fan_delta(phase, room, target, compensazione)
            spinta = notte_fonda and self._sleep_boost_active(now)
            fan = (
                self._boost_fan(
                    scarto_ventola, climate.attributes.get("fan_modes"), now
                )
                if spinta
                else None
            )
            if fan is None:
                spinta = False
                fan = self._fan_for(
                    scarto_ventola,
                    climate.attributes.get("fan_mode"),
                    now,
                    climate.attributes.get("fan_modes"),
                    FAN_BANDS_SLEEP if notte_fonda else FAN_BANDS,
                    self._fan_hysteresis(phase),
                )
        if phase == PHASE_SLEEP:
            # Alette FISSE anche di notte, nella stessa posizione del giorno. Prima
            # era `swing` (vane_sleep_position): ma oscillando mescolavano l'aria e
            # il freddo non restava in basso dove si dorme, la camera risaliva e la
            # macchina faticava a riprendere i gradi dopo la spinta iniziale.
            # Tolto il 13 agosto 2026 su segnalazione dell'utente.
            alette_h = self._cfg(CONF_VANE_DAY_H, DEFAULT_VANE_DAY) or None
            alette_v = self._cfg(CONF_VANE_DAY_V, DEFAULT_VANE_DAY) or None
        elif phase in (PHASE_WIND_DOWN, PHASE_DAY) and self._vane_day_due(now):
            # Fine della notte: le alette tornano ferme, una volta sola. Anche in
            # PHASE_DAY, non solo in wind_down: con lo spegnimento del mattino
            # disattivato (morning_off_enabled=False) la fase wind_down non esiste
            # piu' e senza questo le alette restavano in swing tutto il giorno.
            alette_h = self._cfg(CONF_VANE_DAY_H, DEFAULT_VANE_DAY) or None
            alette_v = self._cfg(CONF_VANE_DAY_V, DEFAULT_VANE_DAY) or None
        else:
            alette_h = alette_v = None
        alette = alette_h
        detail = f"{program}, ventola {fan or 'invariata'}"
        if spinta:
            detail += " (spinta iniziale)"
        if trim is not None and casa is not None:
            linea = float(self._cfg(CONF_HOUSE_TARGET, DEFAULT_HOUSE_TARGET) or 0.0)
            detail += f", casa {casa:.1f} su linea {linea:.1f}"
        if compensazione:
            detail += f", +{compensazione:.1f} per esterna {outdoor:.0f}"
        if alette:
            detail += f", alette {alette}"
        if delta is not None:
            detail += f", scarto {delta:+.1f}"
        # Quale numero ha deciso la ventola: senza questo, in plancia non si
        # distingue una ventola che segue la casa da una che segue la ripresa.
        if scarto_ventola is not None and delta is not None and abs(scarto_ventola - delta) >= 0.05:
            detail += f", ventola su {scarto_ventola:+.1f}"
        if humidity is not None:
            detail += f", umidità {humidity:.0f}%"
        return Desired(
            hvac=program,
            setpoint=target,
            fan=fan,
            eco=self._eco_decision(room, target, outdoor),
            mute=is_night,
            night=is_night,
            vane_h=alette_h,
            vane_v=alette_v,
            reason=f"smart {phase}: target {target}, {detail}",
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
                # L'evento manuale arriva prima di questa passata. Se si torna
                # senza salvare, un riavvio dentro l'override rimette subito il
                # controller al comando. Un fallimento resta ritentabile perche'
                # `_stored` avanza soltanto dopo un salvataggio riuscito.
                await self._async_save_memoria()
                return

            now = dt_util.now()
            try:
                self._morning_off_armed = False
                self._sleep_start_armed = False
                self._morning_cool_off_armed = False
                self._approval_armed = None
                desired = self._compute(now)
                self._apply_errors.clear()
                await self._apply(desired)
                if self._morning_off_armed and not self._apply_errors:
                    # The switch-off went through: no second attempt today.
                    self._morning_off_done_on = now.date()
                if self._morning_cool_off_armed and not self._apply_errors:
                    self._morning_cool_off_done_on = now.date()
                    # Chi vuole avvisare di aprire le finestre ascolta questo.
                    self.hass.bus.async_fire(
                        EVENT_COOL_OFF, {"entity_id": self.climate_entity}
                    )
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
                if self._approval_armed is not None:
                    # Marcata come se l'avvio fosse avvenuto: e' cosi' che un
                    # silenzio o un no chiudono la giornata senza altro stato.
                    if self._start_reason == START_REASON_DAY:
                        self._day_start_done_on = now.date()
                    else:
                        self._sleep_start_done_on = now.date()
                    self.hass.bus.async_fire(
                        EVENT_APPROVAL_NEEDED,
                        {"entity_id": self.climate_entity, **self._approval_armed},
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
        # Fuori dal lock: salva solo se qualcosa si e' davvero mosso.
        await self._async_save_memoria()

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
                self._morning_cool_off_armed = False
                self._sleep_start_armed = False
                return
            # Treat the unit as already in the target mode for the rest of this pass.
            cur_mode = desired.hvac

        # 2) Setpoint. Cooling/dry and the winter heat-assist cycle all send one
        # (fan/eco below stay cooling-only: the winter spec leaves fan/vane
        # untouched, "start simple" until there is field data to justify more).
        # Snap the desired value to the climate's own step first (a unit that
        # quantizes, e.g. to whole degrees, would report back a value that never
        # equals ours and we would re-send at every pass); the small tolerance
        # absorbs float noise in the reported state. _last_setpoint_cmd stores the
        # snapped value, so the manual detection compares against what the device
        # will actually echo.
        # The offset shifts what the unit is asked for, never the target we aim
        # the room at: active_target and the eco decision keep using the real
        # goal, so the diagnostics do not start lying to compensate a machine.
        # It is calibrated for cooling overshoot on the return-air reading only:
        # no field data yet justifies applying it to the winter heat setpoint.
        if not hvac_blocked and desired.hvac in (HVAC_COOL, HVAC_DRY, HVAC_HEAT):
            want_set = desired.setpoint
            if want_set is not None and desired.hvac != HVAC_HEAT:
                want_set += self.setpoint_offset
            if want_set is not None:
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

        # Fan / eco only make sense while we intend the unit to cool or
        # dehumidify (MODE_SMART's `dry` still takes a fan step); the winter
        # heat-assist cycle above stops at the setpoint.
        if not hvac_blocked and desired.hvac in (HVAC_COOL, HVAC_DRY):
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
        # hvac mode (vedi il ramo `heat` di _compute).
        await self._apply_switch(CONF_MUTE_SWITCH, desired.mute)
        await self._apply_switch(CONF_NIGHT_SWITCH, desired.night)
        # Alette: chieste solo dentro la notte fonda, fuori restano dove sono.
        restore_vanes = (
            self.current_phase in (PHASE_WIND_DOWN, PHASE_DAY)
            and self._vane_day_due(now)
            and (desired.vane_h is not None or desired.vane_v is not None)
        )
        vane_h_done = await self._apply_select(CONF_VANE_H, desired.vane_h)
        vane_v_done = await self._apply_select(CONF_VANE_V, desired.vane_v)
        if restore_vanes and vane_h_done and vane_v_done:
            self._vane_restored_on = now.date()

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

    async def _apply_select(self, conf_key: str, wanted: str | None) -> bool:
        """Same discipline as _apply_switch, for an option-valued entity.

        Idempotent, respects the settle window and the unit's refusals, and leaves
        the entity alone when nothing is configured or the option is not offered.
        Returns True when no entity is configured, the target is already satisfied,
        or the requested option was applied successfully; returns False while a
        requested target remains incomplete.
        """
        if wanted is None:
            return True
        entity_id = self._cfg(conf_key)
        if not entity_id:
            return True
        st = self.hass.states.get(entity_id)
        if st is None or st.state in _UNAVAILABLE:
            return False
        opzioni = st.attributes.get("options")
        if opzioni and wanted not in opzioni:
            self._apply_errors.append(f"{conf_key}: posizione {wanted} non prevista")
            return False
        if st.state == wanted:
            return True
        now = dt_util.now()
        refused_at = self._aux_refused_at.get(conf_key)
        if (
            refused_at is not None
            and (now - refused_at).total_seconds() < AUX_REFUSAL_BACKOFF_SECONDS
        ):
            self._apply_errors.append(f"{conf_key}: rifiutato dall'unita', riprovo dopo")
            return False
        settle_until = self._settle_aux_until.get(conf_key)
        if (
            settle_until is not None
            and now < settle_until
            and self._last_aux_cmd.get(conf_key) == wanted
        ):
            return False
        if self._stopped or not self.enabled:
            return False
        had_prev = conf_key in self._last_aux_cmd
        prev = self._last_aux_cmd.get(conf_key)
        self._last_aux_cmd[conf_key] = wanted
        self._settle_aux_until[conf_key] = now + timedelta(
            seconds=COMMAND_SETTLE_SECONDS
        )
        if not await self._call_target(
            "select", "select_option", entity_id, {"option": wanted}
        ):
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
