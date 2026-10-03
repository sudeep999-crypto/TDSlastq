import json
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

app = FastAPI()

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}


@app.middleware("http")
async def add_cors(request: Request, call_next):
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=CORS_HEADERS)
    try:
        response = await call_next(request)
    except Exception as e:
        response = JSONResponse({"error": str(e)}, status_code=500)
    for k, v in CORS_HEADERS.items():
        response.headers[k] = v
    return response


# ---- load the data once ----
raw = json.loads((Path(__file__).parent / "q-vercel-latency.json").read_text(encoding="utf-8"))
if isinstance(raw, dict):
    raw = next(v for v in raw.values() if isinstance(v, list))

REGION_KEYS = ["region", "Region"]
LATENCY_KEYS = ["latency_ms", "latency", "latencyMs"]
UPTIME_KEYS = ["uptime_pct", "uptime", "uptime_percent"]


def pick(rec, keys):
    for k in keys:
        if k in rec:
            return rec[k]
    raise KeyError(f"none of {keys} found in {list(rec)}")


records = [
    {
        "region": pick(r, REGION_KEYS),
        "latency": float(pick(r, LATENCY_KEYS)),
        "uptime": float(pick(r, UPTIME_KEYS)),
    }
    for r in raw
]


def percentile(values: List[float], p: float) -> float:
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


class Query(BaseModel):
    regions: List[str]
    threshold_ms: Optional[float] = 180


@app.get("/")
@app.get("/api")
@app.get("/api/latency")
def health():
    return {"status": "ok", "usage": "POST {\"regions\": [...], \"threshold_ms\": 180}"}


@app.post("/")
@app.post("/api")
@app.post("/api/latency")
def metrics(q: Query):
    out = {}
    for region in q.regions:
        rows = [r for r in records if r["region"] == region]
        if not rows:
            out[region] = {"avg_latency": 0, "p95_latency": 0, "avg_uptime": 0, "breaches": 0}
            continue
        lat = [r["latency"] for r in rows]
        up = [r["uptime"] for r in rows]
        out[region] = {
            "avg_latency": sum(lat) / len(lat),
            "p95_latency": percentile(lat, 95),
            "avg_uptime": sum(up) / len(up),
            "breaches": sum(1 for x in lat if x > q.threshold_ms),
        }
    return {**out, "regions": out}