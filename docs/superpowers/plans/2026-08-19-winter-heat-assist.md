# Aiuto invernale ai caloriferi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementare e testare nel repo il ciclo di aiuto invernale che fa
scaldare attivamente la camera da letto quando i caloriferi non bastano,
lasciando inalterato il comportamento di ogni altra installazione finche' non
viene configurato a mano.

**Architecture:** Un nuovo blocco dentro `_compute`, al posto del ramo
passivo "fuori stagione: non tocco il riscaldamento". Due soglie
sull'aria di ripresa della camera (le stesse gia' lette per il
raffrescamento) fanno da isteresi naturale: sotto la soglia di avvio si
accende in `heat` verso il tetto, raggiunto il tetto si spegne. Una rete di
sicurezza legge la media delle altre stanze prima di ogni avvio. Stato
persistito fra un riavvio e l'altro con lo stesso schema gia' in uso per
`_cold_night`/`_cold_night_resting`.

**Tech Stack:** Python 3, `unittest` (nessun `pytest`/Home Assistant reale
disponibile nel sandbox: la suite si esegue con `python3 test_regressions.py`,
che installa stub minimi di `homeassistant.*` prima di importare il
controller).

**Spec:** `docs/superpowers/specs/2026-08-19-winter-heat-assist-design.md`

## Global Constraints

- Modificare soltanto `const.py`, `controller.py`, `test_regressions.py`,
  `config_flow.py`, `manifest.json`.
- La funzione resta **disattivata di default** (`winter_room_start=0.0`):
  nessuna installazione esistente cambia comportamento finche' non la
  configura a mano. Questo e' un requisito, non un dettaglio: verificarlo con
  un test dedicato.
- Nessuna distribuzione sull'istanza live in questo piano: lo spec lo dice
  esplicitamente, siamo ad agosto. L'ultimo task si ferma al commit.
- Ogni task deve terminare con `python3 test_regressions.py` interamente
  verde prima del commit.
- Non toccare la logica di raffrescamento, l'anello estivo o `_cold_night*`:
  il nuovo blocco vive esclusivamente dentro il ramo `if not summer:`.

---

### Task 1: Costanti e ciclo di decisione invernale

**Files:**
- Modify: `const.py:82-89` (accanto a `CONF_AUTO_START_OUTDOOR` /
  `CONF_NIGHT_START_OUTDOOR`) e `const.py:151-152` (accanto ai relativi
  `DEFAULT_*`)
- Modify: `controller.py:47` (blocco import `CONF_*`), `controller.py:97`
  (blocco import `DEFAULT_*`), `controller.py:342` (`__init__`),
  `controller.py:887` (`_memoria`), `controller.py:1014`
  (`_async_load_memoria`), `controller.py:1998-2002` (ramo `if not summer:`)
- Test: `test_regressions.py` (nuova sezione dopo i test del riposo per
  notte fredda)

**Interfaces:**
- Consumes: `HVAC_HEAT`, `HVAC_OFF`, `PHASE_SLEEP`, `PHASE_WIND_DOWN`,
  `self._house_average()`, `self._cfg(key, default)`, `Desired` (gia'
  definiti in `controller.py`).
- Produces: `CONF_WINTER_ROOM_START`, `CONF_WINTER_ROOM_TARGET`,
  `CONF_WINTER_HOUSE_CEILING`, `DEFAULT_WINTER_ROOM_START` (0.0),
  `DEFAULT_WINTER_ROOM_TARGET` (19.0), `DEFAULT_WINTER_HOUSE_CEILING` (0.0)
  in `const.py`; attributo persistito `self._winter_heating: bool` sul
  controller, usato da Task 2 solo per lettura diagnostica (nessuna nuova
  dipendenza verso l'esterno).

- [ ] **Step 1: Aggiungere le costanti in `const.py`**

Aprire `const.py`. Alla riga 82, dopo la costante esistente:

```python
CONF_AUTO_START_OUTDOOR = "auto_start_outdoor"
```

aggiungere, prima di `CONF_NIGHT_START_OUTDOOR` (riga 89):

```python
# Le due soglie dell'aiuto invernale, sulla stessa aria di ripresa gia'
# letta per il raffrescamento: sono gia' la propria isteresi (un grado di
# distanza fra avvio e tetto), non serve aggiungerne una separata. Zero
# disattiva tutto - il comportamento resta quello di sempre, passivo.
CONF_WINTER_ROOM_START = "winter_room_start"
CONF_WINTER_ROOM_TARGET = "winter_room_target"
# Rete di sicurezza: non accende se la media delle altre stanze e' gia' al
# tetto di casa. Zero disattiva il controllo (nessun tetto).
CONF_WINTER_HOUSE_CEILING = "winter_house_ceiling"
```

Alla riga 151, dopo:

```python
DEFAULT_AUTO_START_OUTDOOR = 0.0
```

aggiungere, prima di `DEFAULT_NIGHT_START_OUTDOOR = 20.0`:

```python
DEFAULT_WINTER_ROOM_START = 0.0    # zero: aiuto invernale disattivato
DEFAULT_WINTER_ROOM_TARGET = 19.0
DEFAULT_WINTER_HOUSE_CEILING = 0.0   # zero: nessun tetto casa
```

- [ ] **Step 2: Verificare le costanti con un'importazione diretta**

`const.py` non importa `homeassistant`, quindi si importa senza stub:

```bash
cd /root/code/clima_smart
python3 -c "
import const
assert const.CONF_WINTER_ROOM_START == 'winter_room_start'
assert const.CONF_WINTER_ROOM_TARGET == 'winter_room_target'
assert const.CONF_WINTER_HOUSE_CEILING == 'winter_house_ceiling'
assert const.DEFAULT_WINTER_ROOM_START == 0.0
assert const.DEFAULT_WINTER_ROOM_TARGET == 19.0
assert const.DEFAULT_WINTER_HOUSE_CEILING == 0.0
print('OK costanti')
"
```

Expected: `OK costanti`, nessun `AttributeError`.

- [ ] **Step 3: Scrivere i test del ciclo invernale (falliranno: RED)**

Aggiungere in `test_regressions.py`, subito dopo il metodo
`test_cold_night_rest_resumes_outside_the_start_window` (cercare quella
stringa per posizionarsi: e' l'ultimo test della sezione "notte fredda"
aggiunta stasera) e prima di `test_cool_morning_stops_a_running_unit`:

```python
    # ------------------------------------------------- aiuto invernale
    def _con_casa_inverno(self, room=17.0, altre=(17.0, 17.0, 17.0), outdoor=5.0):
        """Camera fredda fuori stagione, con le tre stanze collegate per il
        tetto di sicurezza. `_not_summer_since` e' gia' maturo - ancorato a
        mezzanotte meno il margine di conferma, non a `GIORNO`, cosi' resta
        valido per qualunque ora del giorno usino i singoli test (anche
        quelle precedenti a mezzogiorno, come la notte fonda): con l'ancora
        su `GIORNO` una chiamata delle due di notte avrebbe calcolato un
        tempo trascorso negativo e sarebbe rimasta, per sbaglio, dentro la
        stagione calda."""
        ctrl = self._smart_controller(room=room, outdoor=outdoor)
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
            winter_room_start=18.0,
            winter_room_target=19.0,
            winter_house_ceiling=20.0,
        )
        mezzanotte = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
        ctrl._not_summer_since = mezzanotte - timedelta(
            seconds=controller_module.SEASON_EXIT_CONFIRM_SECONDS
        )
        return ctrl

    def test_winter_heat_starts_below_the_start_threshold(self):
        """Sotto i 18 gradi, fuori stagione e da svegli, la pompa di calore
        aiuta i caloriferi puntando al tetto di 19."""
        ctrl = self._con_casa_inverno(room=17.5)
        ctrl.hass.states.values["climate.test"].state = "off"
        desired = ctrl._compute(GIORNO)
        self.assertEqual(desired.hvac, "heat")
        self.assertEqual(desired.setpoint, 19.0)
        self.assertTrue(ctrl._winter_heating)

    def test_winter_heat_stops_at_the_target(self):
        """Raggiunti i 19 gradi il ciclo si ferma: e' un tetto, non un
        anello da inseguire di continuo."""
        ctrl = self._con_casa_inverno(room=17.5)
        ctrl.hass.states.values["climate.test"].state = "off"
        ctrl._compute(GIORNO)   # avvia il ciclo
        self.assertTrue(ctrl._winter_heating)
        ctrl.hass.states.values["climate.test"].state = "heat"
        ctrl.hass.states.values["climate.test"].attributes[
            "current_temperature"
        ] = 19.0
        desired = ctrl._compute(GIORNO + timedelta(minutes=20))
        self.assertEqual(desired.hvac, "off")
        self.assertFalse(ctrl._winter_heating)

    def test_winter_heat_does_not_start_during_sleep(self):
        """Il sonno resta escluso: nemmeno una camera molto fredda deve
        accendere la pompa di calore mentre si dorme."""
        ctrl = self._con_casa_inverno(room=16.0)
        self._orari(ctrl)   # sleep 23:30-07:30 di default
        ctrl.hass.states.values["climate.test"].state = "off"
        desired = ctrl._compute(NOW.replace(hour=2, minute=0))
        self.assertIsNone(desired.hvac)
        self.assertFalse(ctrl._winter_heating)

    def test_winter_heat_stops_if_sleep_begins_mid_cycle(self):
        """Un ciclo gia' avviato si interrompe se la notte fonda entra prima
        che la camera raggiunga il tetto: il confine col sonno e' netto,
        nessuna eccezione per un ciclo gia' in corso."""
        ctrl = self._con_casa_inverno(room=17.5)
        self._orari(ctrl)
        ctrl.hass.states.values["climate.test"].state = "off"
        ctrl._compute(GIORNO)   # avvia di giorno
        self.assertTrue(ctrl._winter_heating)
        ctrl.hass.states.values["climate.test"].state = "heat"
        desired = ctrl._compute(NOW.replace(hour=2, minute=0))   # entra la notte fonda
        self.assertEqual(desired.hvac, "off")
        self.assertFalse(ctrl._winter_heating)

    def test_winter_heat_does_not_start_during_wind_down(self):
        """Nemmeno nella coda di wind-down, prima che il giorno cominci
        davvero."""
        ctrl = self._con_casa_inverno(room=16.0)
        self._orari(ctrl)   # morning_off_enabled default True -> wind_down 07:30-08:00
        ctrl.hass.states.values["climate.test"].state = "off"
        desired = ctrl._compute(NOW.replace(hour=7, minute=45))
        self.assertIsNone(desired.hvac)
        self.assertFalse(ctrl._winter_heating)

    def test_winter_heat_respects_the_house_ceiling(self):
        """Se la casa e' gia' a 20 gradi o oltre, la camera non deve
        aggiungersi: i caloriferi stanno gia' facendo il loro lavoro."""
        ctrl = self._con_casa_inverno(room=17.5, altre=(20.0, 20.0, 20.0))
        ctrl.hass.states.values["climate.test"].state = "off"
        desired = ctrl._compute(GIORNO)
        self.assertIsNone(desired.hvac)
        self.assertFalse(ctrl._winter_heating)

    def test_winter_heat_state_survives_a_restart(self):
        """Un riavvio a meta' ciclo non deve perdere il contesto: senza
        persistenza il ciclo ripartirebbe da capo invece di ricordare che
        stava gia' scaldando."""
        ctrl = self._con_casa_inverno(room=17.5)
        ctrl.hass.states.values["climate.test"].state = "off"
        ctrl._compute(GIORNO)
        self.assertTrue(ctrl._winter_heating)
        asyncio.run(ctrl._async_save_memoria())
        dopo = self._riavvia(ctrl)
        self.assertTrue(dopo._winter_heating)

    def test_winter_heat_disabled_by_default(self):
        """Senza configurare winter_room_start, il comportamento resta
        quello di sempre: passivo, non tocca il riscaldamento. Protegge
        ogni altra installazione di questa integrazione condivisa."""
        ctrl = self._smart_controller(room=15.0, outdoor=5.0)
        ctrl._not_summer_since = GIORNO - timedelta(
            seconds=controller_module.SEASON_EXIT_CONFIRM_SECONDS
        )
        desired = ctrl._compute(GIORNO)
        self.assertIsNone(desired.hvac)
        self.assertIn("non tocco il riscaldamento", desired.reason)
```

- [ ] **Step 4: Eseguire la suite e confermare il fallimento (RED)**

```bash
cd /root/code/clima_smart
python3 test_regressions.py 2>&1 | tail -40
```

Expected: `AttributeError` (`_con_casa_inverno`/`entry.options` non
riconosciuti come opzioni valide non e' un problema - il problema atteso e'
che `ctrl._winter_heating` non esiste, e che `desired.hvac` per
`test_winter_heat_starts_below_the_start_threshold` sia `None` invece di
`"heat"`) e diversi `FAIL`/`ERROR`, uno per ciascuno degli otto test nuovi.
Il resto della suite (181 test precedenti) deve restare verde: se anche un
test vecchio fallisce, fermarsi e capire perche' prima di proseguire.

- [ ] **Step 5: Importare le nuove costanti in `controller.py`**

Alla riga 47 del blocco import, dopo:

```python
    CONF_HOUSE_SENSORS,
```

aggiungere, in ordine alfabetico rispetto alle righe vicine (fra
`CONF_VANE_V,` e la fine del blocco, oppure semplicemente qui subito dopo
`CONF_HOUSE_SENSORS,` - l'ordine alfabetico stretto non e' verificato da
nessun test, basta che compaiano):

```python
    CONF_WINTER_ROOM_START,
    CONF_WINTER_ROOM_TARGET,
    CONF_WINTER_HOUSE_CEILING,
```

Alla riga 97 del blocco `DEFAULT_*`, dopo:

```python
    DEFAULT_NIGHT_START_OUTDOOR,
```

aggiungere:

```python
    DEFAULT_WINTER_ROOM_START,
    DEFAULT_WINTER_ROOM_TARGET,
    DEFAULT_WINTER_HOUSE_CEILING,
```

- [ ] **Step 6: Stato iniziale in `__init__`**

Alla riga 342, subito dopo:

```python
        self._cold_night_resting = False
```

aggiungere:

```python
        # Aiuto invernale: acceso o spento, con le due soglie configurate
        # (avvio/tetto) come propria isteresi - stesso schema di
        # _cold_night, stessa ragione di persistenza.
        self._winter_heating = False
```

- [ ] **Step 7: Persistenza - salvataggio**

Alla riga 887 (dentro `_memoria`), subito dopo:

```python
            "cold_night_resting": self._cold_night_resting,
```

aggiungere:

```python
            "winter_heating": self._winter_heating,
```

- [ ] **Step 8: Persistenza - caricamento**

Alla riga 1014 (dentro `_async_load_memoria`), subito dopo il blocco che
carica `riposo_notte`/`self._cold_night_resting` (le quattro righe che
iniziano con `riposo_notte = dati.get("cold_night_resting", False)`),
aggiungere:

```python
        scaldo_inverno = dati.get("winter_heating", False)
        self._winter_heating = (
            scaldo_inverno if isinstance(scaldo_inverno, bool) else False
        )
```

- [ ] **Step 9: Il ciclo di decisione, al posto del ramo passivo**

Alla riga 1998, sostituire integralmente:

```python
        if not summer:
            self.active_target = None
            if cooling_active:
                return Desired(hvac=HVAC_OFF, reason="fuori stagione: spengo raffrescamento")
            return Desired(reason="fuori stagione: non tocco il riscaldamento")
```

con:

```python
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
            if soglia_avvio <= 0 or target_inverno <= 0:
                # Aiuto invernale non configurato: comportamento di sempre.
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
                casa_libera = tetto_casa <= 0 or casa is None or casa < tetto_casa
                self._winter_heating = room < soglia_avvio and casa_libera
            if not self._winter_heating:
                self.active_target = None
                if cur_mode == HVAC_HEAT:
                    return Desired(
                        hvac=HVAC_OFF, reason="inverno: camera al tetto, mi fermo"
                    )
                return Desired(reason="fuori stagione: non tocco il riscaldamento")
            self.active_target = target_inverno
            return Desired(
                hvac=HVAC_HEAT,
                setpoint=target_inverno,
                reason=f"inverno: aiuto i caloriferi, target {target_inverno}",
            )

        self._winter_heating = False
```

L'ultima riga (`self._winter_heating = False`) e' **fuori** dal blocco
`if not summer:` (stessa indentazione dell'`if`, non al suo interno): tutti
i rami dentro il blocco terminano con un `return`, quindi quella riga viene
eseguita solo quando si e' in stagione calda, per azzerare lo stato invernale
quando la stagione torna. Verificare con attenzione l'indentazione dopo
l'incolla.

- [ ] **Step 10: Eseguire la suite e confermare il successo (GREEN)**

```bash
cd /root/code/clima_smart
python3 test_regressions.py 2>&1 | tail -20
```

Expected: `Ran 189 tests` (181 precedenti + 8 nuovi), `OK`, nessun `FAIL` ne'
`ERROR`.

- [ ] **Step 11: Commit**

```bash
cd /root/code/clima_smart
git add const.py controller.py test_regressions.py
git commit -m "$(cat <<'EOF'
Aiuto invernale ai caloriferi: ciclo a soglia sulla camera

Nel ramo "fuori stagione", oggi passivo, la pompa di calore aiuta
attivamente i caloriferi: sotto winter_room_start (default 0.0,
disattivato) si accende in heat verso winter_room_target, isteresi data
dalle due soglie stesse. Esclusa notte fonda e wind-down. Rete di
sicurezza: non parte se la media delle altre stanze e' gia' a
winter_house_ceiling o oltre. Stato persistito come _cold_night.

8 nuovi test (189 totali): avvio sotto soglia, arresto al tetto,
spegnimento se la notte fonda entra a meta' ciclo,
esclusione sonno e wind-down, tetto casa, sopravvivenza al riavvio,
disattivato di default (nessuna installazione esistente cambia
comportamento).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Esposizione nel config flow

**Files:**
- Modify: `config_flow.py:44` (blocco import `CONF_*`), `config_flow.py`
  (blocco import `DEFAULT_*`, vicino a `DEFAULT_NIGHT_START_OUTDOOR`),
  `config_flow.py:349-353` (schema, subito dopo la voce
  `CONF_NIGHT_START_OUTDOOR`)

**Interfaces:**
- Consumes: `CONF_WINTER_ROOM_START`, `CONF_WINTER_ROOM_TARGET`,
  `CONF_WINTER_HOUSE_CEILING` e i relativi `DEFAULT_*` (prodotti dal Task 1
  in `const.py`).
- Produces: tre nuovi campi nello schema delle opzioni, selezionabili
  dall'utente dall'interfaccia di Home Assistant.

- [ ] **Step 1: Importare le costanti**

In `config_flow.py`, riga 44, dopo:

```python
    CONF_NIGHT_START_OUTDOOR,
```

aggiungere:

```python
    CONF_WINTER_ROOM_START,
    CONF_WINTER_ROOM_TARGET,
    CONF_WINTER_HOUSE_CEILING,
```

Cercare `DEFAULT_NIGHT_START_OUTDOOR,` nello stesso file (blocco import
`DEFAULT_*`, poco piu' sotto) e aggiungere subito dopo:

```python
    DEFAULT_WINTER_ROOM_START,
    DEFAULT_WINTER_ROOM_TARGET,
    DEFAULT_WINTER_HOUSE_CEILING,
```

- [ ] **Step 2: Aggiungere i tre campi allo schema**

Alla riga 349, dopo il blocco esistente che termina con:

```python
                vol.Required(
                    CONF_NIGHT_START_OUTDOOR,
                    default=_num(
                        CONF_NIGHT_START_OUTDOOR, DEFAULT_NIGHT_START_OUTDOOR
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=45)),
```

aggiungere, prima della voce `CONF_AUTO_START_SLEEP` che segue:

```python
                vol.Required(
                    CONF_WINTER_ROOM_START,
                    default=_num(
                        CONF_WINTER_ROOM_START, DEFAULT_WINTER_ROOM_START
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=30)),
                vol.Required(
                    CONF_WINTER_ROOM_TARGET,
                    default=_num(
                        CONF_WINTER_ROOM_TARGET, DEFAULT_WINTER_ROOM_TARGET
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=30)),
                vol.Required(
                    CONF_WINTER_HOUSE_CEILING,
                    default=_num(
                        CONF_WINTER_HOUSE_CEILING, DEFAULT_WINTER_HOUSE_CEILING
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=30)),
```

- [ ] **Step 3: Verificare la sintassi**

`config_flow.py` importa `homeassistant.helpers.selector` e `voluptuous`,
non disponibili nel sandbox: non si puo' importare davvero, solo
verificarne la sintassi.

```bash
cd /root/code/clima_smart
python3 -c "import ast; ast.parse(open('config_flow.py').read()); print('OK sintassi config_flow')"
```

Expected: `OK sintassi config_flow`, nessuna eccezione.

- [ ] **Step 4: Eseguire comunque l'intera suite**

```bash
cd /root/code/clima_smart
python3 test_regressions.py 2>&1 | tail -10
```

Expected: `Ran 189 tests`, `OK` (questo task non tocca `controller.py`, la
suite deve restare identica al Task 1).

- [ ] **Step 5: Commit**

```bash
cd /root/code/clima_smart
git add config_flow.py
git commit -m "$(cat <<'EOF'
Esporre le soglie dell'aiuto invernale nel config flow

winter_room_start, winter_room_target, winter_house_ceiling
selezionabili dall'interfaccia Home Assistant come le altre soglie
esistenti, di default disattivati (0.0).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Versione e verifica finale

**Files:**
- Modify: `manifest.json:4`

**Interfaces:**
- Consumes: nessuna (solo la stringa di versione).
- Produces: manifest a `1.17.0`, verifica finale prima della pubblicazione.

- [ ] **Step 1: Aggiornare la versione**

In `manifest.json`, cambiare:

```json
  "version": "1.16.0",
```

in:

```json
  "version": "1.17.0",
```

- [ ] **Step 2: Verificare il JSON e l'intera suite**

```bash
cd /root/code/clima_smart
python3 -c "import json; json.load(open('manifest.json')); print('OK json')"
python3 -c "import ast; ast.parse(open('controller.py').read()); ast.parse(open('const.py').read()); ast.parse(open('config_flow.py').read()); print('OK sintassi')"
python3 test_regressions.py 2>&1 | tail -10
```

Expected: `OK json`, `OK sintassi`, `Ran 189 tests`, `OK`.

- [ ] **Step 3: Commit**

```bash
cd /root/code/clima_smart
git add manifest.json
git commit -m "$(cat <<'EOF'
Clima Smart 1.17.0 - aiuto invernale ai caloriferi

Versione che include il ciclo a soglia sulla camera per la stagione
fredda (disattivato di default) e le sue tre opzioni nel config flow.
Nessuna distribuzione sull'istanza in questo commit: siamo ad agosto,
l'installazione live avverra' prima dell'inverno.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
git log --oneline -5
```

- [ ] **Step 4: Pubblicare su GitHub**

```bash
cd /root/code/clima_smart
git push origin main
```

Expected: push accettato, nessun conflitto (il branch locale era gia'
allineato a `origin/main` prima di iniziare questo piano).

---

## Note per chi esegue

- Non installare nulla su Home Assistant: questo piano si ferma al repo.
  L'installazione live e' un passo separato, da fare piu' avanti, con lo
  stesso rito di backup/riavvio/verifica gia' descritto nei piani
  precedenti (`docs/superpowers/plans/2026-08-09-clima-smart-1.12.4.md` ne
  e' un esempio completo).
- Se un qualunque step di verifica non da' esattamente l'output atteso,
  fermarsi e capire perche' prima di passare allo step successivo - non
  proseguire "tanto probabilmente e' a posto".
- I numeri di riga indicati sono quelli del repo al 19 agosto 2026, subito
  dopo il commit `3b1b07a` (1.16.0) e `37fb171` (spec). Se nel frattempo il
  repo e' cambiato, cercare le stringhe indicate invece di fidarsi del
  numero di riga.
