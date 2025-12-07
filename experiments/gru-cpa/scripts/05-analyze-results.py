#!/usr/bin/env python3
"""Analyze experiment results."""

import os
import json
import glob
import pandas as pd
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
RESULTS_DIR = os.path.join(PROJECT_DIR, "results")


def load_data(exp_dir):
    data = {}
    for f in ["summary.json"]:
        p = os.path.join(exp_dir, f)
        if os.path.exists(p):
            with open(p) as fp:
                data['summary'] = json.load(fp)
    for f in ["metrics.csv", "pod_metrics.csv"]:
        p = os.path.join(exp_dir, f)
        if os.path.exists(p):
            data[f.replace('.csv','')] = pd.read_csv(p)
    return data


def calc_metrics(data):
    m = {}
    if 'summary' in data:
        m['completion_time'] = data['summary'].get('duration_seconds', 0)
    
    if 'metrics' in data and len(data['metrics']) > 0:
        df = data['metrics']
        df['dt'] = df['timestamp'].diff().fillna(0)
        
        if 'pending_tasks' in df.columns:
            pending = df['pending_tasks'].astype(float)
            m['p99_pending'] = np.percentile(pending, 99)
            m['max_pending'] = pending.max()
            m['avg_pending'] = pending.mean()
        
        if 'allocated_pods' in df.columns:
            m['vcpu_seconds'] = (df['allocated_pods'].astype(float) * df['dt']).sum()
    
    return m


def compare(base_dir, gru_dir):
    base = calc_metrics(load_data(base_dir))
    gru = calc_metrics(load_data(gru_dir))
    
    result = {'baseline': base, 'gru_cpa': gru, 'improvement': {}}
    for k in base:
        if k in gru and isinstance(base[k], (int, float)) and base[k] > 0:
            result['improvement'][k] = ((base[k] - gru[k]) / base[k]) * 100
    return result


def print_table(cmp):
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    fmt = "{:<25} {:>12} {:>12} {:>12}"
    print(fmt.format("Metric", "Baseline", "GRU-CPA", "Improve"))
    print("-" * 60)
    
    for k in ['completion_time', 'vcpu_seconds', 'p99_pending', 'avg_pending']:
        bv = cmp['baseline'].get(k, 'N/A')
        gv = cmp['gru_cpa'].get(k, 'N/A')
        imp = f"{cmp['improvement'].get(k, 0):+.1f}%" if k in cmp['improvement'] else 'N/A'
        if isinstance(bv, float): bv = f"{bv:.2f}"
        if isinstance(gv, float): gv = f"{gv:.2f}"
        print(fmt.format(k, str(bv), str(gv), imp))
    
    print("=" * 60)


def main():
    base_dirs = sorted(glob.glob(os.path.join(RESULTS_DIR, "baseline-*")))
    gru_dirs = sorted(glob.glob(os.path.join(RESULTS_DIR, "gru-cpa-*")))
    
    if not base_dirs or not gru_dirs:
        print("No results found. Run experiments first.")
        return
    
    cmp = compare(base_dirs[-1], gru_dirs[-1])
    print_table(cmp)
    
    with open(os.path.join(RESULTS_DIR, "comparison.json"), 'w') as f:
        json.dump(cmp, f, indent=2, default=str)


if __name__ == "__main__":
    main()
