"""La casa e' prevedibile? Studio termico sui dati veri, prima di scrivere codice.

Modello: un bilancio termico del primo ordine, l'unica forma che si possa tarare
onestamente su qualche settimana di dati e spiegare a voce.

    T[t+1] - T[t] = a*(Test[t] - T[t]) + b*Sole[t] + c*Potenza[t] + d

  a  quanto la casa insegue l'esterna (dispersione dei muri, 1/costante di tempo)
  b  quanto la scalda il sole
  c  quanto la raffredda il clima per watt speso
  d  il resto costante (persone, elettrodomestici, deriva dei sensori)

Tutto in Python puro - niente numpy - risolvendo le equazioni normali con
l'eliminazione di Gauss. Sono quattro incognite: si fa a mano senza vergogna.

Il giudizio NON e' l'errore a un'ora, che e' facile: e' l'errore a **tre ore**,
srotolando il modello su se stesso, su giorni che il modello non ha mai visto.
Quella e' la domanda che decide se un avvio anticipato ha senso.
"""
import datetime
import json
import statistics

BASE = "/tmp/claude-0/-root-code/7ea276ac-6d53-4105-9b70-2e2c4802a8f4/scratchpad"
d = json.load(open(f"{BASE}/serie.json"))
serie = {k: {int(t): v for t, v in s.items()} for k, s in d.items()}


def riscontro_sole():
    """Il sole di Tado dice le stesse cose del piranometro? Se no, non si usa."""
    comuni = sorted(set(serie["sole"]) & set(serie["sole_wm2"]))
    if len(comuni) < 100:
        return None
    x = [serie["sole"][t] for t in comuni]
    y = [serie["sole_wm2"][t] for t in comuni]
    mx, my = statistics.fmean(x), statistics.fmean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = (sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)) ** 0.5
    return len(comuni), (num / den if den else 0.0)


def campioni():
    """Ore in cui esiste tutto il necessario, con l'ora successiva disponibile."""
    ore = sorted(set(serie["salotto"]) & set(serie["cucina"]) & set(serie["esterna"])
                 & set(serie["sole"]) & set(serie["potenza"]))
    casa = {t: (serie["salotto"][t] + serie["cucina"][t]) / 2 for t in ore}
    out = []
    for t in ore:
        t1 = t + 3600
        if t1 not in casa:
            continue
        out.append({
            "t": t,
            "casa": casa[t], "casa1": casa[t1],
            "est": serie["esterna"][t],
            "sole": serie["sole"][t],
            "pot": serie["potenza"][t],
        })
    return out, casa


def risolvi(A, b):
    """Eliminazione di Gauss con pivot parziale."""
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
    """Regressione lineare: righe = lista di (vettore_ingressi, uscita)."""
    k = len(righe[0][0])
    A = [[0.0] * k for _ in range(k)]
    b = [0.0] * k
    for x, y in righe:
        for i in range(k):
            b[i] += x[i] * y
            for j in range(k):
                A[i][j] += x[i] * x[j]
    return risolvi(A, b)


def ingressi(c):
    return [c["est"] - c["casa"], c["sole"], c["pot"] / 1000.0, 1.0]


dati, casa_per_ora = campioni()
print(f"campioni orari utilizzabili: {len(dati)}")
r = riscontro_sole()
if r:
    print(f"riscontro sole Tado vs piranometro: {r[0]} ore in comune, "
          f"correlazione {r[1]:+.3f}")

# --- addestramento e verifica su giorni SEPARATI --------------------------
per_giorno = {}
for c in dati:
    g = datetime.datetime.fromtimestamp(c["t"]).astimezone().date()
    per_giorno.setdefault(g, []).append(c)
giorni = sorted(per_giorno)
taglio = int(len(giorni) * 0.75)
g_train, g_test = giorni[:taglio], giorni[taglio:]
print(f"giorni: {len(giorni)} totali -> {len(g_train)} per imparare, "
      f"{len(g_test)} mai visti (dal {g_test[0]})")

train = [c for g in g_train for c in per_giorno[g]]
coef = minimi_quadrati([(ingressi(c), c["casa1"] - c["casa"]) for c in train])
a, b_, c_, d_ = coef
print("\ncoefficienti imparati:")
print(f"  a  inseguimento esterna   {a:+.5f} /ora   (costante di tempo {1/a:6.1f} ore)")
print(f"  b  spinta del sole        {b_:+.5f} °C/ora per punto di sole")
print(f"  c  effetto del clima      {c_:+.5f} °C/ora per kW")
print(f"  d  resto costante         {d_:+.5f} °C/ora")


def errore_a_orizzonte(insieme, ore_avanti):
    """Srotola il modello su se stesso per N ore e misura l'errore finale."""
    errori = []
    for g in insieme:
        cc = per_giorno[g]
        indice = {c["t"]: c for c in cc}
        for c0 in cc:
            prev = c0["casa"]
            ok = True
            for k in range(ore_avanti):
                c = indice.get(c0["t"] + k * 3600)
                if c is None:
                    ok = False
                    break
                prev += (a * (c["est"] - prev) + b_ * c["sole"]
                         + c_ * c["pot"] / 1000.0 + d_)
            vero = casa_per_ora.get(c0["t"] + ore_avanti * 3600)
            if ok and vero is not None:
                errori.append(abs(prev - vero))
    if not errori:
        return None
    errori.sort()
    return (statistics.fmean(errori), errori[len(errori) // 2],
            errori[int(len(errori) * 0.9)], len(errori))


print("\nerrore di previsione sui giorni MAI VISTI (gradi):")
print(f"{'orizzonte':>10} {'medio':>7} {'mediano':>8} {'90° perc':>9} {'casi':>6}")
for h in (1, 2, 3, 4, 6):
    e = errore_a_orizzonte(g_test, h)
    if e:
        print(f"{h:>8} h {e[0]:7.2f} {e[1]:8.2f} {e[2]:9.2f} {e[3]:6d}")

# --- il confronto che conta: fare meglio del "domani come oggi"? ----------
print("\nconfronto con la previsione banale (la casa resta com'e'):")
for h in (1, 3, 6):
    banali = []
    for g in g_test:
        for c0 in per_giorno[g]:
            vero = casa_per_ora.get(c0["t"] + h * 3600)
            if vero is not None:
                banali.append(abs(c0["casa"] - vero))
    e = errore_a_orizzonte(g_test, h)
    if banali and e:
        print(f"  {h} h: modello {e[0]:.2f}°  |  banale {statistics.fmean(banali):.2f}°  "
              f"|  guadagno {100*(1-e[0]/statistics.fmean(banali)):+.0f}%")
