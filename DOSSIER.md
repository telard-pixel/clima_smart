# Clima Smart — dossier tecnico dell'impianto

**Ultimo aggiornamento: 6 agosto 2026, ore 08:30 (Europe/Rome).**
**Versione in funzione: 1.7.0.**

Questo documento è scritto perché possa essere letto da un'altra intelligenza
artificiale, o da un tecnico, senza avere accesso alla conversazione che l'ha
prodotto. Contiene solo misure fatte sull'impianto reale e la loro fonte. Dove
un numero è una stima e non una misura, **è scritto esplicitamente**.

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

| grandezza | entità | difetto noto |
|---|---|---|
| temperatura camera | `climate.clima_camera` attributo `current_temperature` | **è l'aria di ripresa, non la stanza.** Un passo di ventola la sposta di **1.0 °C** in due minuti, verificato su ~40 transizioni indipendenti |
| valvola camera | `sensor.camera_da_letto_temperatura` (Tado) | sta **dentro il getto d'aria**: legge 20.3 mentre la ripresa legge 26.0. Inutilizzabile |
| falso termometro | `sensor.camera_da_letto_temperatura_2` / `cucina_temperatura_2` | è la **temperatura interna della scheda** di uno Shelly 1 Gen4. Media settimanale 32.3 °C. Da ignorare |
| media di casa | `sensor.clima_smart_media_di_casa` | media di salotto, cucina, ingresso (tre valvole Tado). Costruita bene, ma **nasconde uno scarto da −0.5 a +1.6 secondo la stanza** |
| esterna | `sensor.meteo_montichiari_temperatura` | stazione Bresser **dell'utente**, ma installata al ristorante dove lavora, **4.2 km da casa**. Riporta **gradi interi**, aggiorna ogni 5 minuti |
| umidità | `sensor.ingresso_umidita` | 38-53% nella settimana, sempre sotto la soglia `dry` di 60 |

**Non esiste un termometro ambiente in camera fuori dal getto d'aria.** È il buco
principale della strumentazione, e la ragione della domanda aperta n. 2.

---

## 3. Assetto in funzione (1.7.0)

### Ciclo giornaliero

| ora | comportamento |
|---|---|
| 23:00 → 07:30 | notte fonda, target **22.5** (comandati 22.0), ventola per bande notturne, alette in `swing`. Primi 15 minuti a ventola `high` («spinta iniziale») se lo scarto supera 0.3 |
| 07:30 → 08:30 | `cool` con ventola `auto`. Provato `dry`, misurato peggiore a pari deriva della camera: 0.396 kWh in `dry` contro 0.364 in `cool`, e 0.333 contro 0.293 il giorno dopo |
| 08:30 | spegnimento, **una volta sola** |
| dalle 09:00 | riaccensione automatica se **esterna ≥ 29** *e* (**camera ≥ 27** *oppure* **media di casa ≥ 26.5**). Nessuna attesa a orologio: l'attesa fissa fino alle 10:00 era un valore predefinito mai scelto |
| giorno | target **25.0** più compensazione adattiva |

### Parametri, con la loro origine

| parametro | valore | origine |
|---|---|---|
| `target_home` | 25.0 | scelta utente (predefinito 26.0) |
| `target_sleep` | 22.5 | scelta utente (predefinito 23.0) |
| `setpoint_offset` | −1.0 | misurato, **ma non è documentato a quale velocità di ventola** - ed e' la pezza che il sensore di stanza (opzione `room_sensor`, aggiunta nella 1.6.0) esiste per togliere |
| soglie avvio | 27.0 / 26.5 / 29.0 | attivate dall'utente (predefinite: disattivate) |
| bande ventola giorno | 2.0 `high` / 1.0 `medium` / 0.0 `low` | misurate |
| isteresi ventola giorno | **1.0 in salita, 0.5 in discesa** | misurata. Simmetrica a 1.5 la ventola non saliva mai (serviva scarto 2.5, il massimo osservato e' 2.5); simmetrica a 1.0 entrava in `medium` a 2.0 e non ne usciva piu' perche' pretendeva 0.0, costando 0.70 kWh in un pomeriggio senza consegnare freddo. Asimmetrica: entra a 2.0, esce a 0.5 |
| isteresi ventola notte | **0.5** | scelta: con 1.5 `low` sarebbe irraggiungibile, e `low` è il silenzio |
| permanenza minima ventola | 1800 s | misurata: fra i passi ci sono 8 W, non valgono un comando ogni 10 minuti |
| adattivo | partenza 33, pendenza 0.25, tetto 1.5, attesa 3600 s | misto. **Il tetto dichiarato 1.5 vale in realta' 1.0**: viene portato a un multiplo del passo macchina prima di arrotondare |
| spinta iniziale notte | 15 min, soglia 0.3 | misurata sull'episodio del 4-5 agosto |

---

## 4. Il bilancio energetico, misurato

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

## 5. Il listino prezzi delle leve, misurato

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

### 7.1 Il silenzio notturno non viene consegnato — **comfort, non energia**

`FAN_BANDS_SLEEP` scende a `low` sotto scarto −0.5; con isteresi 0.5 serve
**−1.0**, cioè camera **≤ 20.5** (target 22.5, correzione −1.0). La camera si
assesta a 23.0 e il minimo mai registrato è 21.5. Risultato misurato: la ventola
notturna è **`medium` per il 97% del tempo** (393 campioni su 404).

L'utente ha scollegato il muto proprio perché «il silenzio si fa con la ventola
bassa». **Quel silenzio, per costruzione, non gli arriva mai.**

### 7.2 La ventola non modula più, in nessuna delle due fasi

Con isteresi 1.5, salire da `low` a `medium` di giorno richiede uno scarto **≥ 2.5**
(banda 1.0 + isteresi 1.5), cioè camera ≥ 27.5 con target 25. Il massimo mai
osservato in fase `day` è **+2.5**, presente lo **0.6%** del tempo; `high`
(serve ≥ 3.5) **0.0%**. Quindi oggi la ventola è **`low` fisso di giorno e
`medium` fisso di notte**, e le bande diurne sono decorative.

Questo ha chiuso il disastro del 5 agosto, ma se l'intenzione era avere una
ventola che modula, **oggi non modula**. Costo energetico dell'immobilità: 8 W,
irrilevante. Costo di comfort: da valutare.

### 7.3 Il tetto dell'adattivo dichiara 1.5 e vale 1.0

Il codice porta il tetto su un multiplo del quanto **prima** di arrotondare:
`floor(1.5 / 1.0) × 1.0 = 1.0`. Confermato dallo storico, dove il target attivo
assume **solo 25.0 o 26.0**, mai 25.5 o 26.5. Il valore mostrato nelle opzioni
non è quello ottenuto.

### 7.4 Tre chiavi di configurazione morte

`presence_entity`, `presence_home_state`, `target_away` non sono più referenziate
da nessuna parte nella 1.4.0.

### 7.5 La correzione −1.0 è tarata su una velocità di ventola ignota

Poiché un passo di ventola sposta la lettura di un grado pieno, la correzione è
giusta a una velocità e sbagliata di un grado a un'altra. Indizio nei dati: lo
scarto camera‑target è **positivo di giorno** (+0.5/+1.0, il grado sopra target
che l'utente accetta) ma **negativo alle 04‑05** (−0.53/−0.56). *Inferenza
plausibile, non isolata sperimentalmente.*

---

## 8. Comfort consegnato, misurato su 71 ore stabili

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
   sovrascrive.
4. I timestamp restituiti dall'API storica di Home Assistant sono **UTC**. Tre
   revisori indipendenti hanno tratto conclusioni sbagliate ignorandolo.

---

## 11. Domande aperte, e la misura che le chiuderebbe

| # | domanda | misura necessaria |
|---|---|---|
| 1 | Il `cool` al posto del `dry` fra 07:30 e 08:30 conviene sull'energia dell'**ora intera**? | primo confronto utile: 6 agosto contro 5 agosto. *Previsione: +0.1/0.2 kWh, cioè non conviene* |
| 2 | A quale velocità di ventola è tarata la correzione −1.0? | **richiede un termometro ambiente in camera**, fuori dal getto |
| 3 | Quanto vale un grado di target notturno? | 8‑10 notti alternate 22.5 / **23.5** (non 23.0, che è identico), confrontando i kWh 23:00‑07:30 normalizzati sull'esterna |
| 4 | Ripartire alle 09:00 conviene? | 6 giorni alternati 09:00 / 10:00, confrontando i kWh 09:00‑13:00 a esterna appaiata |

---

## 12. Acquisti giustificati

**Uno solo: un termometro ambiente in camera, fuori dal getto d'aria.**

- **Decisione oggi presa male senza di lui:** la correzione −1.0 è un numero fisso
  che non sa quale velocità di ventola stia distorcendo la lettura, e non c'è modo
  di verificare se il target notturno venga davvero consegnato.
- **Come si vedrebbe la differenza:** confrontandolo per qualche notte con la
  ripresa a `low` e a `medium`. Se la differenza fra i due non è costante, la
  correzione fissa è formalmente sbagliata e si vede a colpo d'occhio.
- **Strada compatibile con la rete isolata:** in camera c'è già uno **Shelly 1
  Gen4 alimentato a rete**, che supporta il ruolo di gateway BLE per i dispositivi
  Shelly BLU. *Verificato:* il Gen4 fa da gateway BLU. *Non verificato:* che il
  dato di un BLU H&T arrivi a Home Assistant per quella via — l'integrazione
  Shelly non supporta i BLU H&T, che passano da **BTHome**. **Questo anello va
  accertato prima dell'acquisto.**
- Alternativa già valutata: **Shelly H&T Gen3** Wi‑Fi, da alimentare via USB‑C
  (a batteria trasmette solo a scatti di 0.5 °C, troppo grossolano per un anello
  di controllo).

**Nessun altro sensore è giustificato**, e per il criterio richiesto: non
cambierebbe nessuna decisione. Le altre stanze hanno già le valvole Tado e il
loro problema è fisico, non di misura; una stazione meteo locale non sposterebbe
nessuna giornata estiva, perché le soglie che usano l'esterna sono superate per
ampio margine tutti i giorni.

---

## 13. Storia delle modifiche, per non ripetere gli errori

| versione | cambiamento | esito |
|---|---|---|
| 0.19.0 | spinta iniziale a ventola `high` nei primi 15 min della notte | funziona, costo sotto il rumore |
| 1.1.0 | quanto dell'adattivo agganciato al passo macchina; isteresi ventola 0.3→0.5 | il quanto ha risolto l'oscillazione del setpoint (14 scatti → 4 in replay). **L'isteresi 0.3→0.5 era un no‑op**: con letture a mezzo grado entrambe arrotondano alle stesse soglie |
| 1.2.0 | ventola diurna sulla media di casa; stato persistente ai riavvii; limiti di plausibilità; `cool` invece di `dry` nella coda | **la ventola sulla media di casa è costata il 50%, ritirata in giornata.** Il resto è rimasto |
| 1.3.0 | tolta l'attesa fissa 08:30‑10:00 | funziona; costa 1‑3 cent/giorno e compra ~0.25 K di casa |
| **1.4.0** | ventola diurna di nuovo sulla ripresa, isteresi 1.5 di giorno e 0.5 di notte | ha chiuso il problema, **ma ha reso la ventola inerte in entrambe le fasi** |

**Errori metodologici commessi e da non ripetere:**
- cambiare il **segnale** di un anello lasciando le **soglie** tarate sull'altro;
- dedurre un nesso causale da una transizione in cui **due cose cambiano insieme**
  (il caso della spinta notturna: setpoint e ventola cambiano nello stesso minuto);
- leggere i timestamp dell'API storica come locali quando sono UTC;
- dichiarare installata una versione senza verificare il `manifest.json` **sul
  disco dell'istanza** e il riavvio nel log.
