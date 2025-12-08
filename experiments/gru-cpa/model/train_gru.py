#!/usr/bin/env python3
"""GRU model training for KubeRay task prediction."""

import os
import json
import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

# Config
SEQ_LEN = 60
PRED_HORIZON = 30
HIDDEN = 64
EPOCHS = 100
BATCH = 32

MODEL_PATH = os.path.join(os.path.dirname(__file__), "gru_model.h5")
SCALER_PATH = os.path.join(os.path.dirname(__file__), "scaler_params.json")
DATASET_PATH = os.path.join(os.path.dirname(__file__), "dataset_10k.json")


def load_dataset():
    """Load the dataset collected from Prometheus."""
    if not os.path.exists(DATASET_PATH):
        raise FileNotFoundError(f"Dataset not found: {DATASET_PATH}")
    
    with open(DATASET_PATH) as f:
        d = json.load(f)
    
    data = np.array(d['data'], dtype=np.float32)
    meta = d.get('metadata', {})
    
    print(f"Loaded {len(data)} samples")
    print(f"  Source: {meta.get('source', 'prometheus')}")
    print(f"  Cluster: {meta.get('cluster', 'OpenShift')}")
    
    return data


def validate(data):
    """Basic data validation."""
    ok = True
    if np.isnan(data).any() or np.isinf(data).any():
        print("ERROR: NaN or Inf in data")
        ok = False
    if len(data) < SEQ_LEN + PRED_HORIZON + 1000:
        print(f"ERROR: Need at least {SEQ_LEN + PRED_HORIZON + 1000} samples")
        ok = False
    if np.std(data) < 1:
        print("WARNING: Low variability")
    return ok


def make_sequences(data):
    """Create training sequences."""
    X, y = [], []
    for i in range(len(data) - SEQ_LEN - PRED_HORIZON):
        X.append(data[i:i+SEQ_LEN])
        y.append(data[i+SEQ_LEN+PRED_HORIZON-1])
    return np.array(X).reshape((-1, SEQ_LEN, 1)), np.array(y)


def build_model():
    """Build GRU model."""
    m = keras.Sequential([
        layers.Input(shape=(SEQ_LEN, 1)),
        layers.GRU(HIDDEN, return_sequences=True),
        layers.Dropout(0.2),
        layers.GRU(HIDDEN//2),
        layers.Dropout(0.2),
        layers.Dense(32, activation='relu'),
        layers.Dense(1)
    ])
    m.compile(optimizer='adam', loss='mse', metrics=['mae'])
    return m


def train():
    """Train the GRU model."""
    print("=" * 50)
    print("GRU Training")
    print("=" * 50)
    
    # Load data
    data = load_dataset()
    
    if not validate(data):
        return None
    
    # Normalize
    mu, sig = data.mean(), data.std()
    norm = (data - mu) / sig
    print(f"Normalized: mean={mu:.2f}, std={sig:.2f}")
    
    with open(SCALER_PATH, 'w') as f:
        json.dump({'mean': float(mu), 'std': float(sig)}, f)
    
    # Create sequences
    X, y = make_sequences(norm)
    print(f"Sequences: {X.shape[0]}")
    
    # Split
    split = int(len(X) * 0.8)
    X_tr, X_val = X[:split], X[split:]
    y_tr, y_val = y[:split], y[split:]
    print(f"Train: {len(X_tr)}, Val: {len(X_val)}")
    
    # Build and train
    model = build_model()
    model.summary()
    
    cbs = [
        keras.callbacks.EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True),
        keras.callbacks.ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=5)
    ]
    
    model.fit(X_tr, y_tr, epochs=EPOCHS, batch_size=BATCH,
              validation_data=(X_val, y_val), callbacks=cbs)
    
    loss, mae = model.evaluate(X_val, y_val, verbose=0)
    print(f"\nVal MSE: {loss:.4f}, MAE: {mae:.4f}")
    
    model.save(MODEL_PATH)
    print(f"Saved to {MODEL_PATH}")
    
    return model


def load_model():
    """Load trained model."""
    return keras.models.load_model(MODEL_PATH)


def predict(model, seq):
    """Make prediction."""
    with open(SCALER_PATH) as f:
        s = json.load(f)
    
    norm = (seq - s["mean"]) / s["std"]
    X = norm.reshape((1, len(norm), 1))
    pred = model.predict(X, verbose=0)[0][0]
    return pred * s["std"] + s["mean"]


if __name__ == "__main__":
    train()
