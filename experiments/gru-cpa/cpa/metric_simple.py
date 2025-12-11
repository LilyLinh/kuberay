#!/usr/bin/env python3
"""CPA metric script - reads Ray task metrics directly from head pod."""

import os
import sys
import json
import requests
from datetime import datetime
from collections import deque

SEQ_LEN = int(os.getenv("SEQUENCE_LENGTH", "30"))
RAY_DASHBOARD = os.getenv("RAY_DASHBOARD_URL", "http://test-cluster-head-svc:8265")

# In-memory history (in real deployment, use persistent storage)
HISTORY_FILE = "/tmp/task_history.json"
history = deque(maxlen=SEQ_LEN)

# Load history
try:
    with open(HISTORY_FILE) as f:
        history = deque(json.load(f), maxlen=SEQ_LEN)
except:
    pass


def get_ray_tasks():
    """Get current pending task count from Ray dashboard API."""
    try:
        r = requests.get(f"{RAY_DASHBOARD}/api/cluster_status", timeout=5)
        if r.status_code == 200:
            data = r.json()
            # Extract pending tasks from cluster state
            pending = data.get("data", {}).get("clusterStatus", {}).get("autoscalerSummary", {}).get("pendingTasksTotal", 0)
            return float(pending)
    except:
        pass

    # Fallback: try direct metrics endpoint
    try:
        r = requests.get(f"{RAY_DASHBOARD}/metrics", timeout=5)
        if r.status_code == 200:
            for line in r.text.split('\n'):
                if 'ray_scheduler_tasks{State="PENDING_ARGS_AVAIL"}' in line:
                    return float(line.split()[-1])
    except:
        pass

    return 0.0


def main():
    current = get_ray_tasks()

    # Update history
    history.append(current)

    # Save history
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(list(history), f)
    except:
        pass

    out = {
        "history": list(history),
        "current_demand": current,
        "timestamp": datetime.utcnow().isoformat(),
        "sequence_length": len(history)
    }
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
