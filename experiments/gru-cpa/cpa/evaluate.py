#!/usr/bin/env python3
"""
CPA Evaluate Script (Controller)

This script reads the metric data from stdin, uses the GRU model
to predict future demand, and outputs the target replica count.

Implements a hybrid proactive-reactive algorithm:
- Proactive: Scale based on predicted future demand
- Reactive: Fall back to current demand if prediction is lower

Part of the Custom Pod Autoscaler framework.
Reference: https://custom-pod-autoscaler.readthedocs.io/
"""

import os
import sys
import json
import numpy as np

# Try to import TensorFlow (might not be available during testing)
try:
    import tensorflow as tf
    tf.get_logger().setLevel('ERROR')
    from tensorflow import keras
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False

# Configuration from environment
MODEL_PATH = os.getenv("MODEL_PATH", "/app/model/gru_model.h5")
SCALER_PATH = os.getenv("SCALER_PATH", "/app/model/scaler_params.json")
CPUS_PER_POD = float(os.getenv("CPUS_PER_POD", "1"))
MIN_REPLICAS = int(os.getenv("MIN_REPLICAS", "1"))
MAX_REPLICAS = int(os.getenv("MAX_REPLICAS", "10"))
SCALE_UP_BUFFER = float(os.getenv("SCALE_UP_BUFFER", "1.2"))  # 20% buffer


def load_model_and_scaler():
    """Load the pre-trained GRU model and scaler parameters."""
    if not TF_AVAILABLE:
        return None, None
    
    try:
        model = keras.models.load_model(MODEL_PATH)
        with open(SCALER_PATH, 'r') as f:
            scaler_params = json.load(f)
        return model, scaler_params
    except Exception as e:
        print(f"Warning: Could not load model: {e}", file=sys.stderr)
        return None, None


def predict_future_demand(model, scaler_params: dict, history: list) -> float:
    """
    Use GRU model to predict future task demand.
    
    Args:
        model: Trained GRU model
        scaler_params: Normalization parameters (mean, std)
        history: Historical task counts
    
    Returns:
        Predicted future task count
    """
    if model is None or scaler_params is None:
        return 0.0
    
    # Convert to numpy array
    sequence = np.array(history, dtype=np.float32)
    
    # Normalize
    normalized = (sequence - scaler_params["mean"]) / scaler_params["std"]
    
    # Reshape for GRU: (batch_size, sequence_length, features)
    X = normalized.reshape((1, len(normalized), 1))
    
    # Predict
    prediction = model.predict(X, verbose=0)[0][0]
    
    # Denormalize
    predicted_demand = prediction * scaler_params["std"] + scaler_params["mean"]
    
    # Ensure non-negative
    return max(0.0, predicted_demand)


def calculate_replicas(demand: float) -> int:
    """
    Calculate required replicas based on demand.
    
    Args:
        demand: Number of pending tasks (logical CPUs needed)
    
    Returns:
        Number of worker pod replicas needed
    """
    import math
    
    # Apply scale-up buffer for headroom
    buffered_demand = demand * SCALE_UP_BUFFER
    
    # Calculate replicas (ceiling division)
    replicas = math.ceil(buffered_demand / CPUS_PER_POD)
    
    # Clamp to min/max bounds
    return max(MIN_REPLICAS, min(MAX_REPLICAS, replicas))


def hybrid_scaling_algorithm(current_demand: float, predicted_demand: float) -> int:
    """
    Hybrid proactive-reactive scaling algorithm.
    
    This is a key contribution: by taking max() of current and predicted,
    we ensure the system is robust to both:
    1. Predicted spikes (proactive scaling)
    2. Unpredicted spikes (reactive fallback)
    
    Args:
        current_demand: Current pending task count
        predicted_demand: GRU-predicted future task count
    
    Returns:
        Target replica count
    """
    # Calculate replicas for each scenario
    current_replicas = calculate_replicas(current_demand)
    predicted_replicas = calculate_replicas(predicted_demand)
    
    # Hybrid logic: take the maximum
    # This ensures we scale proactively when prediction is high
    # AND reactively when current demand spikes unexpectedly
    target_replicas = max(current_replicas, predicted_replicas, MIN_REPLICAS)
    
    # Log decision for debugging
    print(f"Scaling decision: current={current_demand:.1f} ({current_replicas} pods), "
          f"predicted={predicted_demand:.1f} ({predicted_replicas} pods) -> "
          f"target={target_replicas} pods", file=sys.stderr)
    
    return target_replicas


def main():
    """
    Main entry point for the evaluate script.
    
    Reads metric JSON from stdin, calculates target replicas,
    and outputs JSON to stdout.
    """
    # Read metric data from stdin
    try:
        input_data = sys.stdin.read()
        metric_data = json.loads(input_data)
    except json.JSONDecodeError as e:
        print(f"Error parsing input JSON: {e}", file=sys.stderr)
        # Return minimum replicas on error
        output = {"targetReplicas": MIN_REPLICAS}
        sys.stdout.write(json.dumps(output))
        return
    
    # Extract data
    history = metric_data.get("history", [])
    current_demand = metric_data.get("current_demand", 0.0)
    
    # Load model
    model, scaler_params = load_model_and_scaler()
    
    # Predict future demand
    if model is not None and len(history) > 0:
        predicted_demand = predict_future_demand(model, scaler_params, history)
    else:
        # Fallback to current demand if model unavailable
        predicted_demand = current_demand
        print("Warning: Model unavailable, using current demand as prediction", 
              file=sys.stderr)
    
    # Calculate target replicas using hybrid algorithm
    target_replicas = hybrid_scaling_algorithm(current_demand, predicted_demand)
    
    # Output JSON for CPA framework
    output = {
        "targetReplicas": target_replicas
    }
    
    sys.stdout.write(json.dumps(output))


if __name__ == "__main__":
    main()

