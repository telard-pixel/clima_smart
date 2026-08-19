# Aiuto invernale ai caloriferi - design

## Obiettivo

Oggi, fuori dalla stagione calda (`not summer`, sotto `summer_threshold`), il
controller resta passivo sul riscaldamento: non lo tocca mai, ne' in bene ne'
in male. L'utente vuole che nella stagione fredda la pompa di calore aiuti
attivamente i caloriferi in camera da letto, dove la temperatura tenuta in
casa e' al massimo 20 gradi e in camera al massimo 19. Non deve toccare le
altre stanze, non deve scaldare durante il sonno, e deve rispettare i due
tetti come limiti, non come obiettivi da inseguire in ogni momento.

## Meccanica del ciclo

Nuovo blocco in `_compute`, dentro il ramo `if not summer:` che oggi si
limita a "fuori stagione: non tocco il riscaldamento". Attivo solo in
`MODE_SMART`, solo fuori dalle fasi `PHASE_SLEEP` e `PHASE_WIND_DOWN`.

Due soglie sulla stessa aria di ripresa gia' usata per il raffrescamento -
quella che la macchina stessa insegue, non il comodino:

- **avvio**: `winter_room_start` (default 18.0). Sotto questa temperatura, se
  l'unita' e' spenta o in un modo diverso da `heat`, si passa a `heat` con
  target `winter_room_target`.
- **arresto**: `winter_room_target` (default 19.0). Raggiunta o superata, si
  spegne.

Le due soglie sono gia' la propria isteresi (un grado pieno fra le due): non
serve un'isteresi separata sopra. Stato persistito fra un riavvio e l'altro
con lo stesso schema del riposo per notte fredda (`_winter_heating`,
salvato/ricaricato in `_memoria`/`_async_load_memoria`), cosi' un riavvio a
meta' ciclo non perde il contesto e non ricomincia daccapo un ciclo gia'
avviato.

## Rete di sicurezza casa

Prima di accendere si legge la media di salotto/cucina/studio (stessi
`house_sensors` dell'estate, stessa funzione `_house_average`). Se e' gia' a
`winter_house_ceiling` (default 20.0) o oltre, l'avvio non parte: i
caloriferi stanno gia' facendo il loro lavoro, la camera non deve
aggiungersi. Nessun anello: solo questo controllo puntuale, valutato a ogni
passata come una guardia, non come un target da inseguire.

Se l'aria di ripresa o la media di casa non sono disponibili, il ciclo non
parte (fail closed, stessa filosofia della guardia estiva "fuori stagione").

## Esclusione del sonno

Riusa `sleep_start`/`sleep_end` gia' configurati, nessun nuovo orario.
`PHASE_SLEEP` e `PHASE_WIND_DOWN` sono escluse dall'avvio; se un ciclo era
gia' partito ed entra la notte fonda, si spegne come qualunque altro
riscaldamento attivo quando la fase cambia (nessuna eccezione per un ciclo
in corso: il confine e' netto).

## Cosa resta fuori da questa versione

Ventola e alette non vengono comandate: nessun valore inviato, l'unita'
decide da sola. A differenza del raffrescamento non ci sono ancora misure sul
campo per tarare bande sensate; si parte semplice e si affina quando arriva
il primo inverno vero con dati reali, come e' successo con l'estate. Nessun
anello sulle altre stanze (scartato in fase di brainstorming): la camera
scalda se stessa, il resto della casa resta compito dei caloriferi.

## Configurazione

Tre nuove opzioni nel config flow, accanto alle altre:

- `winter_room_start` (default 18.0)
- `winter_room_target` (default 19.0)
- `winter_house_ceiling` (default 20.0)

Nessuna nuova entita' collegata: riusa `climate_entity` (l'aria di ripresa,
gia' letta per il raffrescamento) e `house_sensors`, entrambi gia' esistenti.
Il comodino non entra in questo ciclo.

## Test previsti

- parte sotto 18 fuori dal sonno, casa sotto 20;
- non parte durante notte fonda ne' wind-down, anche sotto 18;
- non parte se la casa e' gia' a 20 o oltre, anche con la camera fredda;
- si ferma raggiunti i 19;
- lo stato (`_winter_heating`) sopravvive a un riavvio a ciclo in corso;
- un ciclo in corso si interrompe se la notte fonda entra prima che la
  camera raggiunga il target.

## Non fa parte di questa modifica

Nessuna distribuzione qui prevista: siamo ad agosto, la stagione fredda e'
lontana. Spec e piano restano pronti; l'installazione sull'istanza avverra'
prima dell'inverno, con lo stesso rito di backup/riavvio/verifica gia' usato
per ogni rilascio di Clima Smart.
