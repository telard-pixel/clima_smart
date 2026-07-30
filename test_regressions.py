"""Lightweight regression tests for controller logic without a full HA install."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import importlib
from pathlib import Path
import sys
import types
import unittest


NOW = datetime.now().astimezone()


def _install_ha_stubs() -> None:
    ha = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    config_entries.ConfigEntryError = RuntimeError
    const = types.ModuleType("homeassistant.const")
    const.UnitOfTemperature = types.SimpleNamespace(CELSIUS="°C")
    core = types.ModuleType("homeassistant.core")
    core.Event = object
    core.HomeAssistant = object
    core.callback = lambda func: func
    helpers = types.ModuleType("homeassistant.helpers")
    event = types.ModuleType("homeassistant.helpers.event")
    event.async_call_later = lambda *args, **kwargs: lambda: None
    event.async_track_state_change_event = lambda *args, **kwargs: lambda: None
    event.async_track_time_interval = lambda *args, **kwargs: lambda: None
    util = types.ModuleType("homeassistant.util")
    dt = types.ModuleType("homeassistant.util.dt")
    dt.now = lambda: NOW
    util.dt = dt
    unit_conversion = types.ModuleType("homeassistant.util.unit_conversion")

    class TemperatureConverter:
        @staticmethod
        def convert(value, from_unit, to_unit):
            if from_unit == to_unit:
                return value
            if from_unit == "°F" and to_unit == "°C":
                return (value - 32) * 5 / 9
            if from_unit == "°C" and to_unit == "°F":
                return value * 9 / 5 + 32
            raise ValueError("unsupported unit")

    unit_conversion.TemperatureConverter = TemperatureConverter
    sys.modules.update(
        {
            "homeassistant": ha,
            "homeassistant.config_entries": config_entries,
            "homeassistant.const": const,
            "homeassistant.core": core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.event": event,
            "homeassistant.util": util,
            "homeassistant.util.dt": dt,
            "homeassistant.util.unit_conversion": unit_conversion,
        }
    )


_install_ha_stubs()
package = types.ModuleType("clima_smart")
package.__path__ = [str(Path(__file__).parent)]
sys.modules["clima_smart"] = package
controller_module = importlib.import_module("clima_smart.controller")


class Context:
    def __init__(self, user_id=None):
        self.user_id = user_id


class State:
    def __init__(self, state, attributes=None, user_id=None):
        self.state = state
        self.attributes = attributes or {}
        self.context = Context(user_id)


class Event:
    def __init__(self, old, new):
        self.data = {"old_state": old, "new_state": new}


class Entry:
    entry_id = "test"

    def __init__(self, data=None, options=None):
        self.data = data or {"climate_entity": "climate.test"}
        self.options = options or {}
        self.tasks: list[str] = []

    def async_create_background_task(self, hass, coro, name):
        """Record the scheduled pass; close the coroutine so nothing runs."""
        self.tasks.append(name)
        coro.close()


class States:
    def __init__(self, values):
        self.values = values

    def get(self, entity_id):
        return self.values.get(entity_id)


class Hass:
    def __init__(self, states=None):
        self.states = States(states or {})
        self.config = types.SimpleNamespace(
            units=types.SimpleNamespace(temperature_unit="°C")
        )


def make_controller(states=None, data=None):
    ctrl = controller_module.ClimaSmartController(Hass(states), Entry(data))
    ctrl.enabled = True
    return ctrl


class ControllerRegressionTests(unittest.TestCase):
    def test_direct_user_change_wins_during_settle(self):
        ctrl = make_controller()
        ctrl._settle_setpoint_until = NOW + timedelta(seconds=60)
        ctrl._maybe_flag_manual(
            Event(
                State("cool", {"temperature": 25}),
                State("cool", {"temperature": 26}, user_id="user"),
            )
        )
        self.assertTrue(ctrl.override_active)

    def test_contextless_cloud_echo_is_ignored_during_settle(self):
        ctrl = make_controller()
        ctrl._last_setpoint_cmd = 26
        ctrl._settle_setpoint_until = NOW + timedelta(seconds=60)
        ctrl._maybe_flag_manual(
            Event(
                State("cool", {"temperature": 25}),
                State("cool", {"temperature": 26}),
            )
        )
        self.assertFalse(ctrl.override_active)

    def test_divergent_contextless_change_wins_during_settle(self):
        ctrl = make_controller()
        ctrl._last_setpoint_cmd = 26
        ctrl._settle_setpoint_until = NOW + timedelta(seconds=60)
        ctrl._maybe_flag_manual(
            Event(
                State("cool", {"temperature": 25}),
                State("cool", {"temperature": 22}),
            )
        )
        self.assertTrue(ctrl.override_active)

    def test_hvac_echo_may_materialize_setpoint_and_fan(self):
        ctrl = make_controller()
        ctrl._last_hvac_cmd = "cool"
        ctrl._settle_hvac_until = NOW + timedelta(seconds=60)
        ctrl._maybe_flag_manual(
            Event(
                State("off", {"temperature": None, "fan_mode": None}),
                State("cool", {"temperature": 24, "fan_mode": "auto"}),
            )
        )
        self.assertFalse(ctrl.override_active)

    def test_stale_last_command_does_not_hide_manual_change(self):
        ctrl = make_controller()
        ctrl._last_setpoint_cmd = 26
        ctrl._settle_setpoint_until = NOW - timedelta(seconds=1)
        ctrl._maybe_flag_manual(
            Event(
                State("cool", {"temperature": 25}),
                State("cool", {"temperature": 26}),
            )
        )
        self.assertTrue(ctrl.override_active)

    def test_manual_fan_change_starts_override(self):
        ctrl = make_controller()
        ctrl._maybe_flag_manual(
            Event(
                State("cool", {"fan_mode": "auto"}),
                State("cool", {"fan_mode": "low"}),
            )
        )
        self.assertTrue(ctrl.override_active)

    def test_unavailable_presence_keeps_last_known_value(self):
        data = {
            "climate_entity": "climate.test",
            "presence_entity": "person.test",
        }
        ctrl = make_controller({"person.test": State("home")}, data)
        self.assertTrue(ctrl._is_home())
        ctrl.hass.states.values["person.test"] = State("unavailable")
        self.assertTrue(ctrl._is_home())

    def test_failed_hvac_call_clears_settle_window(self):
        ctrl = make_controller(
            {"climate.test": State("off", {"temperature": 25})}
        )

        async def fail_call(*args, **kwargs):
            return False

        ctrl._call = fail_call
        asyncio.run(
            ctrl._apply(controller_module.Desired(hvac="cool", setpoint=25))
        )
        self.assertIsNone(ctrl._settle_hvac_until)

    def test_master_off_during_hvac_call_stops_followup_commands(self):
        ctrl = make_controller(
            {
                "climate.test": State(
                    "off",
                    {
                        "temperature": 24,
                        "temperature_unit": "°C",
                        "hvac_modes": ["off", "cool"],
                    },
                )
            }
        )
        ctrl.enabled = True
        calls = []

        async def turn_off_during_first_call(domain, service, data):
            calls.append(service)
            ctrl.enabled = False
            return True

        ctrl._call = turn_off_during_first_call
        asyncio.run(
            ctrl._apply(
                controller_module.Desired(
                    hvac="cool", setpoint=26, fan="auto"
                )
            )
        )
        self.assertEqual(calls, ["set_hvac_mode"])

    def test_restore_barrier_needs_both_entities(self):
        ctrl = make_controller()
        ctrl.mark_restore_ready("master")
        self.assertFalse(ctrl._restore_event.is_set())
        ctrl.mark_restore_ready("mode")
        self.assertTrue(ctrl._restore_event.is_set())

    def test_evaluate_is_blocked_until_restore_is_complete(self):
        ctrl = make_controller()
        asyncio.run(ctrl.async_evaluate("evento anticipato"))
        self.assertEqual(ctrl.last_reason, "attendo ripristino entità master/modo")

    def test_outdoor_missing_never_starts_cooling(self):
        climate = State(
            "off",
            {
                "current_temperature": 30,
                "temperature_unit": "°C",
                "hvac_modes": ["off", "cool"],
            },
        )
        ctrl = make_controller({"climate.test": climate})
        ctrl.enabled = True
        desired = ctrl._compute(NOW)
        self.assertIsNone(desired.hvac)

    def test_fahrenheit_room_is_converted_for_decisions(self):
        climate = State(
            "cool",
            {
                "current_temperature": 77,
                "temperature_unit": "°F",
                "hvac_modes": ["off", "cool"],
            },
        )
        ctrl = make_controller({"climate.test": climate})
        ctrl.hass.config.units.temperature_unit = "°F"
        ctrl.mode = "comfort"
        desired = ctrl._compute(NOW)
        self.assertEqual(desired.setpoint, ctrl.target_home)

    def test_linked_entity_change_requires_reload(self):
        ctrl = make_controller()
        self.assertFalse(ctrl.config_data_changed)
        ctrl.entry.data = {"climate_entity": "climate.other"}
        self.assertTrue(ctrl.config_data_changed)

    def test_unsupported_hvac_still_updates_mute_and_night(self):
        """An hvac mode the unit lacks must not freeze muto/notte on the old phase."""
        data = {
            "climate_entity": "climate.test",
            "mute_switch": "switch.mute",
            "night_switch": "switch.night",
        }
        ctrl = make_controller(
            {
                "climate.test": State("off", {"hvac_modes": ["off", "heat"]}),
                "switch.mute": State("off"),
                "switch.night": State("off"),
            },
            data,
        )
        calls = []

        async def record(domain, service, entity_id, data=None):
            calls.append((service, entity_id))
            return True

        ctrl._call_target = record
        asyncio.run(
            ctrl._apply(
                controller_module.Desired(
                    hvac="cool", setpoint=25, mute=True, night=True
                )
            )
        )
        self.assertEqual(
            calls, [("turn_on", "switch.mute"), ("turn_on", "switch.night")]
        )
        self.assertTrue(
            any("non supportata" in err for err in ctrl._apply_errors), ctrl._apply_errors
        )

    def test_diagnostics_cleared_when_climate_unavailable(self):
        ctrl = make_controller({"climate.test": State("unavailable")})
        ctrl.current_phase = "day"
        ctrl.active_target = 26.0
        desired = ctrl._compute(NOW)
        self.assertEqual(desired.reason, "clima non disponibile")
        self.assertIsNone(ctrl.current_phase)
        self.assertIsNone(ctrl.active_target)

    def test_half_degree_setpoint_rounds_up_not_to_even(self):
        attrs = {"min_temp": 16.0, "max_temp": 30.0, "target_temp_step": 1.0}
        snap = controller_module._snap_setpoint
        self.assertEqual(snap(25.5, attrs), 26.0)
        self.assertEqual(snap(16.5, attrs), 17.0)   # round() avrebbe dato 16.0
        self.assertEqual(snap(40.0, attrs), 30.0)   # oltre il massimo
        self.assertEqual(snap(10.0, attrs), 16.0)   # sotto il minimo

    def test_active_target_is_what_the_unit_will_hold(self):
        climate = State(
            "cool",
            {
                "current_temperature": 27,
                "hvac_modes": ["off", "cool"],
                "min_temp": 16.0,
                "max_temp": 30.0,
                "target_temp_step": 1.0,
            },
        )
        ctrl = make_controller({"climate.test": climate})
        ctrl.mode = "comfort"
        ctrl.entry.options = {"target_home": 25.5}
        desired = ctrl._compute(NOW)
        # Il sensore diagnostico deve dire 26, non il 25.5 che nessuno terrà.
        self.assertEqual(ctrl.active_target, 26.0)

        sent = []

        async def record(domain, service, data):
            sent.append((service, data))
            return True

        ctrl._call = record
        asyncio.run(ctrl._apply(desired))
        self.assertIn(("set_temperature", {"temperature": 26.0}), sent)

    def test_override_zero_minutes_keeps_control(self):
        ctrl = make_controller()
        ctrl.entry.options = {"override_minutes": 0}
        ctrl._start_override("comando manuale rilevato")
        self.assertFalse(ctrl.override_active)
        self.assertIsNone(ctrl.override_until)
        self.assertIn("override disattivato", ctrl.last_reason)

    # ------------------------------------------------------------- MODE_SMART
    def _smart_controller(self, room=27.0, humidity=None, fan="auto", outdoor=30.0):
        states = {
            "climate.test": State(
                "cool",
                {
                    "current_temperature": room,
                    "fan_mode": fan,
                    "fan_modes": ["high", "medium", "low", "auto"],
                    "hvac_modes": ["off", "cool", "dry"],
                    "min_temp": 16.0,
                    "max_temp": 30.0,
                    "target_temp_step": 1.0,
                },
            ),
            "sensor.outdoor": State(str(outdoor), {"unit_of_measurement": "°C"}),
        }
        data = {"climate_entity": "climate.test", "outdoor_sensor": "sensor.outdoor"}
        if humidity is not None:
            states["sensor.humidity"] = State(str(humidity))
            data["humidity_sensor"] = "sensor.humidity"
        ctrl = make_controller(states, data)
        ctrl.mode = "smart"
        ctrl.entry.options = {"target_home": 25.0, "target_away": 30.0}
        return ctrl

    def test_smart_fan_follows_the_gap(self):
        for room, expected in ((27.5, "high"), (26.5, "medium"), (25.2, "low")):
            ctrl = self._smart_controller(room=room)
            desired = ctrl._compute(NOW)
            self.assertEqual(desired.fan, expected, f"stanza {room}")
            self.assertEqual(desired.setpoint, 25.0)

    def test_smart_ignores_presence(self):
        """Il target resta quello di casa anche con la presenza a 'not_home'."""
        ctrl = self._smart_controller(room=27.0)
        ctrl.entry.data = dict(
            ctrl.entry.data, presence_entity="person.test"
        )
        ctrl.hass.states.values["person.test"] = State("not_home")
        desired = ctrl._compute(NOW)
        self.assertEqual(desired.setpoint, 25.0)   # non 30 (target_away)

    def test_smart_fan_upgrades_at_once_but_downgrades_slowly(self):
        ctrl = self._smart_controller(room=27.5)
        self.assertEqual(ctrl._compute(NOW).fan, "high")
        # La stanza scende di colpo: il declassamento non deve essere immediato.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 25.2
        self.assertEqual(ctrl._compute(NOW).fan, "high")
        # Passato il tempo di attesa, scende.
        later = NOW + timedelta(seconds=controller_module.MIN_FAN_DWELL_SECONDS + 1)
        self.assertEqual(ctrl._compute(later).fan, "low")
        # E una risalita vale subito, senza aspettare.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 27.5
        self.assertEqual(ctrl._compute(later).fan, "high")

    def test_smart_fan_ignores_a_gap_that_only_touches_the_band_edge(self):
        """Misurato sull'unità vera: la stanza a 26.0 con target 25 tocca il confine
        della banda `medium` e prima faceva salire la ventola sei volte in 82
        minuti. Con il margine anche in salita deve restare su `low`."""
        ctrl = self._smart_controller(room=25.5)
        self.assertEqual(ctrl._compute(NOW).fan, "low")
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 26.0
        self.assertEqual(ctrl._compute(NOW).fan, "low")   # scarto +1.0: sul confine
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 26.2
        self.assertEqual(ctrl._compute(NOW).fan, "low")   # +1.2: ancora dentro il margine
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 26.4
        self.assertEqual(ctrl._compute(NOW).fan, "medium")  # +1.4: deriva vera

    def test_smart_fan_holds_inside_the_hysteresis_band(self):
        ctrl = self._smart_controller(room=27.5)
        self.assertEqual(ctrl._compute(NOW).fan, "high")
        later = NOW + timedelta(seconds=controller_module.MIN_FAN_DWELL_SECONDS + 1)
        # 1.9 sopra: dentro la banda di isteresi (2.0 - 0.3), la ventola tiene.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 26.9
        self.assertEqual(ctrl._compute(later).fan, "high")
        # 1.6 sopra: fuori dalla banda, adesso scende.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 26.6
        self.assertEqual(ctrl._compute(later).fan, "medium")

    def test_smart_night_caps_the_fan(self):
        ctrl = self._smart_controller(room=27.5)
        ctrl.entry.options = dict(
            ctrl.entry.options,
            morning_off_start="08:00:00",
            day_start="10:00:00",
            night_start="00:00:00",   # tutto il giorno e' fascia notte
        )
        desired = ctrl._compute(NOW.replace(hour=23, minute=0))
        self.assertEqual(desired.fan, controller_module.NIGHT_MAX_FAN)
        self.assertTrue(desired.mute)
        self.assertTrue(desired.night)

    def test_smart_uses_dry_when_muggy_and_at_temperature(self):
        ctrl = self._smart_controller(room=25.2, humidity=65)
        desired = ctrl._compute(NOW)
        self.assertEqual(desired.hvac, "dry")
        # Isteresi: a 57% resta in dry, sotto 55 torna a cool.
        ctrl.hass.states.values["sensor.humidity"] = State("57")
        self.assertEqual(ctrl._compute(NOW).hvac, "dry")
        ctrl.hass.states.values["sensor.humidity"] = State("54")
        self.assertEqual(ctrl._compute(NOW).hvac, "cool")

    def test_smart_never_dehumidifies_a_warm_room(self):
        ctrl = self._smart_controller(room=27.0, humidity=80)
        self.assertEqual(ctrl._compute(NOW).hvac, "cool")

    def test_smart_without_humidity_sensor_stays_on_cool(self):
        ctrl = self._smart_controller(room=25.1)
        self.assertEqual(ctrl._compute(NOW).hvac, "cool")

    def test_smart_treats_zero_humidity_as_missing(self):
        """Il sensore dell'Haier riporta 0.0 quando non ha nulla da dire."""
        ctrl = self._smart_controller(room=25.1, humidity=0)
        self.assertIsNone(ctrl._read_humidity())
        self.assertEqual(ctrl._compute(NOW).hvac, "cool")

    def test_smart_leaves_fan_alone_if_step_unsupported(self):
        ctrl = self._smart_controller(room=27.5)
        ctrl.hass.states.values["climate.test"].attributes["fan_modes"] = ["auto"]
        self.assertIsNone(ctrl._compute(NOW).fan)

    def test_dry_program_still_gets_setpoint_and_fan(self):
        ctrl = self._smart_controller(room=25.2, humidity=70, fan="high")
        desired = ctrl._compute(NOW)
        self.assertEqual(desired.hvac, "dry")
        sent = []

        async def record(domain, service, data):
            sent.append(service)
            return True

        ctrl._call = record
        asyncio.run(ctrl._apply(desired))
        self.assertIn("set_hvac_mode", sent)
        self.assertIn("set_temperature", sent)
        self.assertIn("set_fan_mode", sent)

    def test_event_burst_collapses_into_one_evaluation(self):
        ctrl = make_controller()
        ctrl._queue_evaluate("evento")
        ctrl._queue_evaluate("evento")
        ctrl._queue_evaluate("intervallo")
        self.assertEqual(len(ctrl.entry.tasks), 1)
        # Una volta che la valutazione e' partita, la successiva torna ad accodarsi.
        asyncio.run(ctrl.async_evaluate("evento"))
        ctrl._queue_evaluate("evento")
        self.assertEqual(len(ctrl.entry.tasks), 2)


if __name__ == "__main__":
    unittest.main()
