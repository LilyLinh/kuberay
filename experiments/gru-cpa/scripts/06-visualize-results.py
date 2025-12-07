#!/usr/bin/env python3
"""Generate charts from experiment results."""

import os
import json
import glob
import pandas as pd
import numpy as np

try:
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
    HAS_PLT = True
except ImportError:
    HAS_PLT = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
RESULTS_DIR = os.path.join(PROJECT_DIR, "results")


def load_metrics(d):
    p = os.path.join(d, "metrics.csv")
    if os.path.exists(p):
        df = pd.read_csv(p)
        df['time'] = df['timestamp'] - df['timestamp'].min()
        return df
    return pd.DataFrame()


def plot_comparison(base, gru, out_dir):
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    
    ax = axes[0,0]
    if 'allocated_pods' in base.columns:
        ax.plot(base['time'], base['allocated_pods'], 'r-', label='HPA', lw=2)
    if 'allocated_pods' in gru.columns:
        ax.plot(gru['time'], gru['allocated_pods'], 'g-', label='GRU-CPA', lw=2)
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Workers')
    ax.set_title('Allocated Pods')
    ax.legend()
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    
    ax = axes[0,1]
    if 'pending_tasks' in base.columns:
        ax.plot(base['time'], base['pending_tasks'].astype(float), 'r-', label='HPA', lw=2)
    if 'pending_tasks' in gru.columns:
        ax.plot(gru['time'], gru['pending_tasks'].astype(float), 'g-', label='GRU-CPA', lw=2)
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Pending')
    ax.set_title('Pending Tasks')
    ax.legend()
    
    ax = axes[1,0]
    if 'allocated_pods' in base.columns and 'requested_cpus' in base.columns:
        ax.fill_between(base['time'], base['allocated_pods'].astype(float),
                        base['requested_cpus'].astype(float), alpha=0.3, color='r')
        ax.plot(base['time'], base['allocated_pods'], 'r--', label='Allocated')
        ax.plot(base['time'], base['requested_cpus'].astype(float), 'r-', label='Demand')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('CPUs')
    ax.set_title('HPA: Allocation vs Demand')
    ax.legend()
    
    ax = axes[1,1]
    if 'allocated_pods' in gru.columns and 'requested_cpus' in gru.columns:
        ax.fill_between(gru['time'], gru['allocated_pods'].astype(float),
                        gru['requested_cpus'].astype(float), alpha=0.3, color='g')
        ax.plot(gru['time'], gru['allocated_pods'], 'g--', label='Allocated')
        ax.plot(gru['time'], gru['requested_cpus'].astype(float), 'g-', label='Demand')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('CPUs')
    ax.set_title('GRU-CPA: Allocation vs Demand')
    ax.legend()
    
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "comparison.png"), dpi=150)
    plt.close()


def plot_bars(cmp, out_dir):
    base = cmp.get('baseline', {})
    gru = cmp.get('gru_cpa', {})
    
    metrics = ['completion_time', 'vcpu_seconds', 'max_pending', 'avg_pending']
    labels = ['Time (s)', 'CPU-Sec', 'Max Pending', 'Avg Pending']
    
    base_vals = [base.get(m, 0) for m in metrics]
    gru_vals = [gru.get(m, 0) for m in metrics]
    
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(x - 0.2, base_vals, 0.4, label='HPA', color='#e74c3c')
    ax.bar(x + 0.2, gru_vals, 0.4, label='GRU-CPA', color='#2ecc71')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    ax.set_title('HPA vs GRU-CPA')
    
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "bars.png"), dpi=150)
    plt.close()


def main():
    if not HAS_PLT:
        print("matplotlib required: pip install matplotlib")
        return
    
    plt.style.use('seaborn-v0_8-whitegrid')
    
    base_dirs = sorted(glob.glob(os.path.join(RESULTS_DIR, "baseline-*")))
    gru_dirs = sorted(glob.glob(os.path.join(RESULTS_DIR, "gru-cpa-*")))
    
    if not base_dirs or not gru_dirs:
        print("Need both baseline and gru-cpa results")
        return
    
    base_df = load_metrics(base_dirs[-1])
    gru_df = load_metrics(gru_dirs[-1])
    
    cmp_path = os.path.join(RESULTS_DIR, "comparison.json")
    cmp = json.load(open(cmp_path)) if os.path.exists(cmp_path) else {}
    
    out_dir = os.path.join(RESULTS_DIR, "figures")
    os.makedirs(out_dir, exist_ok=True)
    
    if not base_df.empty and not gru_df.empty:
        plot_comparison(base_df, gru_df, out_dir)
    if cmp:
        plot_bars(cmp, out_dir)
    
    print(f"Saved to {out_dir}")


if __name__ == "__main__":
    main()
