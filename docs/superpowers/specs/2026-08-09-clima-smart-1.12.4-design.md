# Clima Smart 1.12.4 design

## Obiettivo

Rilasciare una correzione minima che spenga anche il programma `dry` quando la
stagione calda è terminata e ridurre in modo reversibile l'aggressività del
controllo live impostando `trim_min` da 22 a 23 °C.

## Modifica al controller

La guardia fuori stagione deve trattare `dry` come `cool`: entrambi producono
raffrescamento/deumidificazione e devono ricevere `HVAC_OFF` dopo la conferma di
uscita dalla stagione calda. `heat` e gli altri stati non devono essere spenti.
Non sono previsti refactoring o cambiamenti alle altre decisioni del controller.

Il manifest passa da `1.12.3` a `1.12.4`. La regressione automatica deve fallire
sul tag 1.12.3 e passare con la correzione.

## Configurazione live

L'unico parametro modificato è `trim_min`, da 22.0 a 23.0 °C. Target casa,
target sonno, soglie di avvio, orari e ogni collegamento di entità restano
invariati. La modifica deve avvenire dopo un backup valido e deve poter essere
annullata ripristinando il valore 22.0.

## Distribuzione e rollback

Prima delle scritture su Home Assistant si creano:

- un backup Home Assistant verificato;
- un archivio mirato dei file live interessati;
- una copia privata della configurazione Clima Smart precedente.

Si distribuiscono soltanto i file necessari alla 1.12.4, riletti via Samba e
confrontati byte per byte. Dopo un unico riavvio si verifica che Home Assistant
sia `RUNNING`, la config entry sia `loaded`, il manifest sia 1.12.4 e non siano
comparsi errori Clima Smart. Poi si imposta `trim_min=23.0` tramite il normale
flusso Home Assistant e si controllano stato diagnostico, target e almeno un
ciclo periodico.

Il rollback ripristina i file salvati, riporta `trim_min` a 22.0 e riavvia una
sola volta.

## Verifica e pubblicazione

La validazione comprende la regressione `dry`, l'intera suite, compilazione
Python, JSON, `git diff --check`, confronto dei file live e osservazione runtime.
Solo dopo la verifica live si pubblica una PR dedicata, la si integra in `main`
e si crea la release/tag `1.12.4`.
