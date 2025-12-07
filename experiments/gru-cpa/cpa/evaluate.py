#!/usr/bin/env python3
"""CPA evaluate script - calculates target replicas from predicted demand."""

import os
import sys
import json
import math
import numpy as np

try:
    import tensorflow as tf
    tf.get_logger().setLevel('ERROR')
    from tensorflow import keras
    HAS_TF = True
except ImportError:
    HAS_TF = False

MODEL_PATH = os.getenv("MODEL_PATH", "/app/model/gru_model.h5")
SCALER_PATH = os.getenv("SCALER_PATH", "/app/model/scaler_params.json")
CPUS_PER_POD = float(os.getenv("CPUS_PER_POD", "1"))
MIN_REPLICAS = int(os.getenv("MIN_REPLICAS", "1"))
MAX_REPLICAS = int(os.getenv("MAX_REPLICAS", "10"))
BUFFER = float(os.getenv("SCALE_UP_BUFFER", "1.2"))


def load_model():
    if not HAS_TF:
        return None, None
    try:
        model = keras.models.load_model(MODEL_PATH)
        with open(SCALER_PATH) as f:
            scaler = json.load(f)
        return model, scaler
    except:
        return None, None


def predict(model, scaler, history):
    if model is None:
        return 0.0
    seq = np.array(history, dtype=np.float32)
    norm = (seq - scaler["mean"]) / scaler["std"]
    X = norm.reshape((1, len(norm), 1))
    pred = model.predict(X, verbose=0)[0][0]
    return max(0.0, pred * scaler["std"] + scaler["mean"])


def calc_replicas(demand):
    n = math.ceil(demand * BUFFER / CPUS_PER_POD)
    return max(MIN_REPLICAS, min(MAX_REPLICAS, n))


def main():
    try:
        data = json.loads(sys.stdin.read())
    except:
        sys.stdout.write(json.dumps({"targetReplicas": MIN_REPLICAS}))
        return
    
    history = data.get("history", [])
    current = data.get("current_demand", 0.0)
    
    model, scaler = load_model()
    predicted = predict(model, scaler, history) if model and history else current
    
    target = max(calc_replicas(current), calc_replicas(predicted), MIN_REPLICAS)
    print(f"current={current:.1f}, predicted={predicted:.1f} -> {target} replicas", file=sys.stderr)
    
    sys.stdout.write(json.dumps({"targetReplicas": target}))


if __name__ == "__main__":
    main()
