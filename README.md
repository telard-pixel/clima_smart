# Clima Smart

Integrazione custom per Home Assistant che fa da "cervello" a un climatizzatore
esistente (es. uno split Haier esposto da [addhOn](https://github.com/tis24dev/addhOn)).
Non crea un nuovo `climate`: **pilota quello che hai già** tramite normali service
call, replicando — e rendendo configurabile da UI — una logica di automazione
validata per il comfort con risparmio energetico.

## Modo Adattivo (`smart`)

Il modo per «imposto 25 gradi e al resto pensa tu». Tiene **un solo target** (quello
di casa, la presenza non conta), applica le stesse fasce orarie di `auto`, e in più
decide da sé:

- **la ventola**, in base a quanto la stanza è ancora sopra il target: 2 gradi o più
  → `high`, 1 o più → `medium`, sotto → `low`. Entrambe le direzioni chiedono 0.3 di
  margine oltre il confine della banda, e le discese anche 10 minuti dall'ultimo
  cambio: senza, un'unità che riporta a mezzi gradi fa ticchettare la ventola
  restando appoggiata sul confine.
- **il programma**: `dry` quando l'aria è umida (oltre il 60%) ma la temperatura è già
  a posto, `cool` in tutti gli altri casi. Serve un sensore di umidità interna
  configurato: senza quello resta sempre su `cool`.

**Sul muto:** finché uno switch «muto» resta collegato, la ventola non viene
comandata mentre è acceso. Questa unità con il muto attivo rifiuta una velocità
imposta e torna su `auto` dopo circa un minuto, e quel ritorno veniva letto come un
intervento manuale, con un'ora di controllo ceduta ogni volta. Se il silenzio lo
vuoi ottenere dalla velocità, lascia il campo «muto» vuoto e la ventola resta
governata dal profilo.

### Il profilo notturno (modo Adattivo)

- **notte fonda** (`sleep_start` → `sleep_end`, di norma `23:00` → `07:30`): target
  proprio, più basso, e ventola a due soli passi — `medium` finché la stanza non
  arriva, poi `low` per mantenere. Mai `high`.
- **scarico mattutino** (dalla fine della notte fonda allo spegnimento): programma
  `dry` con ventola `auto`, per togliere l'afa senza raffreddare ancora.
- **spegnimento del mattino** (`morning_off_start`, di norma `08:30`): avviene **una
  volta sola**, dentro una finestra di mezz'ora. Non è uno stato imposto: se
  riaccendi il clima in mattinata viene gestito col profilo di giorno, non rispento.

In questo modo il controller **non accende mai** l'unità di sua iniziativa: decidi
tu quando parte, lui decide come lavora. Le uniche due eccezioni sono programmate e
avvengono una volta sola: lo spegnimento del mattino e — se attivi «avvio
automatico» — l'accensione all'apertura della notte fonda, che lancia l'evento
`clima_smart_avviato` per chi vuole annunciarla.

### Correzione setpoint

Le unità split leggono l'aria di ripresa e si fermano prima: qui la stanza si
assestava fra 0.5 e 1.0 sopra un setpoint di 25.0. La correzione sposta **solo ciò
che viene chiesto alla macchina**, non il target: il sensore diagnostico continua a
dire 25 mentre all'unità arriva 24.

## Cosa fa

- Si controlla sulla **temperatura interna** del clima (non su un sensore nel flusso d'aria).
- Setpoint **fisso** in raffreddamento: 26 °C a casa, 27 °C fuori casa (presenza via `device_tracker`).
- **Eco con isteresi asimmetrica** anti-flapping (banda morta tra ON e OFF).
- Fasce orarie in modalità `auto`: giorno (ventola auto), notte (muto + modalità notte),
  e una fascia mattutina in cui spegne solo se sta raffreddando (non tocca il riscaldamento).
- **Rilevamento override manuale**: se intervieni a mano, cede il controllo per un tempo configurabile.
- Rispetta stagione e riscaldamento: non forza mai il `cool` in inverno o mentre l'unità riscalda.

## Entità

- **Switch** `Attivo` — abilita/disabilita il controllo (off = controllo manuale del clima).
- **Select** `Modo` — adattivo / auto / comfort / away / notte / spento.
- **Number** — target casa/fuori/notte fonda, correzione setpoint, isteresi eco,
  soglie eco-esterno, soglia stagione calda, override (min).
- **Sensor** (diagnostici) — fase corrente, target attivo, stato/motivo dell'ultima decisione.

## Installazione

1. Copia la cartella `clima_smart/` in `config/custom_components/`.
2. Riavvia Home Assistant.
3. **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → "Clima Smart"** e
   seleziona il `climate` da pilotare, il `device_tracker` di presenza, i sensori di
   temperatura esterna (principale + fallback), il sensore di umidità interna
   (opzionale, serve al modo Adattivo) e gli switch ausiliari (eco / muto / notte).

I parametri di tuning si regolano poi dalle entità `number`/`select`, oppure dal flusso opzioni.

## Note

- Testata su Home Assistant 2026.7.2.
- Stato attuale: `0.12.0` — l'avvio diurno guarda anche i **termometri delle
  altre stanze**: il resto della casa si scalda prima della camera, quindi la loro
  media fa partire l'unità prima del picco esterno. Due condizioni indipendenti
  (camera oppure media di casa), entrambe subordinate a una temperatura esterna
  minima, così una giornata fresca non fa partire niente.
- `0.11.0` — **avvio diurno**: se di giorno il clima è spento e la
  stanza supera una soglia, viene acceso una volta al giorno. È l'avvio vero, e
  l'evento `clima_smart_avviato` porta `motivo: giorno`, distinto dal `motivo:
  notte` dell'apertura della notte fonda, che è solo l'orario che comincia.
- `0.10.0` — avvio serale facoltativo: all'apertura della notte
  fonda, se il clima è spento, lo accende **una volta sola** e lancia l'evento
  `clima_smart_avviato`, così un'automazione può annunciarlo a voce. Fuori da quel
  momento vale sempre la regola: il controller non accende mai da sé.
- `0.9.1` — quando l'unità rifiuta un comando su uno switch
  ausiliario (rimettendolo com'era una sessantina di secondi dopo, senza contesto
  utente) non viene più scambiato per un intervento manuale, e quello switch resta
  in pace per mezz'ora invece di essere ricomandato a ogni passata.
- `0.9.0` — giro di correzioni dopo una revisione a due voci: lo
  spegnimento del mattino non tocca più un riscaldamento acceso e viene segnato
  solo se il comando riesce; la ventola sale al gradino intermedio invece di
  restare bassa; la barriera di ripristino non blocca più il controller se
  un'entità è disabilitata; la fusione delle raffiche funziona davvero; un nostro
  cambio di programma non viene più scambiato per un tuo comando; `cool`/`dry` ha
  isteresi anche sullo scarto. Validazioni nuove nel form, messaggi d'errore
  tradotti, e 59 prove fra cui la prima batteria sulle regole del form.
- `0.8.0` — profilo notturno completo: notte fonda con ventola a
  due passi, scarico mattutino in `dry`, spegnimento una tantum, e il controller
  non accende mai l'unità da sé.
- `0.7.0` — finestra di notte fonda con target proprio e correzione setpoint
  configurabile.
- `0.6.x` — nuovo modo **Adattivo**, che decide ventola e programma
  dai sensori invece di tenerli fissi, più il campo opzionale per il sensore di
  umidità interna.
- `0.5.0` — il target diagnostico coincide con quello che l'unità riceve davvero,
  muto/notte non si fermano più su una modalità HVAC non supportata, la
  diagnostica si azzera quando il clima è irraggiungibile, override a 0 minuti non
  annuncia più una scadenza inesistente e le raffiche di eventi si fondono in una
  sola valutazione.
