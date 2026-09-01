# Clima Smart — dossier tecnico dell'impianto

**Ultimo aggiornamento: 1 settembre 2026, ore 23:45 (Europe/Rome).**
**Versione in funzione: 1.23.0.**

Questo documento è scritto perché possa essere letto da un'altra intelligenza
artificiale, o da un tecnico, senza avere accesso alla conversazione che l'ha
prodotto. Contiene solo misure fatte sull'impianto reale e la loro fonte. Dove
un numero è una stima e non una misura, **è scritto esplicitamente**.

**Come leggere le date.** Fra la stesura originale (6 agosto, versione 1.7.0) e
oggi sono passate sedici versioni. Le misure di agosto non sono state rifatte e
**restano etichettate con la loro data**: valgono per l'assetto di allora, che
non è quello di adesso. Dove una misura è stata rifatta il 1 settembre, i due
numeri stanno accanto. Nessun numero di agosto è stato aggiornato "a occhio".

---

## 1. L'impianto

| | |
|---|---|
| unità | Haier **AS35PBPHRA-PRE**, 12000 BTU, inverter |
| collocazione | camera da letto |
| superficie servita | trilocale di **80 m²**, la sola unità della casa |
| collegamento | cloud Haier (`hOn`) tramite integrazione custom `addhOn` |
| misura elettrica | **Shelly 2PM Gen3** su linea dedicata, lettura locale |
| controllo | integrazione custom `clima_smart` (repo `telard-pixel/clima_smart`) |

`clima_smart` **non crea** un'entità `climate`: pilota `climate.clima_camera`
tramite chiamate di servizio. Ogni installazione richiede il **riavvio di Home
Assistant Core** (il reload della entry non reimporta i moduli già caricati).

### Curva potenza–frequenza, misurata

**Misurata in luglio-agosto 2026, quando il sensore di frequenza funzionava
ancora. Oggi non è più rifacibile** (§2): resta l'unica fonte sugli Hz di questa
macchina, e va trattata come tale.

**Attenzione: la retta vale solo sopra i 28 Hz.** Sotto, la macchina ha uno
zoccolo fisso — ventole interna ed esterna, elettronica, minimo del compressore —
che la formula lineare non descrive affatto.

| Hz | W misurati | W/Hz | la retta direbbe |
|---|---|---|---|
| 12 | **233** | 19.4 | 18 ✗ |
| 18 | **320** | 17.8 | 125 ✗ |
| 28 | 369 | 13.2 | 302 |
| 32 | 385 | 12.0 | 372 |
| 40 | 509 | 12.7 | 514 ✓ |
| 45 | 623 | 13.8 | 602 ✓ |
| 56 | 772 | 13.8 | 797 ✓ |
| 71 | 1071 | 15.1 | 1063 ✓ |

```
sopra i 28 Hz:   W ≈ 17.7 × Hz − 194
sotto i 28 Hz:   la retta sbaglia fino a dieci volte
macchina spenta: 1.6 W
campo di modulazione osservato: 12 → 81 Hz
```

**Conseguenze da non dimenticare:**

1. Il rendimento migliore sta fra **28 e 45 Hz** (12-13 W/Hz). Sotto peggiora
   perché lo zoccolo domina, sopra i 56 peggiora perché sale a 15 W/Hz. La
   macchina passa già li' quasi tutto il suo tempo: 27.7% a 40 Hz, 18.8% a 45,
   13.5% a 32.
2. **Un secondo split non farebbe risparmiare.** Ogni macchina si porta dietro
   il proprio zoccolo da ~230 W, quindi due unita' a 20 Hz consumerebbero circa
   660 W contro i 509 di una sola a 40 Hz: stesso freddo, **il 30% in piu'**.
   Un secondo split si compra per il comfort — cucina e salotto in temperatura,
   porta della camera chiusa di notte — non per la bolletta, che salirebbe di un
   20-25%.
3. La vecchia formula da datasheet (22 W/Hz) sovrastimava del **55-69%** ed e'
   stata sostituita dalla misura dello Shelly.

---

## 2. I sensori, e i loro difetti

**Aggiornato il 1 settembre 2026.** Rispetto ad agosto la strumentazione è
cambiata in due punti che contano: **il termometro di camera esiste** (era
l'unico acquisto giustificato del §12) e **il sensore di frequenza del
compressore non c'è più**.

| grandezza | entità collegata oggi | difetto noto |
|---|---|---|
| temperatura camera (anello di controllo) | `climate.clima_camera` attributo `current_temperature` | **è l'aria di ripresa, non la stanza.** Un passo di ventola la sposta di **1.0 °C** in due minuti, verificato su ~40 transizioni indipendenti. Resta il riferimento del controllo perché è ciò che la macchina stessa insegue |
| temperatura camera (limite) | `sensor.bthome_sensor_89af_temperatura` | il termometro al comodino, **fuori dal getto**. Serve da limite, non da riferimento: messo al posto della ripresa il 6 agosto rendeva lo scarto sempre piccolo, la ventola non saliva mai e il compressore restava inchiodato a 46 Hz. Divario ripresa − comodino misurato il 23 agosto su 362 campioni contemporanei: **+1.9/+2.8 di giorno a porta aperta, +0.9/+1.1 di notte a porta chiusa**; dipende dalla porta, non dal compressore |
| esterna | `sensor.esterna_filtrata` (primaria), `sensor.meteo_montichiari_temperatura_precisa` (riserva) | la stazione Bresser dell'utente è installata al ristorante, **4.2 km da casa**. La catena filtrata/precisa è stata introdotta dopo la stesura originale |
| umidità | `sensor.umidita_media_casa` | non più il solo sensore d'ingresso: è una media di casa |
| media delle altre stanze | `sensor.salotto_temperatura`, `sensor.cucina_temperatura`, `sensor.temperatura_studio` | sono le tre collegate oggi all'anello di casa. Nascondono uno scarto da −0.5 a +1.6 secondo la stanza |
| **frequenza compressore** | `sensor.clima_camera_frequenza_compressore` — **DISABILITATO** | **non è affidabile**: smetteva di aggiornare e per farlo ripartire serviva a volte **staccare l'unità dalla rete elettrica**. Disabilitato dall'utente di proposito. Detto il 1 settembre 2026. **Non progettare verifiche che dipendano dagli Hz**: si ricavano semmai dalla potenza dello Shelly letta al contrario sulla curva del §1, sapendo che oltre gli 81 Hz osservati è estrapolazione |
| falso termometro | `sensor.camera_da_letto_temperatura_2` / `cucina_temperatura_2` | è la **temperatura interna della scheda** di uno Shelly 1 Gen4. Media settimanale 32.3 °C. Da ignorare |

**Conseguenza del termometro di camera:** la correzione setpoint, che ad agosto
valeva −1.0 ed era "la pezza che il sensore di stanza esiste per togliere", **oggi
è a 0.0**. La pezza è stata effettivamente tolta.

## 3. Assetto in funzione (1.23.0)

**Letto il 1 settembre 2026 dalla memoria della config entry**, non dai
predefiniti del codice: sono i 37 valori realmente in funzione.

### Ciclo giornaliero

| ora | comportamento |
|---|---|
| 23:00 → 08:00 | notte fonda (`sleep_start` 23:00, `sleep_end` 08:00), target **22.5** — che la macchina riceve come **23.0**, vedi §6.2 |
| dalle 22:00 | fascia notte (`night_start`) |
| 08:30 | spegnimento del mattino **disattivato** (`morning_off_enabled = False`, dal 12 agosto: di giorno il clima deve restare acceso) |
| dalle 10:00 | fascia giorno (`day_start`) |
| giorno | target dato dall'**anello di casa**, non più fisso: `house_target` 26.3 come linea, target camera fra `trim_min` 24.0 e `trim_max` 27.0 |

### I parametri, con la loro origine

| parametro | valore | origine |
|---|---|---|
| `target_home` | **24.0** | scelta utente (era 25.0 ad agosto) |
| `target_sleep` | 22.5 | scelta utente |
| `setpoint_offset` | **0.0** | era −1.0: tolto quando è arrivato il termometro di camera |
| `summer_threshold` | 19.0 | scelta utente |
| anello di casa | linea 26.3, trim 24.0–27.0, `trim_min_hot` 23.0 sopra `hot_outdoor` 36.0, `room_floor` 21.0 | introdotto dopo la stesura originale; una correzione ogni 45 minuti, un passo macchina alla volta |
| soglie avvio diurno | stanza **27.0**, casa **27.5**, esterna **26.0** | erano 27.0 / 26.5 / 29.0 ad agosto |
| `start_approval` | **True** | il controller non parte più da solo: lancia un evento e aspetta un sì su Telegram. **Nessun timeout: nessuna risposta significa spento** |
| `auto_start_sleep` | True | avvio automatico all'apertura del sonno |
| notte mite | `night_mild_outdoor` 22.0, `target_sleep_mild` 23.0 | se fuori è mite la notte fonda si accontenta |
| aiuto invernale | parte sotto 18.0, target camera 19.0, tetto casa 20.0 | fuori stagione aiuta i caloriferi |
| eco | banda 2.0, ON sotto 33.0, OFF sopra 34.0 | |
| adattivo sull'esterna | **disattivato** (`adaptive_outdoor_start = 0.0`) | ad agosto era attivo con partenza 33; misurato allora un effetto ≈ 0 |
| override manuale | 60 minuti | |
| alette | giorno `position_0` / `position_5`, **fisse anche di notte** | dal 13 agosto: oscillando mescolavano l'aria e il freddo non restava in basso |

**Non più esistente:** l'opzione `vane_sleep_position`, rimossa nella 1.23.0
perché dal 13 agosto non la leggeva più nessuno. Un valore orfano può restare
nella memoria della entry: è inerte.

## 4. Il bilancio energetico, misurato

### 4.1 Agosto 2026 (versione 1.7.0) — **misura storica, non più l'assetto attuale**


Media dei tre giorni pieni (2, 3, 4 agosto), giornata definita 23:00 → 23:00.
Fonte: statistiche a 5 minuti dello Shelly, coincidenti al grammo con
l'esportazione CSV fornita dall'utente.

| fascia | kWh | quota | W medi | kWh per grado‑ora consegnato |
|---|---|---|---|---|
| notte fonda 23:00‑07:30 | **3.728** | 30.7% | 439 | **0.1125** (una stanza sola) |
| coda 07:30‑08:30 | 0.409 | 3.4% | 409 | 0.186 |
| pausa 08:30‑10:00 | 0.022 | 0.2% | 15 | — |
| ripartenza 10:00‑11:30 | 1.137 | 9.3% | **758** | 0.165 |
| regime 11:30‑19:00 | **4.636** | **38.1%** | 618 | **0.0782** (tutta la casa) |
| sera 19:00‑23:00 | 2.229 | 18.3% | 557 | 0.0944 |
| **totale** | **12.161** | | | |

Singoli giorni: 12.064 · 12.112 · 12.310 kWh.
**365 kWh/mese, 32.8 € di sola materia energia a 0.09 €/kWh, cioè il 56% dei 655
kWh dichiarati per l'intera abitazione.**

- La fascia **più cara in assoluto** è il regime diurno (38%).
- La **più cara all'ora** è la ripartenza (758 W).
- La **più cara per grado consegnato** è la notte fonda: +44% rispetto al regime,
  e li consegna su **una stanza sola** invece che su 80 m².

---

### 4.2 Dieci giorni fino al 1 settembre 2026 (versioni 1.19 → 1.23)

Stesse fonti (statistiche orarie dello Shelly, giornata 23:00 → 23:00), lette il
1 settembre.

| giornata | kWh | esterna media 12–18 |
|---|---|---|
| 22/08 | 3.00 | 28.2 |
| 23/08 | 2.40 | 29.2 |
| 24/08 | 3.34 | 24.6 |
| 25/08 | 4.27 | 29.1 |
| 26/08 | 9.98 | 29.8 |
| 27/08 | 6.26 | 28.9 |
| 28/08 | 5.84 | 29.5 |
| 29/08 | 7.19 | 29.8 |
| 30/08 | 6.16 | 31.0 |
| 31/08 | 7.40 | 29.7 |
| **media** | **5.58** | **29.0** |

**Da 12.16 a 5.58 kWh al giorno: il 46% di prima**, con esterne pomeridiane
confrontabili (29.0 di media contro i 30.8–32.3 delle giornate di agosto usate
nel confronto del §6.3: oggi fa un po' meno caldo, non la metà).

**Da dove viene il dimezzamento, misurato.** Le due cause si separano:

| | agosto (1.7.0) | fine agosto (1.19→1.23) |
|---|---|---|
| ore in cui la macchina assorbe | **24** (girava praticamente sempre) | **16.1** |
| watt medi mentre lavora | **507** (media sulle 24 h) | **335** |

0.67 × 0.66 = 0.44, contro lo 0.46 misurato: **la decomposizione torna**. Circa
metà del risparmio viene dal fatto che la macchina sta ferma più a lungo, l'altra
metà dal fatto che quando lavora tira meno.

**Attenzione a non attribuirlo al software.** Le ore in meno hanno una causa
dichiarata e non software: `start_approval` è acceso, quindi molte mattine la
macchina **non parte finché una persona non dice di sì** (il 31 agosto il
permesso è arrivato alle 11:29). I watt in meno sono compatibili con l'anello di
casa, che di giorno chiede alla camera un target spesso più alto del vecchio 25.0
fisso — ma **non è isolato sperimentalmente**, e la stagione nel frattempo è
girata. *Quanto sopra è una decomposizione misurata; l'attribuzione delle cause è
un'inferenza plausibile, non una misura.*

## 5. Il listino prezzi delle leve, misurato

**Misure di inizio agosto 2026, assetto 1.7.0. Non rifatte.** Due voci sono oggi
fuori contesto: il "+1 °C di target diurno" era misurato su un target **fisso**,
mentre oggi il target di giorno lo decide l'anello di casa e si muove da solo fra
24.0 e 27.0; la pausa mattutina 08:30-10:00 non esiste più (spegnimento del
mattino disattivato). Restano valide come ordini di grandezza del **costo di un
grado**, non come previsione di risparmio su questo assetto.

| leva | valore | qualità del dato |
|---|---|---|
| **+1 °C di target diurno** | **−0.95/−1.00 kWh/giorno** (73‑77 W/grado) | **misurato**, confronto appaiato su 10 celle ora×esterna, confermato da regressione multipla (−63 ± 8 W/grado) |
| +1 °C di target notturno | −0.45/−0.65 kWh/notte (4‑6 cent) | **stimato** da regressione oraria; la controprova a coppie di notti ha dato segni opposti, il rumore vince con sole 4 notti |
| pausa mattutina 08:30‑10:00 | **+0.47 kWh/giorno risparmiati** (4.2 cent) | misurato‑dedotto |
| ripartenza alle 09:00 anziché 10:00 | **costa 0.10‑0.32 kWh/giorno in più** | dedotto: compra ~0.25 K di casa fra le 09:00 e le 11:00 |
| passo di ventola | 8 W | misurato |
| spinta iniziale notturna | sotto il rumore | misurato |
| compensazione adattiva | effetto ≈ 0 (attiva 15 campioni in 5 giorni) | misurato |
| standby a macchina spenta | 1.6 W, 0.3 cent/giorno | misurato |

**Il target diurno è la leva tre volte più grossa di quella notturna.** Non è una
proposta: è il prezzo, perché la decisione è di comfort e spetta all'utente.

---

## 6. Fatti misurati che smentiscono ipotesi intuitive

Sono i punti su cui un analista arriverebbe a conclusioni sbagliate ragionando
soltanto.

### 6.1 La casa **non** si scalda di notte

| notte | casa 23:00 | casa 07:30 | Δ |
|---|---|---|---|
| 01→02 | 26.46 | 26.53 | +0.07 |
| 02→03 | 26.41 | 26.45 | +0.03 |
| 03→04 | 26.93 | 26.57 | −0.36 |
| 04→05 | 25.83 | 26.57 | +0.74 |
| | | **media** | **+0.12 K** |

Di notte fuori ci sono 26‑28 gradi e in casa 26.4‑27.0: sono in equilibrio, non
c'è forza motrice. Il riscaldamento vero avviene **fra le 07:30 e le 10:00**
(+0.57 K), cioè nella coda e nella pausa a macchina spenta. **La notte fonda è
cara ma non lascia debiti al mattino.**

### 6.2 Mezzo grado di target notturno **non esiste** su questa macchina

Il passo del setpoint è 1.0. Quindi:

| target | comandato grezzo | comandato reale |
|---|---|---|
| 22.5 (attuale) | 21.5 | **22.0** |
| 23.0 | 22.0 | **22.0** ← identico |
| 23.5 | 22.5 | 23.0 |

Da 22.5 a 23.0 la macchina riceve **esattamente lo stesso valore**. Il primo
scalino vero è 23.5. Corollario: di notte la correzione −1.0 viene mangiata a
metà dalla quantizzazione, e l'effetto reale è −0.5.

### 6.3 La portata d'aria è il **tetto** del compressore

Provato e ritirato il 5 agosto. Cambiando il segnale della ventola dalla ripresa
alla media di casa senza ritarare le soglie, la ventola si è bloccata su `high` e
la macchina ha potuto salire a **71 Hz e 1090 W** invece di strozzarsi sui 40:

| giorno | casa 10:00→11:48 | raffrescamento | esterna | kWh |
|---|---|---|---|---|
| 03/08 | 27.25 → 26.67 | +0.58 | 31.0 °C | 1.334 |
| 04/08 | 26.96 → 26.50 | +0.46 | 32.3 °C | 1.288 |
| **05/08** | 27.12 → 26.57 | +0.55 | **30.8 °C** | **2.002** |

Stesso raffrescamento, esterna più fresca, **50% di energia in più**. Ritorno
indietro alle 12:00, con discesa misurata: 1090 → 825 → 597 → 625 W di regime,
compressore da 71 a 45 Hz.

**Causa dell'errore:** i due segnali non stanno sullo stesso livello. Lo scarto
sulla ripresa oscilla intorno a **+1.0**, quello sulla media di casa fra **+1.6 e
+2.2**, perché il resto della casa è più caldo della camera in cui vive la
macchina. Con le stesse bande la ventola sale di un passo **per costruzione**.

### 6.4 Il `dry` non risparmia su questa macchina

Confronto a frequenza comparabile, mezz'ora contro mezz'ora:

| giorno | `cool` | `dry` | differenza |
|---|---|---|---|
| 03/08 | 301 W | 305 W | +4 W |
| 04/08 | 347 W | 368 W | **+21 W** |

Segno contrario all'attesa. Inoltre il `dry` da umidità **non è mai scattato** in
quattro giorni: l'umidità è rimasta fra 38 e 53% contro una soglia di 60.

---

## 7. Difetti aperti, in ordine di gravità

**Rivisto il 1 settembre 2026.** Dei cinque difetti dell'elenco originale ne
restano aperti due, e nessuno dei due è quello che sembrava più grave.

### 7.1 Il silenzio notturno arriva, ma poco — **comfort, non energia. APERTO**

Misurato sui dieci giorni fino al 1 settembre, distribuzione della ventola in
notte fonda (23:00–08:00, 299 campioni):

| passo | quota |
|---|---|
| `medium` | **77%** |
| `high` | 11% |
| `low` | **5%** |
| `auto` | 5% |

Ad agosto `medium` valeva il 97% e `low` il 3%: è migliorato, ma **`low` — che
per l'utente è il silenzio — resta un'eccezione**. Il vincolo §9.3 non è ancora
onorato davvero.

### 7.2 La ventola non modula — **RISOLTO, misurato**

Era il difetto peggiore di agosto: `low` fisso di giorno, `medium` fisso di
notte, bande diurne decorative. Stessa misura, fascia 10:00–22:00, 343 campioni:
**`medium` 37%, `low` 37%, `auto` 21%, `high` 3%.** La ventola modula.

### 7.3 Il tetto dell'adattivo dichiarava 1.5 e valeva 1.0 — **SOSPESO**

Non riverificato, ma senza effetto pratico: l'adattivo sull'esterna è
**disattivato** (`adaptive_outdoor_start = 0.0`). Se un giorno lo si riaccende,
questo è il primo punto da ricontrollare.

### 7.4 Le chiavi di configurazione morte — **RISOLTO**

`presence_home_state` e `target_away` non esistono più nel codice.
`presence_entity` invece è **viva** (la usa `_fuori_casa`) e dal 1 settembre è
**scegliibile dal flusso di configurazione**: fino a quel giorno non compariva in
nessuna schermata e il suo predefinito era cablato su `person.rob`, l'entità di
una sola installazione. Su qualunque altra la guardia "non accendo la notte fonda
se sono fuori" restava spenta in silenzio.

### 7.5 La correzione −1.0 tarata su una velocità di ventola ignota — **RISOLTO**

`setpoint_offset` oggi vale **0.0**: con il termometro di camera collegato la
pezza non serve più.

### 7.6 Due cose note e deliberatamente lasciate così

- **La soglia "assorbimento anomalo" del guardiano (1250 W) sta sotto il tetto
  fisico della macchina.** Il 30 agosto ha segnalato 1304 W durante un'accensione
  **manuale** con camera a 28.5, esterna a 33 e setpoint 22: estrapolando il
  rapporto W/Hz della curva del §1 agli 81 Hz osservati si ottiene ~1296 W, cioè
  la macchina al massimo, non un guasto. L'utente ha scelto di **lasciare 1250**:
  meglio un falso allarme che perdere un evento fuori inviluppo. *L'estrapolazione
  non è una misura, e non è verificabile: vedi il sensore Hz nel §2.*
- **`DRY_TARGET_SLEW_SECONDS_PER_DEGREE` (600 s/grado) è verificato funzionare,
  non riverificato come numero.** È tarato su un solo episodio reale (28 agosto,
  08:58: 601 secondi esatti fra il salto dell'anello e il rientro in `dry`). La
  ricerca del 1 settembre su 90 giorni di cronologia **non ha trovato nessun altro
  episodio con la stessa firma**: la combinazione umidità sopra soglia + `dry`
  attivo + passo dell'anello proprio sul bordo è rara. Due inneschi post-correzione
  (29 agosto, 10:03 e 10:48, umidità 62%) sono passati **senza capovolgimenti**: il
  meccanismo tiene, ma una seconda misura indipendente della costante non esiste.

## 8. Comfort consegnato, misurato su 71 ore stabili

**Misura di inizio agosto 2026, assetto 1.7.0. Non rifatta.** Da allora è nato
l'anello di casa, che punta esattamente al problema descritto qui sotto: le
stanze diverse dalla camera. Una misura nuova, con lo stesso metodo, direbbe se
l'anello ha consegnato — ed è la prima cosa da rifare quando servirà un giudizio
sul comfort e non sull'energia.

Percentuale di tempo entro **1 °C** dal target realmente attivo:

| stanza | % |
|---|---|
| camera (ripresa) | **87.1%** |
| ingresso | 48.3% |
| salotto | 24.3% |
| cucina | **12.7%** |

Salotto, cucina e ingresso stanno allo **0%** fra le 21:00 e le 09:00: è il
vincolo dichiarato — di notte la porta della camera resta quasi chiusa e il resto
della casa non viene raffrescato. La **cucina resta la peggiore anche in pieno
regime pomeridiano** (+1.0/+1.6), l'ingresso è la più fredda e arriva sotto
target.

---

## 9. Vincoli dell'utente, non negoziabili

1. La camera si assesta **un grado sopra il target** e va bene così: «il comfort
   lo vedo dai sensori, non farei lavorare il doppio la macchina per un grado».
2. Di **notte la porta della camera resta quasi chiusa**. La media di casa non è
   un segnale di carico valido in quella fascia.
3. **`low` di notte è il silenzio.** Qualunque proposta che lo tolga va scartata.
4. La rete IoT è **volutamente isolata**: uscita verso Internet sì, ingresso no.
   Non va sbloccata.
5. Ogni riavvio di Home Assistant va **concordato**, e mai vicino alle 10:00,
   23:00, 07:30, 08:30 — sono i momenti in cui il controller agisce.

## 10. Trappole verificate sul campo

1. Comandare direttamente `climate.clima_camera` con un token utente porta
   `context.user_id` e fa scattare l'**override manuale di 60 minuti**. Si passa
   sempre dalle entità dell'integrazione.
2. Con il **muto** acceso l'unità **rifiuta la velocità di ventola imposta** e
   rimette `auto` dopo ~66 secondi (misurato due volte). Stessa cosa con **eco**.
   Per questo muto, modalità notte ed eco sono tutti **scollegati**.
3. L'entità di aggiornamento di HACS riporta la versione **dell'ultima release
   GitHub**, non quella dei file installati: un'installazione manuale senza tag
   lascia HACS convinto di avere la versione vecchia, e prima o poi la
   sovrascrive. **Verificato che era successo davvero:** il 1 settembre 2026
   l'ultimo tag sul repo era `1.20.1` mentre sul disco girava la **1.22.1** — le
   1.21.x e 1.22.x non erano mai state taggate, e la trappola è rimasta armata per
   una settimana. Regola: **ogni installazione va accompagnata dal tag**, anche
   quando i file si copiano a mano.
4. I timestamp restituiti dall'API storica di Home Assistant sono **UTC**. Tre
   revisori indipendenti hanno tratto conclusioni sbagliate ignorandolo.

---

## 11. Domande aperte, e la misura che le chiuderebbe

**Rivisto il 1 settembre 2026.**

| # | domanda | stato |
|---|---|---|
| 1 | Il `cool` al posto del `dry` fra 07:30 e 08:30 conviene sull'ora intera? | **superata**: la coda mattutina non esiste più con questo assetto (`sleep_end` 08:00, spegnimento del mattino disattivato) |
| 2 | A quale velocità di ventola è tarata la correzione −1.0? | **chiusa**: la correzione è 0.0, il termometro di camera è arrivato |
| 3 | Quanto vale un grado di target notturno? | **aperta**. Servono 8-10 notti alternate 22.5 / **23.5** (non 23.0, che la macchina riceve identico: §6.2), confrontando i kWh 23:00–08:00 normalizzati sull'esterna |
| 4 | Ripartire alle 09:00 conviene? | **superata da `start_approval`**: oggi l'ora di partenza la decide una persona rispondendo su Telegram, non una soglia |
| 5 | **Perché `low` di notte arriva solo il 5% del tempo?** | **nuova, aperta.** È il difetto §7.1. La misura che la chiude: distribuzione della ventola notturna dopo aver spostato il bordo delle bande notturne, a parità di target |
| 6 | **Il dimezzamento dei consumi quanto deve all'anello di casa e quanto alle ore in meno?** | **nuova, aperta.** La decomposizione ore/watt del §4.2 è misurata, l'attribuzione no. La chiuderebbe una settimana con `start_approval` spento e l'anello attivo, confrontata con una a parti invertite |

## 12. Acquisti giustificati

**Aggiornato il 1 settembre 2026: l'unico acquisto giustificato è stato fatto.**

Il termometro ambiente in camera, fuori dal getto d'aria, **c'è**:
`sensor.bthome_sensor_89af_temperatura`, un BTHome. Ha prodotto esattamente i due
risultati per cui era stato chiesto:

1. la correzione setpoint fissa **è stata tolta** (da −1.0 a 0.0);
2. il divario ripresa − comodino è stato **misurato** invece che supposto, e si è
   scoperto che dipende dalla **porta della camera**, non dal compressore: +1.9/+2.8
   di giorno a porta aperta, +0.9/+1.1 di notte a porta chiusa (362 campioni
   contemporanei, 23 agosto). Il vecchio "3.1-3.5" era troppo grande e misurato
   solo di giorno.

Va ricordato però che **il termometro di camera non è diventato il riferimento
del controllo, e non deve diventarlo**: provato il 6 agosto al posto della
ripresa, rendeva lo scarto sempre piccolo, la ventola non saliva mai e il
compressore restava inchiodato (setpoint abbassato di due gradi, due ore ferme a
46 Hz). Serve da **limite**, per dire quando la camera ha dato abbastanza.

**Nessun altro acquisto è giustificato**, e per il criterio richiesto: non
cambierebbe nessuna decisione. Un'eccezione la merita il **sensore di frequenza
del compressore**, che non è un acquisto ma un ripristino: oggi è disabilitato
perché inaffidabile (§2), e la sua assenza rende non verificabili gli eventi di
assorbimento anomalo (§7.6). Non vale però lo staccare la corrente all'unità per
farlo ripartire.

## 13. Storia delle modifiche, per non ripetere gli errori

| versione | cambiamento | esito |
|---|---|---|
| 0.19.0 | spinta iniziale a ventola `high` nei primi 15 min della notte | funziona, costo sotto il rumore |
| 1.1.0 | quanto dell'adattivo agganciato al passo macchina; isteresi ventola 0.3→0.5 | il quanto ha risolto l'oscillazione del setpoint (14 scatti → 4 in replay). **L'isteresi 0.3→0.5 era un no‑op**: con letture a mezzo grado entrambe arrotondano alle stesse soglie |
| 1.2.0 | ventola diurna sulla media di casa; stato persistente ai riavvii; limiti di plausibilità; `cool` invece di `dry` nella coda | **la ventola sulla media di casa è costata il 50%, ritirata in giornata.** Il resto è rimasto |
| 1.3.0 | tolta l'attesa fissa 08:30‑10:00 | funziona; costa 1‑3 cent/giorno e compra ~0.25 K di casa |
| **1.4.0** | ventola diurna di nuovo sulla ripresa, isteresi 1.5 di giorno e 0.5 di notte | ha chiuso il problema, **ma ha reso la ventola inerte in entrambe le fasi** |

### Da 1.7.0 a 1.23.0 (7 agosto → 1 settembre 2026)

Sedici versioni. Le svolte, non l'elenco completo:

| versione | cambiamento | esito |
|---|---|---|
| **1.8.0** | di giorno comanda la casa, la camera è lo strumento: nasce l'anello di casa | è l'assetto tuttora in funzione |
| 1.9.x | l'esterna torna a contare ma **sui limiti**; il comodino torna a essere solo un limite | corregge l'errore del 6 agosto |
| 1.10.0 | esterna filtrata, banda più stretta | |
| 1.11.1 → 1.12.2 | l'anello riconosce la saturazione; **il passo si giudica dal risultato** e la lezione si salva su disco | chiude l'oscillazione dell'8 agosto |
| 1.13.0 | lo spegnimento del mattino diventa disattivabile | poi disattivato il 12 agosto |
| 1.14.2 | **alette fisse anche di notte** | il freddo resta in basso dove si dorme |
| 1.15.0 | la notte fonda non parte se sono fuori | usa `presence_entity` |
| 1.16.0 | riposo per notte fredda, spegnimento per mattina fresca | |
| 1.17.0 | aiuto invernale ai caloriferi | |
| **1.18.0** | **il clima chiede il permesso prima di partire** (`start_approval`) | cambia il profilo dei consumi più di qualunque taratura: vedi §4.2 |
| 1.19.0 | la notte mite si accontenta | |
| 1.20.x | spinta notturna, soglia ventola media a 1.5 | la ventola torna a modulare: §7.2 |
| **1.21.0** | niente da raffreddare significa **ventilare**, non fermarsi (`fan_only`) | introduce anche il buco chiuso nella 1.23.0 |
| 1.21.3 | l'eco del nostro comando vince sul context | niente più falsi override da comandi nostri |
| 1.22.0 | cinque bug dalla revisione a tre del 27 agosto | |
| 1.22.1 | il giudizio dry/cool non insegue più i passi dell'anello | §7.6, secondo punto |
| **1.23.0** | cinque bug dalla revisione a tre del 1 settembre | il più grave: `fan_only` non era riconosciuto come ciclo nostro, e un'unità in sola ventilazione a fine stagione **non veniva più spenta da nessuno** |

**Il metodo che ha prodotto di più:** la *revisione a tre*. Tre revisori
indipendenti, ognuno su un angolo diverso (macchina a stati e persistenza; soglie
e isteresi numeriche; integrazione con l'hardware reale), che non si vedono fra
loro, e ogni segnalazione riverificata a mano prima di toccare il codice. Tre
sessioni su tre hanno prodotto bug veri: 1.13.1, 1.22.0, 1.23.0.

**Errori metodologici commessi e da non ripetere:**
- cambiare il **segnale** di un anello lasciando le **soglie** tarate sull'altro;
- dedurre un nesso causale da una transizione in cui **due cose cambiano insieme**
  (il caso della spinta notturna: setpoint e ventola cambiano nello stesso minuto);
- leggere i timestamp dell'API storica come locali quando sono UTC;
- dichiarare installata una versione senza verificare il `manifest.json` **sul
  disco dell'istanza** e il riavvio nel log.
