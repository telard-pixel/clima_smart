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
# Ora fissa in pieno giorno: senza questa le prove del modo Adattivo
# cambiavano risultato secondo l'ora in cui giravano, per esempio finendo
# dentro la finestra di notte fonda.
GIORNO = NOW.replace(hour=12, minute=0, second=0, microsecond=0)


def _install_ha_stubs() -> None:
    ha = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    exceptions = types.ModuleType("homeassistant.exceptions")
    exceptions.ConfigEntryError = RuntimeError
    exceptions.HomeAssistantError = RuntimeError
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
            "homeassistant.exceptions": exceptions,
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
validation = importlib.import_module("clima_smart.validation")


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

        tentativi = []

        async def fail_call(domain, service, data=None):
            tentativi.append(service)
            return False

        ctrl._call = fail_call
        asyncio.run(
            ctrl._apply(controller_module.Desired(hvac="cool", setpoint=25))
        )
        # Asserzione positiva: il comando e' stato davvero tentato, quindi il None
        # qui sotto significa "finestra ripulita", non "mai armata".
        self.assertEqual(tentativi, ["set_hvac_mode"])
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
            desired = ctrl._compute(GIORNO)
            self.assertEqual(desired.fan, expected, f"stanza {room}")
            self.assertEqual(desired.setpoint, 25.0)

    def test_smart_ignores_presence(self):
        """Il target resta quello di casa anche con la presenza a 'not_home'."""
        ctrl = self._smart_controller(room=27.0)
        ctrl.entry.data = dict(
            ctrl.entry.data, presence_entity="person.test"
        )
        ctrl.hass.states.values["person.test"] = State("not_home")
        desired = ctrl._compute(GIORNO)
        self.assertEqual(desired.setpoint, 25.0)   # non 30 (target_away)

    def test_smart_fan_upgrades_at_once_but_downgrades_slowly(self):
        ctrl = self._smart_controller(room=27.5)
        self.assertEqual(ctrl._compute(GIORNO).fan, "high")
        # La stanza scende di colpo: il declassamento non deve essere immediato.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 25.2
        self.assertEqual(ctrl._compute(GIORNO).fan, "high")
        # Passato il tempo di attesa, scende.
        later = GIORNO + timedelta(seconds=controller_module.MIN_FAN_DWELL_SECONDS + 1)
        self.assertEqual(ctrl._compute(later).fan, "low")
        # E una risalita vale subito, senza aspettare.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 27.5
        self.assertEqual(ctrl._compute(later).fan, "high")

    def test_smart_fan_ignores_a_gap_that_only_touches_the_band_edge(self):
        """Misurato sull'unità vera: la stanza a 26.0 con target 25 tocca il confine
        della banda `medium` e prima faceva salire la ventola sei volte in 82
        minuti. Con il margine anche in salita deve restare su `low`."""
        ctrl = self._smart_controller(room=25.5)
        self.assertEqual(ctrl._compute(GIORNO).fan, "low")
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 26.0
        self.assertEqual(ctrl._compute(GIORNO).fan, "low")   # scarto +1.0: sul confine
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 26.2
        self.assertEqual(ctrl._compute(GIORNO).fan, "low")   # +1.2: ancora dentro il margine
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 26.4
        self.assertEqual(ctrl._compute(GIORNO).fan, "medium")  # +1.4: deriva vera

    def test_smart_fan_holds_inside_the_hysteresis_band(self):
        ctrl = self._smart_controller(room=27.5)
        self.assertEqual(ctrl._compute(GIORNO).fan, "high")
        later = GIORNO + timedelta(seconds=controller_module.MIN_FAN_DWELL_SECONDS + 1)
        # 1.9 sopra: dentro la banda di isteresi (2.0 - 0.3), la ventola tiene.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 26.9
        self.assertEqual(ctrl._compute(later).fan, "high")
        # 1.6 sopra: fuori dalla banda, adesso scende.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 26.6
        self.assertEqual(ctrl._compute(later).fan, "medium")

    def test_no_fan_command_when_a_mute_switch_is_linked_and_on(self):
        """Con un muto collegato e acceso la ventola non si comanda: l'unita' la
        rimette su `auto` e il ritorno verrebbe letto come intervento manuale.
        Senza muto collegato, invece, la ventola resta nostra."""
        ctrl = self._smart_controller(room=27.5)
        ctrl.entry.data = dict(ctrl.entry.data, mute_switch="switch.mute")
        ctrl.hass.states.values["switch.mute"] = State("on")
        desired = controller_module.Desired(hvac="cool", setpoint=25, fan="high")
        self.assertTrue(ctrl._quiet_mode_on(desired))
        ctrl.entry.data = {
            k: v for k, v in ctrl.entry.data.items() if k != "mute_switch"
        }
        self.assertFalse(ctrl._quiet_mode_on(desired))

    def test_smart_uses_dry_when_muggy_and_at_temperature(self):
        ctrl = self._smart_controller(room=25.2, humidity=65)
        desired = ctrl._compute(GIORNO)
        self.assertEqual(desired.hvac, "dry")
        # Isteresi: a 57% resta in dry, sotto 55 torna a cool.
        ctrl.hass.states.values["sensor.humidity"] = State("57")
        self.assertEqual(ctrl._compute(GIORNO).hvac, "dry")
        ctrl.hass.states.values["sensor.humidity"] = State("54")
        self.assertEqual(ctrl._compute(GIORNO).hvac, "cool")

    def test_smart_never_dehumidifies_a_warm_room(self):
        ctrl = self._smart_controller(room=27.0, humidity=80)
        self.assertEqual(ctrl._compute(GIORNO).hvac, "cool")

    def test_smart_without_humidity_sensor_stays_on_cool(self):
        ctrl = self._smart_controller(room=25.1)
        self.assertEqual(ctrl._compute(GIORNO).hvac, "cool")

    def test_smart_treats_zero_humidity_as_missing(self):
        """Il sensore dell'Haier riporta 0.0 quando non ha nulla da dire."""
        ctrl = self._smart_controller(room=25.1, humidity=0)
        self.assertIsNone(ctrl._read_humidity())
        self.assertEqual(ctrl._compute(GIORNO).hvac, "cool")

    def test_smart_leaves_fan_alone_if_step_unsupported(self):
        ctrl = self._smart_controller(room=27.5)
        ctrl.hass.states.values["climate.test"].attributes["fan_modes"] = ["auto"]
        self.assertIsNone(ctrl._compute(GIORNO).fan)

    def test_dry_program_still_gets_setpoint_and_fan(self):
        ctrl = self._smart_controller(room=25.2, humidity=70, fan="high")
        desired = ctrl._compute(GIORNO)
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

    # -------------------------------- notte fonda, correzione, muto e ventola
    def _orari(self, ctrl, **extra):
        ctrl.entry.options = dict(
            ctrl.entry.options,
            morning_off_start="08:00:00",
            day_start="10:00:00",
            night_start="22:00:00",
            sleep_start="23:30:00",
            sleep_end="07:30:00",
            **extra,
        )

    def test_sleep_window_wraps_around_midnight(self):
        ctrl = self._smart_controller()
        self._orari(ctrl)
        casi = {
            (23, 29): "night",   # un minuto prima
            (23, 30): "sleep",   # inizio
            (0, 15): "sleep",    # oltre mezzanotte
            (7, 29): "sleep",       # un minuto prima della fine
            (7, 30): "wind_down",   # fine notte fonda: si scarica fino allo stop
            (9, 0): "gap",          # dopo lo spegnimento del mattino
            (12, 0): "day",
        }
        for (h, m), atteso in casi.items():
            self.assertEqual(
                ctrl._phase(NOW.replace(hour=h, minute=m)), atteso, f"{h:02d}:{m:02d}"
            )

    def test_sleep_window_uses_its_own_target(self):
        ctrl = self._smart_controller(room=26.0)
        self._orari(ctrl, target_sleep=23.0)
        desired = ctrl._compute(NOW.replace(hour=2, minute=0))
        self.assertEqual(desired.setpoint, 23.0)
        self.assertEqual(ctrl.current_phase, "sleep")
        self.assertEqual(desired.fan, "medium")   # ancora lontano dal target
        # Fuori dalla finestra si torna al target di casa.
        self.assertEqual(ctrl._compute(NOW.replace(hour=12, minute=0)).setpoint, 25.0)

    def test_setpoint_offset_shifts_the_command_not_the_target(self):
        ctrl = self._smart_controller(room=27.0)
        ctrl.entry.options = dict(ctrl.entry.options, setpoint_offset=-1.0)
        # GIORNO, non NOW: con l'ora vera questa prova falliva fra le 23:30 e le
        # 08:30, quando la fase diventa notte fonda e il target e' un altro.
        desired = ctrl._compute(GIORNO)
        self.assertEqual(desired.setpoint, 25.0)      # l'obiettivo resta 25
        self.assertEqual(ctrl.active_target, 25.0)    # e il sensore pure
        sent = []

        async def record(domain, service, data):
            sent.append((service, data))
            return True

        ctrl._call = record
        asyncio.run(ctrl._apply(desired))
        # ...ma alla macchina arriva un grado in meno
        self.assertIn(("set_temperature", {"temperature": 24.0}), sent)

    def test_no_fan_command_while_quiet_mode_is_on(self):
        """Con `muto` acceso l'unita' rimette `auto` da sola: comandarla significa
        farsi leggere come intervento manuale e perdere il controllo per un'ora."""
        data = {"climate_entity": "climate.test", "mute_switch": "switch.mute"}
        ctrl = make_controller(
            {
                "climate.test": State(
                    "cool",
                    {
                        "temperature": 25.0,
                        "fan_mode": "auto",
                        "fan_modes": ["high", "medium", "low", "auto"],
                        "hvac_modes": ["off", "cool"],
                    },
                ),
                "switch.mute": State("on"),
            },
            data,
        )
        sent = []

        async def record(domain, service, data=None):
            sent.append(service)
            return True

        ctrl._call = record
        ctrl._call_target = lambda *a, **k: record("switch")
        asyncio.run(
            ctrl._apply(controller_module.Desired(hvac="cool", setpoint=23, fan="low"))
        )
        # Positiva piu' negativa: il setpoint parte, la ventola no. Senza la prima
        # questa prova passerebbe anche se _apply fosse uscito subito.
        self.assertIn("set_temperature", sent)
        self.assertNotIn("set_fan_mode", sent)

    # --------------------------------------------- profilo notturno completo
    def _orologio(self, quando):
        """Fissa l'ora vista dal controller e la ripristina a fine prova: una
        prova che fallisce a meta' non deve lasciare l'orologio finto acceso per
        quelle dopo (successo gia' pagato una volta)."""
        controller_module.dt_util.now = lambda: quando
        self.addCleanup(setattr, controller_module.dt_util, "now", lambda: NOW)

    def _profilo_notte(self, ctrl):
        ctrl.entry.options = dict(
            ctrl.entry.options,
            target_home=25.0,
            target_sleep=22.0,
            sleep_start="23:00:00",
            sleep_end="07:30:00",
            morning_off_start="08:30:00",
            day_start="10:00:00",
            night_start="22:00:00",
        )

    def test_night_profile_fan_medium_until_target_then_low(self):
        ctrl = self._smart_controller(room=26.0)
        self._profilo_notte(ctrl)
        notte = GIORNO.replace(hour=23, minute=30)
        desired = ctrl._compute(notte)
        self.assertEqual(ctrl.current_phase, "sleep")
        self.assertEqual(desired.setpoint, 22.0)
        self.assertEqual(desired.fan, "medium")   # 4 gradi da scendere
        # Arrivato al target passa a low, dopo l'attesa anti-ticchettio.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 22.0
        dopo = notte + timedelta(seconds=controller_module.MIN_FAN_DWELL_SECONDS + 1)
        self.assertEqual(ctrl._compute(dopo).fan, "low")

    def test_night_profile_never_uses_high(self):
        ctrl = self._smart_controller(room=30.0)   # otto gradi sopra
        self._profilo_notte(ctrl)
        self.assertEqual(ctrl._compute(GIORNO.replace(hour=2)).fan, "medium")

    def test_wind_down_is_dry_with_fan_auto(self):
        ctrl = self._smart_controller(room=23.0)
        self._profilo_notte(ctrl)
        desired = ctrl._compute(GIORNO.replace(hour=8, minute=0))
        self.assertEqual(ctrl.current_phase, "wind_down")
        self.assertEqual(desired.hvac, "dry")
        self.assertEqual(desired.fan, "auto")
        self.assertEqual(desired.setpoint, 22.0)

    def test_morning_switch_off_happens_once(self):
        ctrl = self._smart_controller(room=24.0)
        self._profilo_notte(ctrl)
        ctrl._restore_event.set()
        inviati = []

        async def riesce(domain, service, data=None):
            inviati.append(service)
            return True

        ctrl._call = riesce
        self._orologio(GIORNO.replace(hour=8, minute=31))
        asyncio.run(ctrl.async_evaluate("prova"))
        self.assertEqual(inviati, ["turn_off"])

        # L'unita' si spegne davvero, come farebbe la macchina vera.
        ctrl.hass.states.values["climate.test"].state = "off"
        self._orologio(GIORNO.replace(hour=8, minute=36))
        asyncio.run(ctrl.async_evaluate("prova"))
        self.assertEqual(inviati, ["turn_off"])

        # Riaccesa dall'utente dentro la finestra: viene gestita, non rispenta.
        ctrl.hass.states.values["climate.test"].state = "cool"
        self._orologio(GIORNO.replace(hour=8, minute=40))
        asyncio.run(ctrl.async_evaluate("prova"))
        self.assertNotIn("turn_off", inviati[1:])

    def test_morning_switch_off_not_attempted_late(self):
        """Oltre la finestra non ci si prova nemmeno: un riavvio a meta' mattina
        non deve spegnere un clima appena riacceso a mano."""
        ctrl = self._smart_controller(room=24.0)
        self._profilo_notte(ctrl)
        tardi = ctrl._compute(GIORNO.replace(hour=9, minute=30))
        self.assertNotEqual(tardi.hvac, "off")

    def test_smart_never_turns_the_unit_on(self):
        ctrl = self._smart_controller(room=28.0)
        self._profilo_notte(ctrl)
        ctrl.hass.states.values["climate.test"].state = "off"
        desired = ctrl._compute(GIORNO.replace(hour=23, minute=30))
        self.assertIsNone(desired.hvac)
        self.assertIsNone(desired.setpoint)
        self.assertIn("non lo accendo", desired.reason)

    def test_daytime_profile_returns_after_the_switch_off(self):
        ctrl = self._smart_controller(room=27.0)
        self._profilo_notte(ctrl)
        desired = ctrl._compute(GIORNO.replace(hour=12, minute=0))
        self.assertEqual(desired.setpoint, 25.0)
        self.assertEqual(desired.hvac, "cool")

    # ------------------------------------- correzioni dalla revisione a due voci
    def test_morning_switch_off_spares_a_running_heater(self):
        """`!= off` comprendeva anche `heat`: d'inverno spegneva il riscaldamento."""
        ctrl = self._smart_controller(room=19.0, outdoor=8.0)
        self._profilo_notte(ctrl)
        ctrl.hass.states.values["climate.test"].state = "heat"
        desired = ctrl._compute(GIORNO.replace(hour=8, minute=31))
        self.assertNotEqual(desired.hvac, "off")

    def test_morning_switch_off_retries_when_the_command_fails(self):
        ctrl = self._smart_controller(room=24.0)
        self._profilo_notte(ctrl)
        ctrl._restore_event.set()

        async def fallisce(domain, service, data=None):
            return False

        ctrl._call = fallisce
        self._orologio(GIORNO.replace(hour=8, minute=31))
        asyncio.run(ctrl.async_evaluate("prova"))
        self.assertIsNone(ctrl._morning_off_done_on)   # non marcato: si riprova

        inviati = []

        async def riesce(domain, service, data=None):
            inviati.append(service)
            return True

        ctrl._call = riesce
        asyncio.run(ctrl.async_evaluate("prova"))
        self.assertIn("turn_off", inviati)
        self.assertEqual(ctrl._morning_off_done_on, GIORNO.date())

    def test_two_band_jump_lands_on_the_middle_step(self):
        """Con scarto fra 2.0 e 2.3 la ventola ripiegava su `low`: piu' la stanza
        era calda, piu' andava piano."""
        ctrl = self._smart_controller(room=25.0)
        ctrl.entry.options = dict(ctrl.entry.options, target_home=25.0)
        self.assertEqual(ctrl._compute(GIORNO).fan, "low")
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 27.0
        self.assertEqual(ctrl._compute(GIORNO).fan, "medium")   # non piu' low
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 27.4
        self.assertEqual(ctrl._compute(GIORNO).fan, "high")

    def test_restore_timeout_opens_the_barrier_degraded(self):
        controller_module.RESTORE_TIMEOUT_SECONDS = 0.05
        self.addCleanup(setattr, controller_module, "RESTORE_TIMEOUT_SECONDS", 10)
        """Disabilitando una delle due entita' il controller restava fermo per
        sempre: ora la barriera si apre, ma il controllo resta spento."""
        ctrl = make_controller()
        asyncio.run(ctrl.async_start())
        self.assertTrue(ctrl._restore_event.is_set())
        self.assertFalse(ctrl.enabled)
        self.assertIn("non ripristinate", ctrl.last_reason)
        # E da qui in poi le valutazioni girano, invece di uscire tutte.
        asyncio.run(ctrl.async_evaluate("intervallo"))
        self.assertIn("disattivato", ctrl.last_reason)

    def test_our_own_mode_change_is_not_a_manual_command(self):
        ctrl = make_controller()
        ctrl._last_hvac_cmd = "dry"
        ctrl._settle_hvac_until = NOW + timedelta(seconds=60)
        ctrl._settle_mode_change_until = NOW + timedelta(seconds=60)
        ctrl._maybe_flag_manual(
            Event(
                State("cool", {"temperature": 25.0, "fan_mode": "low"}),
                State("dry", {"temperature": 24.0, "fan_mode": "auto"}),
            )
        )
        self.assertFalse(ctrl.override_active)

    def test_a_real_manual_command_still_wins_after_a_mode_change(self):
        ctrl = make_controller()
        ctrl._last_hvac_cmd = "dry"
        ctrl._settle_mode_change_until = NOW - timedelta(seconds=1)   # scaduta
        ctrl._maybe_flag_manual(
            Event(
                State("cool", {"fan_mode": "low"}),
                State("cool", {"fan_mode": "high"}),
            )
        )
        self.assertTrue(ctrl.override_active)

    def test_dry_does_not_flap_on_the_gap_threshold(self):
        ctrl = self._smart_controller(room=25.2, humidity=65)
        self.assertEqual(ctrl._compute(GIORNO).hvac, "dry")
        # La stanza sale fino al confine: senza isteresi qui tornava a cool.
        for temperatura, atteso in ((26.0, "dry"), (26.4, "dry"), (26.6, "cool")):
            ctrl.hass.states.values["climate.test"].attributes[
                "current_temperature"
            ] = temperatura
            self.assertEqual(
                ctrl._compute(GIORNO).hvac, atteso, f"stanza {temperatura}"
            )

    # ------------------------------- l'unita' che rifiuta uno switch ausiliario
    def _con_eco(self):
        data = {"climate_entity": "climate.test", "eco_switch": "switch.eco"}
        ctrl = make_controller(
            {
                "climate.test": State("cool", {"temperature": 22.0, "fan_mode": "low"}),
                "switch.eco": State("off"),
            },
            data,
        )
        return ctrl

    def test_unit_refusing_an_aux_switch_is_not_a_manual_command(self):
        """Misurato due volte: acceso il muto alle 22:03:41 l'unita' rimette `auto`
        66 s dopo; acceso l'eco alle 02:09:45 lo spegne 68 s dopo. Senza contesto
        utente, e ogni volta costava un'ora di controllo ceduta."""
        ctrl = self._con_eco()
        ctrl._last_aux_cmd["eco_switch"] = True
        ctrl._settle_aux_until["eco_switch"] = NOW + timedelta(seconds=120)
        ctrl._maybe_flag_manual_switch(
            "eco_switch", Event(State("on"), State("off"))
        )
        self.assertFalse(ctrl.override_active)
        self.assertIn("eco_switch", ctrl._aux_refused_at)
        self.assertIn("rifiutato", ctrl.last_reason)

    def test_a_refused_switch_is_not_commanded_again_right_away(self):
        ctrl = self._con_eco()
        ctrl._aux_refused_at["eco_switch"] = NOW
        inviati = []

        async def record(domain, service, entity_id, data=None):
            inviati.append((service, entity_id))
            return True

        ctrl._call_target = record
        acceso = asyncio.run(ctrl._apply_switch("eco_switch", True))
        self.assertFalse(acceso)
        self.assertEqual(inviati, [])
        self.assertTrue(any("rifiutato" in e for e in ctrl._apply_errors))

    def test_a_refused_switch_is_tried_again_after_the_backoff(self):
        ctrl = self._con_eco()
        ctrl._aux_refused_at["eco_switch"] = NOW - timedelta(
            seconds=controller_module.AUX_REFUSAL_BACKOFF_SECONDS + 1
        )
        inviati = []

        async def record(domain, service, entity_id, data=None):
            inviati.append((service, entity_id))
            return True

        ctrl._call_target = record
        self.assertTrue(asyncio.run(ctrl._apply_switch("eco_switch", True)))
        self.assertEqual(inviati, [("turn_on", "switch.eco")])

    def test_a_real_hand_on_an_aux_switch_still_wins(self):
        ctrl = self._con_eco()
        ctrl._last_aux_cmd["eco_switch"] = True
        ctrl._settle_aux_until["eco_switch"] = NOW + timedelta(seconds=120)
        ctrl._maybe_flag_manual_switch(
            "eco_switch", Event(State("on"), State("off", user_id="utente"))
        )
        self.assertTrue(ctrl.override_active)

    def test_an_aux_change_outside_the_window_is_still_manual(self):
        ctrl = self._con_eco()
        ctrl._last_aux_cmd["eco_switch"] = True
        ctrl._settle_aux_until["eco_switch"] = NOW - timedelta(seconds=1)
        ctrl._maybe_flag_manual_switch(
            "eco_switch", Event(State("on"), State("off"))
        )
        self.assertTrue(ctrl.override_active)
        self.assertNotIn("eco_switch", ctrl._aux_refused_at)

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


class ValidationTests(unittest.TestCase):
    """Regole del form, provate direttamente: `validation` non importa ne' Home
    Assistant ne' voluptuous, quindi qui non c'e' nessuno stub di mezzo."""

    BASE = {
        "morning_off_start": "08:30:00",
        "day_start": "10:00:00",
        "night_start": "22:00:00",
        "sleep_start": "23:00:00",
        "sleep_end": "07:30:00",
        "eco_outdoor_on": 33.0,
        "eco_outdoor_off": 35.0,
        "presence_home_state": "home",
    }

    def valida(self, **cambi):
        return validation.validate_options({**self.BASE, **cambi})

    def test_configurazione_sana_passa(self):
        self.assertIsNone(self.valida())

    def test_ordine_orari(self):
        self.assertEqual(self.valida(day_start="07:00:00"), "invalid_time_order")

    def test_finestra_notturna_nulla(self):
        self.assertEqual(
            self.valida(sleep_start="23:00:00", sleep_end="23:00:00"),
            "invalid_sleep_window",
        )

    def test_notte_che_supera_lo_spegnimento(self):
        """Con sleep_end dopo lo spegnimento sparisce la fascia dry e lo
        spegnimento non avviene mai: il clima raffredda tutto il giorno."""
        self.assertEqual(
            self.valida(sleep_end="09:00:00", morning_off_start="08:00:00"),
            "invalid_wind_down",
        )

    def test_notte_che_finisce_esattamente_allo_spegnimento(self):
        self.assertEqual(
            self.valida(sleep_end="08:30:00"), "invalid_wind_down"
        )

    def test_soglie_eco_invertite(self):
        self.assertEqual(
            self.valida(eco_outdoor_on=36.0), "invalid_eco_range"
        )

    def test_stato_presenza_vuoto(self):
        for valore in ("", "   "):
            self.assertEqual(
                self.valida(presence_home_state=valore),
                "invalid_presence_state",
                repr(valore),
            )

    def test_stato_presenza_ripulito(self):
        self.assertEqual(validation.normalise_presence_state("  home "), "home")

    def test_switch_ausiliari_distinti(self):
        self.assertTrue(
            validation.aux_switches_are_distinct(
                {"eco_switch": "switch.a", "mute_switch": "switch.b"}
            )
        )
        self.assertFalse(
            validation.aux_switches_are_distinct(
                {"eco_switch": "switch.a", "night_switch": "switch.a"}
            )
        )
        # Due caselle vuote non sono un duplicato.
        self.assertTrue(
            validation.aux_switches_are_distinct(
                {"eco_switch": None, "mute_switch": None}
            )
        )


if __name__ == "__main__":
    unittest.main()
