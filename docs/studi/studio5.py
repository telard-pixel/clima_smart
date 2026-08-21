"""Il modello va meglio o peggio quando fa fresco?

L'obiezione: se con 76 giorni il predittivo perde contro le nostre regole, perche'
dovrebbe andar meglio con le giornate fredde? Si puo' rispondere senza aspettare
l'autunno, dividendo i giorni gia' disponibili per quanto sono stati caldi e
guardando come cambia il confronto col banale.

Se il vantaggio del modello CALA sui giorni piu' freschi, allora aspettare
l'autunno non serve a niente: sappiamo gia' che andra' peggio.
"""
import datetime
import json
import statistics

BASE = "/tmp/claude-0/-root-code/7ea276ac-6d53-4105-9b70-2e2c4802a8f4/scratchpad"
d = json.load(open(f"{BASE}/serie.json"))
serie = {k: {int(t): v for t, v in s.items()} for k, s in d.items()}
A, B, D, C = 0.01352, 0.00075, 0.06466, -0.2390   # dai due regimi di studio2

ore = sorted(set(serie["salotto"]) & set(serie["cucina"]) & set(serie["esterna"])
             & set(serie["sole"]) & set(serie["potenza"]))
casa = {t: (serie["salotto"][t] + serie["cucina"][t]) / 2 for t in ore}

giorni = {}
for t in ore:
    g = datetime.datetime.fromtimestamp(t).astimezone().date()
    giorni.setdefault(g, []).append(t)

righe = []
for g, tt in sorted(giorni.items()):
    if len(tt) < 20:
        continue
    righe.append((g, max(serie["esterna"][t] for t in tt), tt))

# tutti i giorni, ordinati per quanto sono stati caldi
righe.sort(key=lambda r: r[1])
meta = len(righe) // 2
freschi, caldi = righe[:meta], righe[meta:]


def confronto(gruppo, h=3):
    em, eb, mosso = [], [], []
    for g, estmax, tt in gruppo:
        idx = set(tt)
        for t0 in tt:
            prev = casa[t0]
            ok = True
            for k in range(h):
                t = t0 + k * 3600
                if t not in idx:
                    ok = False
                    break
                prev += (A * (serie["esterna"][t] - prev) + B * serie["sole"][t]
                         + D + C * serie["potenza"][t] / 1000.0)
            vero = casa.get(t0 + h * 3600)
            if ok and vero is not None:
                em.append(abs(prev - vero))
                eb.append(abs(casa[t0] - vero))
                mosso.append(abs(vero - casa[t0]))
    if not em:
        return None
    m, b = statistics.fmean(em), statistics.fmean(eb)
    return m, b, 100 * (1 - m / b), statistics.fmean(mosso), len(em)


print("Il confronto modello-vs-banale, a 3 ore, diviso per quanto e' stata calda "
      "la giornata\n")
print(f"{'gruppo':<22} {'est.max':>8} {'modello':>8} {'banale':>7} "
      f"{'guadagno':>9} {'quanto si muove':>16}")
for nome, gruppo in (("meta' piu' fresca", freschi), ("meta' piu' calda", caldi)):
    r = confronto(gruppo)
    if r:
        em = statistics.fmean(x[1] for x in gruppo)
        print(f"{nome:<22} {em:8.1f} {r[0]:8.2f} {r[1]:7.2f} {r[2]:+8.0f}% "
              f"{r[3]:15.2f}°")

print("\nsuddiviso piu' finemente, per fascia di esterna massima:")
print(f"{'fascia':<14} {'giorni':>7} {'modello':>8} {'banale':>7} {'guadagno':>9}")
for lo, hi in ((0, 30), (30, 34), (34, 37), (37, 99)):
    gruppo = [r for r in righe if lo <= r[1] < hi]
    if len(gruppo) < 3:
        continue
    r = confronto(gruppo)
    if r:
        print(f"{lo}-{hi if hi < 99 else '+':<11} {len(gruppo):7d} "
              f"{r[0]:8.2f} {r[1]:7.2f} {r[2]:+8.0f}%")
