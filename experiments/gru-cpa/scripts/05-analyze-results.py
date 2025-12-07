#!/usr/bin/env python3
"""
Analyze and compare experiment results.

Calculates the key metrics from the paper:
- p99 Task Pending Time
- Total Job Completion Time
- Total vCPU-Seconds Consumed
- Resource Wastage Score
- Cold-Start Penalty Score
"""

import os
import sys
import json
import glob
import pandas as pd
import numpy as np
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
RESULTS_DIR = os.path.join(PROJECT_DIR, "results")


def load_experiment_data(experiment_dir: str) -> dict:
    """Load all data from an experiment directory."""
    data = {}
    
    # Load summary
    summary_path = os.path.join(experiment_dir, "summary.json")
    if os.path.exists(summary_path):
        with open(summary_path, 'r') as f:
            data['summary'] = json.load(f)
    
    # Load metrics CSV
    metrics_path = os.path.join(experiment_dir, "metrics.csv")
    if os.path.exists(metrics_path):
        data['metrics'] = pd.read_csv(metrics_path)
    
    # Load pod metrics CSV
    pod_metrics_path = os.path.join(experiment_dir, "pod_metrics.csv")
    if os.path.exists(pod_metrics_path):
        data['pod_metrics'] = pd.read_csv(pod_metrics_path)
    
    return data


def calculate_metrics(data: dict) -> dict:
    """Calculate all research metrics from experiment data."""
    metrics = {}
    
    if 'summary' in data:
        metrics['job_completion_time'] = data['summary'].get('duration_seconds', 0)
        metrics['experiment_type'] = data['summary'].get('experiment', 'unknown')
    
    if 'metrics' in data and len(data['metrics']) > 0:
        df = data['metrics']
        
        # Calculate time deltas
        df['time_delta'] = df['timestamp'].diff().fillna(0)
        
        # p99 Task Pending Time (approximate from pending task counts)
        if 'pending_tasks' in df.columns:
            # Higher pending = longer wait
            pending_values = df['pending_tasks'].astype(float)
            metrics['p99_pending_tasks'] = np.percentile(pending_values, 99)
            metrics['max_pending_tasks'] = pending_values.max()
            metrics['avg_pending_tasks'] = pending_values.mean()
        
        # Total vCPU-Seconds (allocated_pods * CPUs_per_pod * time)
        CPUS_PER_POD = 1.0
        if 'allocated_pods' in df.columns:
            allocated = df['allocated_pods'].astype(float)
            vcpu_seconds = (allocated * CPUS_PER_POD * df['time_delta']).sum()
            metrics['total_vcpu_seconds'] = vcpu_seconds
        
        # Resource Wastage Score
        # When allocated > demanded, we're over-provisioned
        if 'allocated_pods' in df.columns and 'requested_cpus' in df.columns:
            allocated_cpus = df['allocated_pods'].astype(float) * CPUS_PER_POD
            demanded_cpus = df['requested_cpus'].astype(float)
            
            over_provision = (allocated_cpus - demanded_cpus).clip(lower=0)
            metrics['resource_wastage_score'] = (over_provision * df['time_delta']).sum()
        
        # Cold-Start Penalty Score
        # When demanded > allocated, tasks are waiting
        if 'allocated_pods' in df.columns and 'requested_cpus' in df.columns:
            allocated_cpus = df['allocated_pods'].astype(float) * CPUS_PER_POD
            demanded_cpus = df['requested_cpus'].astype(float)
            
            under_provision = (demanded_cpus - allocated_cpus).clip(lower=0)
            metrics['cold_start_penalty_score'] = (under_provision * df['time_delta']).sum()
    
    return metrics


def compare_experiments(baseline_dir: str, gru_cpa_dir: str) -> dict:
    """Compare baseline HPA vs GRU-CPA experiments."""
    baseline_data = load_experiment_data(baseline_dir)
    gru_cpa_data = load_experiment_data(gru_cpa_dir)
    
    baseline_metrics = calculate_metrics(baseline_data)
    gru_cpa_metrics = calculate_metrics(gru_cpa_data)
    
    comparison = {
        'baseline': baseline_metrics,
        'gru_cpa': gru_cpa_metrics,
        'improvements': {}
    }
    
    # Calculate improvements
    for key in baseline_metrics:
        if key in gru_cpa_metrics and isinstance(baseline_metrics[key], (int, float)):
            baseline_val = baseline_metrics[key]
            gru_val = gru_cpa_metrics[key]
            
            if baseline_val > 0:
                improvement = ((baseline_val - gru_val) / baseline_val) * 100
                comparison['improvements'][key] = {
                    'absolute': baseline_val - gru_val,
                    'percentage': improvement
                }
    
    return comparison


def print_comparison_table(comparison: dict):
    """Print a formatted comparison table."""
    print("\n" + "=" * 70)
    print("EXPERIMENT RESULTS COMPARISON")
    print("=" * 70)
    
    headers = ["Metric", "Baseline (HPA)", "GRU-CPA", "Improvement"]
    row_format = "{:<30} {:>15} {:>15} {:>15}"
    
    print(row_format.format(*headers))
    print("-" * 70)
    
    baseline = comparison['baseline']
    gru_cpa = comparison['gru_cpa']
    improvements = comparison['improvements']
    
    metrics_to_show = [
        ('job_completion_time', 'Job Completion Time (s)'),
        ('total_vcpu_seconds', 'Total vCPU-Seconds'),
        ('resource_wastage_score', 'Resource Wastage Score'),
        ('cold_start_penalty_score', 'Cold-Start Penalty'),
        ('p99_pending_tasks', 'p99 Pending Tasks'),
        ('max_pending_tasks', 'Max Pending Tasks'),
        ('avg_pending_tasks', 'Avg Pending Tasks'),
    ]
    
    for key, label in metrics_to_show:
        baseline_val = baseline.get(key, 'N/A')
        gru_val = gru_cpa.get(key, 'N/A')
        
        if key in improvements:
            imp = improvements[key]
            imp_str = f"{imp['percentage']:+.1f}%"
        else:
            imp_str = 'N/A'
        
        if isinstance(baseline_val, float):
            baseline_val = f"{baseline_val:.2f}"
        if isinstance(gru_val, float):
            gru_val = f"{gru_val:.2f}"
        
        print(row_format.format(label, str(baseline_val), str(gru_val), imp_str))
    
    print("=" * 70)


def main():
    """Main analysis entry point."""
    # Find experiment directories
    baseline_dirs = sorted(glob.glob(os.path.join(RESULTS_DIR, "baseline-*")))
    gru_cpa_dirs = sorted(glob.glob(os.path.join(RESULTS_DIR, "gru-cpa-*")))
    
    if not baseline_dirs:
        print("No baseline experiment results found")
        print(f"Run: ./scripts/03-run-baseline-hpa.sh")
        return
    
    if not gru_cpa_dirs:
        print("No GRU-CPA experiment results found")
        print(f"Run: ./scripts/04-run-gru-cpa.sh")
        return
    
    # Use most recent experiments
    baseline_dir = baseline_dirs[-1]
    gru_cpa_dir = gru_cpa_dirs[-1]
    
    print(f"Analyzing experiments:")
    print(f"  Baseline: {os.path.basename(baseline_dir)}")
    print(f"  GRU-CPA:  {os.path.basename(gru_cpa_dir)}")
    
    comparison = compare_experiments(baseline_dir, gru_cpa_dir)
    print_comparison_table(comparison)
    
    # Save comparison to JSON
    output_path = os.path.join(RESULTS_DIR, "comparison.json")
    with open(output_path, 'w') as f:
        json.dump(comparison, f, indent=2, default=str)
    print(f"\nComparison saved to: {output_path}")


if __name__ == "__main__":
    main()

