#!/usr/bin/env python3
"""Collect Ray metrics from cluster for GRU training dataset."""

import subprocess
import json
import time
import re
import argparse
import os
from datetime import datetime, timedelta

OUT = os.path.join(os.path.dirname(__file__), "..", "model", "dataset_10k.json")


def kubectl(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def get_head(ns):
    return kubectl(f"kubectl get pods -n {ns} -l ray.io/node-type=head -o jsonpath='{{.items[0].metadata.name}}'")


def get_metrics(ns, pod):
    out = kubectl(f"kubectl exec -n {ns} {pod} -c ray-head -- wget -qO- http://localhost:8080/metrics 2>/dev/null")
    m = {}
    for line in out.split('\n'):
        if line.startswith('ray_'):
            match = re.match(r'(ray_\w+)\{([^}]*)\}\s+([\d.e+-]+)', line)
            if match:
                name, labels, val = match.groups()
                if name not in m: m[name] = []
                m[name].append({'labels': labels, 'value': float(val)})
    return m


def collect(ns, mins, interval=10):
    pod = get_head(ns)
    if not pod:
        print("No head pod found")
        return []
    
    print(f"Collecting from {pod} for {mins}min")
    
    pts = []
    end = datetime.now() + timedelta(minutes=mins)
    
    while datetime.now() < end:
        m = get_metrics(ns, pod)
        
        pt = {'ts': datetime.now().isoformat(), 'pending': 0, 'running': 0, 'cpu': 0}
        for x in m.get('ray_scheduler_tasks', []):
            if 'PENDING' in x['labels']: pt['pending'] += x['value']
            elif 'RUNNING' in x['labels']: pt['running'] += x['value']
        for x in m.get('ray_node_cpu_utilization', []):
            pt['cpu'] = x['value']
        
        pts.append(pt)
        rem = (end - datetime.now()).seconds / 60
        print(f"\r{len(pts)}: pending={pt['pending']:.0f} cpu={pt['cpu']:.1f}% ({rem:.1f}m left)", end='', flush=True)
        time.sleep(interval)
    
    print(f"\nCollected {len(pts)} samples")
    return pts


def save(pts, ns):
    pending = [p['pending'] for p in pts]
    cpu = [p['cpu'] for p in pts]
    
    # use cpu if no pending tasks recorded
    signal = cpu if sum(pending) == 0 else pending
    
    out = {
        "metadata": {
            "total_samples": len(signal),
            "source": "prometheus_collection",
            "description": "Task demand data collected from Ray cluster via Prometheus metrics",
            "metrics_used": ["ray_scheduler_tasks", "ray_node_cpu_utilization"],
            "cluster": "OpenShift RHOAI",
            "namespace": ns,
            "start": pts[0]['ts'] if pts else None,
            "end": pts[-1]['ts'] if pts else None,
            "created": datetime.now().strftime("%Y-%m-%d")
        },
        "data": signal,
        "statistics": {
            "mean": sum(signal)/len(signal) if signal else 0,
            "max": max(signal) if signal else 0,
            "min": min(signal) if signal else 0
        }
    }
    
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"Saved to {OUT}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Collect Ray metrics for GRU training")
    p.add_argument("-n", "--namespace", default="gru-cpa-experiment")
    p.add_argument("-d", "--duration", type=int, default=10)
    p.add_argument("-i", "--interval", type=int, default=10)
    args = p.parse_args()
    
    pts = collect(args.namespace, args.duration, args.interval)
    if pts:
        save(pts, args.namespace)
