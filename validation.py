"""Pure validation rules, deliberately free of Home Assistant and voluptuous.

The config flow and the number entities both need these checks, and keeping them
here means they can be exercised without a Home Assistant install: everything in
this module is plain Python and returns error keys that exist in `translations/`.
"""

from __future__ import annotations

from typing import Any

from .const import (
    CONF_DAY_START,
    CONF_ECO_OUTDOOR_OFF,
    CONF_ECO_OUTDOOR_ON,
    CONF_ECO_SWITCH,
    CONF_MORNING_OFF_START,
    CONF_MUTE_SWITCH,
    CONF_NIGHT_START,
    CONF_NIGHT_SWITCH,
    CONF_PRESENCE_HOME_STATE,
    CONF_SLEEP_END,
    CONF_SLEEP_START,
)


def time_to_minutes(value: Any) -> int:
    """'HH:MM[:SS]' to minutes since midnight."""
    hh, mm = str(value).split(":")[:2]
    return int(hh) * 60 + int(mm)


def aux_switches_are_distinct(values: dict[str, Any]) -> bool:
    """Prevent two logical features from fighting over the same real switch."""
    selected = [
        values.get(key)
        for key in (CONF_ECO_SWITCH, CONF_MUTE_SWITCH, CONF_NIGHT_SWITCH)
        if values.get(key)
    ]
    return len(selected) == len(set(selected))


def normalise_presence_state(value: Any) -> str:
    return str(value).strip()


def validate_options(values: dict[str, Any]) -> str | None:
    """Return the translation key of the first broken rule, or None.

    Order matters only for which message the user sees first; each rule is
    independent.
    """
    morning = time_to_minutes(values[CONF_MORNING_OFF_START])
    day = time_to_minutes(values[CONF_DAY_START])
    night = time_to_minutes(values[CONF_NIGHT_START])
    if not (morning < day < night):
        return "invalid_time_order"

    sleep_start = time_to_minutes(values[CONF_SLEEP_START])
    sleep_end = time_to_minutes(values[CONF_SLEEP_END])
    if sleep_start == sleep_end:
        # A zero-length window would silently disable the sleep target.
        return "invalid_sleep_window"
    if sleep_end >= morning:
        # The wind-down phase is "sleep_end <= t < morning_off": with the two
        # crossed it can never happen, and worse, the morning switch-off falls
        # inside the sleep window where it is never even looked for, so the unit
        # would keep cooling all day.
        return "invalid_wind_down"

    if values[CONF_ECO_OUTDOOR_ON] >= values[CONF_ECO_OUTDOOR_OFF]:
        # _eco_decision checks the "on" condition first: a swapped or equal pair
        # makes the "off" branch unreachable and eco gets stuck on.
        return "invalid_eco_range"

    if not normalise_presence_state(values[CONF_PRESENCE_HOME_STATE]):
        # An empty string never equals a tracker state, so the controller would
        # silently use the away target forever.
        return "invalid_presence_state"

    return None
