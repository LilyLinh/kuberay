#!/usr/bin/env python3
"""
Real GRU Controller - Runs locally, uses actual model predictions
This script:
1. Monitors Ray cluster metrics in real-time
2. Uses trained GRU model to predict demand
3. Scales RayCluster based on predictions
4. Logs all decisions for thesis analysis
"""

import os
import sys
import json
import time
import subprocess
import numpy as np
from datetime import datetime
from collections import deque

# Add model directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'model'))

# Configuration
NAMESPACE = os.getenv('NAMESPACE', 'gru-cpa-experiment')
RAYCLUSTER = os.getenv('RAYCLUSTER', 'test-cluster')
MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', 'model', 'gru_model.keras')
SCALER_PATH = os.path.join(os.path.dirname(__file__), '..', 'model', 'scaler_params.json')
LOG_FILE = os.path.join(os.path.dirname(__file__), '..', 'results', f'gru-controller-{datetime.now().strftime("%Y%m%d-%H%M%S")}.log')

SEQ_LEN = 30
INTERVAL = 2  # Check every 2 seconds (faster response)
TASKS_PER_WORKER = 20
MIN_WORKERS = 1
MAX_WORKERS = 10
BUFFER = 1.2

# History buffer
history = deque(maxlen=SEQ_LEN)

# Load GRU model
print("Loading GRU model...")
try:
    from tensorflow import keras
    from tensorflow.keras import layers
    import tensorflow as tf

    # Define Attention layer for loading
    class Attention(layers.Layer):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

        def build(self, input_shape):
            self.W = self.add_weight(shape=(input_shape[-1], 1), initializer='glorot_uniform', trainable=True, name='attention_W')
            self.b = self.add_weight(shape=(input_shape[1], 1), initializer='zeros', trainable=True, name='attention_b')
            super().build(input_shape)

        def call(self, x):
            score = tf.nn.tanh(tf.tensordot(x, self.W, axes=1) + self.b)
            weights = tf.nn.softmax(score, axis=1)
            return tf.reduce_sum(x * weights, axis=1)

        def get_config(self):
            return super().get_config()

    # Load model with custom objects
    model = keras.models.load_model(MODEL_PATH, custom_objects={'Attention': Attention})
    with open(SCALER_PATH) as f:
        scaler = json.load(f)
    print(f"✓ Model loaded: {MODEL_PATH}")
    print(f"✓ Scaler: mean={scaler['mean']:.2f}, std={scaler['std']:.2f}")
except Exception as e:
    print(f"ERROR loading model: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)


def log(msg):
    """Log with timestamp to console and file."""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)

    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')


def run_cmd(cmd):
    """Run shell command."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return False, "", str(e)


def get_ray_demand():
    """
    Get demand signal from Ray cluster.
    Uses CPU utilization as proxy for workload (same as training data collection).
    """
    import re

    # Get head pod
    head_cmd = f"kubectl get pods -n {NAMESPACE} -l ray.io/node-type=head -o jsonpath='{{.items[0].metadata.name}}'"
    ok, pod_name, _ = run_cmd(head_cmd)

    if not ok or not pod_name:
        return 0.0

    # Get metrics using wget (same as collect-ray-metrics.py)
    metrics_cmd = f"kubectl exec -n {NAMESPACE} {pod_name} -c ray-head -- wget -qO- http://localhost:8080/metrics 2>/dev/null"
    ok, output, _ = run_cmd(metrics_cmd)

    if not ok or not output:
        return 0.0

    # Parse metrics - use CPU utilization as demand signal
    # (This matches how training data was collected)
    cpu_total = 0.0
    cpu_count = 0

    for line in output.split('\n'):
        if line.startswith('ray_node_cpu_utilization'):
            match = re.match(r'ray_node_cpu_utilization\{([^}]*)\}\s+([\d.e+-]+)', line)
            if match:
                labels, value = match.groups()
                cpu_total += float(value)
                cpu_count += 1

    # Return average CPU utilization across all nodes
    return cpu_total / cpu_count if cpu_count > 0 else 0.0


def predict_demand(history_list):
    """Use GRU model to predict future demand."""
    if len(history_list) < SEQ_LEN:
        # Not enough history, return current value
        return history_list[-1] if history_list else 0.0

    # Prepare input
    seq = np.array(history_list[-SEQ_LEN:], dtype=np.float32)
    normalized = (seq - scaler['mean']) / scaler['std']
    X = normalized.reshape(1, SEQ_LEN, 1)

    # Predict
    pred_normalized = model.predict(X, verbose=0)[0][0]
    predicted = pred_normalized * scaler['std'] + scaler['mean']

    return max(0.0, predicted)


def calculate_workers(current_demand, predicted_demand):
    """
    Calculate needed workers based on demand (CPU utilization).
    Demand is CPU percentage (can be 0-200+ for multi-node).
    """
    # Use max of current and predicted (hybrid approach)
    demand = max(current_demand, predicted_demand)

    # Aggressive scaling strategy for Ray workloads
    # Each node has ~2 CPUs, so scale based on CPU demand
    # Scale up aggressively to handle bursts
    if demand < 5:
        workers = 1
    elif demand < 20:
        workers = 2
    elif demand < 50:
        workers = 3
    elif demand < 100:
        workers = 4
    else:
        # For high CPU (100+), scale based on total CPU load
        workers = int(np.ceil(demand / 50.0))  # 1 worker per 50% CPU

    # Clamp to limits
    return max(MIN_WORKERS, min(MAX_WORKERS, workers))


def get_current_workers():
    """Get current worker replicas from RayCluster."""
    cmd = f"kubectl get raycluster {RAYCLUSTER} -n {NAMESPACE} -o json"
    ok, output, _ = run_cmd(cmd)

    if ok:
        try:
            data = json.loads(output)
            specs = data.get('spec', {}).get('workerGroupSpecs', [])
            if specs:
                return specs[0].get('replicas', 1)
        except:
            pass

    return 1


def scale_workers(target):
    """Scale RayCluster workers using JSON patch."""
    # Use JSON patch to only update the replicas field
    patch = [{
        "op": "replace",
        "path": "/spec/workerGroupSpecs/0/replicas",
        "value": target
    }]

    cmd = f"kubectl patch raycluster {RAYCLUSTER} -n {NAMESPACE} --type=json -p '{json.dumps(patch)}'"
    ok, output, err = run_cmd(cmd)

    if ok:
        log(f"  ✓ SCALED to {target} workers")
        return True
    else:
        log(f"  ✗ SCALE FAILED: {err}")
        return False


def main():
    """Main controller loop."""
    log("="*80)
    log("GRU-CPA CONTROLLER STARTED")
    log(f"Namespace: {NAMESPACE}")
    log(f"RayCluster: {RAYCLUSTER}")
    log(f"Check interval: {INTERVAL}s")
    log(f"Model: {os.path.basename(MODEL_PATH)}")
    log(f"Log file: {LOG_FILE}")
    log("="*80)

    iteration = 0

    try:
        while True:
            iteration += 1

            # 1. Get current metrics
            current_demand = get_ray_demand()
            history.append(current_demand)

            # 2. Predict future demand using GRU
            if len(history) >= SEQ_LEN:
                predicted_demand = predict_demand(list(history))
                use_prediction = True
            else:
                predicted_demand = current_demand
                use_prediction = False

            # 3. Calculate workers needed
            target_workers = calculate_workers(current_demand, predicted_demand)

            # 4. Get current state
            current_workers = get_current_workers()

            # 5. Log decision
            status = "SCALING" if target_workers != current_workers else "STABLE"
            mode = "GRU" if use_prediction else "REACTIVE"

            log(f"[{iteration:03d}] Demand={current_demand:.0f}, Predicted={predicted_demand:.0f} ({mode}), "
                f"Workers={current_workers}→{target_workers}, History={len(history)}/{SEQ_LEN} | {status}")

            # 6. Scale if needed
            if target_workers != current_workers:
                scale_workers(target_workers)

            # Wait for next iteration
            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        log("="*80)
        log("Controller stopped by user")
        log(f"Total iterations: {iteration}")
        log(f"History collected: {len(history)} samples")
        log(f"Log saved to: {LOG_FILE}")
        log("="*80)


if __name__ == "__main__":
    main()
