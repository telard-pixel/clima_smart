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
    storage = types.ModuleType("homeassistant.helpers.storage")

    class Store:
        """Archivio finto: tiene i dati in un dizionario condiviso per chiave, cosi'
        una prova puo' simulare un riavvio ricreando il controller con la stessa."""

        _dati: dict = {}

        def __init__(self, hass, version, key):
            self.key = key

        async def async_load(self):
            return Store._dati.get(self.key)

        async def async_save(self, data):
            Store._dati[self.key] = data

    storage.Store = Store
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
            "homeassistant.helpers.storage": storage,
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


class Bus:
    """Registra gli eventi lanciati, per poterli verificare."""

    def __init__(self):
        self.eventi = []

    def async_fire(self, tipo, dati=None):
        self.eventi.append((tipo, dati or {}))


class Hass:
    def __init__(self, states=None):
        self.states = States(states or {})
        self.bus = Bus()
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
        ctrl.mode = "smart"
        desired = ctrl._compute(GIORNO)
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
        ctrl.mode = "smart"
        ctrl.entry.options = {"target_home": 25.5}
        desired = ctrl._compute(GIORNO)
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

    def _casa_accesa(self, **kw):
        """Come `_con_casa`, ma col clima acceso: qui si prova la ventola, non l'avvio."""
        ctrl = self._con_casa(**kw)
        ctrl.hass.states.values["climate.test"].state = "cool"
        return ctrl

    def test_day_fan_reads_the_house_not_the_return_air(self):
        """Un passo di ventola vale un grado pieno sulla lettura della macchina, a
        stanza ferma: decidere la ventola su quel numero significa chiudere l'anello
        sul proprio attuatore. Di giorno decide la media delle altre stanze."""
        ctrl = self._casa_accesa(room=27.5, altre=(25.2, 25.2, 25.2))
        # La ripresa direbbe +2.5, cioe' `high`; la casa dice +0.2, cioe' `low`.
        self.assertEqual(ctrl._compute(GIORNO).fan, "low")
        # E se la casa si scalda davvero, la ventola sale.
        for i in range(3):
            ctrl.hass.states.values[f"sensor.stanza{i}"] = State("26.6", {})
        self.assertEqual(ctrl._compute(GIORNO).fan, "medium")

    def test_day_fan_ignores_the_adaptive_compensation(self):
        """Quattro delle sei salite di ventola del 4 agosto sono state causate dal
        target che si abbassava, a stanza ferma: il quanto adattivo vale un grado e
        i bordi di banda distano un grado, quindi spostava la ventola per
        costruzione. La ventola guarda il target base."""
        casa = (26.6, 26.6, 26.6)
        senza = self._casa_accesa(room=27.0, altre=casa, outdoor=30.0)
        con = self._casa_accesa(room=27.0, altre=casa, outdoor=36.0)
        for c in (senza, con):
            c.entry.options = dict(
                c.entry.options,
                adaptive_outdoor_start=33.0,
                adaptive_slope=0.25,
                adaptive_max=1.5,
            )
        # L'esterna a 36 alza il target di un grado pieno...
        self.assertEqual(con._compute(GIORNO).setpoint, 26.0)
        self.assertEqual(senza._compute(GIORNO).setpoint, 25.0)
        # ...ma la ventola non se ne accorge, perche' la casa non e' cambiata.
        self.assertEqual(con._compute(GIORNO).fan, senza._compute(GIORNO).fan)

    def test_day_fan_falls_back_to_the_return_air_without_house_sensors(self):
        """Senza media di casa non si resta senza decisione: si torna alla ripresa."""
        ctrl = self._casa_accesa(room=27.5, altre=())
        self.assertEqual(ctrl._compute(GIORNO).fan, "high")

    def test_night_fan_measures_against_the_commanded_setpoint(self):
        """Di notte comanda ancora la camera, perche' `low` e' il silenzio. Ma il
        confronto e' col setpoint che la macchina tiene davvero: col target nominale
        si scendeva a `low` proprio quando la macchina arrivava."""
        ctrl = self._casa_accesa(room=21.9, altre=(26.5, 26.5, 26.5))
        self._orari(ctrl, target_sleep=22.5)
        ctrl.entry.options = dict(ctrl.entry.options, setpoint_offset=-1.0)
        notte = NOW.replace(hour=2, minute=0)
        # Setpoint comandato 21.5: la camera a 21.9 e' sopra, quindi `medium`.
        # Col vecchio riferimento (il target nominale 22.5) lo scarto sarebbe stato
        # -0.6 e la ventola sarebbe scesa a `low` proprio mentre la macchina
        # raggiungeva il proprio setpoint: la patologia da evitare.
        self.assertEqual(ctrl._compute(notte).fan, "medium")
        # `low` resta possibile, e serve, perche' di notte e' anche il silenzio: ma
        # ora pretende una camera davvero fredda, un grado sotto il comandato.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 20.4
        dopo = notte + timedelta(seconds=controller_module.MIN_FAN_DWELL_SECONDS + 60)
        self.assertEqual(ctrl._compute(dopo).fan, "low")

    # ------------------------------------------ stato che sopravvive al riavvio
    def _riavvia(self, vecchio):
        """Un controller nuovo con la stessa chiave d'archivio: e' cio' che accade a
        Home Assistant quando si riavvia, o quando l'integrazione viene ricaricata
        perche' e' cambiata un'entita' collegata."""
        nuovo = make_controller(vecchio.hass.states.values, dict(vecchio.entry.data))
        nuovo.entry.options = dict(vecchio.entry.options)
        nuovo.mode = vecchio.mode
        asyncio.run(nuovo._async_load_memoria())
        return nuovo

    def test_a_restart_does_not_undo_the_manual_override(self):
        """Il caso peggiore segnalato: il clima parte da solo, l'utente lo spegne a
        mano, e un riavvio dentro l'ora di resa glielo riaccendeva."""
        ctrl = self._smart_controller(room=27.0)
        ctrl._start_override("prova")
        self.assertTrue(ctrl.override_active)
        asyncio.run(ctrl._async_save_memoria())
        dopo = self._riavvia(ctrl)
        self.assertTrue(dopo.override_active, "la resa manuale deve sopravvivere")

    def test_a_restart_does_not_repeat_the_daytime_start(self):
        """L'avvio diurno e' il peggiore dei tre perche' non ha finestra oraria:
        senza persistenza poteva riscattare ore dopo il riavvio."""
        ctrl = self._smart_controller(room=27.0)
        ctrl._day_start_done_on = GIORNO.date()
        asyncio.run(ctrl._async_save_memoria())
        dopo = self._riavvia(ctrl)
        self.assertEqual(dopo._day_start_done_on, GIORNO.date())

    def test_a_restart_keeps_the_adaptive_compensation(self):
        """Ripartire da zero abbassava il target di un grado finche' l'esterna non
        risaliva sopra la soglia di salita."""
        ctrl = self._smart_controller(room=27.0)
        ctrl.adaptive_extra = 1.0
        asyncio.run(ctrl._async_save_memoria())
        self.assertEqual(self._riavvia(ctrl).adaptive_extra, 1.0)

    def test_an_unreadable_store_does_not_stop_the_start(self):
        """Un archivio illeggibile e' un guaio, non un motivo per non partire."""
        ctrl = self._smart_controller(room=27.0)

        async def esplode():
            raise RuntimeError("archivio rotto")

        ctrl._store.async_load = esplode
        asyncio.run(ctrl._async_load_memoria())
        self.assertIsNone(ctrl._day_start_done_on)

    def test_smart_fan_follows_the_gap(self):
        for room, expected in ((27.5, "high"), (26.5, "medium"), (25.2, "low")):
            ctrl = self._smart_controller(room=room)
            desired = ctrl._compute(GIORNO)
            self.assertEqual(desired.fan, expected, f"stanza {room}")
            self.assertEqual(desired.setpoint, 25.0)

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
        self.assertEqual(ctrl._compute(GIORNO).fan, "low")   # +1.4: margine allargato a 0.5
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 26.5
        self.assertEqual(ctrl._compute(GIORNO).fan, "medium")  # +1.5: deriva vera

    def test_smart_fan_holds_inside_the_hysteresis_band(self):
        ctrl = self._smart_controller(room=27.5)
        self.assertEqual(ctrl._compute(GIORNO).fan, "high")
        later = GIORNO + timedelta(seconds=controller_module.MIN_FAN_DWELL_SECONDS + 1)
        # 1.6 sopra: dentro la banda di isteresi (2.0 - 0.5), la ventola tiene.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 26.6
        self.assertEqual(ctrl._compute(later).fan, "high")
        # 1.4 sopra: fuori dalla banda, adesso scende.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 26.4
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

    def test_sleep_boost_runs_the_fan_high_then_hands_back_to_the_bands(self):
        """All'ingresso nella notte fonda il target scende di colpo: la ventola va
        al massimo per i primi minuti, poi torna alle due bande della notte."""
        ctrl = self._smart_controller(room=26.0)
        self._orari(ctrl, target_sleep=23.0)   # finestra dalle 23:30
        dentro = ctrl._compute(NOW.replace(hour=23, minute=35))
        self.assertEqual(dentro.fan, "high")
        self.assertIn("spinta iniziale", dentro.reason)
        # Passati i quindici minuti la spinta finisce, la stanza e' ancora sopra
        # il target e si torna a `medium`.
        dopo = ctrl._compute(NOW.replace(hour=23, minute=50))
        self.assertEqual(dopo.fan, "medium")
        self.assertNotIn("spinta iniziale", dopo.reason)

    def test_sleep_boost_does_not_hold_high_through_the_dwell(self):
        """La permanenza minima frena i declassamenti fra bande, ma `high` non e'
        una banda della notte: a spinta finita si rientra subito, senza attendere
        i dieci minuti, altrimenti la ventola resterebbe al massimo in camera."""
        ctrl = self._smart_controller(room=26.0)
        self._orari(ctrl, target_sleep=23.0)
        self.assertEqual(ctrl._compute(NOW.replace(hour=23, minute=35)).fan, "high")
        # Un minuto dopo la fine della spinta, con la stanza gia' sotto il target:
        # molto meno dei 600 secondi di permanenza.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 21.5
        self.assertEqual(ctrl._compute(NOW.replace(hour=23, minute=46)).fan, "low")

    def test_sleep_boost_skips_a_room_practically_at_target(self):
        """Sotto la soglia di scarto la spinta non ha nulla da abbattere: decidono
        le bande, che a due decimi dal target chiedono `medium`, non `high`."""
        ctrl = self._smart_controller(room=23.2)
        self._orari(ctrl, target_sleep=23.0)
        desired = ctrl._compute(NOW.replace(hour=23, minute=35))
        self.assertEqual(desired.fan, "medium")
        self.assertNotIn("spinta iniziale", desired.reason)

    def test_sleep_boost_survives_midnight(self):
        """Con la finestra che apre a ridosso delle 24 il conteggio dei minuti
        deve scavalcare la mezzanotte, non tornare negativo."""
        ctrl = self._smart_controller(room=26.0)
        self._orari(ctrl, target_sleep=23.0)
        ctrl.entry.options = dict(ctrl.entry.options, sleep_start="23:55:00")
        self.assertTrue(ctrl._sleep_boost_active(NOW.replace(hour=0, minute=5)))
        self.assertFalse(ctrl._sleep_boost_active(NOW.replace(hour=0, minute=15)))

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

    def test_night_profile_holds_medium_down_to_the_target(self):
        """Misurato su una notte intera: scendere a `low` al target fa rallentare
        il compressore da 41 a 30 Hz e la camera se ne va di due gradi. Quindi
        `medium` fino al target, e `low` solo se la stanza va sotto."""
        ctrl = self._smart_controller(room=26.0)
        self._profilo_notte(ctrl)
        notte = GIORNO.replace(hour=23, minute=30)
        desired = ctrl._compute(notte)
        self.assertEqual(ctrl.current_phase, "sleep")
        self.assertEqual(desired.setpoint, 22.0)
        self.assertEqual(desired.fan, "medium")   # 4 gradi da scendere
        dopo = notte + timedelta(seconds=controller_module.MIN_FAN_DWELL_SECONDS + 1)
        # Al target resta medium: e' il punto che stanotte ci e' costato due gradi.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 22.0
        self.assertEqual(ctrl._compute(dopo).fan, "medium")
        # Mezzo grado sotto: ancora medium, siamo dentro il margine.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 21.6
        self.assertEqual(ctrl._compute(dopo).fan, "medium")
        # Un grado sotto: adesso ha senso rallentare.
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 21.0
        self.assertEqual(ctrl._compute(dopo).fan, "low")

    def test_night_profile_never_uses_high(self):
        ctrl = self._smart_controller(room=30.0)   # otto gradi sopra
        self._profilo_notte(ctrl)
        self.assertEqual(ctrl._compute(GIORNO.replace(hour=2)).fan, "medium")

    def test_wind_down_stays_in_cool_with_fan_auto(self):
        """Il `dry` dell'ultima ora non risparmiava niente: misurato su due giornate
        confrontabili, 301 W in `cool` contro 305 in `dry`, e 347 contro 368. Il
        segno e' contrario, quindi si resta in `cool` fino allo spegnimento."""
        ctrl = self._smart_controller(room=23.0)
        self._profilo_notte(ctrl)
        desired = ctrl._compute(GIORNO.replace(hour=8, minute=0))
        self.assertEqual(ctrl.current_phase, "wind_down")
        self.assertEqual(desired.hvac, "cool")
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
        ctrl.hass.states.values["climate.test"].attributes["current_temperature"] = 27.5
        self.assertEqual(ctrl._compute(GIORNO).fan, "high")     # 2.0 + il margine 0.5

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

    # ------------------------------------------------- avvio serale una tantum
    def _pronto_per_avvio(self):
        ctrl = self._smart_controller(room=27.0)
        self._profilo_notte(ctrl)
        ctrl.entry.options = dict(
            ctrl.entry.options, auto_start_sleep=True, sleep_start="22:00:00"
        )
        ctrl.hass.states.values["climate.test"].state = "off"
        ctrl._restore_event.set()
        return ctrl

    def test_evening_start_turns_the_unit_on_once(self):
        ctrl = self._pronto_per_avvio()
        inviati = []

        async def riesce(domain, service, data=None):
            inviati.append(service)
            return True

        ctrl._call = riesce
        self._orologio(GIORNO.replace(hour=22, minute=1))
        asyncio.run(ctrl.async_evaluate("prova"))
        self.assertIn("set_hvac_mode", inviati)
        self.assertEqual(ctrl._sleep_start_done_on, GIORNO.date())
        # E ha annunciato l'avvio a chi ascolta.
        tipi = [t for t, _ in ctrl.hass.bus.eventi]
        self.assertIn(controller_module.EVENT_STARTED, tipi)

        # Spento dall'utente piu' tardi: non lo riaccende.
        inviati.clear()
        self._orologio(GIORNO.replace(hour=23, minute=30))
        asyncio.run(ctrl.async_evaluate("prova"))
        self.assertEqual(inviati, [])

    def test_daytime_start_when_the_room_gets_hot(self):
        """L'avvio vero: la stanza si e' scaldata e qualcuno deve chiudere le
        finestre. L'evento porta il motivo, cosi' l'annuncio distingue."""
        ctrl = self._smart_controller(room=28.5)
        self._profilo_notte(ctrl)
        ctrl.entry.options = dict(ctrl.entry.options, auto_start_room=28.0)
        ctrl.hass.states.values["climate.test"].state = "off"
        ctrl._restore_event.set()
        inviati = []

        async def riesce(domain, service, data=None):
            inviati.append(service)
            return True

        ctrl._call = riesce
        self._orologio(GIORNO.replace(hour=12, minute=0))
        asyncio.run(ctrl.async_evaluate("prova"))
        self.assertIn("set_hvac_mode", inviati)
        tipo, dati = ctrl.hass.bus.eventi[-1]
        self.assertEqual(tipo, controller_module.EVENT_STARTED)
        self.assertEqual(dati["motivo"], controller_module.START_REASON_DAY)

        # Spento a mano piu' tardi: non lo riaccende oggi.
        inviati.clear()
        ctrl.hass.states.values["climate.test"].state = "off"
        self._orologio(GIORNO.replace(hour=15, minute=0))
        asyncio.run(ctrl.async_evaluate("prova"))
        self.assertEqual(inviati, [])

    def _con_casa(self, room=26.0, altre=(27.0, 26.5, 25.5), outdoor=31.0):
        ctrl = self._smart_controller(room=room, outdoor=outdoor)
        self._profilo_notte(ctrl)
        for i, valore in enumerate(altre):
            ctrl.hass.states.values[f"sensor.stanza{i}"] = State(
                str(valore), {"unit_of_measurement": "°C"}
            )
        ctrl.entry.data = dict(
            ctrl.entry.data,
            house_sensors=[f"sensor.stanza{i}" for i in range(len(altre))],
        )
        ctrl.entry.options = dict(
            ctrl.entry.options,
            auto_start_room=28.0,
            auto_start_house=26.0,
            auto_start_outdoor=28.0,
        )
        ctrl.hass.states.values["climate.test"].state = "off"
        return ctrl

    def test_house_average_skips_unusable_readings(self):
        ctrl = self._con_casa(altre=(27.0, 26.0))
        self.assertAlmostEqual(ctrl._house_average(), 26.5)
        ctrl.hass.states.values["sensor.stanza1"] = State("unavailable")
        self.assertAlmostEqual(ctrl._house_average(), 27.0)
        ctrl.hass.states.values["sensor.stanza0"] = State("unknown")
        self.assertIsNone(ctrl._house_average())

    def test_house_average_starts_before_the_bedroom_gets_hot(self):
        """La camera e' ancora sotto la sua soglia, ma il resto della casa no:
        e' il segnale che permette di partire prima del picco."""
        ctrl = self._con_casa(room=26.0, altre=(27.0, 26.5, 25.5))
        desired = ctrl._compute(GIORNO.replace(hour=12, minute=0))
        self.assertEqual(desired.hvac, "cool")
        self.assertIn("casa", desired.reason)

    def test_cool_day_never_starts_by_itself(self):
        ctrl = self._con_casa(altre=(29.0, 29.0), outdoor=24.0)
        desired = ctrl._compute(GIORNO.replace(hour=12, minute=0))
        self.assertIsNone(desired.hvac)

    def test_without_house_sensors_only_the_room_counts(self):
        ctrl = self._con_casa(room=26.0, altre=())
        ctrl.entry.data = {
            k: v for k, v in ctrl.entry.data.items() if k != "house_sensors"
        }
        self.assertIsNone(ctrl._house_average())
        self.assertIsNone(ctrl._compute(GIORNO.replace(hour=12, minute=0)).hvac)

    def test_no_daytime_start_below_the_threshold(self):
        ctrl = self._smart_controller(room=27.0)
        self._profilo_notte(ctrl)
        ctrl.entry.options = dict(ctrl.entry.options, auto_start_room=28.0)
        ctrl.hass.states.values["climate.test"].state = "off"
        desired = ctrl._compute(GIORNO.replace(hour=12, minute=0))
        self.assertIsNone(desired.hvac)

    def test_daytime_start_disabled_by_default(self):
        ctrl = self._smart_controller(room=31.0)
        self._profilo_notte(ctrl)
        ctrl.hass.states.values["climate.test"].state = "off"
        desired = ctrl._compute(GIORNO.replace(hour=12, minute=0))
        self.assertIsNone(desired.hvac)

    def test_night_start_carries_its_own_reason(self):
        ctrl = self._pronto_per_avvio()

        async def riesce(domain, service, data=None):
            return True

        ctrl._call = riesce
        self._orologio(GIORNO.replace(hour=22, minute=1))
        asyncio.run(ctrl.async_evaluate("prova"))
        tipo, dati = ctrl.hass.bus.eventi[-1]
        self.assertEqual(dati["motivo"], controller_module.START_REASON_NIGHT)

    def test_evening_start_is_off_unless_asked_for(self):
        ctrl = self._pronto_per_avvio()
        ctrl.entry.options = dict(ctrl.entry.options, auto_start_sleep=False)
        self._orologio(GIORNO.replace(hour=22, minute=1))
        desired = ctrl._compute(GIORNO.replace(hour=22, minute=1))
        self.assertIsNone(desired.hvac)
        self.assertIn("non lo accendo", desired.reason)

    def test_evening_start_not_attempted_late(self):
        ctrl = self._pronto_per_avvio()
        desired = ctrl._compute(GIORNO.replace(hour=23, minute=0))
        self.assertIsNone(desired.hvac)

    def test_evening_start_retries_when_the_command_fails(self):
        ctrl = self._pronto_per_avvio()

        async def fallisce(domain, service, data=None):
            return False

        ctrl._call = fallisce
        self._orologio(GIORNO.replace(hour=22, minute=1))
        asyncio.run(ctrl.async_evaluate("prova"))
        self.assertIsNone(ctrl._sleep_start_done_on)
        self.assertEqual(ctrl.hass.bus.eventi, [])

    # ------------------------------------------ target adattivo sull'esterna
    def _con_adattivo(self, outdoor):
        ctrl = self._smart_controller(room=28.0, outdoor=outdoor)
        self._profilo_notte(ctrl)
        ctrl.entry.options = dict(
            ctrl.entry.options,
            target_home=25.0,
            adaptive_outdoor_start=33.0,
            adaptive_slope=0.25,
            adaptive_max=1.5,
        )
        return ctrl

    def test_adaptive_target_does_not_flip_on_a_wobbling_station(self):
        """La stazione riporta gradi interi e oscilla a cavallo della soglia: senza
        difese la compensazione ballava ogni cinque minuti, e ogni ballo era un
        comando di setpoint alla macchina - beep compreso."""
        ctrl = self._con_adattivo(34.0)
        t0 = GIORNO
        self.assertEqual(ctrl._adaptive_extra(34.0, t0), 0.5)
        # torna a 33: non deve ridiscendere subito
        self.assertEqual(ctrl._adaptive_extra(33.0, t0 + timedelta(minutes=5)), 0.5)
        # e nemmeno risalire e riscendere di continuo
        self.assertEqual(ctrl._adaptive_extra(34.0, t0 + timedelta(minutes=10)), 0.5)
        # passata l'attesa e tornata l'esterna sotto la soglia, scende
        dopo = t0 + timedelta(
            seconds=controller_module.ADAPTIVE_MIN_DWELL_SECONDS + 60
        )
        self.assertEqual(ctrl._adaptive_extra(32.0, dopo), 0.0)

    def test_adaptive_target_raises_only_when_it_is_hot(self):
        """Sulla macchina di prova, che ha passo 1.0, la compensazione si muove a
        gradi interi: a 34 gradi esterni il quarto di grado calcolato non arriva
        a mezzo passo e resta zero, a 36 diventa un grado pieno."""
        casi = {30.0: 25.0, 33.0: 25.0, 34.0: 25.0, 36.0: 26.0, 38.0: 26.0}
        for esterna, atteso in casi.items():
            ctrl = self._con_adattivo(esterna)
            desired = ctrl._compute(GIORNO)
            self.assertEqual(desired.setpoint, atteso, f"esterna {esterna}")

    def test_adaptive_target_is_capped(self):
        """Il tetto di 1.5 su una macchina a gradi interi vale 1.0: il mezzo grado
        che avanza non saprebbe dove andare, e arrotondarlo in su sforerebbe il
        massimo che l'utente ha impostato."""
        ctrl = self._con_adattivo(45.0)   # ben oltre il massimo
        self.assertEqual(ctrl._compute(GIORNO).setpoint, 26.0)

    def test_adaptive_target_falls_back_to_half_degrees_without_a_step(self):
        """Se la macchina non dichiara il proprio passo si torna al mezzo grado."""
        valori = {self._con_adattivo(e)._adaptive_extra(e, GIORNO) for e in (34.0, 34.9)}
        self.assertEqual(valori, {0.5})

    def test_adaptive_target_quantises_on_the_machine_step(self):
        """Il quanto lo detta la macchina: mezzo grado su un'unita' a passo 1.0
        diventava un grado pieno una volta arrotondato, cioe' il doppio di quanto
        deciso."""
        ctrl = self._con_adattivo(36.0)
        self.assertEqual(ctrl._adaptive_extra(36.0, GIORNO, 1.0), 1.0)
        ctrl = self._con_adattivo(34.0)
        self.assertEqual(ctrl._adaptive_extra(34.0, GIORNO, 1.0), 0.0)

    def test_adaptive_target_survives_the_station_of_the_fourth_of_august(self):
        """La traccia vera del 4 agosto: l'esterna ha attraversato la soglia dieci
        volte fra le 12 e le 21 e il setpoint l'ha seguita ogni volta. Con il
        quanto della macchina la banda morta va da 33 a 35, e quella sequenza
        produce un solo scatto invece di dieci."""
        ctrl = self._con_adattivo(33.0)
        traccia = [33, 34, 33, 34, 35, 34, 33, 34, 33, 34, 35, 36, 35, 34, 33]
        cambi = 0
        prec = 0.0
        for i, esterna in enumerate(traccia):
            # Un campione ogni cinque minuti, come la stazione vera.
            valore = ctrl._adaptive_extra(
                float(esterna), GIORNO + timedelta(minutes=5 * i), 1.0
            )
            if valore != prec:
                cambi += 1
                prec = valore
        self.assertLessEqual(cambi, 1, "il setpoint non deve rincorrere la stazione")

    def test_adaptive_target_off_by_default(self):
        ctrl = self._smart_controller(room=28.0, outdoor=40.0)
        self._profilo_notte(ctrl)
        ctrl.entry.options = dict(ctrl.entry.options, target_home=25.0)
        self.assertEqual(ctrl._compute(GIORNO).setpoint, 25.0)

    def test_keep_it_off_wins_over_everything(self):
        """L'unico altro modo rimasto: il controller tiene spenta l'unita' e non
        adatta un bel niente, per quanto faccia caldo."""
        ctrl = self._con_adattivo(38.0)
        ctrl.mode = "off"
        desired = ctrl._compute(GIORNO)
        self.assertEqual(desired.hvac, "off")
        self.assertIsNone(desired.setpoint)

    # --------------------------------------------- alette nella notte fonda
    def _con_alette(self, posizioni=("position_0", "position_3", "swing")):
        ctrl = self._smart_controller(room=26.0)
        self._profilo_notte(ctrl)
        ctrl.entry.data = dict(
            ctrl.entry.data,
            vane_horizontal="select.aletta_h",
            vane_vertical="select.aletta_v",
        )
        for eid in ("select.aletta_h", "select.aletta_v"):
            ctrl.hass.states.values[eid] = State(
                posizioni[0], {"options": list(posizioni)}
            )
        return ctrl

    def test_vanes_go_to_swing_in_the_deep_night(self):
        ctrl = self._con_alette()
        desired = ctrl._compute(GIORNO.replace(hour=23, minute=30))
        self.assertEqual(ctrl.current_phase, "sleep")
        self.assertEqual(desired.vane_h, "swing")
        self.assertEqual(desired.vane_v, "swing")
        inviati = []

        async def record(domain, service, entity_id, data=None):
            inviati.append((entity_id, (data or {}).get("option")))
            return True

        ctrl._call_target = record
        asyncio.run(ctrl._apply(desired))
        self.assertIn(("select.aletta_h", "swing"), inviati)
        self.assertIn(("select.aletta_v", "swing"), inviati)

    def test_vanes_are_left_alone_outside_the_deep_night(self):
        ctrl = self._con_alette()
        self.assertIsNone(ctrl._compute(GIORNO.replace(hour=12)).vane_h)
        self.assertIsNone(ctrl._compute(GIORNO.replace(hour=22, minute=0)).vane_h)

    def test_vane_already_in_position_is_not_commanded(self):
        ctrl = self._con_alette(posizioni=("swing", "position_3", "swing"))
        inviati = []

        async def record(domain, service, entity_id, data=None):
            if domain == "select":
                inviati.append(entity_id)
            return True

        ctrl._call_target = record
        asyncio.run(
            ctrl._apply(ctrl._compute(GIORNO.replace(hour=23, minute=30)))
        )
        self.assertEqual(inviati, [])

    def test_vane_position_the_unit_does_not_offer_is_reported(self):
        ctrl = self._con_alette(posizioni=("position_0", "position_3"))
        ctrl.entry.options = dict(ctrl.entry.options, vane_sleep_position="swing")
        asyncio.run(
            ctrl._apply(ctrl._compute(GIORNO.replace(hour=23, minute=30)))
        )
        self.assertTrue(
            any("non prevista" in e for e in ctrl._apply_errors), ctrl._apply_errors
        )

    def test_vanes_go_back_to_the_day_position_once(self):
        """Fine della notte fonda: tornano ferme, e una volta sola - se poi le
        sposti a mano non te le rimette al passaggio dopo."""
        ctrl = self._con_alette(posizioni=("swing", "position_0", "position_5"))
        ctrl.entry.options = dict(
            ctrl.entry.options,
            vane_day_horizontal="position_0",
            vane_day_vertical="position_5",
        )
        mattina = GIORNO.replace(hour=8, minute=0)

        async def succeeds(domain, service, entity_id, data=None):
            return True

        ctrl._call_target = succeeds
        desired = ctrl._compute(mattina)
        self.assertEqual(ctrl.current_phase, "wind_down")
        self.assertEqual(desired.vane_h, "position_0")
        self.assertEqual(desired.vane_v, "position_5")
        asyncio.run(ctrl._apply(desired))
        # Seconda passata nella stessa fascia: non le tocca piu'.
        self.assertIsNone(ctrl._compute(mattina + timedelta(minutes=10)).vane_h)

    def test_wind_down_vane_marker_waits_for_an_actual_restore_request(self):
        ctrl = self._con_alette(posizioni=("swing", "position_0", "position_5"))
        ctrl.entry.options = dict(
            ctrl.entry.options,
            vane_day_horizontal="position_0",
            vane_day_vertical="position_5",
        )
        mattina = GIORNO.replace(hour=8, minute=0)
        ctrl.hass.states.values["climate.test"].state = "off"
        richieste = []

        async def succeeds(domain, service, entity_id, data=None):
            if domain == "select":
                richieste.append((entity_id, data["option"]))
            return True

        ctrl._call_target = succeeds
        self._orologio(mattina)
        first = ctrl._compute(mattina)
        asyncio.run(ctrl._apply(first))
        self.assertEqual(richieste, [])
        self.assertIsNone(ctrl._vane_restored_on)

        dopo = mattina + timedelta(minutes=5)
        ctrl.hass.states.values["climate.test"].state = "cool"
        self._orologio(dopo)
        second = ctrl._compute(dopo)
        self.assertEqual(second.vane_h, "position_0")
        self.assertEqual(second.vane_v, "position_5")
        asyncio.run(ctrl._apply(second))
        self.assertEqual(
            richieste,
            [
                ("select.aletta_h", "position_0"),
                ("select.aletta_v", "position_5"),
            ],
        )
        self.assertEqual(ctrl._vane_restored_on, mattina.date())

    def test_failed_day_vane_restore_is_retried(self):
        ctrl = self._con_alette(posizioni=("swing", "position_0", "position_5"))
        ctrl.entry.options = dict(
            ctrl.entry.options,
            vane_day_horizontal="position_0",
            vane_day_vertical="position_5",
        )
        mattina = GIORNO.replace(hour=8, minute=0)
        tentativi = []

        async def fallisce(domain, service, entity_id, data=None):
            if domain == "select":
                tentativi.append((entity_id, data["option"]))
                # First evaluation: both axes fail. Second evaluation: both succeed.
                return len(tentativi) > 2
            return True

        ctrl._call_target = fallisce
        first = ctrl._compute(mattina)
        asyncio.run(ctrl._apply(first))
        self.assertIsNone(ctrl._vane_restored_on)

        second = ctrl._compute(mattina + timedelta(minutes=5))
        self.assertEqual(second.vane_h, "position_0")
        self.assertEqual(second.vane_v, "position_5")
        asyncio.run(ctrl._apply(second))
        self.assertEqual(len(tentativi), 4)
        self.assertEqual(ctrl._vane_restored_on, mattina.date())

        third = ctrl._compute(mattina + timedelta(minutes=10))
        self.assertIsNone(third.vane_h)
        self.assertIsNone(third.vane_v)

    def test_day_vane_restore_retries_with_one_axis_unconfigured(self):
        ctrl = self._con_alette(posizioni=("swing", "position_0", "position_5"))
        ctrl.entry.data = dict(ctrl.entry.data)
        ctrl.entry.data.pop("vane_vertical")
        ctrl.entry.options = dict(
            ctrl.entry.options,
            vane_day_horizontal="position_0",
            vane_day_vertical="position_5",
        )
        mattina = GIORNO.replace(hour=8, minute=0)
        tentativi = []

        async def fallisce_poi_riesce(domain, service, entity_id, data=None):
            if domain == "select":
                tentativi.append((entity_id, data["option"]))
                return len(tentativi) > 1
            return True

        ctrl._call_target = fallisce_poi_riesce
        asyncio.run(ctrl._apply(ctrl._compute(mattina)))
        self.assertEqual(tentativi, [("select.aletta_h", "position_0")])
        self.assertIsNone(ctrl._vane_restored_on)

        asyncio.run(ctrl._apply(ctrl._compute(mattina + timedelta(minutes=5))))
        self.assertEqual(
            tentativi,
            [
                ("select.aletta_h", "position_0"),
                ("select.aletta_h", "position_0"),
            ],
        )
        self.assertEqual(ctrl._vane_restored_on, mattina.date())

    def test_day_vane_restore_retries_with_one_axis_already_at_target(self):
        ctrl = self._con_alette(posizioni=("swing", "position_0", "position_5"))
        ctrl.hass.states.values["select.aletta_h"] = State(
            "position_0", {"options": ["swing", "position_0", "position_5"]}
        )
        ctrl.entry.options = dict(
            ctrl.entry.options,
            vane_day_horizontal="position_0",
            vane_day_vertical="position_5",
        )
        mattina = GIORNO.replace(hour=8, minute=0)
        tentativi = []

        async def fallisce_poi_riesce(domain, service, entity_id, data=None):
            if domain == "select":
                tentativi.append((entity_id, data["option"]))
                return len(tentativi) > 1
            return True

        ctrl._call_target = fallisce_poi_riesce
        asyncio.run(ctrl._apply(ctrl._compute(mattina)))
        self.assertEqual(tentativi, [("select.aletta_v", "position_5")])
        self.assertIsNone(ctrl._vane_restored_on)

        asyncio.run(ctrl._apply(ctrl._compute(mattina + timedelta(minutes=5))))
        self.assertEqual(
            tentativi,
            [
                ("select.aletta_v", "position_5"),
                ("select.aletta_v", "position_5"),
            ],
        )
        self.assertEqual(ctrl._vane_restored_on, mattina.date())

    def test_no_day_position_configured_leaves_the_vanes_alone(self):
        ctrl = self._con_alette(posizioni=("swing", "position_0", "position_5"))
        desired = ctrl._compute(GIORNO.replace(hour=8, minute=0))
        self.assertIsNone(desired.vane_h)
        self.assertIsNone(desired.vane_v)

    def test_a_hand_on_the_vanes_still_counts_as_manual(self):
        ctrl = self._con_alette()
        ctrl._last_aux_cmd["vane_horizontal"] = "swing"
        ctrl._settle_aux_until["vane_horizontal"] = NOW - timedelta(seconds=1)
        ctrl._maybe_flag_manual_switch(
            "vane_horizontal", Event(State("swing"), State("position_4"))
        )
        self.assertTrue(ctrl.override_active)

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
