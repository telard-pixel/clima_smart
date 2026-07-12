# Clima Smart

Integrazione custom per Home Assistant che fa da "cervello" a un climatizzatore
esistente (es. uno split Haier esposto da [addhOn](https://github.com/tis24dev/addhOn)).
Non crea un nuovo `climate`: **pilota quello che hai già** tramite normali service
call, replicando — e rendendo configurabile da UI — una logica di automazione
validata per il comfort con risparmio energetico.

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
- **Select** `Modo` — auto / comfort / away / notte / spento.
- **Number** — target casa/fuori, isteresi eco, soglie eco-esterno, soglia stagione calda, override (min).
- **Sensor** (diagnostici) — fase corrente, target attivo, stato/motivo dell'ultima decisione.

## Installazione

1. Copia la cartella `clima_smart/` in `config/custom_components/`.
2. Riavvia Home Assistant.
3. **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → "Clima Smart"** e
   seleziona il `climate` da pilotare, il `device_tracker` di presenza, i sensori di
   temperatura esterna (principale + fallback) e gli switch ausiliari (eco / muto / notte).

I parametri di tuning si regolano poi dalle entità `number`/`select`, oppure dal flusso opzioni.

## Note

- Testata su Home Assistant 2026.7.2.
- Stato attuale: `0.4.2` — packaging compatibile con HACS.
