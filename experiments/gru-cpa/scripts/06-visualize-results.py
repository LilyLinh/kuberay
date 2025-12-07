#!/usr/bin/env python3
"""
Visualize experiment results with charts.

Generates publication-quality figures comparing HPA vs GRU-CPA performance.
"""

import os
import sys
import json
import glob
import pandas as pd
import numpy as np

try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import MaxNLocator
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("Warning: matplotlib not available. Install with: pip install matplotlib")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
RESULTS_DIR = os.path.join(PROJECT_DIR, "results")


def setup_plot_style():
    """Configure matplotlib for publication-quality plots."""
    if not MATPLOTLIB_AVAILABLE:
        return
    
    plt.style.use('seaborn-v0_8-whitegrid')
    plt.rcParams.update({
        'font.size': 12,
        'axes.labelsize': 14,
        'axes.titlesize': 16,
        'legend.fontsize': 11,
        'figure.figsize': (12, 8),
        'figure.dpi': 150,
    })


def load_metrics(experiment_dir: str) -> pd.DataFrame:
    """Load metrics CSV from experiment directory."""
    metrics_path = os.path.join(experiment_dir, "metrics.csv")
    if os.path.exists(metrics_path):
        df = pd.read_csv(metrics_path)
        # Convert timestamp to relative time (seconds from start)
        df['time'] = df['timestamp'] - df['timestamp'].min()
        return df
    return pd.DataFrame()


def plot_scaling_comparison(baseline_df: pd.DataFrame, gru_df: pd.DataFrame, output_dir: str):
    """Plot allocated pods over time for both experiments."""
    if not MATPLOTLIB_AVAILABLE:
        return
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    # Plot 1: Allocated Pods over time
    ax1 = axes[0, 0]
    if 'allocated_pods' in baseline_df.columns:
        ax1.plot(baseline_df['time'], baseline_df['allocated_pods'], 
                 label='HPA (Baseline)', color='#e74c3c', linewidth=2)
    if 'allocated_pods' in gru_df.columns:
        ax1.plot(gru_df['time'], gru_df['allocated_pods'], 
                 label='GRU-CPA', color='#2ecc71', linewidth=2)
    ax1.set_xlabel('Time (seconds)')
    ax1.set_ylabel('Allocated Worker Pods')
    ax1.set_title('Autoscaler Response: Allocated Pods')
    ax1.legend()
    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    
    # Plot 2: Pending Tasks over time
    ax2 = axes[0, 1]
    if 'pending_tasks' in baseline_df.columns:
        ax2.plot(baseline_df['time'], baseline_df['pending_tasks'].astype(float), 
                 label='HPA (Baseline)', color='#e74c3c', linewidth=2)
    if 'pending_tasks' in gru_df.columns:
        ax2.plot(gru_df['time'], gru_df['pending_tasks'].astype(float), 
                 label='GRU-CPA', color='#2ecc71', linewidth=2)
    ax2.set_xlabel('Time (seconds)')
    ax2.set_ylabel('Pending Tasks')
    ax2.set_title('Task Queue: Pending Tasks (QoS Indicator)')
    ax2.legend()
    
    # Plot 3: Resource Efficiency (Allocated vs Demanded)
    ax3 = axes[1, 0]
    if 'allocated_pods' in baseline_df.columns and 'requested_cpus' in baseline_df.columns:
        ax3.fill_between(baseline_df['time'], 
                         baseline_df['allocated_pods'].astype(float),
                         baseline_df['requested_cpus'].astype(float),
                         alpha=0.3, color='#e74c3c', label='HPA Waste/Penalty')
        ax3.plot(baseline_df['time'], baseline_df['allocated_pods'], 
                 color='#e74c3c', linestyle='--', label='HPA Allocated')
        ax3.plot(baseline_df['time'], baseline_df['requested_cpus'].astype(float), 
                 color='#c0392b', linestyle='-', label='HPA Demanded')
    ax3.set_xlabel('Time (seconds)')
    ax3.set_ylabel('CPUs')
    ax3.set_title('HPA: Resource Allocation vs Demand')
    ax3.legend()
    
    # Plot 4: GRU-CPA Resource Efficiency
    ax4 = axes[1, 1]
    if 'allocated_pods' in gru_df.columns and 'requested_cpus' in gru_df.columns:
        ax4.fill_between(gru_df['time'], 
                         gru_df['allocated_pods'].astype(float),
                         gru_df['requested_cpus'].astype(float),
                         alpha=0.3, color='#2ecc71', label='GRU-CPA Waste/Penalty')
        ax4.plot(gru_df['time'], gru_df['allocated_pods'], 
                 color='#2ecc71', linestyle='--', label='GRU-CPA Allocated')
        ax4.plot(gru_df['time'], gru_df['requested_cpus'].astype(float), 
                 color='#27ae60', linestyle='-', label='GRU-CPA Demanded')
    ax4.set_xlabel('Time (seconds)')
    ax4.set_ylabel('CPUs')
    ax4.set_title('GRU-CPA: Resource Allocation vs Demand')
    ax4.legend()
    
    plt.tight_layout()
    output_path = os.path.join(output_dir, "scaling_comparison.png")
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()


def plot_metrics_bar_chart(comparison: dict, output_dir: str):
    """Plot bar chart comparing key metrics."""
    if not MATPLOTLIB_AVAILABLE:
        return
    
    baseline = comparison.get('baseline', {})
    gru_cpa = comparison.get('gru_cpa', {})
    
    metrics = [
        ('job_completion_time', 'Job Completion\nTime (s)'),
        ('resource_wastage_score', 'Resource\nWastage'),
        ('cold_start_penalty_score', 'Cold-Start\nPenalty'),
        ('max_pending_tasks', 'Max Pending\nTasks'),
    ]
    
    labels = [m[1] for m in metrics]
    baseline_values = [baseline.get(m[0], 0) for m in metrics]
    gru_values = [gru_cpa.get(m[0], 0) for m in metrics]
    
    x = np.arange(len(labels))
    width = 0.35
    
    fig, ax = plt.subplots(figsize=(10, 6))
    bars1 = ax.bar(x - width/2, baseline_values, width, label='HPA (Baseline)', color='#e74c3c')
    bars2 = ax.bar(x + width/2, gru_values, width, label='GRU-CPA', color='#2ecc71')
    
    ax.set_xlabel('Metric')
    ax.set_ylabel('Value')
    ax.set_title('Performance Comparison: HPA vs GRU-CPA')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    
    # Add value labels on bars
    def add_labels(bars):
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f'{height:.1f}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3),
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=9)
    
    add_labels(bars1)
    add_labels(bars2)
    
    plt.tight_layout()
    output_path = os.path.join(output_dir, "metrics_comparison.png")
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()


def plot_improvement_chart(comparison: dict, output_dir: str):
    """Plot improvement percentages."""
    if not MATPLOTLIB_AVAILABLE:
        return
    
    improvements = comparison.get('improvements', {})
    
    if not improvements:
        print("No improvement data to plot")
        return
    
    metrics = []
    percentages = []
    
    for key, value in improvements.items():
        if isinstance(value, dict) and 'percentage' in value:
            # Clean up metric name for display
            label = key.replace('_', ' ').title()
            metrics.append(label)
            percentages.append(value['percentage'])
    
    if not metrics:
        return
    
    # Sort by improvement (descending)
    sorted_pairs = sorted(zip(metrics, percentages), key=lambda x: x[1], reverse=True)
    metrics, percentages = zip(*sorted_pairs)
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    colors = ['#2ecc71' if p > 0 else '#e74c3c' for p in percentages]
    bars = ax.barh(metrics, percentages, color=colors)
    
    ax.set_xlabel('Improvement (%)')
    ax.set_title('GRU-CPA Improvement over HPA Baseline')
    ax.axvline(x=0, color='black', linewidth=0.5)
    
    # Add percentage labels
    for bar, pct in zip(bars, percentages):
        width = bar.get_width()
        ax.annotate(f'{pct:+.1f}%',
                    xy=(width, bar.get_y() + bar.get_height() / 2),
                    xytext=(5 if width >= 0 else -5, 0),
                    textcoords="offset points",
                    ha='left' if width >= 0 else 'right',
                    va='center', fontsize=10)
    
    plt.tight_layout()
    output_path = os.path.join(output_dir, "improvements.png")
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()


def main():
    """Main visualization entry point."""
    if not MATPLOTLIB_AVAILABLE:
        print("matplotlib is required for visualization")
        print("Install with: pip install matplotlib")
        return
    
    setup_plot_style()
    
    # Find experiment directories
    baseline_dirs = sorted(glob.glob(os.path.join(RESULTS_DIR, "baseline-*")))
    gru_cpa_dirs = sorted(glob.glob(os.path.join(RESULTS_DIR, "gru-cpa-*")))
    
    if not baseline_dirs or not gru_cpa_dirs:
        print("Need both baseline and GRU-CPA experiment results")
        return
    
    # Use most recent experiments
    baseline_dir = baseline_dirs[-1]
    gru_cpa_dir = gru_cpa_dirs[-1]
    
    print(f"Visualizing experiments:")
    print(f"  Baseline: {os.path.basename(baseline_dir)}")
    print(f"  GRU-CPA:  {os.path.basename(gru_cpa_dir)}")
    
    # Load data
    baseline_df = load_metrics(baseline_dir)
    gru_df = load_metrics(gru_cpa_dir)
    
    # Load comparison if available
    comparison_path = os.path.join(RESULTS_DIR, "comparison.json")
    if os.path.exists(comparison_path):
        with open(comparison_path, 'r') as f:
            comparison = json.load(f)
    else:
        comparison = {}
    
    # Create output directory
    output_dir = os.path.join(RESULTS_DIR, "figures")
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate plots
    if not baseline_df.empty and not gru_df.empty:
        plot_scaling_comparison(baseline_df, gru_df, output_dir)
    
    if comparison:
        plot_metrics_bar_chart(comparison, output_dir)
        plot_improvement_chart(comparison, output_dir)
    
    print(f"\nFigures saved to: {output_dir}")


if __name__ == "__main__":
    main()

