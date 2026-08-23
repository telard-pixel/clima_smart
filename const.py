"""Constants for the Clima Smart integration."""

from __future__ import annotations

DOMAIN = "clima_smart"

PLATFORMS: list[str] = ["switch", "select", "number", "sensor"]

# --- Config-entry data keys (set once in the config flow) ---
CONF_CLIMATE = "climate_entity"
CONF_OUTDOOR = "outdoor_sensor"
CONF_OUTDOOR_FALLBACK = "outdoor_fallback_sensor"
CONF_ECO_SWITCH = "eco_switch"
CONF_MUTE_SWITCH = "mute_switch"
CONF_NIGHT_SWITCH = "night_switch"
# Optional indoor humidity source, only used by MODE_SMART to pick the `dry`
# program. Left empty the mode still works, it just never dehumidifies.
CONF_HUMIDITY = "humidity_sensor"
# Un termometro vero della stanza, fuori dal getto d'aria. Quando c'e', prende il
# posto della temperatura di ripresa della macchina - che non e' la stanza ma
# l'aria che rientra nell'unita', e che la ventola stessa sposta di un grado.
CONF_ROOM_SENSOR = "room_sensor"
# The two air-direction selects, if the unit exposes them. Only MODE_SMART uses
# them, and only inside the sleep window: outside it they are left to whoever set
# them last.
CONF_VANE_H = "vane_horizontal"
CONF_VANE_V = "vane_vertical"

# --- Option keys (tunable at runtime via the options flow / number / select) ---
CONF_TARGET_HOME = "target_home"
CONF_ECO_BAND = "eco_band"
CONF_ECO_OUTDOOR_ON = "eco_outdoor_on"
CONF_ECO_OUTDOOR_OFF = "eco_outdoor_off"
CONF_SUMMER_THRESHOLD = "summer_threshold"
CONF_OVERRIDE_MINUTES = "override_minutes"
CONF_DAY_START = "day_start"
CONF_NIGHT_START = "night_start"
CONF_MORNING_OFF_START = "morning_off_start"
CONF_MORNING_OFF_ENABLED = "morning_off_enabled"
# Deep-night window: same quiet behaviour as the night phase, but its own colder
# target. Crosses midnight, so the end is earlier than the start.
CONF_TARGET_SLEEP = "target_sleep"
CONF_SLEEP_START = "sleep_start"
CONF_SLEEP_END = "sleep_end"
# Presenza: se sono fuori, la notte fonda (target piu' freddo + spinta iniziale
# della ventola) non deve partire - non ha senso inseguire i gradi e spingere la
# ventola per una stanza vuota. Fuori casa il clima resta nel regime di comfort,
# come prima dell'inizio della notte fonda. Al rientro riprende da solo. Uno stato
# rotto (unknown/unavailable) o l'entita' vuota valgono "a casa": un GPS guasto non
# deve togliere la notte fonda a chi sta dormendo.
CONF_PRESENCE_ENTITY = "presence_entity"
# Split units read the return air, not the room, and stop short: measured here the
# room settled 0.5-1.0 above a 25.0 setpoint. This shifts what we send to the unit
# without touching the target we aim the room at, so the diagnostics stay honest.
CONF_SETPOINT_OFFSET = "setpoint_offset"
# Position asked of both vanes during the sleep window. `swing` keeps the air
# moving instead of pointing it at the bed, and is offered by both selects on this
# unit; any other value the selects accept works too.
CONF_VANE_SLEEP = "vane_sleep_position"
# Positions restored when the sleep window ends: during the day the vanes stay
# still. Applied once, at the wind-down transition, so moving them by hand later
# is not undone at the next pass.
CONF_VANE_DAY_H = "vane_day_horizontal"
CONF_VANE_DAY_V = "vane_day_vertical"
# MODE_SMART normally never starts the unit. With this on, and only at the opening
# of the sleep window, it may: one attempt per night, so that switching the climate
# off later in the night is not undone at the next pass.
CONF_AUTO_START_SLEEP = "auto_start_sleep"
# Con questa accesa il controller non accende mai da solo: quando le
# condizioni di avvio scattano lancia un evento e lascia decidere una
# persona. Serve perche' le soglie misurate non sanno tutto - il 20 agosto
# 2026 l'avvio e' scattato a regola d'arte un'ora prima di un temporale che
# ha portato l'esterna da 30 a 22 gradi da solo. Chi ascolta l'evento (una
# automazione, fuori di qui) chiede e poi accende. Spenta di default:
# nessuna installazione esistente cambia comportamento.
CONF_START_APPROVAL = "start_approval"
# Daytime start: the room temperature at which the controller switches the unit on
# by itself, once a day. Zero disables it. This is a real start - the room has got
# hot and someone has to close the windows - while the evening one is just the
# night schedule beginning.
CONF_AUTO_START_ROOM = "auto_start_room"
# Other rooms' thermometers. The rest of the house warms up before the bedroom, so
# their average is the earlier signal: it lets the unit start before the outdoor
# peak instead of chasing it. Measured on this house, the bedroom's own Tado valve
# read 22.99 against the Haier's 26.5 in the same room with the unit off for an
# hour and a half, so it is not in this list by default.
CONF_HOUSE_SENSORS = "house_sensors"
CONF_AUTO_START_HOUSE = "auto_start_house"
# Guard: no daytime start at all unless it is really a hot day outside.
CONF_AUTO_START_OUTDOOR = "auto_start_outdoor"
# Le due soglie dell'aiuto invernale, sulla stessa aria di ripresa gia'
# letta per il raffrescamento: sono gia' la propria isteresi (un grado di
# distanza fra avvio e tetto), non serve aggiungerne una separata. Zero
# disattiva tutto - il comportamento resta quello di sempre, passivo.
CONF_WINTER_ROOM_START = "winter_room_start"
CONF_WINTER_ROOM_TARGET = "winter_room_target"
# Rete di sicurezza: non accende se la media delle altre stanze e' gia' al
# tetto di casa. Zero disattiva il controllo (nessun tetto).
CONF_WINTER_HOUSE_CEILING = "winter_house_ceiling"
# Sotto questa esterna la notte fonda entra in un regime diverso: l'aria di
# ripresa non basta piu' a dire se in stanza si sta gia' bene, perche' legge il
# condotto e non il letto. Sotto soglia si media esterna e comodino, e si lascia
# riposare la macchina quando quella media e' gia' al target di notte fonda -
# tanto fuori sta facendo il lavoro da solo. Zero disattiva: notte fonda sempre
# uguale, come prima.
CONF_NIGHT_START_OUTDOOR = "night_start_outdoor"

# --- Notte mite: fuori e' fresco ma le finestre restano chiuse ---
# Fra la notte normale e la pausa per notte fredda manca una via di mezzo, e
# nasce da un vincolo che non e' termico ma di sicurezza: di notte le finestre
# restano chiuse, quindi l'aria fresca di fuori non entra e il clima resta
# l'unica cosa che raffredda. Pero' con l'esterna bassa i muri smettono di
# spingere calore dentro, e inseguire il target pieno diventa spesa senza
# guadagno: la notte del 21 agosto 2026, con 21 gradi fuori, la macchina
# lavorava a 460-580 W per scendere da 26.5 a 22.
# Quindi sotto `night_mild_outdoor` la notte fonda si accontenta di
# `target_sleep_mild`, piu' alto del target pieno. Non e' la pausa per notte
# fredda, che spegne: qui la macchina continua a lavorare, solo con un obiettivo
# meno ambizioso. Zero disattiva: notte fonda sempre uguale, come prima.
CONF_NIGHT_MILD_OUTDOOR = "night_mild_outdoor"
CONF_TARGET_SLEEP_MILD = "target_sleep_mild"

# --- La linea di comfort delle altre stanze (anello esterno) ---
# Di giorno l'obiettivo non e' la camera: sono salotto, cucina e ingresso. La
# camera e' lo strumento - sta piu' fredda perche' e' la sorgente di freddo di
# tutto il trilocale, e l'aria passa dalla porta aperta. Quindi il target della
# camera non lo sceglie l'utente: lo sceglie il controller, tanto basso quanto
# serve perche' le altre stanze stiano sulla linea. Zero disattiva tutto e si
# torna al target fisso di prima.
CONF_HOUSE_TARGET = "house_target"
# Estremi entro cui il controller puo' muovere il target della camera.
CONF_TRIM_MIN = "trim_min"
CONF_TRIM_MAX = "trim_max"
# Con un termometro in camera (`room_sensor`), sotto questa temperatura non si
# scende oltre: la camera serve la casa, ma resta una stanza in cui si dorme.
# Zero disattiva il limite.
CONF_ROOM_FLOOR = "room_floor"
# Vincolo di realta', non un secondo regolatore: sopra questa temperatura esterna
# la macchina e' al limite e chiedere alla camera meno di `trim_min_hot` non porta
# gradi in casa, porta solo frequenza. Misurato: il rendimento e' migliore fra 28
# e 45 Hz (12-13 W/Hz) e peggiora sopra i 56 (15 W/Hz a 71). Zero disattiva.
CONF_HOT_OUTDOOR = "hot_outdoor"
CONF_TRIM_MIN_HOT = "trim_min_hot"

# --- Target adattivo sull'esterna ---
# Chiedere 25 gradi con 28 fuori e con 36 fuori non e' la stessa richiesta: nella
# seconda la macchina insegue un divario che non le compete, e il grado in piu'
# dentro non si sente. Sopra una soglia il target sale in proporzione, fino a un
# massimo. Misurato su questa unita': W = 17.7 x Hz - 194, quindi ogni grado di
# divario in meno si traduce in frequenza piu' bassa e rendimento migliore.
CONF_ADAPTIVE_START = "adaptive_outdoor_start"
CONF_ADAPTIVE_SLOPE = "adaptive_slope"
CONF_ADAPTIVE_MAX = "adaptive_max"

# --- Defaults (validated values from the original automation) ---
DEFAULT_TARGET_HOME = 26.0
DEFAULT_ECO_BAND = 2.0
DEFAULT_ECO_OUTDOOR_ON = 33.0
DEFAULT_ECO_OUTDOOR_OFF = 34.0
DEFAULT_SUMMER_THRESHOLD = 21.0
DEFAULT_OVERRIDE_MINUTES = 60
DEFAULT_DAY_START = "10:00:00"
DEFAULT_NIGHT_START = "22:00:00"
DEFAULT_MORNING_OFF_START = "08:00:00"
# Lo spegnimento del mattino e la pausa (gap) che lo segue si possono togliere.
# Misurato su questa casa: il calore entra fra le 07:30 e le 10:00, quindi
# spegnere alle 08:30 lascia la casa scaldarsi proprio nella finestra peggiore e
# si riparte da piu' caldo - controproducente. Con lo spegnimento disattivato,
# dopo la notte fonda si passa diretti alla gestione di giorno (anello attivo),
# senza wind_down ne' gap ne' spegnimento. Default True per non cambiare il
# comportamento delle installazioni esistenti.
DEFAULT_MORNING_OFF_ENABLED = True
DEFAULT_TARGET_SLEEP = 23.0
DEFAULT_SLEEP_START = "23:30:00"
DEFAULT_SLEEP_END = "07:30:00"
DEFAULT_PRESENCE_ENTITY = "person.rob"
DEFAULT_SETPOINT_OFFSET = 0.0
DEFAULT_VANE_SLEEP = "swing"
DEFAULT_VANE_DAY = ""
DEFAULT_AUTO_START_SLEEP = False
DEFAULT_START_APPROVAL = False
DEFAULT_AUTO_START_ROOM = 0.0
DEFAULT_AUTO_START_HOUSE = 0.0
DEFAULT_AUTO_START_OUTDOOR = 0.0
DEFAULT_WINTER_ROOM_START = 0.0    # zero: aiuto invernale disattivato
DEFAULT_WINTER_ROOM_TARGET = 19.0
DEFAULT_WINTER_HOUSE_CEILING = 0.0   # zero: nessun tetto casa
DEFAULT_NIGHT_START_OUTDOOR = 20.0
DEFAULT_NIGHT_MILD_OUTDOOR = 0.0   # zero: nessuna notte mite, come prima
DEFAULT_TARGET_SLEEP_MILD = 23.0
DEFAULT_ADAPTIVE_START = 0.0      # zero disattiva del tutto l'adattamento
DEFAULT_ADAPTIVE_SLOPE = 0.25     # un quarto di grado di target per grado esterno
DEFAULT_ADAPTIVE_MAX = 1.5
DEFAULT_HOUSE_TARGET = 0.0       # zero: anello esterno disattivato
DEFAULT_TRIM_MIN = 21.0
DEFAULT_TRIM_MAX = 27.0
DEFAULT_ROOM_FLOOR = 0.0         # zero: nessun limite inferiore in camera
DEFAULT_HOT_OUTDOOR = 0.0        # zero: nessun vincolo legato all'esterna
DEFAULT_TRIM_MIN_HOT = 23.0

# While the unit is already cooling, the season threshold drops by this much, so a
# cycle in progress is not cut off by a small dip in the outdoor reading.
SUMMER_HYSTERESIS = 2.0
# Una lettura fuori da questo intervallo non e' una temperatura, e' un guasto.
# Serve perche' la difesa "sensore non disponibile" non scattava su un numero
# assurdo: quello passava come valido e scavalcava la protezione scritta apposta.
PLAUSIBLE_MIN_C = -30.0
PLAUSIBLE_MAX_C = 60.0
# E anche dentro l'intervallo plausibile, uscire dalla stagione calda spegne il
# condizionatore per il resto della giornata: con la soglia a 21 gradi bastava
# **una sola** lettura sotto 19 per farlo in pieno agosto. Prima di spegnere si
# pretende che la condizione duri, cosi' un campione isolato non decide nulla.
SEASON_EXIT_CONFIRM_SECONDS = 900

# Versione del piccolo archivio che tiene in vita, fra un riavvio e l'altro, i
# contrassegni "gia' fatto oggi" e la resa manuale.
STORAGE_VERSION = 1

# Ripiego, quando la macchina non dichiara il proprio passo: normalmente
# l'adattamento si quantizza su `target_temp_step`, perche' uno scatto piu' fine
# del passo del climatizzatore non arriva mai come lo si e' pensato. Misurato:
# con questo mezzo grado il comando 24.5 diventava 25.0, un grado pieno.
ADAPTIVE_QUANTUM = 0.5
# Due difese contro il ballo, le stesse della ventola. Salire e' immediato: se
# fuori si alza sul serio, il target deve seguire. Scendere richiede un quanto
# intero di margine, cioe' che l'esterna torni sotto la soglia che aveva fatto
# salire. E fra un cambio e l'altro passa comunque questo tempo, cosi' una
# stazione che oscilla fra 33 e 35 non produce un comando ogni cinque minuti.
# Un'ora e non venti minuti: col vecchio valore l'attesa non frenava nulla, si
# limitava a dettare il ritmo dell'oscillazione, che infatti il 4 agosto e' stata
# di venti-venticinque minuti esatti. L'esterna si muove piano, ridecidere spesso
# non aggiunge informazione.
ADAPTIVE_MIN_DWELL_SECONDS = 3600

# --- Anello esterno: quanto piano correggere ---
# Una casa risponde in ore, non in minuti: misurato, il pomeriggio piu' efficace
# ha tolto 0.72 gradi alla media in otto ore. Correggere in fretta significa solo
# rincorrere il rumore dei termometri.
HOUSE_TRIM_DWELL_SECONDS = 2700          # tre quarti d'ora fra una correzione e l'altra
# Banda morta attorno alla linea di comfort: dentro questa, non si tocca niente.
HOUSE_TRIM_DEADBAND = 0.25
# L'esterna riporta gradi interi e balla sulla soglia: senza questo margine il
# vincolo si accenderebbe e spegnerebbe a ogni lettura. E' lo stesso difetto che
# il 4 agosto ha fatto rincorrere il setpoint dieci volte in un pomeriggio.
#
# Storia di questo numero, perche' spiega a cosa serve. Nato a 1.0, e la sera del
# 6 agosto il vincolo si e' acceso e spento due volte in venti minuti: la
# stazione ballava fra 34 e 36 e attraversava tutta la banda. Portato a 2.0 per
# assorbire quel ballo.
#
# Poi si e' scoperto che il ballo non era la temperatura: Weather Underground
# consegna i gradi Celsius **interi**, perche' la stazione carica in Fahrenheit e
# la conversione arrotonda. Chiedendo i dati in Fahrenheit e mediandoli su venti
# minuti, l'esterna e' diventata liscia: passo mediano 0.55 invece di 1.00, mezza
# inversione all'ora invece di 2.3.
#
# Quindi **1.0**, non 2.0 e nemmeno 0.5. La regola imparata due volte su questo
# impianto e' che **la banda deve restare piu' larga del passo del segnale**: la
# media mobile ha passo mediano 0.55, quindi mezzo grado di banda si farebbe
# attraversare da un singolo campione e il lampeggio tornerebbe. Un grado la
# copre con margine e dimezza comunque l'attesa rispetto a prima.
HOT_OUTDOOR_HYSTERESIS = 1.0
# Stessa isteresi, stesso motivo, sul lato opposto: la media esterna/comodino
# balla sulla soglia dei 22 quanto quella esterna/hot_outdoor balla sulla sua.
COLD_NIGHT_HYSTERESIS = 1.0
# E ancora la stessa, sulla soglia della notte mite. Qui il segnale e' l'esterna
# nuda, che di notte scivola lentamente ma balla sul decimo: senza banda, una
# notte assestata a ridosso della soglia farebbe rimbalzare il target fra pieno
# e mite - e un grado di target su questa macchina e' un grado di scarto, che si
# trascina dietro anche la ventola.
NIGHT_MILD_HYSTERESIS = 1.0

# --- Anello esterno: il freno della saturazione ---
# La camera e' lo strumento, non l'obiettivo: si accetta che stia piu' fredda del
# resto della casa, perche' e' da li' che parte il freddo. Ma quel divario ha un
# punto oltre il quale non compra piu' niente, e il 7 agosto 2026 lo abbiamo
# misurato su 36 finestre di un'ora, pomeriggi dal 2 al 7 agosto, tenendo conto
# dell'esterna:
#
#   un grado in piu' di divario casa-camera
#     sul calo della casa   +0.006 C/h   con errore tipico 0.136 e R2 = 0.01
#     sulla potenza           +40 W
#
# Cioe': **il costo si misura, il beneficio no**. Sotto quella soglia di
# rilevabilita' non c'e' un guadagno piccolo, c'e' un guadagno che non si vede.
# Il collo di bottiglia non e' la potenza della macchina, e' l'aria che deve
# passare da una stanza all'altra: raffreddare ancora di piu' la camera non la
# fa passare piu' in fretta.
#
# La giornata che ha fatto scattare la misura: il 7 agosto, il giorno **piu'
# fresco** della settimana (30.6 di media contro 33.9), ha speso 6.756 kWh contro
# 5.641 del 3 agosto (+20%) per portare la casa allo stesso identico punto
# (26.50 contro 26.38). L'anello aveva inchiodato il target al suo minimo, 22.0,
# e il divario era sopra 1.5 per quasi tutto il giorno.
#
# 1.5 perche' quasi tutto il raffreddamento osservato e' avvenuto sotto 1.2, e
# lascia margine. L'isteresi segue la regola imparata due volte su questo
# impianto - **la banda deve restare piu' larga del passo del segnale**: qui il
# segnale e' l'aria di ripresa, che si muove a mezzo grado, quindi 0.75.
SATURATION_GAP = 1.5
SATURATION_HYSTERESIS = 0.75

# --- Anello esterno: il passo si giudica dal risultato ---
# Il freno del divario ha un difetto di fondo, visto sul campo l'8 agosto 2026: il
# divario si stringe **proprio quando la macchina lavora bene**, cosi' il freno
# molla, il target riscende e la macchina ricomincia a tirare. Un cane che si
# morde la coda. Il divario e' un indizio; il risultato e' la prova.
#
# Quindi ogni passo in giu' viene giudicato da quello che ottiene: dopo una
# attesa piena, se la media di casa non e' scesa di almeno questo, il passo non ha
# reso e va restituito. Misurato su tutti i passi in giu' registrati (5, 6 e 8
# agosto), la separazione e' netta:
#
#   8 ago 10:18  25->24   casa -0.12   ha reso
#   8 ago 11:03  24->23   casa -0.02
#   8 ago 11:49  23->22   casa +0.20
#   6 ago 14:40  25->24   casa +0.01
#   6 ago 15:25  24->23   casa +0.01
#
# Uno su cinque. 0.10 sta in mezzo fra il passo che ha reso e il migliore di
# quelli che non hanno reso, e vale come "almeno un decimo in tre quarti d'ora",
# cioe' circa 0.13 gradi orari: il ritmo dei pomeriggi in cui la casa scendeva
# davvero.
TRIM_PROBE_GAIN = 0.10

# How long async_start waits for the master switch and the mode select to restore
# before opening the barrier in degraded mode.
RESTORE_TIMEOUT_SECONDS = 10

# Periodic re-evaluation cadence (event-driven updates happen on top of this).
UPDATE_INTERVAL_SECONDS = 300
# After we send a command, ignore "manual override" detection for this long so the
# cloud round-trip catching up to our value is not mistaken for a user action.
# 180s gives ~2-3x margin over the typical Haier cloud latency (10-60s).
COMMAND_SETTLE_SECONDS = 180
# Hard cap on a single climate/switch service call. A hung Haier cloud must not
# block the control loop nor the lock-drain in async_stop (unload) indefinitely;
# on timeout the call is treated as failed and retried on the next pass.
SERVICE_CALL_TIMEOUT_SECONDS = 60

# --- Operating modes (the "Modo" select) ---
MODE_OFF = "off"
# L'unico modo di controllo: target fisso con le fasce orarie, ventola e programma
# decisi dai sensori, target adattato alla temperatura esterna.
MODE_SMART = "smart"
# Due soli modi. Gli altri quattro erano il ricalco dell'automazione originale e
# nessuno li usava: la logica adattiva li comprende tutti. `off` resta perche' non
# e' un doppione dello switch master - quello dice "non toccare niente", questo
# dice "tienilo spento", che con gli avvii automatici e' un'altra cosa.
MODES: list[str] = [MODE_SMART, MODE_OFF]

# --- MODE_SMART: fan steps by how far the room still is above target ---
# Read as: 3 degrees or more above -> high, 1 or more -> medium, otherwise low.
#
# `high` alzata da 2.0 a 3.0 il 12 agosto 2026, sull'analisi energetica a tre
# agenti indipendenti. Misurato: `high` assorbe ~800 W (53 Hz) contro ~420 W (29
# Hz) di `medium` - **raddoppia la potenza**. Il 10 agosto la ventola e' stata
# alta 3.5 ore (fino a 72 Hz, 814 W) e la casa **non e' scesa di un grado**:
# potenza doppia, zero raffreddamento in piu'. La causa: l'anello abbassa il
# target per servire la casa, lo scarto camera-target sale a ~3, e la vecchia
# soglia 2.0 (effettiva 3.0 con l'isteresi) faceva scattare `high` su uno scarto
# **artificiale**, non su un vero bisogno di raffreddare la camera. La giornata
# piu' efficiente (9 agosto: casa piu' fredda, 28.7 Hz, la piu' economica pur col
# meteo piu' caldo) girava tutta a `medium`. Con soglia 3.0 (effettiva 4.0),
# `high` resta come valvola per il pull-down da avvio molto caldo, ma il regime
# lavora a `medium`, il cuore efficiente della macchina (28-45 Hz).
FAN_BANDS: tuple[tuple[float, str], ...] = (
    (3.0, "high"),
    (1.0, "medium"),
    (0.0, "low"),
)
# Increasing order, used to compare two steps and to cap the night one.
FAN_ORDER: tuple[str, ...] = ("low", "medium", "high")
# A downgrade needs the gap to be this far inside the lower band, and this many
# seconds since the last change: without both, a tenth of a degree of noise in
# the reported temperature would cycle the fan up and down forever.
# **Piu' largo del guadagno dell'anello, che e' stato misurato e vale 1.0.**
# La ventola decide su un numero che la ventola stessa sposta: un passo vale un
# grado pieno sulla temperatura di ripresa, in un paio di minuti, con le altre
# stanze ferme a due centesimi. Con una banda piu' stretta del guadagno
# l'oscillazione e' aritmetica, non sfortuna: il 4 agosto i punti di inversione
# sono caduti dodici volte esatte su 26.5 e 25.5, cioe' sui bordi di banda.
#
# E il passaggio da 0.3 a 0.5 non aveva cambiato **nulla**: questa unita' riporta
# a passi di mezzo grado, quindi 1.0+0.3 e 1.0+0.5 arrotondano entrambi alla
# stessa prima lettura raggiungibile, 1.5, e 1.0-0.3 e 1.0-0.5 entrambi a 0.5.
# Numero cambiato, comportamento identico.
#
# **Margine asimmetrico**, e non e' un vezzo: salire di un passo costa, scendere
# fa risparmiare, quindi le due direzioni non meritano la stessa reticenza.
#
# Misurato il 5 agosto. Con margine simmetrico 1.0 la ventola entrava in `medium`
# a scarto 2.0 e per uscirne pretendeva 0.0, cioe' la stanza esattamente sul
# target: e' entrata alle 13:30 e non e' piu' uscita per otto ore. Il conto di quel
# pomeriggio, a pari esterna: 5.409 kWh contro 4.648 e 4.713 dei due giorni prima,
# **+0.70 kWh**, e la casa e' rimasta piu' calda (+0.14 gradi guadagnati contro
# +0.23 e +0.34). Piu' portata d'aria alza il tetto del compressore, e la potenza
# media e' passata da ~600 a 691 W: novanta watt, di cui la ventola ne vale otto.
#
# Con 1.0 in salita e 0.5 in discesa si entrava a 2.0 e si usciva a 0.5: banda
# larga 1.5, piu' del guadagno dell'anello misurato (1.0), quindi niente ciclo
# limite.
#
# **Spostata il 23 agosto 2026, su richiesta dell'utente**, che con lo scarto a
# +1.5 e la ventola ferma su `low` ha giudicato la macchina troppo pigra. Fra 0.5
# e 2.0 la ventola restava bassa e non ne usciva: un punto fisso ampio mezzo
# grado piu' del guadagno, in cui la casa puo' stare a lungo.
#
# **Solo la salita**, da 1.0 a 0.5: si entra a **1.5** e si continua a uscire a
# **0.5**. La banda passa da 1.5 a 1.0.
#
# La scelta e' fra due lezioni gia' pagate, e le si e' pesate cosi'. Spostare
# tutta la banda (salita 0.5, discesa 1.0) avrebbe tenuto la larghezza a 1.5 ma
# portato l'uscita a 0.0 - **esattamente la condizione del 5 agosto**, quando
# `medium` rimase otto ore e costo' 0.70 kWh in piu' a pari esterna consegnando
# meno raffrescamento. Quella e' una misura, non un rischio. Stringere la banda a
# 1.0 la porta invece **pari** al guadagno dell'anello, che e' la condizione
# limite dell'oscillazione del 4 agosto - ma quell'oscillazione fu misurata con
# `MIN_FAN_DWELL_SECONDS` a **dieci minuti**, e rigiocando la traccia con la
# permanenza a mezz'ora gli scatti scesero da 14 a 4. La permanenza, non la
# larghezza, e' oggi la difesa vera: e frena le discese, cioe' proprio il verso
# in cui il ciclo si chiuderebbe.
#
# Quindi si accetta la banda pari al guadagno e **si sorveglia il numero di
# cambi di ventola al giorno**: erano 36 in 11 giorni in fascia diurna, uno solo
# sotto la mezz'ora. Se risalgono, la banda va riallargata e la richiesta
# rinegoziata.
#
# Effetto collaterale nella stessa direzione: anche `high` diventa piu' facile,
# si entra a 3.5 invece che a 4.0. Ma `high` costa il doppio di `medium`: se il
# consumo dei pomeriggi caldi peggiora, il primo indiziato e' questo.
FAN_HYSTERESIS_UP = 0.5
FAN_HYSTERESIS_DOWN = 0.5
# Di notte no, e per un motivo che non e' tecnico: `low` e' il silenzio in camera,
# ed e' la ragione per cui il muto e' scollegato. Con 1.5 la discesa avrebbe
# preteso due gradi sotto il setpoint comandato, cioe' non sarebbe mai avvenuta.
# E non serve: la notte fra il 4 e il 5 agosto, con questo valore, ha prodotto
# **due soli cambi di ventola in sette ore**, perche' la tabella notturna ha un
# bordo solo e la permanenza minima di mezz'ora basta gia'.
FAN_HYSTERESIS_SLEEP = 0.5
# Mezz'ora invece di dieci minuti. Ha senso perche' fra i due passi non c'e'
# nulla da guadagnare: misurati a 45 Hz costanti, `low` 637 W e `medium` 645 W,
# otto watt. Non vale un comando ogni dieci minuti.
MIN_FAN_DWELL_SECONDS = 1800

# --- MODE_SMART: `dry` program, only with a humidity sensor configured ---
# Muggy but already at temperature: dehumidifying is what actually helps, and it
# draws less than compressor cooling. Two thresholds, again to avoid flapping.
DRY_HUMIDITY_ON = 60.0
DRY_HUMIDITY_OFF = 55.0
# Above this gap the room needs cooling, not dehumidifying. The second value is
# the extra slack before leaving dry, so the program does not swap back and
# forth while the reported temperature sits on the threshold.
DRY_MAX_DELTA = 1.0
DRY_DELTA_HYSTERESIS = 0.5

# --- Day phases (only meaningful in MODE_AUTO / MODE_SMART) ---
PHASE_DAY = "day"
PHASE_NIGHT = "night"
PHASE_GAP = "gap"
# Inside the night, the stretch where the colder sleep target applies.
PHASE_SLEEP = "sleep"
# Between the end of the sleep window and the morning switch-off: keep holding the
# night target, but at the lowest fan step.
PHASE_WIND_DOWN = "wind_down"

# --- MODE_SMART, sleep window: only two steps, and never `high` ---
# `medium` all the way down to the target, `low` only once the room is clearly
# below it. Measured over a night: dropping to `low` at the target made this unit
# throttle the compressor from 41 Hz to 30, the return-air reading climbed two
# degrees in half an hour, and it took three and a half hours at 40 Hz to come
# back. Slowing the fan here does not save anything, it just takes the room away.
FAN_BANDS_SLEEP: tuple[tuple[float, str], ...] = ((-0.5, "medium"), (-100.0, "low"))
# ...con una sola eccezione, all'ingresso nella finestra: li' il target scende di
# parecchi gradi in un colpo solo, e la ventola al massimo per i primi minuti
# abbatte in fretta invece di far lavorare a lungo il compressore in salita.
# Passata la spinta si torna alle bande qui sopra, e non serve alcuna attesa
# perche' `high` non e' un passo di questa tabella: `_fan_for` lo scarta come
# riferimento e riparte subito da media o bassa secondo lo scarto.
SLEEP_BOOST_MINUTES = 15
# Sotto questo scarto la stanza e' gia' a posto e la spinta non ha nulla da fare.
SLEEP_BOOST_MIN_DELTA = 0.3
# The morning switch-off is a one-shot, not a state to enforce: outside this many
# minutes past its time it is not attempted at all, so a restart later in the
# morning cannot switch off a unit the user has just turned back on.
MORNING_OFF_WINDOW_MINUTES = 30
# Same idea for the evening start: one attempt inside this window after
# sleep_start, so a climate switched off at 01:00 stays off.
SLEEP_START_WINDOW_MINUTES = 30

# Fired when the controller starts the unit by itself, so an automation can
# announce it. Data: entity_id, target, phase, and `motivo`, which tells the two
# apart: "giorno" is the room getting hot, "notte" is the schedule beginning.
EVENT_STARTED = "clima_smart_avviato"
# Lanciato quando il controller avrebbe avviato ma `start_approval` glielo
# impedisce: chi ascolta chiede a una persona e, se acconsente, accende.
# Dati: entity_id, motivo, fase, casa, camera, esterna, target.
EVENT_APPROVAL_NEEDED = "clima_smart_avvio_richiesto"
START_REASON_DAY = "giorno"
START_REASON_NIGHT = "notte"

# Fired when the morning switch-off for a cool day goes through, so an
# automation can suggest opening the windows instead. Data: entity_id.
EVENT_COOL_OFF = "clima_smart_spento_per_fresco"

# Measured twice on this unit: an aux switch we just turned on comes back to its
# previous value about 60-70 s later, with no user context, when the unit does not
# accept it (mute, then eco, both while a fan step was forced). After such a
# refusal the switch is left alone for this long instead of being re-commanded at
# every pass.
AUX_REFUSAL_BACKOFF_SECONDS = 1800

# HVAC constants we rely on (kept as literals to avoid importing climate internals).
HVAC_COOL = "cool"
HVAC_HEAT = "heat"
HVAC_OFF = "off"
HVAC_DRY = "dry"

# hass.data storage key
DATA_CONTROLLER = "controller"
