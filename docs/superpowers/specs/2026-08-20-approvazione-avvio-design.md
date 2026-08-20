# Approvazione dell'avvio automatico - design

## Obiettivo

Oggi il controller, in modo Smart, accende il clima da solo quando scattano le
condizioni: di giorno `_day_start_due` (esterna sopra soglia E camera o media
di casa sopra le loro), la sera l'avvio della notte fonda. L'utente vuole
decidere lui, caso per caso, perche' le condizioni misurate non sanno tutto:
il 20 agosto 2026 il clima e' partito alle 10:54 con la casa a 27.1, e le
previsioni orarie davano un temporale per le 13:00 con l'esterna in calo da 30
a 22 gradi. Le soglie erano rispettate, ma accendere era comunque sbagliato.

Quindi: quando il clima **starebbe** per partire, arriva una notifica con i
pulsanti e il quadro meteo delle ore successive; il clima non parte finche'
l'utente non risponde. Nessuna risposta significa **spento** - scelta
esplicita dell'utente, nessun avvio automatico dopo un timeout.

## Divisione delle responsabilita'

L'integrazione e' pubblica su HACS e potenzialmente usata da altri: **non deve
sapere nulla di Telegram, ne' del meteo**. La divisione e':

- **L'integrazione annuncia.** Sa quando partirebbe e perche'; lancia un
  evento e non parte.
- **L'istanza chiede.** Un'automazione raccoglie l'evento, compone il
  messaggio col meteo e lo manda; alla risposta accende il clima.

Da li' in poi il controller governa l'unita' accesa come ha sempre fatto - e'
il suo comportamento originale, dichiarato nel codice: "MODE_SMART never
starts the unit: the user decides when it runs, we decide how it runs".

## Nell'integrazione (repo)

Una sola opzione nuova, `start_approval`, **spenta di default**: nessuna
installazione esistente cambia comportamento.

Quando e' accesa, nei due punti in cui il controller avvierebbe:

- avvio diurno (`_day_start_due`, in `_compute`)
- avvio serale della notte fonda (`_sleep_start_due`)

il controller **non parte**, e invece:

1. lancia l'evento `clima_smart_avvio_richiesto` con i dati che servono a
   comporre il messaggio: `entity_id`, `motivo` (la stessa stringa che
   comparirebbe nel diagnostico, es. "casa 27.6 oltre 27.5"), `fase`
   (`day` o `sleep`), `casa`, `camera`, `esterna`, `target` (quello che
   avrebbe chiesto);
2. **marca la giornata come gia' decisa**, con lo stesso contrassegno che usa
   oggi per non riaccendere due volte (`_day_start_done_on` o
   `_sleep_start_done_on`);
3. restituisce la decisione passiva, con un motivo esplicito
   ("chiedo il permesso") cosi' il sensore diagnostico dice la verita'.

Il contrassegno e' la parte elegante: "chiedi una volta sola" e "dopo un no
non insistere" si ottengono **senza nessuna macchina a stati nuova**, perche'
quel contrassegno esiste gia', e' gia' persistito fra un riavvio e l'altro, e
gia' significa "per oggi la questione e' chiusa".

**Cosa non chiede**: la ripresa dal riposo per notte fredda
(`_cold_night_resting`). Non e' un avvio nuovo, e' il rientro da una pausa che
il controller stesso ha deciso mentre l'unita' era gia' in funzione con il
consenso dell'utente. Chiedere li' sarebbe rumore.

L'evento viene lanciato in `async_evaluate`, con lo stesso schema del gia'
esistente `EVENT_STARTED`: `_compute` arma un contrassegno, `async_evaluate`
lancia l'evento e marca la giornata. Non essendoci nessun comando da mandare
all'unita', non c'e' da attendere l'esito di `_apply`.

## Sull'istanza (fuori dal repo)

Due automazioni in `automations.yaml`, piu' l'integrazione Telegram
configurata col token in `secrets.yaml` (mai in chiaro in
`configuration.yaml`).

**Automazione della domanda**, innescata dall'evento:

- legge le previsioni orarie con `weather.get_forecasts` su
  `weather.forecast_casa` (verificato: fornisce temperatura, precipitazione e
  condizione ora per ora; la stazione Montichiari invece non da' previsioni
  orarie, risponde con un errore del server);
- compone un riassunto delle ore successive - temperatura e pioggia - e lo
  mette nel messaggio insieme al motivo e alle temperature attuali;
- manda il messaggio su Telegram con due pulsanti, **Accendi** e
  **Lascia spento**;
- manda **in parallelo** la stessa informazione su `notify.iphone`.

Quel doppio invio non e' ridondanza inutile: senza, un bot irraggiungibile
lascerebbe l'utente senza clima e senza avviso, perche' la giornata risulta
gia' decisa. L'iPhone e' il canale che gia' funziona per tutte le altre
notifiche del progetto.

**Automazione della risposta**, innescata dal callback di Telegram:

- **Accendi** -> accende il clima (`climate.set_hvac_mode: cool`). Il
  controller, che sorveglia gia' l'entita' del clima, se ne accorge e prende
  in mano target, ventola e alette alla prima valutazione utile;
- **Lascia spento** -> non fa nulla; la giornata e' gia' marcata;
- in entrambi i casi risponde al callback, cosi' il pulsante smette di girare,
  e aggiorna il messaggio con la scelta fatta.

**Da verificare in fase di realizzazione:** che accendere il clima da
un'automazione non faccia scattare l'override manuale di 60 minuti. Il
rilevamento guarda `context.user_id`, che per un'automazione dovrebbe essere
assente - ma se scattasse, il controller resterebbe fermo un'ora proprio dopo
un consenso, che e' l'opposto di quel che serve. Se succede, la via
alternativa e' esporre dall'integrazione un pulsante di consenso, che fa
partire il controller dall'interno senza passare per un comando esterno.

## Prove

Nella suite esistente, che gira senza Home Assistant installato:

- con l'approvazione attiva l'avvio diurno non parte, lancia l'evento e marca
  la giornata;
- con l'approvazione attiva l'avvio serale non parte, lancia l'evento e marca
  la sera;
- la ripresa dal riposo per notte fredda **non** chiede il permesso;
- con l'approvazione spenta - il default - non cambia niente: nessun evento,
  avvio normale;
- l'evento porta motivo, fase e le tre temperature;
- chiesto una volta, non si richiede nella stessa giornata;
- il contrassegno sopravvive a un riavvio, quindi non si richiede dopo un
  riavvio pomeridiano.

## Fuori da questa modifica

Nessun timeout con avvio automatico: e' una scelta esplicita dell'utente, non
una semplificazione. Nessuna richiesta ripetuta se la giornata peggiora dopo
un no: un no chiude la questione fino al giorno dopo. Nessun uso del meteo
**dentro** la logica di avvio - le previsioni informano la persona che decide,
non spostano le soglie; se un giorno si volesse una soglia che guarda le
previsioni, sarebbe un'altra funzionalita', da misurare a parte.
