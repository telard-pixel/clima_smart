"""Constants for the Clima Smart integration."""

from __future__ import annotations

DOMAIN = "clima_smart"

PLATFORMS: list[str] = ["switch", "select", "number", "sensor"]

# --- Config-entry data keys (set once in the config flow) ---
CONF_CLIMATE = "climate_entity"
CONF_PRESENCE = "presence_entity"
CONF_OUTDOOR = "outdoor_sensor"
CONF_OUTDOOR_FALLBACK = "outdoor_fallback_sensor"
CONF_ECO_SWITCH = "eco_switch"
CONF_MUTE_SWITCH = "mute_switch"
CONF_NIGHT_SWITCH = "night_switch"
# Optional indoor humidity source, only used by MODE_SMART to pick the `dry`
# program. Left empty the mode still works, it just never dehumidifies.
CONF_HUMIDITY = "humidity_sensor"

# --- Option keys (tunable at runtime via the options flow / number / select) ---
CONF_TARGET_HOME = "target_home"
CONF_TARGET_AWAY = "target_away"
CONF_ECO_BAND = "eco_band"
CONF_ECO_OUTDOOR_ON = "eco_outdoor_on"
CONF_ECO_OUTDOOR_OFF = "eco_outdoor_off"
CONF_SUMMER_THRESHOLD = "summer_threshold"
CONF_OVERRIDE_MINUTES = "override_minutes"
CONF_DAY_START = "day_start"
CONF_NIGHT_START = "night_start"
CONF_MORNING_OFF_START = "morning_off_start"
# Deep-night window: same quiet behaviour as the night phase, but its own colder
# target. Crosses midnight, so the end is earlier than the start.
CONF_TARGET_SLEEP = "target_sleep"
CONF_SLEEP_START = "sleep_start"
CONF_SLEEP_END = "sleep_end"
CONF_PRESENCE_HOME_STATE = "presence_home_state"
# Split units read the return air, not the room, and stop short: measured here the
# room settled 0.5-1.0 above a 25.0 setpoint. This shifts what we send to the unit
# without touching the target we aim the room at, so the diagnostics stay honest.
CONF_SETPOINT_OFFSET = "setpoint_offset"
# MODE_SMART normally never starts the unit. With this on, and only at the opening
# of the sleep window, it may: one attempt per night, so that switching the climate
# off later in the night is not undone at the next pass.
CONF_AUTO_START_SLEEP = "auto_start_sleep"
# Daytime start: the room temperature at which the controller switches the unit on
# by itself, once a day. Zero disables it. This is a real start - the room has got
# hot and someone has to close the windows - while the evening one is just the
# night schedule beginning.
CONF_AUTO_START_ROOM = "auto_start_room"

# --- Defaults (validated values from the original automation) ---
DEFAULT_TARGET_HOME = 26.0
DEFAULT_TARGET_AWAY = 27.0
DEFAULT_ECO_BAND = 2.0
DEFAULT_ECO_OUTDOOR_ON = 33.0
DEFAULT_ECO_OUTDOOR_OFF = 34.0
DEFAULT_SUMMER_THRESHOLD = 21.0
DEFAULT_OVERRIDE_MINUTES = 60
DEFAULT_DAY_START = "10:00:00"
DEFAULT_NIGHT_START = "22:00:00"
DEFAULT_MORNING_OFF_START = "08:00:00"
DEFAULT_TARGET_SLEEP = 23.0
DEFAULT_SLEEP_START = "23:30:00"
DEFAULT_SLEEP_END = "07:30:00"
DEFAULT_SETPOINT_OFFSET = 0.0
DEFAULT_AUTO_START_SLEEP = False
DEFAULT_AUTO_START_ROOM = 0.0
DEFAULT_PRESENCE_HOME_STATE = "home"

# While the unit is already cooling, the season threshold drops by this much, so a
# cycle in progress is not cut off by a small dip in the outdoor reading.
SUMMER_HYSTERESIS = 2.0

# How long async_start waits for the master switch and the mode select to restore
# before opening the barrier in degraded mode.
RESTORE_TIMEOUT_SECONDS = 10

# Periodic re-evaluation cadence (event-driven updates happen on top of this).
UPDATE_INTERVAL_SECONDS = 300
# After we send a command, ignore "manual override" detection for this long so the
# cloud round-trip catching up to our value is not mistaken for a user action.
# 180s gives ~2-3x margin over the typical Haier cloud latency (10-60s).
COMMAND_SETTLE_SECONDS = 180
# Hard cap on a single climate/switch service call. A hung Haier cloud must not
# block the control loop nor the lock-drain in async_stop (unload) indefinitely;
# on timeout the call is treated as failed and retried on the next pass.
SERVICE_CALL_TIMEOUT_SECONDS = 60

# --- Operating modes (the "Modo" select) ---
MODE_AUTO = "auto"
MODE_COMFORT = "comfort"
MODE_AWAY = "away"
MODE_NIGHT = "night"
MODE_OFF = "off"
# Fixed target (never the away one) plus the day/night phases, and on top of that
# the fan step and the program are driven by indoor/outdoor readings instead of
# being pinned to "auto".
MODE_SMART = "smart"
MODES: list[str] = [
    MODE_SMART,
    MODE_AUTO,
    MODE_COMFORT,
    MODE_AWAY,
    MODE_NIGHT,
    MODE_OFF,
]

# --- MODE_SMART: fan steps by how far the room still is above target ---
# Read as: 2 degrees or more above -> high, 1 or more -> medium, otherwise low.
FAN_BANDS: tuple[tuple[float, str], ...] = (
    (2.0, "high"),
    (1.0, "medium"),
    (0.0, "low"),
)
# Increasing order, used to compare two steps and to cap the night one.
FAN_ORDER: tuple[str, ...] = ("low", "medium", "high")
# A downgrade needs the gap to be this far inside the lower band, and this many
# seconds since the last change: without both, a tenth of a degree of noise in
# the reported temperature would cycle the fan up and down forever.
FAN_HYSTERESIS = 0.3
MIN_FAN_DWELL_SECONDS = 600

# --- MODE_SMART: `dry` program, only with a humidity sensor configured ---
# Muggy but already at temperature: dehumidifying is what actually helps, and it
# draws less than compressor cooling. Two thresholds, again to avoid flapping.
DRY_HUMIDITY_ON = 60.0
DRY_HUMIDITY_OFF = 55.0
# Above this gap the room needs cooling, not dehumidifying. The second value is
# the extra slack before leaving dry, so the program does not swap back and
# forth while the reported temperature sits on the threshold.
DRY_MAX_DELTA = 1.0
DRY_DELTA_HYSTERESIS = 0.5

# --- Day phases (only meaningful in MODE_AUTO / MODE_SMART) ---
PHASE_DAY = "day"
PHASE_NIGHT = "night"
PHASE_GAP = "gap"
# Inside the night, the stretch where the colder sleep target applies.
PHASE_SLEEP = "sleep"
# Between the end of the sleep window and the morning switch-off: keep holding the
# night target, but at the lowest fan step.
PHASE_WIND_DOWN = "wind_down"

# --- MODE_SMART, sleep window: only two steps, and never `high` ---
# Medium until the room reaches the night target, then low to hold it.
FAN_BANDS_SLEEP: tuple[tuple[float, str], ...] = ((0.3, "medium"), (0.0, "low"))
# The morning switch-off is a one-shot, not a state to enforce: outside this many
# minutes past its time it is not attempted at all, so a restart later in the
# morning cannot switch off a unit the user has just turned back on.
MORNING_OFF_WINDOW_MINUTES = 30
# Same idea for the evening start: one attempt inside this window after
# sleep_start, so a climate switched off at 01:00 stays off.
SLEEP_START_WINDOW_MINUTES = 30

# Fired when the controller starts the unit by itself, so an automation can
# announce it. Data: entity_id, target, phase, and `motivo`, which tells the two
# apart: "giorno" is the room getting hot, "notte" is the schedule beginning.
EVENT_STARTED = "clima_smart_avviato"
START_REASON_DAY = "giorno"
START_REASON_NIGHT = "notte"

# Measured twice on this unit: an aux switch we just turned on comes back to its
# previous value about 60-70 s later, with no user context, when the unit does not
# accept it (mute, then eco, both while a fan step was forced). After such a
# refusal the switch is left alone for this long instead of being re-commanded at
# every pass.
AUX_REFUSAL_BACKOFF_SECONDS = 1800

# HVAC constants we rely on (kept as literals to avoid importing climate internals).
HVAC_COOL = "cool"
HVAC_HEAT = "heat"
HVAC_OFF = "off"
HVAC_DRY = "dry"

# hass.data storage key
DATA_CONTROLLER = "controller"
