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
CONF_PRESENCE_HOME_STATE = "presence_home_state"

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
DEFAULT_PRESENCE_HOME_STATE = "home"

# While the unit is already cooling, the season threshold drops by this much, so a
# cycle in progress is not cut off by a small dip in the outdoor reading.
SUMMER_HYSTERESIS = 2.0

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
# At night the fan never goes above this, whatever the gap says.
NIGHT_MAX_FAN = "medium"
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
# Above this gap the room needs cooling, not dehumidifying.
DRY_MAX_DELTA = 1.0

# --- Day phases (only meaningful in MODE_AUTO) ---
PHASE_DAY = "day"
PHASE_NIGHT = "night"
PHASE_GAP = "gap"

# HVAC constants we rely on (kept as literals to avoid importing climate internals).
HVAC_COOL = "cool"
HVAC_HEAT = "heat"
HVAC_OFF = "off"
HVAC_DRY = "dry"

# hass.data storage key
DATA_CONTROLLER = "controller"
