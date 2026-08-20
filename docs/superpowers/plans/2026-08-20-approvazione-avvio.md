# Approvazione dell'avvio automatico Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quando il clima starebbe per partire da solo, chiedere il permesso su
Telegram con il quadro meteo delle ore successive, e non partire finche' non
arriva una risposta.

**Architecture:** L'integrazione annuncia, l'istanza chiede. Una sola opzione
nuova (`start_approval`, spenta di default) fa si' che nei due punti di avvio
il controller non parta, lanci un evento e marchi la giornata come gia' decisa
- riusando il contrassegno giornaliero che esiste ed e' gia' persistito, senza
nessuna macchina a stati nuova. Telegram e meteo vivono interamente nelle
automazioni sull'istanza, cosi' il codice condiviso su HACS non acquisisce
dipendenze.

**Tech Stack:** Python 3, `unittest` (la suite gira senza Home Assistant: si
esegue con `python3 test_regressions.py`, che installa stub minimi di
`homeassistant.*`). Sull'istanza: Home Assistant 2026.8, integrazione
`telegram_bot`, `weather.get_forecasts`.

**Spec:** `docs/superpowers/specs/2026-08-20-approvazione-avvio-design.md`

## Global Constraints

- La funzione e' **spenta di default** (`start_approval=False`): nessuna
  installazione esistente di questa integrazione HACS cambia comportamento
  finche' non la si accende a mano. Requisito, non dettaglio: va coperto da un
  test dedicato.
- **Nessuna dipendenza da Telegram o dal meteo nel repo.** L'integrazione
  lancia un evento generico e basta. Chi tocca `controller.py`, `const.py` o
  `config_flow.py` per parlare di Telegram sta sbagliando task.
- La ripresa dal riposo per notte fredda (`riparte_dal_riposo`,
  `_cold_night_resting`) **non chiede il permesso**: non e' un avvio nuovo.
- Nessun timeout con avvio automatico. Nessuna risposta significa spento.
- Ogni task nel repo finisce con `python3 test_regressions.py` interamente
  verde prima del commit. Partenza: 192 test.
- Le modifiche sull'istanza (Task 4 e 5) toccano la produzione: backup prima,
  e **il riavvio di Home Assistant va concordato con l'utente**, mai fatto di
  iniziativa.

---

### Task 1: Il cancello dell'approvazione nel controller

**Files:**
- Modify: `const.py:68` (accanto a `CONF_AUTO_START_SLEEP`), `const.py:157`
  (accanto a `DEFAULT_AUTO_START_SLEEP`), `const.py:434` (accanto a
  `EVENT_STARTED`)
- Modify: `controller.py:121` (import eventi), `controller.py:373`
  (`__init__`), `controller.py:2177-2198` (avvio serale),
  `controller.py:2214-2225` (avvio diurno), `controller.py:2356-2387`
  (`async_evaluate`)
- Test: `test_regressions.py`

**Interfaces:**
- Consumes: `START_REASON_DAY`, `START_REASON_NIGHT`, `HVAC_COOL`,
  `Desired`, `self._reachable_target()`, `self._house_average()`,
  `self._cfg()` (tutti gia' presenti in `controller.py`).
- Produces: in `const.py` le costanti `CONF_START_APPROVAL`
  (`"start_approval"`), `DEFAULT_START_APPROVAL` (`False`),
  `EVENT_APPROVAL_NEEDED` (`"clima_smart_avvio_richiesto"`) - consumate dal
  Task 2 (config flow) e dal Task 5 (automazioni). Sul controller
  l'attributo `self._approval_armed: dict | None`.
- L'evento porta: `entity_id`, `motivo`, `fase`, `casa`, `camera`,
  `esterna`, `target`. Il Task 5 costruisce il messaggio da questi campi:
  non cambiare i nomi senza aggiornare anche quello.

- [ ] **Step 1: Aggiungere le costanti in `const.py`**

Alla riga 68, dopo `CONF_AUTO_START_SLEEP = "auto_start_sleep"`, aggiungere:

```python
# Con questa accesa il controller non accende mai da solo: quando le
# condizioni di avvio scattano lancia un evento e lascia decidere una
# persona. Serve perche' le soglie misurate non sanno tutto - il 20 agosto
# 2026 l'avvio e' scattato a regola d'arte un'ora prima di un temporale che
# ha portato l'esterna da 30 a 22 gradi da solo. Chi ascolta l'evento (una
# automazione, fuori di qui) chiede e poi accende. Spenta di default:
# nessuna installazione esistente cambia comportamento.
CONF_START_APPROVAL = "start_approval"
```

Alla riga 157, dopo `DEFAULT_AUTO_START_SLEEP = False`, aggiungere:

```python
DEFAULT_START_APPROVAL = False
```

Alla riga 434, dopo `EVENT_STARTED = "clima_smart_avviato"`, aggiungere:

```python
# Lanciato quando il controller avrebbe avviato ma `start_approval` glielo
# impedisce: chi ascolta chiede a una persona e, se acconsente, accende.
# Dati: entity_id, motivo, fase, casa, camera, esterna, target.
EVENT_APPROVAL_NEEDED = "clima_smart_avvio_richiesto"
```

- [ ] **Step 2: Verificare le costanti**

`const.py` non importa `homeassistant`, quindi si importa senza stub:

```bash
cd /root/code/clima_smart
python3 -c "
import const
assert const.CONF_START_APPROVAL == 'start_approval'
assert const.DEFAULT_START_APPROVAL is False
assert const.EVENT_APPROVAL_NEEDED == 'clima_smart_avvio_richiesto'
print('OK costanti')
"
```

Expected: `OK costanti`.

- [ ] **Step 3: Scrivere i test (falliranno: RED)**

Aggiungere in `test_regressions.py`, subito dopo il metodo
`test_winter_heat_disabled_by_default` (cercare quella stringa: e' l'ultimo
test della sezione invernale) e prima di
`test_cool_morning_stops_a_running_unit`:

```python
    # --------------------------------------------- approvazione dell'avvio
    def _con_approvazione(self, room=28.0, altre=(28.0, 28.0, 28.0), outdoor=30.0):
        """Condizioni di avvio diurno gia' soddisfatte, con l'approvazione
        accesa. Il clima e' spento: e' il caso in cui il controller
        partirebbe da solo."""
        ctrl = self._smart_controller(room=room, outdoor=outdoor)
        ctrl.hass.states.values["climate.test"].state = "off"
        for i, v in enumerate(altre):
            ctrl.hass.states.values[f"sensor.stanza{i}"] = State(
                str(v), {"unit_of_measurement": "°C"}
            )
        ctrl.entry.data = dict(
            ctrl.entry.data,
            house_sensors=[f"sensor.stanza{i}" for i in range(len(altre))],
        )
        ctrl.entry.options = dict(
            ctrl.entry.options,
            auto_start_outdoor=26.0,
            auto_start_room=27.0,
            auto_start_house=27.5,
            morning_off_enabled=False,
            start_approval=True,
        )
        return ctrl

    def _eventi(self, ctrl, tipo):
        return [d for t, d in ctrl.hass.bus.eventi if t == tipo]

    def _pronto_a_valutare(self, ctrl, quando=GIORNO):
        """Quel che serve a `async_evaluate` per arrivare davvero alla logica.

        Tre inciampi, tutti gia' pagati altrove in questo file: senza
        `_restore_event` la passata esce subito ("attendo ripristino"); senza
        orologio fissato userebbe l'ora vera del calcolatore, e la prova
        cambierebbe risultato secondo l'ora in cui gira; e `_call` va sostituito
        perche' l'Hass finto non ha `services`, quindi un comando vero
        riempirebbe `_apply_errors` e i contrassegni non verrebbero mai marcati.
        """
        self._orologio(quando)
        ctrl._restore_event.set()
        inviati = []

        async def registra(domain, service, data):
            inviati.append((service, data))
            return True

        ctrl._call = registra
        return inviati

    def test_approval_blocks_the_daytime_start(self):
        """Con l'approvazione accesa il controller non accende: annuncia e
        aspetta che qualcuno decida."""
        ctrl = self._con_approvazione()
        desired = ctrl._compute(GIORNO)
        self.assertIsNone(desired.hvac)
        self.assertIn("chiedo il permesso", desired.reason)

    def test_approval_fires_the_event_with_the_numbers_to_decide_on(self):
        """L'evento deve bastare, da solo, a comporre il messaggio: motivo,
        fase e le tre temperature. Chi ascolta non deve rileggere gli stati."""
        ctrl = self._con_approvazione()
        self._pronto_a_valutare(ctrl)
        asyncio.run(ctrl.async_evaluate("prova"))
        eventi = self._eventi(ctrl, controller_module.EVENT_APPROVAL_NEEDED)
        self.assertEqual(len(eventi), 1)
        dati = eventi[0]
        self.assertEqual(dati["entity_id"], "climate.test")
        self.assertEqual(dati["fase"], "day")
        self.assertIn("casa", dati["motivo"])
        self.assertAlmostEqual(dati["casa"], 28.0)
        self.assertAlmostEqual(dati["camera"], 28.0)
        self.assertAlmostEqual(dati["esterna"], 30.0)
        self.assertIsNotNone(dati["target"])

    def test_approval_asks_once_per_day(self):
        """Chiesto una volta, non si richiede: il contrassegno del giorno
        viene marcato come se l'avvio fosse avvenuto, cosi' un silenzio o un
        no chiudono la questione senza bisogno di altro stato."""
        ctrl = self._con_approvazione()
        self._pronto_a_valutare(ctrl)
        asyncio.run(ctrl.async_evaluate("prima"))
        self.assertEqual(ctrl._day_start_done_on, GIORNO.date())
        asyncio.run(ctrl.async_evaluate("seconda"))
        eventi = self._eventi(ctrl, controller_module.EVENT_APPROVAL_NEEDED)
        self.assertEqual(len(eventi), 1, "non deve richiedere nella stessa giornata")

    def test_approval_survives_a_restart(self):
        """Un riavvio nel pomeriggio non deve far ripartire le domande: il
        contrassegno e' gia' fra quelli persistiti."""
        ctrl = self._con_approvazione()
        self._pronto_a_valutare(ctrl)
        asyncio.run(ctrl.async_evaluate("prima"))
        asyncio.run(ctrl._async_save_memoria())
        dopo = self._riavvia(ctrl)
        self.assertEqual(dopo._day_start_done_on, GIORNO.date())

    def test_approval_blocks_the_evening_start_too(self):
        """Anche l'avvio della notte fonda chiede il permesso, e se nessuno
        risponde la notte fonda non parte."""
        ctrl = self._con_approvazione(room=26.0)
        self._orari(ctrl, target_sleep=22.0)   # notte fonda dalle 23:30
        ctrl.entry.options = dict(ctrl.entry.options, auto_start_sleep=True)
        # Dentro i trenta minuti di finestra dell'avvio serale, non prima:
        # alle 23:05 la fase sarebbe ancora `night` e il ramo non si aprirebbe.
        sera = NOW.replace(hour=23, minute=35)
        desired = ctrl._compute(sera)
        self.assertIsNone(desired.hvac)
        self.assertIn("chiedo il permesso", desired.reason)

    def test_approval_does_not_ask_to_resume_from_the_cold_night_rest(self):
        """La ripresa dal riposo per notte fredda non e' un avvio nuovo: e' il
        rientro da una pausa decisa dal controller su un'unita' che era gia'
        accesa col consenso dell'utente. Chiedere li' sarebbe rumore."""
        ctrl = self._con_approvazione(room=26.0, outdoor=15.0)
        self._orari(ctrl, target_sleep=22.0)
        ctrl.entry.options = dict(
            ctrl.entry.options, night_start_outdoor=20.0, summer_threshold=5.0
        )
        ctrl.hass.states.values["sensor.comodino"] = State("21.0", {})
        ctrl.entry.data = dict(ctrl.entry.data, room_sensor="sensor.comodino")
        notte = NOW.replace(hour=2, minute=0)
        ctrl.hass.states.values["climate.test"].state = "cool"
        self.assertEqual(ctrl._compute(notte).hvac, "off")   # entra in riposo
        self.assertTrue(ctrl._cold_night_resting)
        ctrl.hass.states.values["climate.test"].state = "off"
        ctrl.hass.states.values["sensor.comodino"] = State("33.0", {})
        ripresa = ctrl._compute(NOW.replace(hour=3, minute=0))
        self.assertEqual(ripresa.hvac, "cool")
        self.assertNotIn("chiedo il permesso", ripresa.reason)

    def test_without_approval_nothing_changes(self):
        """Spenta - il default - il comportamento resta quello di sempre:
        nessun evento, avvio normale. Protegge ogni altra installazione."""
        ctrl = self._con_approvazione()
        ctrl.entry.options = dict(ctrl.entry.options, start_approval=False)
        inviati = self._pronto_a_valutare(ctrl)
        asyncio.run(ctrl.async_evaluate("prova"))
        self.assertEqual(self._eventi(ctrl, controller_module.EVENT_APPROVAL_NEEDED), [])
        # Positiva, non solo negativa: senza questa la prova passerebbe anche
        # se il controller non avesse fatto proprio nulla.
        self.assertIn("set_hvac_mode", [s for s, _ in inviati])
        avviati = self._eventi(ctrl, controller_module.EVENT_STARTED)
        self.assertEqual(len(avviati), 1, "deve essere partito davvero")
```

- [ ] **Step 4: Eseguire la suite e confermare il fallimento (RED)**

```bash
cd /root/code/clima_smart
python3 test_regressions.py 2>&1 | tail -40
```

Expected: fallimenti (`AttributeError` su
`controller_module.EVENT_APPROVAL_NEEDED`, e i test che si aspettano
`chiedo il permesso`) per i sette test nuovi. I 192 precedenti devono restare
verdi: se ne fallisce uno vecchio, fermarsi e capire perche'.

- [ ] **Step 5: Importare le costanti in `controller.py`**

Nel blocco import da `.const`, accanto alle altre `CONF_*`, aggiungere
`CONF_START_APPROVAL,`; accanto alle `DEFAULT_*`, `DEFAULT_START_APPROVAL,`;
e alla riga 121, dopo `EVENT_STARTED,`, aggiungere `EVENT_APPROVAL_NEEDED,`.
(L'ordine alfabetico stretto non e' verificato da nessun test: basta che
compaiano nel blocco giusto.)

- [ ] **Step 6: Stato iniziale in `__init__`**

Alla riga 373, subito dopo `self._sleep_start_armed = False`, aggiungere:

```python
        # I dati dell'evento di richiesta, armati da `_compute` e lanciati da
        # `async_evaluate`: stesso schema degli altri contrassegni, ma qui non
        # c'e' nessun comando da mandare all'unita', quindi non dipende
        # dall'esito di `_apply`.
        self._approval_armed: dict | None = None
```

- [ ] **Step 7: Il metodo che legge l'opzione**

Aggiungere subito prima di `def _day_start_due(` (cercare quella stringa):

```python
    def _start_approval(self) -> bool:
        """Se l'avvio deve passare da una persona invece di scattare da solo."""
        valore = self._cfg(CONF_START_APPROVAL, DEFAULT_START_APPROVAL)
        return bool(valore) if valore is not None else DEFAULT_START_APPROVAL
```

- [ ] **Step 8: Il cancello sull'avvio serale**

Alla riga 2178, sostituire:

```python
            if notte_fonda and (riparte_dal_riposo or self._sleep_start_due(now)):
                self._sleep_start_armed = True
```

con:

```python
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
```

- [ ] **Step 9: Il cancello sull'avvio diurno**

Alla riga 2214, sostituire:

```python
            if perche is not None:
                self._sleep_start_armed = True
```

con:

```python
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
```

- [ ] **Step 10: Lanciare l'evento e marcare la giornata**

Alla riga 2360, dopo `self._morning_cool_off_armed = False`, aggiungere
l'azzeramento:

```python
                self._approval_armed = None
```

E subito dopo il blocco `if self._sleep_start_armed and not self._apply_errors:`
(quello che finisce con la parentesi di `async_fire(EVENT_STARTED, {...})`,
riga 2387), aggiungere:

```python
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
```

- [ ] **Step 11: Eseguire la suite (GREEN)**

```bash
cd /root/code/clima_smart
python3 test_regressions.py 2>&1 | tail -20
```

Expected: `Ran 199 tests` (192 + 7), `OK`, nessun `FAIL` ne' `ERROR`.

- [ ] **Step 12: Commit**

```bash
cd /root/code/clima_smart
git add const.py controller.py test_regressions.py
git commit -m "$(cat <<'EOF'
Il clima puo' chiedere il permesso prima di partire

Nuova opzione start_approval, spenta di default: quando e' accesa, nei due
punti in cui il controller avvierebbe - di giorno e la sera per la notte
fonda - non parte, lancia l'evento clima_smart_avvio_richiesto con motivo,
fase e temperature, e marca la giornata come gia' decisa. Chi ascolta
l'evento (una automazione, fuori dall'integrazione) chiede a una persona e
se acconsente accende; da li' il controller governa come sempre.

Il "chiedi una volta sola" e il "dopo un no non insistere" riusano il
contrassegno giornaliero che esisteva gia' ed era gia' persistito: nessuna
macchina a stati nuova.

La ripresa dal riposo per notte fredda non chiede: non e' un avvio nuovo.

Nessuna dipendenza da Telegram o dal meteo qui: l'integrazione annuncia e
basta.

7 nuovi test (199 totali).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: L'opzione nell'interfaccia

**Files:**
- Modify: `config_flow.py` (blocchi import `CONF_*` e `DEFAULT_*`, e lo
  schema delle opzioni accanto a `CONF_AUTO_START_SLEEP`)
- Modify: `translations/it.json`, `translations/en.json`
  (`options.step.init.data`)

**Interfaces:**
- Consumes: `CONF_START_APPROVAL`, `DEFAULT_START_APPROVAL` dal Task 1.
- Produces: il campo nel modulo delle opzioni; nessuna interfaccia di codice
  per i task successivi.

- [ ] **Step 1: Importare le costanti**

In `config_flow.py`, nel blocco import da `.const`, aggiungere
`CONF_START_APPROVAL,` fra le `CONF_*` e `DEFAULT_START_APPROVAL,` fra le
`DEFAULT_*`.

- [ ] **Step 2: Aggiungere il campo allo schema**

Cercare nello schema delle opzioni la voce esistente:

```python
                vol.Required(
                    CONF_AUTO_START_SLEEP,
                    default=_num(CONF_AUTO_START_SLEEP, DEFAULT_AUTO_START_SLEEP),
                ): bool,
```

e aggiungere **subito dopo**:

```python
                vol.Required(
                    CONF_START_APPROVAL,
                    default=_num(CONF_START_APPROVAL, DEFAULT_START_APPROVAL),
                ): bool,
```

- [ ] **Step 3: Le etichette, piu' quella mancante di `morning_off_enabled`**

Eseguire:

```bash
cd /root/code/clima_smart
python3 << 'PYEOF'
import json, collections

payload = {
    "it": {
        "start_approval": "Chiedi il permesso prima di avviare (invece di partire da solo)",
        "morning_off_enabled": "Spegni al mattino all'orario fisso e attendi l'inizio del giorno",
    },
    "en": {
        "start_approval": "Ask for permission before starting (instead of starting by itself)",
        "morning_off_enabled": "Switch off in the morning at the fixed time and wait for the day to begin",
    },
}
for lang, labels in payload.items():
    path = f"translations/{lang}.json"
    with open(path) as f:
        d = json.load(f, object_pairs_hook=collections.OrderedDict)
    d["options"]["step"]["init"]["data"].update(labels)
    with open(path, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(path, "ok")
PYEOF
```

`morning_off_enabled` era senza etichetta da prima di questo lavoro e
compariva nel modulo come chiave grezza: e' una riga, si sistema qui.

- [ ] **Step 4: Verificare**

`config_flow.py` importa `voluptuous` e `homeassistant.helpers.selector`, non
installati nel sandbox: si puo' solo controllarne la sintassi.

```bash
cd /root/code/clima_smart
python3 -c "import ast; ast.parse(open('config_flow.py').read()); print('OK sintassi')"
python3 -c "
import json
for lang in ('it','en'):
    d=json.load(open(f'translations/{lang}.json'))
    data=d['options']['step']['init']['data']
    assert 'start_approval' in data, lang
    assert 'morning_off_enabled' in data, lang
    print(lang, 'ok:', data['start_approval'])
"
python3 test_regressions.py 2>&1 | tail -5
```

Expected: `OK sintassi`, le due etichette stampate, `Ran 199 tests`, `OK`.

- [ ] **Step 5: Commit**

```bash
cd /root/code/clima_smart
git add config_flow.py translations/it.json translations/en.json
git commit -m "$(cat <<'EOF'
L'approvazione dell'avvio si accende dall'interfaccia

Aggiunta anche l'etichetta di morning_off_enabled, che mancava da prima e
compariva nel modulo come chiave grezza.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Versione, verifica del repo, pubblicazione

**Files:**
- Modify: `manifest.json:4`

**Interfaces:**
- Consumes: nulla.
- Produces: manifest a `1.18.0`, `main` pubblicato su GitHub.

- [ ] **Step 1: Aggiornare la versione**

In `manifest.json` cambiare `"version": "1.17.0",` in `"version": "1.18.0",`.

- [ ] **Step 2: Verifica completa**

```bash
cd /root/code/clima_smart
python3 -c "import json; json.load(open('manifest.json')); print('OK json')"
python3 -c "import ast; [ast.parse(open(f).read()) for f in ('controller.py','const.py','config_flow.py','number.py','sensor.py')]; print('OK sintassi')"
python3 test_regressions.py 2>&1 | tail -5
git diff --check
```

Expected: `OK json`, `OK sintassi`, `Ran 199 tests`, `OK`, nessun output da
`git diff --check`.

- [ ] **Step 3: Commit e pubblicazione**

```bash
cd /root/code/clima_smart
git add manifest.json
git commit -m "$(cat <<'EOF'
Clima Smart 1.18.0 - il clima chiede il permesso prima di partire

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
git push origin main
git log --oneline -4
```

---

### Task 4: Installazione dell'integrazione e del bot sull'istanza

**PRODUZIONE.** Questo task modifica l'istanza Home Assistant di casa. Backup
prima di ogni scrittura, e **il riavvio va chiesto all'utente**: non
riavviare di iniziativa, e mai di notte.

**Files (sull'host `homeassistant`, non nel repo):**
- Modify: `/config/secrets.yaml` (creare se assente)
- Modify: `/config/configuration.yaml` (blocco `telegram_bot` e `notify`)
- Copy: `const.py`, `controller.py`, `config_flow.py`, `translations/it.json`,
  `translations/en.json`, `manifest.json` in
  `/config/custom_components/clima_smart/`

**Interfaces:**
- Consumes: i file del repo dopo il Task 3.
- Produces: un servizio di notifica Telegram funzionante sull'istanza, che il
  Task 5 usa; l'opzione `start_approval` disponibile nelle opzioni.

- [ ] **Step 1: Backup**

```bash
timeout 20 ssh homeassistant "cp /config/configuration.yaml /config/configuration.yaml.bak-prima-telegram-\$(date +%Y%m%d-%H%M%S)"
timeout 20 ssh homeassistant "tar czf /config/clima_smart-prima-di-1.18.0-\$(date +%Y%m%d-%H%M%S).tar.gz -C /config/custom_components clima_smart"
timeout 20 ssh homeassistant "ls -la /config/configuration.yaml.bak-prima-telegram-* /config/clima_smart-prima-di-1.18.0-*"
```

Expected: i due file elencati.

- [ ] **Step 2: Il token in `secrets.yaml`**

Il token sta in
`/tmp/claude-0/-root-code/7ea276ac-6d53-4105-9b70-2e2c4802a8f4/scratchpad/tg_token`
(gia' verificato: bot `@climasmartz_bot`, chat id `8233212`). Va in
`secrets.yaml`, **mai** in chiaro in `configuration.yaml` e mai nel repo.

```bash
TOKEN=$(cat /tmp/claude-0/-root-code/7ea276ac-6d53-4105-9b70-2e2c4802a8f4/scratchpad/tg_token)
timeout 20 ssh homeassistant "touch /config/secrets.yaml && grep -q '^telegram_bot_token:' /config/secrets.yaml || echo 'telegram_bot_token: \"$TOKEN\"' >> /config/secrets.yaml"
timeout 20 ssh homeassistant "grep -c '^telegram_bot_token:' /config/secrets.yaml"
```

Expected: `1`. Non stampare mai il contenuto del token nell'output.

- [ ] **Step 3: Il blocco Telegram in `configuration.yaml`**

Scaricare il file, modificarlo in locale, ricaricarlo (l'host non ha
`python3` e ha solo busybox: si elabora sempre qui e si rimanda su).

Aggiungere in coda a `/config/configuration.yaml`:

```yaml
# =============================================================================
# TELEGRAM
# =============================================================================
# Il bot con cui Clima Smart chiede il permesso di avviarsi. Il token sta in
# secrets.yaml: e' una password a tutti gli effetti, chi ce l'ha comanda il
# bot. `allowed_chat_ids` e' la difesa vera - senza, chiunque scoprisse il
# nome del bot potrebbe premere i pulsanti di casa.
telegram_bot:
  - platform: polling
    api_key: !secret telegram_bot_token
    allowed_chat_ids:
      - 8233212

notify:
  - platform: telegram
    name: telegram_clima
    chat_id: 8233212
```

- [ ] **Step 4: Validare la configurazione**

```bash
timeout 20 hass post /api/config/core/check_config '{}'
```

Expected: `{"result":"valid","errors":null,...}`. Se non e' valido,
**fermarsi**: correggere prima di andare avanti, non riavviare mai con una
configurazione non valida.

- [ ] **Step 5: Copiare i file dell'integrazione**

```bash
cd /root/code/clima_smart
for f in const.py controller.py config_flow.py manifest.json translations/it.json translations/en.json; do
  scp -q "$f" "homeassistant:/config/custom_components/clima_smart/$f" && echo "copiato $f"
done
timeout 20 ssh homeassistant "grep version /config/custom_components/clima_smart/manifest.json"
```

Expected: sei righe `copiato`, e `"version": "1.18.0",`.

- [ ] **Step 6: CHIEDERE IL RIAVVIO ALL'UTENTE**

Non riavviare di iniziativa. Dire all'utente che tutto e' pronto e che serve
un riavvio di Home Assistant (circa quaranta secondi di indisponibilita'),
e attendere il suo assenso esplicito. Se dice di aspettare, fermarsi qui: i
file copiati non fanno nulla finche' non si riavvia.

- [ ] **Step 7: Riavviare e attendere**

Solo dopo l'assenso:

```bash
timeout 15 hass call homeassistant restart '{}'
```

Poi attendere il ritorno con un ciclo (non un `sleep` fisso):

```bash
until timeout 8 hass states 2>/dev/null | grep -q "sensor.clima_smart_fase"; do sleep 3; done
echo "HA tornato su"
```

- [ ] **Step 8: Verificare**

```bash
timeout 20 hass states 2>/dev/null | grep -iE "^notify.telegram|^sensor.clima_smart"
timeout 20 ssh homeassistant "grep -iE 'error|exception|traceback' /config/home-assistant.log" | grep -viE "mini_pc_potenza_cpu|dlna_dms|pychromecast|solax|Nest comodino|lg_thinq" | head -5
```

Expected: `notify.telegram_clima` presente, i sensori `clima_smart` presenti,
nessun errore nuovo nel log.

- [ ] **Step 9: Prova di invio dall'istanza**

```bash
timeout 20 hass call notify.telegram_clima '{"message": "Prova dall'"'"'istanza: il canale funziona."}'
```

Expected: nessun errore, e il messaggio arriva sul telefono dell'utente.
Chiedere conferma all'utente che sia arrivato.

---

### Task 5: Le automazioni che chiedono e reagiscono

**PRODUZIONE.** Modifica `automations.yaml` sull'istanza. Le automazioni si
ricaricano senza riavviare (`automation reload`), quindi qui non serve
fermare Home Assistant.

**Files (sull'host `homeassistant`):**
- Modify: `/config/automations.yaml`

**Interfaces:**
- Consumes: l'evento `clima_smart_avvio_richiesto` coi campi `entity_id`,
  `motivo`, `fase`, `casa`, `camera`, `esterna`, `target` (Task 1);
  `notify.telegram_clima` (Task 4).
- Produces: nulla per i task successivi.

- [ ] **Step 1: Backup**

```bash
timeout 20 ssh homeassistant "cp /config/automations.yaml /config/automations.yaml.bak-prima-approvazione-\$(date +%Y%m%d-%H%M%S)"
timeout 20 ssh homeassistant "grep -c '^- id:\|^- alias:' /config/automations.yaml"
```

Annotare il numero di automazioni: alla fine devono essere due in piu'.

- [ ] **Step 2: Scrivere le due automazioni**

Scaricare `automations.yaml` in locale, aggiungere in coda, ricaricare.

```yaml
- id: clima_smart_chiedi_permesso_avvio
  alias: Clima Smart - chiedi il permesso di avviare
  description: 'Il controller ha deciso che partirebbe ma l''approvazione e'' accesa:
    lancia l''evento e aspetta. Qui si compone la domanda con il quadro meteo delle
    ore successive - il motivo per cui questa funzione esiste e'' proprio quello: il
    20 agosto 2026 l''avvio e'' scattato a regola d''arte un''ora prima di un temporale
    che ha portato l''esterna da 30 a 22 gradi da solo. Il messaggio va su Telegram
    coi pulsanti e in parallelo sull''iPhone: se il bot fosse irraggiungibile, senza
    quella copia si resterebbe senza clima e senza avviso, perche'' la giornata
    risulta gia'' decisa.'
  triggers:
  - trigger: event
    event_type: clima_smart_avvio_richiesto
  conditions: []
  actions:
  - action: weather.get_forecasts
    target:
      entity_id: weather.forecast_casa
    data:
      type: hourly
    response_variable: previsioni
  - variables:
      ore: '{{ (previsioni["weather.forecast_casa"].forecast | default([]))[:5] }}'
      meteo: >-
        {% set righe = namespace(t=[]) %}
        {% for o in ore %}
        {% set righe.t = righe.t + [(o.datetime | as_datetime | as_local).strftime("%H:%M")
        ~ "  " ~ (o.temperature | round(0) | int) ~ "°" ~ (("  " ~ (o.precipitation
        | round(1)) ~ " mm") if (o.precipitation | float(0)) > 0 else "")] %}
        {% endfor %}
        {{ righe.t | join("\n") }}
      pioggia: '{{ ore | map(attribute="precipitation") | map("float", 0) | sum | round(1)
        }}'
      testo: >-
        Clima Smart vorrebbe partire.

        Motivo: {{ trigger.event.data.motivo }}
        Casa {{ trigger.event.data.casa | round(1) }}, camera {{ trigger.event.data.camera
        | round(1) }}, esterna {{ trigger.event.data.esterna | round(1) }}.
        Target che imposterebbe: {{ trigger.event.data.target }}.

        Prossime ore:
        {{ meteo }}
        {{ "Attenzione: sono previsti " ~ pioggia ~ " mm di pioggia." if pioggia | float(0)
        > 0.5 else "" }}
  - action: notify.telegram_clima
    data:
      message: '{{ testo }}'
      data:
        inline_keyboard:
        - 'Accendi:/clima_avvia, Lascia spento:/clima_no'
  - action: notify.mobile_app_iphone
    data:
      title: Clima Smart - chiede di partire
      message: '{{ testo }}'
      data:
        push:
          thread-id: clima-smart
  mode: single

- id: clima_smart_risposta_permesso_avvio
  alias: Clima Smart - risposta al permesso di avvio
  description: 'La risposta ai pulsanti. Accendi mette il clima in cool e basta: da
    li'' il controller, che sorveglia gia'' l''entita'', prende in mano target, ventola
    e alette alla prima valutazione. Lascia spento non fa nulla - la giornata e'' gia''
    marcata dal controller quando ha chiesto, quindi non richiedera''.'
  triggers:
  - trigger: event
    event_type: telegram_callback
    event_data:
      data: /clima_avvia
    id: avvia
  - trigger: event
    event_type: telegram_callback
    event_data:
      data: /clima_no
    id: no
  conditions: []
  actions:
  - choose:
    - conditions:
      - condition: trigger
        id: avvia
      sequence:
      - action: climate.set_hvac_mode
        target:
          entity_id: climate.clima_camera
        data:
          hvac_mode: cool
      - action: telegram_bot.answer_callback_query
        data:
          callback_query_id: '{{ trigger.event.data.id }}'
          message: Accendo.
      - action: telegram_bot.edit_message
        data:
          message_id: '{{ trigger.event.data.message.message_id }}'
          chat_id: '{{ trigger.event.data.chat_id }}'
          message: 'Acceso su tua conferma. Da qui in poi lo governa Clima Smart.'
    - conditions:
      - condition: trigger
        id: no
      sequence:
      - action: telegram_bot.answer_callback_query
        data:
          callback_query_id: '{{ trigger.event.data.id }}'
          message: Lascio spento.
      - action: telegram_bot.edit_message
        data:
          message_id: '{{ trigger.event.data.message.message_id }}'
          chat_id: '{{ trigger.event.data.chat_id }}'
          message: 'Lasciato spento. Non richiedo oggi; se cambi idea accendi pure a
            mano.'
  mode: single
```

- [ ] **Step 3: Caricare e ricaricare**

```bash
timeout 20 hass call automation reload '{}'
timeout 20 hass states 2>/dev/null | grep -c "^automation.clima_smart"
timeout 20 ssh homeassistant "grep -iE 'error' /config/home-assistant.log | tail -5"
```

Expected: due automazioni in piu' rispetto al conteggio dello Step 1, nessun
errore di caricamento.

- [ ] **Step 4: Accendere l'opzione sull'istanza**

L'opzione va accesa nelle opzioni della config entry. Il modulo salva tutti i
campi insieme, quindi vanno riletti e rimandati tutti, cambiando solo
`start_approval`:

```bash
timeout 20 hass post /api/config/config_entries/options/flow '{"handler": "01KZRQ04RG33JKDTGFP86HWREQ"}' > /tmp/flow.json
python3 -c "
import json
d=json.load(open('/tmp/flow.json'))
print('flow_id:', d['flow_id'])
vals={}
for f in d['data_schema']:
    n=f['name']
    v=f.get('default')
    if v is None:
        v=f.get('description',{}).get('suggested_value')
    vals[n]=v
vals['start_approval']=True
print(json.dumps(vals))
"
```

Poi inviare quel JSON allo stesso `flow_id` con
`hass post /api/config/config_entries/options/flow/<flow_id> '<json>'`, e
verificare:

```bash
timeout 20 ssh homeassistant "cat /config/.storage/core.config_entries" | python3 -c "
import json,sys
for e in json.load(sys.stdin)['data']['entries']:
    if e['domain']=='clima_smart':
        o=e['options']
        print('start_approval =', o.get('start_approval'))
        print('auto_start_house =', o.get('auto_start_house'))
        print('winter_room_start =', o.get('winter_room_start'))
"
```

Expected: `start_approval = True`, e gli altri valori invariati
(`auto_start_house = 27.5`, `winter_room_start = 18.0`).

- [ ] **Step 5: Prova reale da capo a fondo**

Non aspettare che le condizioni scattino da sole. Provocare una richiesta
abbassando temporaneamente la soglia della casa sotto il valore attuale
(stesso metodo dello Step 4, cambiando solo `auto_start_house`), a clima
spento, in fascia giorno. Poi:

1. verificare che l'evento sia stato lanciato:
   `hass api /api/states/sensor.clima_smart_stato` deve dire
   "chiedo il permesso";
2. verificare che il messaggio Telegram sia arrivato **coi pulsanti**, e che
   sia arrivata anche la notifica sull'iPhone - chiedere conferma all'utente;
3. controllare che il quadro meteo nel messaggio sia sensato (ore e gradi
   plausibili, non vuoto);
4. premere **Accendi** e verificare che il clima si accenda davvero;
5. **verificare che NON sia scattato l'override manuale** - questo e' il
   punto piu' importante di tutta la prova:
   `hass api /api/states/sensor.clima_smart_stato` deve mostrare
   `override_attivo: false`. Se fosse `true`, il controller resterebbe fermo
   un'ora proprio dopo un consenso, che e' l'opposto di quel che serve: in
   quel caso **fermarsi e riferire**, la via alternativa (esporre un pulsante
   di consenso dall'integrazione, che fa partire il controller dall'interno)
   e' una modifica al repo, non una toppa da improvvisare qui;
6. rimettere `auto_start_house` al valore vero (27.5) e verificarlo.

- [ ] **Step 6: Riferire all'utente**

Riassumere: cosa e' stato installato, che l'opzione e' accesa, l'esito della
prova da capo a fondo, e in particolare se l'override e' scattato o no.

---

## Note per chi esegue

- I numeri di riga sono quelli del repo al commit `97a9e40`. Se il file e'
  cambiato, cercare le stringhe indicate invece di fidarsi del numero.
- L'host `homeassistant` non ha `python3` ed e' busybox: per elaborare un file
  lo si scarica qui, lo si modifica e lo si rimanda su.
- Il token Telegram non va mai stampato nell'output, ne' finire nel repo.
- Se uno step di verifica non da' l'output atteso, fermarsi e capire perche'
  prima di proseguire.
