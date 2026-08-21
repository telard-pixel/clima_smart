"""Raffreddare di notte conviene? La casa ha inerzia: forse si', ma va misurato.

L'inerzia alta (costante di tempo 74 ore) rende la casa un magazzino di freddo.
E di notte il compressore lavora contro 20 gradi invece che contro 38. Domanda:
**quanto freddo si compra per kWh, di notte contro di giorno?**

Si isola l'effetto della macchina sottraendo dalla variazione oraria quello che
la casa avrebbe fatto da sola (dispersione + sole + resto), con i coefficienti
passivi tarati in studio2 sulle sole ore a clima spento. Quel che resta e' il
lavoro della macchina, e lo si divide per i kWh spesi in quell'ora.
"""
import datetime
import json
import statistics

BASE = "/tmp/claude-0/-root-code/7ea276ac-6d53-4105-9b70-2e2c4802a8f4/scratchpad"
d = json.load(open(f"{BASE}/serie.json"))
serie = {k: {int(t): v for t, v in s.items()} for k, s in d.items()}

# coefficienti della casa passiva, da studio2 (ore a clima spento)
A, B, D = 0.01352, 0.00075, 0.06466

ore = sorted(set(serie["salotto"]) & set(serie["cucina"]) & set(serie["esterna"])
             & set(serie["sole"]) & set(serie["potenza"]))
casa = {t: (serie["salotto"][t] + serie["cucina"][t]) / 2 for t in ore}

notte, giorno = [], []
for t in ore:
    if t + 3600 not in casa:
        continue
    pot = serie["potenza"][t]
    if pot < 250:                      # solo ore in cui la macchina lavora davvero
        continue
    kwh = pot / 1000.0
    passiva = A * (serie["esterna"][t] - casa[t]) + B * serie["sole"][t] + D
    effetto = (casa[t + 3600] - casa[t]) - passiva     # gradi/ora dovuti al clima
    resa = -effetto / kwh                              # gradi di casa per kWh
    h = datetime.datetime.fromtimestamp(t).astimezone().hour
    riga = (resa, serie["esterna"][t], pot)
    if h >= 23 or h < 7:
        notte.append(riga)
    elif 11 <= h < 20:
        giorno.append(riga)


def riassunto(nome, v):
    if not v:
        print(f"{nome}: nessun dato")
        return None
    rese = sorted(x[0] for x in v)
    med = statistics.median(rese)
    print(f"{nome:8s} {len(v):4d} ore | resa mediana {med:+6.3f} °C per kWh | "
          f"esterna media {statistics.fmean(x[1] for x in v):5.1f} | "
          f"potenza media {statistics.fmean(x[2] for x in v):5.0f} W")
    return med


print("QUANTO FREDDO SI COMPRA PER kWh (solo ore con la macchina sopra 250 W)\n")
mn = riassunto("notte", notte)
mg = riassunto("giorno", giorno)
if mn and mg and mg != 0:
    print(f"\n  la notte rende {mn/mg:.2f} volte il giorno "
          f"({100*(mn/mg-1):+.0f}%)")

# controprova indipendente: quanti watt servono per NON far salire la casa
print("\nCONTROPROVA - potenza per tenere la casa ferma (variazione entro ±0.05 °C/ora)")
for nome, lo, hi in (("notte", 23, 7), ("giorno", 11, 20)):
    p = []
    for t in ore:
        if t + 3600 not in casa:
            continue
        h = datetime.datetime.fromtimestamp(t).astimezone().hour
        dentro = (h >= lo or h < hi) if lo > hi else (lo <= h < hi)
        if not dentro or serie["potenza"][t] < 100:
            continue
        if abs(casa[t + 3600] - casa[t]) <= 0.05:
            p.append(serie["potenza"][t])
    if p:
        print(f"  {nome:7s} {statistics.median(p):5.0f} W mediani  ({len(p)} ore)")
