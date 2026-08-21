# La casa è prevedibile? — studio preliminare a un controllo adattivo

**21 agosto 2026.** Prima di scrivere una riga di controllore predittivo, una
domanda sola: *sapendo com'è la casa adesso, il sole, l'esterna e cosa fa il
clima, si riesce a indovinare come sarà fra qualche ora?* Se la risposta è no,
nessun adattivo può funzionare, e lo si scopre in un pomeriggio invece che in
tre settimane di notti storte.

**Risposta: no.** Non con questi dati, non con questa casa.

## Cosa si voleva costruire

Un avvio anticipato in stile Tado, rovesciato per il freddo: al mattino il
sistema guarda sole ed esterna previsti, capisce se e quando la casa supererà la
linea di comfort, e accende **con l'anticipo minimo sufficiente** — mai per
accumulare freddo, mai in giornate che non ne hanno bisogno. La soglia di
comfort resta configurata dall'utente; il modello sceglie solo la strategia.

## I dati

Statistiche orarie di Home Assistant, 76 giorni (limite: la potenza del clima
parte dal 6 giugno), 1809 ore.

| serie | fonte | giorni |
|---|---|---|
| salotto, cucina | valvole Tado | 174 |
| esterna | `sensor.casa_temperatura_esterna` | 174 |
| sole (%) | Tado, `sensor.casa_percentuale_solare` | 174 |
| potenza clima | Shelly 2PM Gen3 | 76 |
| sole (W/m²) | piranometro della stazione WU | 46 |

Il sole di Tado è un segnale vero, non un valore fermo: **correlazione +0.824**
col piranometro sulle 1054 ore in comune. Si usa quello perché copre il triplo
del periodo.

La media di casa è stata ricostruita da salotto e cucina: lo studio parte da
prima che `sensor.clima_smart_media_di_casa` avesse `state_class`, quindi le sue
statistiche esistono solo dal 18 agosto.

## Tentativo 1 — modello orario, un solo regime

    T[t+1] − T[t] = a·(Test − T) + b·Sole + c·Potenza + d

Errore a 3 ore sui giorni mai visti: **0.25 °C**. Sembra ottimo, e non lo è: la
previsione banale — *«fra tre ore la casa sarà com'è adesso»* — sbaglia di 0.27.
Il modello la batte dell'8%.

E il coefficiente del sole viene **negativo**: il modello ha imparato che il sole
raffredda. È falso, ed è la trappola classica. Quando c'è sole il clima è acceso,
e i minimi quadrati attribuiscono al sole il merito della macchina. Correlazione
scambiata per causa — lo stesso errore che ha ucciso il vecchio adattivo
sull'esterna.

## Tentativo 2 — due regimi separati

La cura non è un modello più grosso, è un disegno sperimentale migliore: si tara
la **casa passiva** sulle 515 ore a clima spento, dove il termine dell'attuatore
non esiste e sole e dispersione diventano identificabili; poi, tenendo fermi
quei coefficienti, si ricava l'effetto del clima sulle 778 ore a macchina accesa.

    dispersione   a = +0.01352/ora   → costante di tempo 74 ore
    sole          b = +0.00075 °C/ora per punto   (positivo: corretto)
    resto         d = +0.06466 °C/ora
    clima         c = −0.2390 °C/ora per kW

**La fisica ora è giusta. Il modello è peggiorato.**

| orizzonte | modello | banale | guadagno |
|---|---|---|---|
| 1 h | 0.14 | 0.12 | **−10%** |
| 3 h | 0.32 | 0.28 | **−15%** |
| 6 h | 0.49 | 0.40 | **−23%** |
| 12 h | 0.69 | 0.48 | **−43%** |

Sulla domanda che serve davvero al controllore — *la casa supererà 26.3 entro tre
ore?* — su giorni mai visti: **6 previsioni giuste, 11 falsi allarmi, 12
sforamenti mancati.** Accenderebbe a vuoto quasi il doppio delle volte che
accenderebbe a ragione, e si perderebbe due terzi degli sforamenti veri.

## Tentativo 3 — la scala giusta: la giornata

L'utente non aveva chiesto una previsione oraria. Aveva chiesto *«oggi serve?»* —
una decisione al giorno, presa al mattino, su una grandezza più docile: il picco
della casa. Ingressi disponibili alle 9: casa adesso, massimo esterna e sole
medio della giornata (presi dai **valori veri**, non dalle previsioni: è la
versione ottimistica, e se non funziona così non funzionerà mai).

    picco = +0.621·casa9h +0.048·esterna_max +0.0065·sole +8.77

Errore sul picco, giornate mai viste: **0.36 °C** contro 0.48 del banale
(«il picco è la casa delle 9»). **+27%**: il primo guadagno vero dei tre studi.

Poi la classificazione dà **19 giornate su 19 corrette**, e sembra un trionfo.

**Non lo è.** Tutte e 19 le giornate di verifica hanno superato 26.3: il campione
non contiene **nemmeno una giornata fresca**. Un classificatore che dicesse
sempre «sì» otterrebbe lo stesso identico punteggio. Il requisito che più
importava all'utente — *non partire in giornate fresche* — è esattamente quello
che questi dati **non possono verificare**, perché il fresco comincia il 21
agosto, dopo la fine dello storico.

E un fallimento vero resta anche fra i giorni caldi: il **20 agosto**, stimato
27.1, reale **29.0**. Quasi due gradi, proprio nel giorno più caldo.

## Perché

Un numero spiega tutti e tre i tentativi: **l'escursione giornaliera mediana
della casa è 1.13 °C** (massima 3.39, su 73 giorni pieni), con una costante di
tempo di 74 ore.

Questa casa non si muove. La previsione banale è forte proprio perché non c'è
quasi niente da prevedere — e quel poco che muove la casa non è la fisica, sono
le finestre aperte, le porte, le persone. Cose che il modello non vede e che
sono più grandi del segnale che vede.

C'è anche un'ironia utile: il requisito «non partire quando fa fresco» è già
soddisfatto oggi da una **singola soglia** (`auto_start_outdoor`), e il modello
non si è dimostrato capace di fare meglio.

## Cosa fare

**Non costruire il controllo adattivo adesso.** Non perché sia difficile, ma
perché non è dimostrato che serva: i tre guadagni misurati di questo progetto —
il criterio nuovo (−17%), la notte mite (−48% su una notte), gli avvisi sull'aria
gratis — vengono tutti da **regole tarate su misure**, non da previsioni. Non è
un caso: è quello che una casa lenta premia.

Il dataset ha una lacuna precisa e sanabile: **nessuna giornata fresca**. Da oggi
comincia la stagione che la riempie, e `sensor.clima_smart_media_di_casa` ha
`state_class` dal 18 agosto, quindi accumula statistiche permanenti da solo.

Si rifà lo studio quando ci saranno abbastanza giornate sotto soglia da poter
misurare i **falsi allarmi**, che sono la metrica che conta. Gli script sono in
questa cartella e si rigirano così com'è:

    python3 docs/studi/estrai.py && python3 docs/studi/studio3.py

## Poscritto — e allora sfruttare l'inerzia? (`studio4.py`)

Se la casa tiene il freddo 74 ore, verrebbe da raffreddare di notte — quando il
compressore lavora contro 24 gradi invece che contro 33 — e lasciarla scorrere di
giorno. Misurato, e il risultato è rovesciato:

| | resa | esterna media | potenza media |
|---|---|---|---|
| notte (23-07) | **0.158** °C di casa per kWh | 24.1 | 494 W |
| giorno (11-20) | **0.412** °C di casa per kWh | 33.2 | 629 W |

Di notte la macchina rende un terzo, contro quel che direbbe la termodinamica.

**Il motivo non è il rendimento, è la geometria: di notte la porta della camera
è chiusa.** Il clima raffredda la camera e il freddo non raggiunge salotto e
cucina, che sono i sensori con cui si misura «la casa». Prova diretta, notte del
21 agosto: cinque ore di macchina accesa, comodino da 26.5 a 22.6, **media di
casa ferma a 26.2**.

Quindi l'accumulo notturno non è praticabile in questa casa — non per un rendimento
scarso, ma perché quel freddo non può fisicamente arrivare dove servirebbe. Per
farlo bisognerebbe dormire con la porta aperta, con la camera come sorgente di
freddo e il rumore addosso.

**Nota di onestà sui numeri qui sopra: sono confusi anche loro.** Non misurano il
rendimento della macchina notte contro giorno; misurano quanto risponde la casa,
e le due fasce hanno una topologia diversa. Il confronto pulito, in questa casa,
non si può fare con i dati disponibili.
