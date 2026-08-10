# Clima Smart 1.12.4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pubblicare Clima Smart 1.12.4 con lo spegnimento fuori stagione di `dry` e impostare sul live `trim_min=23.0` con backup e rollback verificati.

**Architecture:** La correzione resta confinata alla guardia stagionale del controller e a un test regressivo. Il tuning è una modifica separata alle opzioni della config entry Home Assistant; codice e configurazione hanno snapshot e rollback indipendenti.

**Tech Stack:** Python 3, Home Assistant 2026.8.1 REST/WebSocket API, Samba SMB3, unittest, git, GitHub CLI.

## Global Constraints

- Modificare soltanto `controller.py`, `test_regressions.py`, `manifest.json`, la documentazione 1.12.4 e l'opzione live `trim_min`.
- Conservare invariati tutti gli altri dati e tutte le altre opzioni della config entry.
- Non eseguire scritture live prima di avere backup completo e rollback mirato verificati.
- Effettuare un solo riavvio Home Assistant e verificare almeno un ciclo periodico da 300 secondi.

---

### Task 1: Finalizzare il pacchetto 1.12.4

**Files:**
- Modify: `controller.py:1812-1818`
- Modify: `test_regressions.py:1750-1775`
- Modify: `manifest.json:3`

**Interfaces:**
- Consumes: `HVAC_COOL`, `HVAC_DRY`, `HVAC_OFF`, `SEASON_EXIT_CONFIRM_SECONDS`.
- Produces: manifest 1.12.4 e comportamento `Desired(hvac=HVAC_OFF)` per `dry` fuori stagione.

- [ ] **Step 1: Confermare il RED sul tag 1.12.3**

Eseguire il test aggiunto contro la copia del tag in `/tmp/clima_smart_1_12_3_redcheck`.

```bash
cd /tmp/clima_smart_1_12_3_redcheck
python3 -I test_regressions.py
```

Expected: un solo failure, `test_out_of_season_turns_off_dry_too`, con `None != 'off'`.

- [ ] **Step 2: Confermare l'implementazione minima**

```python
if cur_mode in (HVAC_COOL, HVAC_DRY):
    return Desired(hvac=HVAC_OFF, reason="fuori stagione: spengo raffrescamento")
```

- [ ] **Step 3: Impostare il manifest a 1.12.4**

Cambiare esclusivamente:

```json
"version": "1.12.4"
```

- [ ] **Step 4: Eseguire il GREEN completo**

```bash
python3 -I test_regressions.py
python3 -m compileall -q .
python3 -m json.tool manifest.json >/dev/null
python3 -m json.tool hacs.json >/dev/null
python3 -m json.tool translations/it.json >/dev/null
python3 -m json.tool translations/en.json >/dev/null
git diff --check
```

Expected: 159 test OK e tutti gli altri comandi con exit `0`.

- [ ] **Step 5: Committare esplicitamente lo scope**

```bash
git add controller.py test_regressions.py manifest.json
git commit -m "Fix dry shutdown outside cooling season"
```

---

### Task 2: Creare backup e rollback live

**Files:**
- Create at runtime: `/tmp/ha_clima_1_12_4.py`
- Create: `/root/code/backups/clima_smart_pre_1_12_4_<timestamp>/`
- Create: `/root/code/backups/clima_smart_pre_1_12_4_<timestamp>.tar.gz`
- Create at runtime: `/tmp/clima_smart_pre_1_12_4_options.private.json`

**Interfaces:**
- Consumes: `/root/code/.ha_token`, `/root/code/.smbcredentials`, config entry `01KXCSMQWF3WWC0VH22SFCF025`.
- Produces: backup Home Assistant con database incluso, file live originali e opzioni originali con `trim_min=22.0`.

- [ ] **Step 1: Verificare il preflight live**

Leggere `/api/`, `/api/config`, `backup/info`, config entry, manifest, clima e log. Richiedere `RUNNING`, entry `loaded`, manifest 1.12.3 e zero errori Clima Smart nuovi.

- [ ] **Step 2: Creare e verificare il backup completo**

Usare il comando WebSocket `backup/generate` con nome `pre_clima_smart_1_12_4_<timestamp>`, quindi interrogare `backup/info` finché lo stato torna `idle`. Verificare `homeassistant_included=true`, `database_included=true`, nessun elemento `failed_*` e almeno un agente con size maggiore di zero.

- [ ] **Step 3: Salvare file e configurazione mirati**

Scaricare via SMB `controller.py` e `manifest.json` live, più `.storage/core.config_entries`; estrarre nel file privato soltanto la voce `clima_smart`. Impostare permessi `600` sui dati privati.

- [ ] **Step 4: Verificare il rollback**

Creare l'archivio `.tar.gz`, elencarlo con `tar -tzf`, calcolare SHA-256 e verificare che `controller.py`, `manifest.json` e la configurazione filtrata siano presenti e leggibili.

---

### Task 3: Distribuire codice e tuning live

**Files:**
- Deploy: `controller.py`
- Deploy: `manifest.json`
- Update live option: `trim_min` from `22.0` to `23.0`

**Interfaces:**
- Consumes: commit verificato del Task 1 e rollback verificato del Task 2.
- Produces: file live byte-identici al branch e config entry con una sola differenza nelle opzioni.

- [ ] **Step 1: Caricare soltanto i due file necessari**

```bash
smbclient //192.168.0.170/config -A /root/code/.smbcredentials -m SMB3 \
  -c 'cd custom_components/clima_smart; put controller.py controller.py; put manifest.json manifest.json'
```

- [ ] **Step 2: Rileggere e confrontare prima del riavvio**

Scaricare entrambi i file in una nuova directory `/tmp/clima-smart-1.12.4-verify` e richiedere `cmp -s` positivo e SHA-256 uguale per entrambi. Verificare manifest 1.12.4.

- [ ] **Step 3: Riavviare una sola volta**

Chiamare `POST /api/services/homeassistant/restart`; se la richiesta va in timeout, attendere e interrogare senza inviare un secondo riavvio. Continuare soltanto quando `/api/` risponde e `/api/config` riporta `RUNNING`.

- [ ] **Step 4: Aggiornare l'opzione con il normale options flow**

Avviare `config_entries/options/flow/init` per la config entry, rileggere tutti i valori proposti, cambiare soltanto `trim_min` da `22.0` a `23.0`, inviare l'intero form e richiedere `create_entry` riuscito.

- [ ] **Step 5: Provare che nessun'altra opzione è cambiata**

Rileggere la sola voce `clima_smart` da `.storage/core.config_entries`; confrontare il dizionario precedente e successivo escludendo `trim_min`. Expected: dizionari uguali e `trim_min=23.0`.

---

### Task 4: Verificare runtime e pubblicare

**Files:**
- No additional production files.

**Interfaces:**
- Consumes: installazione live 1.12.4 e ramo git verificato.
- Produces: prova runtime, PR integrata e release GitHub 1.12.4.

- [ ] **Step 1: Verificare il live dopo il tuning**

Controllare entry `loaded`, manifest 1.12.4, master ON, modo smart, `trim_min=23.0`, override inattivo e nessun errore/traceback Clima Smart. Osservare un aggiornamento diagnostico con trigger `intervallo` entro 360 secondi.

- [ ] **Step 2: Eseguire una verifica locale fresca**

```bash
python3 -I test_regressions.py
python3 -m compileall -q .
python3 -m json.tool manifest.json >/dev/null
git diff --check
git status -sb
```

- [ ] **Step 3: Pubblicare ramo e PR**

Verificare `gh auth status`, eseguire `git push -u origin agent/clima-smart-1.12.4` e aprire una PR draft verso `main` con root cause, impatto e verifiche. Portarla ready solo dopo controlli GitHub verdi.

- [ ] **Step 4: Integrare e creare la release**

Eseguire merge non distruttivo della PR, verificare `origin/main`, quindi creare la release/tag `1.12.4` sul merge commit. Verificare che GitHub la riporti come release più recente e che gli artifact HACS contengano manifest 1.12.4.
