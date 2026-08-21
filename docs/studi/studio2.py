"""Secondo tentativo, con l'errore del primo corretto.

Nel primo studio sole e clima erano confusi: quando c'e' sole il clima e' acceso,
e i minimi quadrati hanno dato al sole il merito del raffreddamento (coefficiente
negativo, fisicamente falso). La cura non e' un modello piu' grosso, e' un
disegno sperimentale migliore: **si tarano i due regimi separatamente.**

  1. CASA PASSIVA (clima spento): qui il termine del clima non esiste, e sole e
     dispersione diventano identificabili. E' la casa vera, senza attuatore.
  2. CLIMA ACCESO: tenendo fermi i coefficienti passivi, si ricava quanto
     raffredda la macchina per kW.

E si misura la cosa che serve al controller, che NON e' la temperatura fra tre
ore: e' **quando la casa supera la linea di comfort**. Sbagliare di mezzo grado
non conta niente; sbagliare di tre ore su quando sforare conta tutto.
"""
import datetime
import json
import statistics

BASE = "/tmp/claude-0/-root-code/7ea276ac-6d53-4105-9b70-2e2c4802a8f4/scratchpad"
d = json.load(open(f"{BASE}/serie.json"))
serie = {k: {int(t): v for t, v in s.items()} for k, s in d.items()}
LINEA = 26.3   # la linea di comfort configurata oggi


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
             & set(serie["sole"]) & set(serie["potenza"]))
casa = {t: (serie["salotto"][t] + serie["cucina"][t]) / 2 for t in ore}
camp = []
for t in ore:
    if t + 3600 not in casa:
        continue
    camp.append({"t": t, "casa": casa[t], "casa1": casa[t + 3600],
                 "est": serie["esterna"][t], "sole": serie["sole"][t],
                 "pot": serie["potenza"][t]})

# --- quanto c'e' da prevedere? -------------------------------------------
per_giorno = {}
for c in camp:
    g = datetime.datetime.fromtimestamp(c["t"]).astimezone().date()
    per_giorno.setdefault(g, []).append(c)
escursioni = [max(x["casa"] for x in v) - min(x["casa"] for x in v)
              for v in per_giorno.values() if len(v) >= 20]
print(f"escursione giornaliera della casa: mediana {statistics.median(escursioni):.2f}°, "
      f"massima {max(escursioni):.2f}° (su {len(escursioni)} giorni pieni)")

giorni = sorted(per_giorno)
taglio = int(len(giorni) * 0.75)
g_train, g_test = giorni[:taglio], giorni[taglio:]

passivi = [c for g in g_train for c in per_giorno[g] if c["pot"] < 50]
attivi = [c for g in g_train for c in per_giorno[g] if c["pot"] > 200]
print(f"\nore a clima SPENTO {len(passivi)}  |  a clima ACCESO {len(attivi)}")

# 1. la casa passiva
cp = minimi_quadrati([([c["est"] - c["casa"], c["sole"], 1.0],
                       c["casa1"] - c["casa"]) for c in passivi])
a, b_, d_ = cp
print("\nCASA PASSIVA (clima spento), i coefficienti fisici veri:")
print(f"  dispersione   a = {a:+.5f}/ora  ->  costante di tempo {1/a:.0f} ore")
print(f"  sole          b = {b_:+.5f} °C/ora per punto  "
      f"{'(POSITIVO: il sole scalda, ha senso)' if b_ > 0 else '(NEGATIVO: ancora sbagliato)'}")
print(f"  resto         d = {d_:+.5f} °C/ora")

# 2. il clima, tenendo fermo il resto
ca = minimi_quadrati([([c["pot"] / 1000.0],
                       c["casa1"] - c["casa"]
                       - (a * (c["est"] - c["casa"]) + b_ * c["sole"] + d_))
                      for c in attivi])
c_ = ca[0]
print(f"\nCLIMA ACCESO:  {c_:+.4f} °C/ora per kW sulla media di casa")


def prevedi(c0, ore_avanti, indice):
    prev = c0["casa"]
    for k in range(ore_avanti):
        c = indice.get(c0["t"] + k * 3600)
        if c is None:
            return None
        prev += a * (c["est"] - prev) + b_ * c["sole"] + d_ + c_ * c["pot"] / 1000.0
    return prev


print("\nerrore sui giorni MAI VISTI, contro la previsione banale:")
print(f"{'ore':>4} {'modello':>8} {'banale':>8} {'guadagno':>9}")
for h in (1, 3, 6, 12):
    em, eb = [], []
    for g in g_test:
        indice = {c["t"]: c for c in per_giorno[g]}
        for c0 in per_giorno[g]:
            vero = casa.get(c0["t"] + h * 3600)
            p = prevedi(c0, h, indice)
            if vero is not None and p is not None:
                em.append(abs(p - vero))
                eb.append(abs(c0["casa"] - vero))
    if em:
        print(f"{h:>3}h {statistics.fmean(em):8.2f} {statistics.fmean(eb):8.2f} "
              f"{100*(1-statistics.fmean(em)/statistics.fmean(eb)):+8.0f}%")

# --- la domanda che conta davvero ----------------------------------------
print(f"\nLA DOMANDA VERA: prevedere QUANDO la casa supera {LINEA}")
giusti = sbagliati = mancati = falsi = 0
for g in g_test:
    indice = {c["t"]: c for c in per_giorno[g]}
    for c0 in per_giorno[g]:
        if c0["casa"] >= LINEA:
            continue          # gia' sopra: non c'e' niente da prevedere
        p = prevedi(c0, 3, indice)
        vero = casa.get(c0["t"] + 3 * 3600)
        if p is None or vero is None:
            continue
        prevista = p >= LINEA
        avvenuta = vero >= LINEA
        if prevista and avvenuta:
            giusti += 1
        elif prevista and not avvenuta:
            falsi += 1
        elif avvenuta and not prevista:
            mancati += 1
        else:
            sbagliati += 1
tot = giusti + falsi + mancati
print(f"  sforamenti a 3 ore, sui giorni mai visti:")
print(f"    previsti e avvenuti   {giusti}")
print(f"    previsti e NON avvenuti (falsi allarmi: accenderebbe per niente)  {falsi}")
print(f"    avvenuti e non previsti (mancati: la casa sfora)  {mancati}")
print(f"    correttamente tranquilli  {sbagliati}")
