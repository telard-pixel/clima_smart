"""Scarica le serie orarie che servono allo studio termico e le salva in JSON.

Niente numpy in questo contenitore, quindi tutto in Python puro: qui si fa solo
l'estrazione, il modello sta in `studio.py`. Separati perche' l'estrazione e'
lenta (una chiamata WebSocket per serie) e il modello lo si rigira molte volte.
"""
import datetime
import json
import subprocess

GIORNI = 76   # limite vero: la potenza del clima parte dal 6 giugno
SERIE = {
    "salotto": "sensor.salotto_temperatura",
    "cucina": "sensor.cucina_temperatura",
    "studio": "sensor.temperatura_studio",
    "esterna": "sensor.casa_temperatura_esterna",
    "sole": "sensor.casa_percentuale_solare",              # Tado, 174 giorni
    "sole_wm2": "sensor.meteo_montichiari_radiazione_solare",  # piranometro, per il riscontro
    "potenza": "sensor.potenza_istantanea_clima_camera_2",
    "camera": "sensor.bthome_sensor_89af_temperatura",
}


def orarie(entity):
    fine = datetime.datetime.now().astimezone().replace(microsecond=0)
    inizio = fine - datetime.timedelta(days=GIORNI)
    payload = {
        "start_time": inizio.isoformat(),
        "end_time": fine.isoformat(),
        "statistic_ids": [entity],
        "period": "hour",
        "types": ["mean"],
    }
    out = subprocess.run(
        ["hass", "ws", "recorder/statistics_during_period", json.dumps(payload)],
        capture_output=True, text=True,
    ).stdout
    righe = json.loads(out).get(entity, [])
    return {int(r["start"] // 1000): r["mean"] for r in righe if r.get("mean") is not None}


dati = {}
for nome, ent in SERIE.items():
    d = orarie(ent)
    dati[nome] = d
    print(f"{nome:9s} {len(d):5d} ore")

fuori = "/tmp/claude-0/-root-code/7ea276ac-6d53-4105-9b70-2e2c4802a8f4/scratchpad/serie.json"
json.dump(dati, open(fuori, "w"))
print("scritto", fuori)
