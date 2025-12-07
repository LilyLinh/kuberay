#!/usr/bin/env python3
"""CPA metric script - queries Prometheus for ray_tasks history."""

import os
import sys
import json
import requests
from datetime import datetime, timedelta

PROM_URL = os.getenv("PROMETHEUS_URL", "http://prometheus-server.monitoring:9090")
METRIC = os.getenv("METRIC_NAME", "ray_tasks")
STATE = os.getenv("METRIC_STATE", "PENDING_ARGS_AVAIL")
SEQ_LEN = int(os.getenv("SEQUENCE_LENGTH", "60"))
STEP = int(os.getenv("STEP_SECONDS", "1"))


def query_range(query, start, end, step):
    try:
        r = requests.get(f"{PROM_URL}/api/v1/query_range",
            params={"query": query, "start": start.isoformat()+"Z", "end": end.isoformat()+"Z", "step": step},
            timeout=10)
        data = r.json()
        if data["status"] != "success":
            return []
        results = data.get("data", {}).get("result", [])
        return [(float(ts), float(v)) for ts, v in results[0].get("values", [])] if results else []
    except:
        return []


def get_history():
    end = datetime.utcnow()
    start = end - timedelta(seconds=SEQ_LEN)
    vals = query_range(f'{METRIC}{{State="{STATE}"}}', start, end, f"{STEP}s")
    
    counts = [v[1] for v in vals]
    if len(counts) < SEQ_LEN:
        counts = [0.0] * (SEQ_LEN - len(counts)) + counts
    return counts[-SEQ_LEN:]


def get_current():
    try:
        r = requests.get(f"{PROM_URL}/api/v1/query",
            params={"query": f'{METRIC}{{State="{STATE}"}}'}, timeout=10)
        data = r.json()
        if data["status"] == "success" and data.get("data", {}).get("result"):
            return float(data["data"]["result"][0]["value"][1])
    except:
        pass
    return 0.0


def main():
    out = {
        "history": get_history(),
        "current_demand": get_current(),
        "timestamp": datetime.utcnow().isoformat(),
        "sequence_length": SEQ_LEN
    }
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
