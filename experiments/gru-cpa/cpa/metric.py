#!/usr/bin/env python3
"""
CPA Metric Gatherer (Sensor)

This script queries Prometheus for the ray_tasks metric history
and outputs it as JSON for the evaluate.py script.

Part of the Custom Pod Autoscaler framework.
Reference: https://custom-pod-autoscaler.readthedocs.io/
"""

import os
import sys
import json
import requests
from datetime import datetime, timedelta

# Configuration from environment
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus-server.monitoring:9090")
METRIC_NAME = os.getenv("METRIC_NAME", "ray_tasks")
METRIC_STATE = os.getenv("METRIC_STATE", "PENDING_ARGS_AVAIL")
SEQUENCE_LENGTH = int(os.getenv("SEQUENCE_LENGTH", "60"))
STEP_SECONDS = int(os.getenv("STEP_SECONDS", "1"))


def query_prometheus(query: str, start: datetime, end: datetime, step: str) -> list:
    """
    Query Prometheus for time-series data.
    
    Args:
        query: PromQL query string
        start: Start time
        end: End time
        step: Resolution step (e.g., "1s")
    
    Returns:
        List of (timestamp, value) tuples
    """
    url = f"{PROMETHEUS_URL}/api/v1/query_range"
    params = {
        "query": query,
        "start": start.isoformat() + "Z",
        "end": end.isoformat() + "Z",
        "step": step
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data["status"] != "success":
            raise Exception(f"Prometheus query failed: {data}")
        
        results = data.get("data", {}).get("result", [])
        if not results:
            return []
        
        # Extract values from the first result
        values = results[0].get("values", [])
        return [(float(ts), float(val)) for ts, val in values]
    
    except requests.exceptions.RequestException as e:
        print(f"Error querying Prometheus: {e}", file=sys.stderr)
        return []


def get_pending_tasks_history() -> list:
    """
    Get the history of pending Ray tasks.
    
    Returns:
        List of task counts for the last SEQUENCE_LENGTH seconds
    """
    # Time range
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(seconds=SEQUENCE_LENGTH)
    
    # PromQL query for pending tasks
    # This queries the ray_tasks metric with State="PENDING_ARGS_AVAIL"
    query = f'{METRIC_NAME}{{State="{METRIC_STATE}"}}'
    
    values = query_prometheus(query, start_time, end_time, f"{STEP_SECONDS}s")
    
    if not values:
        # Return zeros if no data available
        return [0.0] * SEQUENCE_LENGTH
    
    # Extract just the values (not timestamps)
    task_counts = [v[1] for v in values]
    
    # Pad or truncate to exact sequence length
    if len(task_counts) < SEQUENCE_LENGTH:
        padding = [0.0] * (SEQUENCE_LENGTH - len(task_counts))
        task_counts = padding + task_counts
    elif len(task_counts) > SEQUENCE_LENGTH:
        task_counts = task_counts[-SEQUENCE_LENGTH:]
    
    return task_counts


def get_current_demand() -> float:
    """Get the current pending task count."""
    url = f"{PROMETHEUS_URL}/api/v1/query"
    query = f'{METRIC_NAME}{{State="{METRIC_STATE}"}}'
    
    try:
        response = requests.get(url, params={"query": query}, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data["status"] != "success":
            return 0.0
        
        results = data.get("data", {}).get("result", [])
        if not results:
            return 0.0
        
        return float(results[0]["value"][1])
    
    except Exception as e:
        print(f"Error getting current demand: {e}", file=sys.stderr)
        return 0.0


def main():
    """
    Main entry point for the metric gatherer.
    
    Outputs JSON to stdout as expected by CPA framework.
    """
    # Get historical data
    history = get_pending_tasks_history()
    
    # Get current demand
    current = get_current_demand()
    
    # Output format expected by evaluate.py
    output = {
        "history": history,
        "current_demand": current,
        "timestamp": datetime.utcnow().isoformat(),
        "sequence_length": SEQUENCE_LENGTH
    }
    
    # Write to stdout (CPA framework reads this)
    sys.stdout.write(json.dumps(output))


if __name__ == "__main__":
    main()

