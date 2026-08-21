"""Terzo tentativo, alla scala giusta: la GIORNATA, non l'ora.

I primi due studi chiedevano al modello di prevedere la casa ora per ora, e
perdevano contro il non-prevedere: questa casa ha un'escursione mediana di 1.13
gradi al giorno e una costante di tempo di 74 ore. Non si muove abbastanza da
rendere utile una previsione oraria.

Ma la domanda dell'utente non era oraria. Era: **oggi serve accendere?** - con
il vincolo esplicito di non partire in giornate fresche come il 21 agosto. Quella
e' UNA decisione al giorno, presa al mattino, su una grandezza molto piu' docile:
il picco della casa nella giornata.

Ingressi disponibili la mattina alle 9: la casa adesso, l'esterna adesso, e cosa
promette la giornata (massimo esterna e sole medio - qui presi dai valori veri,
che e' la versione ottimistica: con le previsioni sarebbe un po' peggio. Se non
funziona nemmeno cosi', con le previsioni non funzionera' di sicuro).
"""
import datetime
import json
import statistics

BASE = "/tmp/claude-0/-root-code/7ea276ac-6d53-4105-9b70-2e2c4802a8f4/scratchpad"
d = json.load(open(f"{BASE}/serie.json"))
serie = {k: {int(t): v for t, v in s.items()} for k, s in d.items()}
LINEA = 26.3


def risolvi(A, b):
    n = len(A)
    M = [list(r) + [b[i]] for i, r in enumerate(A)]
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(M[r][i]))
        M[i], M[p] = M[p], M[i]
        if abs(M[i][i]) < 1e-12:
            return None
        for r in range(i + 1, n):
            f = M[r][i] / M[i][i]
            for c in range(i, n + 1):
                M[r][c] -= f * M[i][c]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (M[i][n] - sum(M[i][c] * x[c] for c in range(i + 1, n))) / M[i][i]
    return x


def minimi_quadrati(righe):
    k = len(righe[0][0])
    A = [[0.0] * k for _ in range(k)]
    b = [0.0] * k
    for x, y in righe:
        for i in range(k):
            b[i] += x[i] * y
            for j in range(k):
                A[i][j] += x[i] * x[j]
    return risolvi(A, b)


ore = sorted(set(serie["salotto"]) & set(serie["cucina"]) & set(serie["esterna"])
             & set(serie["sole"]))
casa = {t: (serie["salotto"][t] + serie["cucina"][t]) / 2 for t in ore}

giorni = {}
for t in ore:
    dt = datetime.datetime.fromtimestamp(t).astimezone()
    giorni.setdefault(dt.date(), []).append((dt.hour, t))

righe = []
for g, vv in sorted(giorni.items()):
    per_ora = dict(vv)
    if 9 not in per_ora or len(vv) < 20:
        continue
    t9 = per_ora[9]
    ore_giorno = [t for h, t in vv if 10 <= h <= 22]
    if not ore_giorno:
        continue
    righe.append({
        "g": g,
        "casa9": casa[t9],
        "est9": serie["esterna"][t9],
        "est_max": max(serie["esterna"][t] for h, t in vv),
        "sole_med": statistics.fmean(serie["sole"][t] for h, t in vv),
        "picco": max(casa[t] for t in ore_giorno),
    })

print(f"giornate complete: {len(righe)}")
tag = int(len(righe) * 0.75)
tr, te = righe[:tag], righe[tag:]
print(f"  {len(tr)} per imparare, {len(te)} mai viste (dal {te[0]['g']})")


def ing(r):
    return [r["casa9"], r["est_max"], r["sole_med"], 1.0]


coef = minimi_quadrati([(ing(r), r["picco"]) for r in tr])
print("\npicco di casa = "
      f"{coef[0]:+.3f}*casa9h {coef[1]:+.3f}*esterna_max {coef[2]:+.4f}*sole {coef[3]:+.2f}")


def stima(r):
    return sum(a * b for a, b in zip(coef, ing(r)))


em = [abs(stima(r) - r["picco"]) for r in te]
eb = [abs(r["casa9"] - r["picco"]) for r in te]
print(f"\nerrore sul picco, giornate mai viste:")
print(f"  modello  {statistics.fmean(em):.2f}°   banale (picco = casa alle 9)  "
      f"{statistics.fmean(eb):.2f}°   guadagno {100*(1-statistics.fmean(em)/statistics.fmean(eb)):+.0f}%")

print(f"\nLA DECISIONE: alle 9 del mattino, oggi la casa superera' {LINEA}?")
gg = ff = mm = tt = 0
for r in te:
    prev, vero = stima(r) >= LINEA, r["picco"] >= LINEA
    if prev and vero: gg += 1
    elif prev and not vero: ff += 1
    elif vero and not prev: mm += 1
    else: tt += 1
print(f"  giuste (serviva, previsto)        {gg}")
print(f"  FALSI ALLARMI (non serviva)       {ff}")
print(f"  MANCATE (serviva, non previsto)   {mm}")
print(f"  giuste (non serviva, non previsto){tt}")
print(f"  -> corrette {gg+tt} su {len(te)} giornate")

print("\ndettaglio delle giornate mai viste:")
for r in te:
    s = stima(r)
    esito = "ok " if (s >= LINEA) == (r["picco"] >= LINEA) else "NO "
    print(f"  {esito}{r['g']}  casa9h {r['casa9']:5.1f}  est_max {r['est_max']:5.1f}"
          f"  sole {r['sole_med']:5.1f}  ->  stimato {s:5.1f}  reale {r['picco']:5.1f}")
