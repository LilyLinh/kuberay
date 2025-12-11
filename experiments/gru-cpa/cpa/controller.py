#!/usr/bin/env python3
"""GRU-CPA Controller - Autoscales RayCluster based on GRU predictions."""

import os
import sys
import json
import time
import subprocess
from datetime import datetime

NAMESPACE = os.getenv("NAMESPACE", "gru-cpa-experiment")
RAYCLUSTER_NAME = os.getenv("RAYCLUSTER_NAME", "test-cluster")
INTERVAL = int(os.getenv("SCALE_INTERVAL", "10"))  # Check every 10 seconds
LOG_FILE = os.getenv("LOG_FILE", "/tmp/gru-cpa.log")


def log(msg):
    """Log with timestamp."""
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
    except:
        pass


def run_cmd(cmd):
    """Run shell command and return output."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)


def get_metrics():
    """Get current metrics from Ray cluster."""
    rc, out, err = run_cmd("python3 /app/metric_simple.py")
    if rc == 0:
        try:
            return json.loads(out)
        except:
            pass
    log(f"ERROR: Failed to get metrics: {err}")
    return {"history": [], "current_demand": 0.0}


def get_target_replicas(metrics):
    """Call evaluate.py to get target replicas."""
    try:
        proc = subprocess.Popen(
            ["python3", "/app/evaluate.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        out, err = proc.communicate(input=json.dumps(metrics), timeout=30)

        if err:
            log(f"GRU: {err.strip()}")

        if proc.returncode == 0:
            result = json.loads(out)
            return result.get("targetReplicas", 1)
    except Exception as e:
        log(f"ERROR: Evaluate failed: {e}")
    return 1


def get_current_replicas():
    """Get current worker replicas from RayCluster."""
    cmd = f"kubectl get raycluster {RAYCLUSTER_NAME} -n {NAMESPACE} -o json"
    rc, out, err = run_cmd(cmd)
    if rc == 0:
        try:
            data = json.loads(out)
            workers = data.get("spec", {}).get("workerGroupSpecs", [])
            if workers:
                return workers[0].get("replicas", 1)
        except:
            pass
    return 1


def scale_workers(target):
    """Scale RayCluster workers."""
    patch = {"spec": {"workerGroupSpecs": [{"replicas": target, "groupName": "workers"}]}}
    cmd = f"kubectl patch raycluster {RAYCLUSTER_NAME} -n {NAMESPACE} --type=merge -p '{json.dumps(patch)}'"
    rc, out, err = run_cmd(cmd)
    if rc == 0:
        log(f"✓ Scaled to {target} workers")
        return True
    else:
        log(f"ERROR: Scale failed: {err}")
        return False


def main():
    """Main control loop."""
    log("="*60)
    log("GRU-CPA Controller starting")
    log(f"Namespace: {NAMESPACE}")
    log(f"RayCluster: {RAYCLUSTER_NAME}")
    log(f"Interval: {INTERVAL}s")
    log("="*60)

    while True:
        try:
            # Get metrics
            metrics = get_metrics()
            current_demand = metrics.get("current_demand", 0.0)
            history_len = len(metrics.get("history", []))

            # Get target replicas from GRU
            target = get_target_replicas(metrics)

            # Get current replicas
            current = get_current_replicas()

            # Scale if needed
            if target != current:
                log(f"Demand={current_demand:.0f}, History={history_len}, Current={current}, Target={target} → Scaling")
                scale_workers(target)
            else:
                log(f"Demand={current_demand:.0f}, History={history_len}, Replicas={current} → No change")

        except KeyboardInterrupt:
            log("Shutting down...")
            break
        except Exception as e:
            log(f"ERROR: {e}")

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
