#!/usr/bin/env python3
"""
GRU Model Training for KubeRay Task Prediction

This script trains a Gated Recurrent Unit (GRU) model to predict
future task demand (ray_tasks metric) for proactive autoscaling.

Based on research showing GRU achieves:
- MSE: 0.00194 (better than LSTM: 0.00195, ARIMA: 0.00197)
- Training time: 0.75s (faster than LSTM: 1.44s)
"""

import os
import json
import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers
from datetime import datetime

# Configuration
SEQUENCE_LENGTH = 60       # 60 data points (e.g., 60 seconds of history)
PREDICTION_HORIZON = 30    # Predict 30 steps ahead
HIDDEN_UNITS = 64
EPOCHS = 100
BATCH_SIZE = 32
VALIDATION_SPLIT = 0.2

MODEL_PATH = os.path.join(os.path.dirname(__file__), "gru_model.h5")
SCALER_PATH = os.path.join(os.path.dirname(__file__), "scaler_params.json")


def generate_synthetic_training_data(num_samples: int = 10000):
    """
    Generate synthetic training data simulating bursty Ray workloads.
    
    In production, this would be replaced with historical Prometheus data
    from actual ray_tasks{State="PENDING_ARGS_AVAIL"} metric.
    """
    np.random.seed(42)
    
    # Generate multiple burst patterns
    data = []
    
    for _ in range(num_samples // 500):
        # Baseline period (low demand)
        baseline = np.random.poisson(5, 100)
        data.extend(baseline)
        
        # Burst ramp-up (sudden spike)
        burst_height = np.random.randint(50, 200)
        ramp_up = np.linspace(5, burst_height, 20) + np.random.randn(20) * 5
        data.extend(ramp_up.astype(int).clip(0))
        
        # Burst peak (sustained high demand)
        peak_duration = np.random.randint(50, 150)
        peak = np.random.poisson(burst_height, peak_duration)
        data.extend(peak)
        
        # Burst ramp-down (gradual decrease)
        ramp_down = np.linspace(burst_height, 10, 30) + np.random.randn(30) * 5
        data.extend(ramp_down.astype(int).clip(0))
        
        # Recovery period
        recovery = np.random.poisson(10, 50)
        data.extend(recovery)
    
    return np.array(data, dtype=np.float32)


def create_sequences(data: np.ndarray, seq_length: int, pred_horizon: int):
    """
    Create input sequences (X) and prediction targets (y).
    
    X: Historical sequence of length seq_length
    y: Future value at pred_horizon steps ahead
    """
    X, y = [], []
    
    for i in range(len(data) - seq_length - pred_horizon):
        X.append(data[i:i + seq_length])
        y.append(data[i + seq_length + pred_horizon - 1])
    
    return np.array(X), np.array(y)


def build_gru_model(input_shape: tuple) -> keras.Model:
    """
    Build the GRU model architecture.
    
    Architecture:
    - Input Layer
    - GRU Layer (captures temporal dependencies)
    - Dense Layer (prediction output)
    """
    model = keras.Sequential([
        layers.Input(shape=input_shape),
        layers.GRU(HIDDEN_UNITS, return_sequences=True),
        layers.Dropout(0.2),
        layers.GRU(HIDDEN_UNITS // 2),
        layers.Dropout(0.2),
        layers.Dense(32, activation='relu'),
        layers.Dense(1)
    ])
    
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=0.001),
        loss='mse',
        metrics=['mae']
    )
    
    return model


def train_model():
    """Train the GRU model and save it."""
    print("=" * 60)
    print("GRU Model Training for KubeRay Task Prediction")
    print("=" * 60)
    
    # Generate training data
    print("\n1. Generating synthetic training data...")
    raw_data = generate_synthetic_training_data()
    print(f"   Generated {len(raw_data)} data points")
    
    # Normalize data
    print("\n2. Normalizing data...")
    data_mean = raw_data.mean()
    data_std = raw_data.std()
    normalized_data = (raw_data - data_mean) / data_std
    print(f"   Mean: {data_mean:.2f}, Std: {data_std:.2f}")
    
    # Save scaler parameters
    scaler_params = {"mean": float(data_mean), "std": float(data_std)}
    with open(SCALER_PATH, 'w') as f:
        json.dump(scaler_params, f)
    print(f"   Saved scaler parameters to {SCALER_PATH}")
    
    # Create sequences
    print("\n3. Creating training sequences...")
    X, y = create_sequences(normalized_data, SEQUENCE_LENGTH, PREDICTION_HORIZON)
    print(f"   X shape: {X.shape}, y shape: {y.shape}")
    
    # Reshape for GRU (samples, timesteps, features)
    X = X.reshape((X.shape[0], X.shape[1], 1))
    
    # Split data
    split_idx = int(len(X) * (1 - VALIDATION_SPLIT))
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]
    print(f"   Training samples: {len(X_train)}, Validation samples: {len(X_val)}")
    
    # Build model
    print("\n4. Building GRU model...")
    model = build_gru_model(input_shape=(SEQUENCE_LENGTH, 1))
    model.summary()
    
    # Train model
    print("\n5. Training model...")
    callbacks = [
        keras.callbacks.EarlyStopping(
            monitor='val_loss',
            patience=10,
            restore_best_weights=True
        ),
        keras.callbacks.ReduceLROnPlateau(
            monitor='val_loss',
            factor=0.5,
            patience=5
        )
    ]
    
    start_time = datetime.now()
    history = model.fit(
        X_train, y_train,
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        validation_data=(X_val, y_val),
        callbacks=callbacks,
        verbose=1
    )
    training_time = (datetime.now() - start_time).total_seconds()
    
    # Evaluate model
    print("\n6. Evaluating model...")
    val_loss, val_mae = model.evaluate(X_val, y_val, verbose=0)
    print(f"   Validation MSE: {val_loss:.6f}")
    print(f"   Validation MAE: {val_mae:.6f}")
    print(f"   Training Time: {training_time:.2f}s")
    
    # Save model
    print(f"\n7. Saving model to {MODEL_PATH}...")
    model.save(MODEL_PATH)
    
    print("\n" + "=" * 60)
    print("Training Complete!")
    print("=" * 60)
    
    return model, history


def load_model() -> keras.Model:
    """Load the pre-trained GRU model."""
    return keras.models.load_model(MODEL_PATH)


def predict(model: keras.Model, sequence: np.ndarray, scaler_params: dict) -> float:
    """
    Make a prediction using the trained model.
    
    Args:
        model: Trained GRU model
        sequence: Historical sequence of task counts
        scaler_params: Normalization parameters
    
    Returns:
        Predicted task count (denormalized)
    """
    # Normalize input
    normalized = (sequence - scaler_params["mean"]) / scaler_params["std"]
    
    # Reshape for model
    X = normalized.reshape((1, len(normalized), 1))
    
    # Predict
    prediction = model.predict(X, verbose=0)[0][0]
    
    # Denormalize
    return prediction * scaler_params["std"] + scaler_params["mean"]


if __name__ == "__main__":
    train_model()

