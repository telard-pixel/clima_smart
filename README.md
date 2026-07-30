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
  → `high`, 1 o più → `medium`, sotto → `low`. Le salite valgono subito, le discese
  solo dopo 10 minuti e con mezzo passo di margine, così non ticchetta. Di notte non
  supera `medium`.
- **il programma**: `dry` quando l'aria è umida (oltre il 60%) ma la temperatura è già
  a posto, `cool` in tutti gli altri casi. Serve un sensore di umidità interna
  configurato: senza quello resta sempre su `cool`.

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
- **Number** — target casa/fuori, isteresi eco, soglie eco-esterno, soglia stagione calda, override (min).
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
- Stato attuale: `0.6.0` — nuovo modo **Adattivo**, che decide ventola e programma
  dai sensori invece di tenerli fissi, più il campo opzionale per il sensore di
  umidità interna.
- `0.5.0` — il target diagnostico coincide con quello che l'unità riceve davvero,
  muto/notte non si fermano più su una modalità HVAC non supportata, la
  diagnostica si azzera quando il clima è irraggiungibile, override a 0 minuti non
  annuncia più una scadenza inesistente e le raffiche di eventi si fondono in una
  sola valutazione.
