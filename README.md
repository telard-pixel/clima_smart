# Clima Smart

Integrazione custom per Home Assistant che fa da "cervello" a un climatizzatore
esistente (es. uno split Haier esposto da [addhOn](https://github.com/tis24dev/addhOn)).
Non crea un nuovo `climate`: **pilota quello che hai già** tramite normali service
call, replicando — e rendendo configurabile da UI — una logica di automazione
validata per il comfort con risparmio energetico.

## Il modo Adattivo, che è l'unico controllo automatico

Il modo per «imposto il target e al resto pensa tu». Applica le fasce orarie e
decide da sé:

- **la ventola di giorno**, in base a quanto la stanza è sopra il target: 2 °C o più
  → `high`, 1 °C o più → `medium`, sotto → `low`. Per evitare oscillazioni, ogni
  passaggio richiede 0,3 °C oltre il confine della fascia; le discese richiedono
  anche 10 minuti dall'ultimo cambio.
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

- **notte** (dalle `22:00`): abilita gli switch muto e modalità notte, se collegati.
- **sonno** (`sleep_start` → `sleep_end`, di norma `23:30` → `07:30`): usa il target
  sonno. Nei primi 15 minuti la ventola va a `high` solo se la stanza è almeno
  0,3 °C sopra quel target; poi usa le bande notturne, `medium` fino a 0,5 °C sotto
  il target e `low` solo oltre quella soglia.
- **scarico mattutino** (dalla fine del sonno allo spegnimento): programma
  `dry` con ventola `auto`, per togliere l'afa senza raffreddare ancora.
- **spegnimento del mattino** (`morning_off_start`, di norma `08:00`): avviene **una
  volta sola**, dentro una finestra di mezz'ora. Non è uno stato imposto: se
  riaccendi il clima in mattinata viene gestito col profilo di giorno, non rispento.

Di norma il controller non accende l'unità. Può però farlo una volta al giorno nella
fase diurna se superi la soglia configurata della stanza oppure della media dei
sensori di casa, con l'eventuale soglia minima esterna come guardia. Può anche farlo
una volta all'apertura del sonno se abiliti l'avvio automatico del sonno. Entrambi
gli avvii emettono `clima_smart_avviato`, con `motivo: giorno` per il superamento
della soglia diurna e `motivo: notte` per l'inizio programmato del sonno.

### Target adattivo sull'esterna

Chiedere 25 gradi con 28 fuori e con 36 fuori non è la stessa richiesta. Sopra una
soglia configurabile il target sale in proporzione, fino a un massimo: meno divario
da colmare significa compressore a frequenza più bassa, e su questa unità la
potenza misurata segue `W = 17.7 × Hz − 194`, quindi il rendimento migliora
scendendo di frequenza. È disattivato di default.

### Correzione setpoint

Le unità split leggono l'aria di ripresa e si fermano prima: qui la stanza si
assestava fra 0.5 e 1.0 sopra un setpoint di 25.0. La correzione sposta **solo ciò
che viene chiesto alla macchina**, non il target: il sensore diagnostico continua a
dire 25 mentre all'unità arriva 24.

## Cosa fa

- Si controlla sulla **temperatura interna** del clima (non su un sensore nel flusso d'aria).
- Target predefiniti: 26 °C di giorno e 23 °C nel sonno.
- **Eco con isteresi asimmetrica** anti-flapping (banda morta tra ON e OFF).
- Fasce predefinite: notte dalle 22:00, sonno 23:30–07:30, spegnimento mattutino
  alle 08:00 e fase diurna dalle 10:00.
- **Rilevamento override manuale**: se intervieni a mano, cede il controllo per un tempo configurabile.
- Rispetta stagione e riscaldamento: non forza mai il `cool` in inverno o mentre l'unità riscalda.

## Entità

- **Switch** `Attivo` — abilita/disabilita il controllo (off = controllo manuale del clima).
- **Select** `Modo` — **adattivo** oppure **tieni spento**. Nient'altro.
- **Number** — target diurno/sonno, correzione setpoint, isteresi eco, soglie
  eco-esterno, soglia stagione calda, override e soglie degli avvii automatici.
- **Sensor** (diagnostici) — fase corrente, target attivo, media di casa, stato/motivo dell'ultima decisione.

## Installazione

1. Copia la cartella `clima_smart/` in `config/custom_components/`.
2. Riavvia Home Assistant.
3. **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → "Clima Smart"** e
   seleziona il `climate` da pilotare, i sensori di temperatura esterna primario e
   fallback, il sensore di umidità interna (opzionale), i sensori di temperatura
   delle altre stanze, gli switch eco/muto/modalità notte e i selettori delle
   alette orizzontale e verticale. Tutti gli ingressi tranne il `climate` sono
   opzionali e si collegano solo quando disponibili.

I parametri di tuning si regolano poi dalle entità `number`/`select`, oppure dal flusso opzioni.

## Note

- Testata su Home Assistant 2026.7.2.
- `1.0.1` — aggiunta la spinta iniziale del sonno: per i primi 15 minuti usa `high`
  quando la stanza è almeno 0,3 °C sopra il target sonno; migliorato il tentativo
  di ripristino delle alette diurne dopo un comando non riuscito; aggiunta la CI.
