#!/usr/bin/env python3
"""GRU model with attention for KubeRay task prediction."""

import os
import json
import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers
from sklearn.metrics import precision_recall_fscore_support

# Custom Attention layer (will be registered for serialization)
class Attention(layers.Layer):
    """Simple attention to focus on important timesteps."""
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

SEQ_LEN = 30
PRED_HORIZON = 2
HIDDEN = 128
EPOCHS = 100
BATCH = 64

MODEL_PATH = os.path.join(os.path.dirname(__file__), "gru_model.keras")
SCALER_PATH = os.path.join(os.path.dirname(__file__), "scaler_params.json")
DATASET_PATH = os.path.join(os.path.dirname(__file__), "dataset_20k.json")
METRICS_PATH = os.path.join(os.path.dirname(__file__), "evaluation_metrics.json")


def load_dataset():
    with open(DATASET_PATH) as f:
        d = json.load(f)
    print(f"Dataset: {d['metadata']['samples']} samples")
    return np.array(d['data'], dtype=np.float32)


def make_sequences(data):
    X, y = [], []
    for i in range(len(data) - SEQ_LEN - PRED_HORIZON):
        X.append(data[i:i+SEQ_LEN])
        y.append(data[i+SEQ_LEN+PRED_HORIZON-1])
    return np.array(X).reshape((-1, SEQ_LEN, 1)), np.array(y)


def build_model():
    inp = layers.Input(shape=(SEQ_LEN, 1))

    x = layers.GRU(HIDDEN, return_sequences=True)(inp)
    x = layers.BatchNormalization()(x)
    x = layers.Dropout(0.2)(x)

    x = layers.GRU(HIDDEN//2, return_sequences=True)(x)
    x = layers.BatchNormalization()(x)
    x = layers.Dropout(0.2)(x)

    # Attention layer to focus on important timesteps
    x = Attention()(x)

    x = layers.Dense(64, activation='relu')(x)
    x = layers.Dropout(0.1)(x)
    x = layers.Dense(32, activation='relu')(x)
    out = layers.Dense(1)(x)

    model = keras.Model(inp, out)
    model.compile(optimizer=keras.optimizers.Adam(0.001), loss='huber', metrics=['mae'])
    return model


def compute_metrics(y_true, y_pred, scaler):
    y_true_raw = y_true * scaler['std'] + scaler['mean']
    y_pred_raw = y_pred * scaler['std'] + scaler['mean']

    # Regression
    mse = np.mean((y_true - y_pred) ** 2)
    rmse = np.sqrt(mse)
    mae = np.mean(np.abs(y_true - y_pred))
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    # SMAPE - exclude near-zero values for fair measurement
    mask = np.abs(y_true_raw) > 5  # Only consider values > 5 tasks
    if mask.sum() > 0:
        denom = (np.abs(y_true_raw[mask]) + np.abs(y_pred_raw[mask])) / 2 + 1e-8
        smape = np.mean(np.abs(y_true_raw[mask] - y_pred_raw[mask]) / denom) * 100
    else:
        smape = 0

    # Directional
    true_dir = np.sign(np.diff(y_true))
    pred_dir = np.sign(np.diff(y_pred))
    dir_acc = np.mean(true_dir == pred_dir) * 100

    # Scaling decisions
    thresh = np.percentile(np.abs(np.diff(y_true_raw)), 30)
    def classify(arr):
        c = np.zeros(len(arr), dtype=int)
        c[arr > thresh] = 1
        c[arr < -thresh] = -1
        return c

    true_cls = classify(np.diff(y_true_raw))
    pred_cls = classify(np.diff(y_pred_raw))

    prec, rec, f1, _ = precision_recall_fscore_support(true_cls, pred_cls, average='weighted', zero_division=0)
    _, _, f1_per, _ = precision_recall_fscore_support(true_cls, pred_cls, labels=[-1, 0, 1], average=None, zero_division=0)

    # Peak detection
    p75 = np.percentile(y_true_raw, 75)
    true_peak = y_true_raw > p75
    pred_peak = y_pred_raw > p75
    tp = np.sum(true_peak & pred_peak)
    peak_prec = tp / (pred_peak.sum() + 1e-8)
    peak_rec = tp / (true_peak.sum() + 1e-8)
    peak_f1 = 2 * peak_prec * peak_rec / (peak_prec + peak_rec + 1e-8)

    # Tolerance - multiple thresholds
    within_5 = np.mean(np.abs(y_true_raw - y_pred_raw) <= 5) * 100
    within_10 = np.mean(np.abs(y_true_raw - y_pred_raw) <= 10) * 100
    rel_tol = np.abs(y_true_raw) * 0.2 + 2  # 20% + 2 buffer
    within_20pct = np.mean(np.abs(y_true_raw - y_pred_raw) <= rel_tol) * 100

    return {
        "regression": {"mse": float(mse), "rmse": float(rmse), "mae": float(mae), "r2": float(r2), "smape": float(smape)},
        "directional": {"accuracy": float(dir_acc)},
        "scaling_decisions": {"precision": float(prec), "recall": float(rec), "f1_weighted": float(f1),
                              "f1_scale_down": float(f1_per[0]), "f1_hold": float(f1_per[1]), "f1_scale_up": float(f1_per[2])},
        "peak_detection": {"precision": float(peak_prec), "recall": float(peak_rec), "f1": float(peak_f1)},
        "tolerance": {"within_5_tasks": float(within_5), "within_10_tasks": float(within_10), "within_20pct": float(within_20pct)}
    }


def train():
    np.random.seed(42)
    tf.random.set_seed(42)

    data = load_dataset()
    mu, sig = data.mean(), data.std()
    norm = (data - mu) / sig
    scaler = {'mean': float(mu), 'std': float(sig)}

    with open(SCALER_PATH, 'w') as f:
        json.dump(scaler, f)

    X, y = make_sequences(norm)
    idx = np.random.permutation(len(X))
    X, y = X[idx], y[idx]

    split = int(len(X) * 0.85)
    X_tr, X_val = X[:split], X[split:]
    y_tr, y_val = y[:split], y[split:]
    print(f"Train: {len(X_tr)}, Val: {len(X_val)}")

    model = build_model()

    cbs = [
        keras.callbacks.EarlyStopping(monitor='val_loss', patience=15, restore_best_weights=True),
        keras.callbacks.ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=6, min_lr=1e-6)
    ]

    model.fit(X_tr, y_tr, epochs=EPOCHS, batch_size=BATCH,
              validation_data=(X_val, y_val), callbacks=cbs, verbose=2)

    y_pred = model.predict(X_val, verbose=0).flatten()
    metrics = compute_metrics(y_val, y_pred, scaler)

    print("\n" + "="*60)
    print("EVALUATION RESULTS")
    print("="*60)

    print("\n Regression:")
    print(f"   R² Score:     {metrics['regression']['r2']:.4f}")
    print(f"   MAE:          {metrics['regression']['mae']:.4f}")
    print(f"   SMAPE:        {metrics['regression']['smape']:.1f}%")

    print("\n Scaling Decisions:")
    print(f"   Precision:    {metrics['scaling_decisions']['precision']:.4f}")
    print(f"   Recall:       {metrics['scaling_decisions']['recall']:.4f}")
    print(f"   F1 Score:     {metrics['scaling_decisions']['f1_weighted']:.4f}")

    print("\n Peak Detection:")
    print(f"   Precision:    {metrics['peak_detection']['precision']:.4f}")
    print(f"   Recall:       {metrics['peak_detection']['recall']:.4f}")
    print(f"   F1 Score:     {metrics['peak_detection']['f1']:.4f}")

    print("\n Directional:")
    print(f"   Accuracy:     {metrics['directional']['accuracy']:.1f}%")

    print("\n Tolerance:")
    print(f"   Within 5:     {metrics['tolerance']['within_5_tasks']:.1f}%")
    print(f"   Within 10:    {metrics['tolerance']['within_10_tasks']:.1f}%")
    print(f"   Within 20%:   {metrics['tolerance']['within_20pct']:.1f}%")

    print("="*60)

    with open(METRICS_PATH, 'w') as f:
        json.dump(metrics, f, indent=2)

    model.save(MODEL_PATH)
    print(f"\nModel saved: {MODEL_PATH}")

    return model, metrics


if __name__ == "__main__":
    train()
