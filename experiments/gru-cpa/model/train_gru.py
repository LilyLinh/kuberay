#!/usr/bin/env python3
"""GRU model training for KubeRay task prediction."""

import os
import json
import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers
from datetime import datetime, timedelta
from typing import Tuple, Optional
import subprocess
import requests
from urllib.parse import urlencode

# Config
SEQ_LEN = 60
PRED_HORIZON = 30
HIDDEN = 64
EPOCHS = 100
BATCH = 32

MODEL_PATH = os.path.join(os.path.dirname(__file__), "gru_model.h5")
SCALER_PATH = os.path.join(os.path.dirname(__file__), "scaler_params.json")
DATA_PATH = os.path.join(os.path.dirname(__file__), "training_data.json")


def get_oc_token():
    r = subprocess.run(["oc", "whoami", "-t"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("oc login required")
    return r.stdout.strip()


def get_prom_url():
    for route in ["prometheus-k8s", "thanos-querier"]:
        r = subprocess.run(
            ["oc", "get", "route", "-n", "openshift-monitoring", route, "-o", "jsonpath={.spec.host}"],
            capture_output=True, text=True
        )
        if r.returncode == 0 and r.stdout.strip():
            return f"https://{r.stdout.strip()}"
    raise RuntimeError("No prometheus route found")


def query_prom(query, start, end, step="1m", url=None, token=None):
    url = url or get_prom_url()
    token = token or get_oc_token()
    
    params = {"query": query, "start": start.isoformat()+"Z", "end": end.isoformat()+"Z", "step": step}
    resp = requests.get(f"{url}/api/v1/query_range?{urlencode(params)}",
                        headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=60)
    
    data = resp.json()
    if data["status"] != "success":
        return np.array([])
    
    vals = []
    for r in data.get("data", {}).get("result", []):
        for _, v in r.get("values", []):
            vals.append(float(v))
    return np.array(vals, dtype=np.float32)


def load_prom_data(hours=24, ns=None):
    end = datetime.utcnow()
    start = end - timedelta(hours=hours)
    
    # try ray_scheduler_tasks first, then fallbacks
    queries = [
        f'sum(ray_scheduler_tasks{{State="PENDING"{f", namespace={ns}" if ns else ""}}})',
        'sum(ray_resources{Name="CPU",State="USED"})',
        'avg(ray_node_cpu_utilization)'
    ]
    
    for q in queries:
        data = query_prom(q, start, end)
        if len(data) > 0:
            return data
    return np.array([])


def load_saved():
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH) as f:
            d = json.load(f)
        return np.array(d['data'], dtype=np.float32)
    return None


def gen_burst(base=5, height=100):
    d = []
    d.extend(np.random.poisson(base, np.random.randint(50,100)))
    
    ramp = np.random.randint(10,30)
    d.extend(np.linspace(base, height, ramp).astype(int).clip(0))
    d.extend(np.random.poisson(height, np.random.randint(30,100)))
    d.extend(np.linspace(height, base*2, np.random.randint(20,50)).astype(int).clip(0))
    d.extend(np.random.poisson(base*2, np.random.randint(30,70)))
    return np.array(d, dtype=np.float32)


def gen_multi_burst(n=3):
    d = np.random.poisson(5, 500).astype(np.float32)
    for _ in range(n):
        s = np.random.randint(0, 400)
        h = np.random.randint(30, 150)
        l = np.random.randint(50, 100)
        d[s:s+l] += np.random.poisson(h, l)
    return d


def gen_periodic(period=100, amp=50):
    t = np.arange(500)
    return (amp*(1+np.sin(2*np.pi*t/period))/2 + np.random.poisson(10,500)).astype(np.float32)


def gen_spiky(n=5):
    d = np.random.poisson(5, 300).astype(np.float32)
    for _ in range(n):
        p = np.random.randint(10,290)
        d[p:p+np.random.randint(3,10)] += np.random.randint(50,200)
    return d


def gen_synthetic(n=10000):
    np.random.seed(42)
    d = []
    for i in range(n//400):
        t = i % 4
        if t == 0: d.extend(gen_burst(height=np.random.randint(50,200)))
        elif t == 1: d.extend(gen_multi_burst(np.random.randint(2,5)))
        elif t == 2: d.extend(gen_periodic(np.random.randint(50,150), np.random.randint(30,100)))
        else: d.extend(gen_spiky(np.random.randint(3,8)))
    return np.array(d, dtype=np.float32)


def validate(data):
    stats = {
        "count": len(data), "mean": float(np.mean(data)), "std": float(np.std(data)),
        "min": float(np.min(data)), "max": float(np.max(data))
    }
    
    ok = True
    if np.isnan(data).sum() > 0 or np.isinf(data).sum() > 0:
        ok = False
    if len(data) < SEQ_LEN + PRED_HORIZON + 1000:
        ok = False
    
    return {"valid": ok, "stats": stats}


def make_sequences(data, seq_len, horizon):
    X, y = [], []
    for i in range(len(data) - seq_len - horizon):
        X.append(data[i:i+seq_len])
        y.append(data[i+seq_len+horizon-1])
    return np.array(X), np.array(y)


def build_model(shape):
    m = keras.Sequential([
        layers.Input(shape=shape),
        layers.GRU(HIDDEN, return_sequences=True),
        layers.Dropout(0.2),
        layers.GRU(HIDDEN//2),
        layers.Dropout(0.2),
        layers.Dense(32, activation='relu'),
        layers.Dense(1)
    ])
    m.compile(optimizer='adam', loss='mse', metrics=['mae'])
    return m


def train(use_prom=False, hours=24, ns=None, use_saved=False):
    print("=" * 50)
    print("GRU Training")
    print("=" * 50)
    
    data = None
    if use_saved:
        data = load_saved()
    if use_prom and data is None:
        data = load_prom_data(hours, ns)
    
    # fallback to synthetic
    if data is None or len(data) < 1000:
        synth = gen_synthetic()
        if data is not None and len(data) > 0:
            data = np.concatenate([synth, data])
        else:
            data = synth
    
    print(f"Data points: {len(data)}")
    
    check = validate(data)
    if not check["valid"]:
        print("Data validation failed")
        return None
    
    # normalize
    mu, sig = data.mean(), data.std()
    norm = (data - mu) / sig
    with open(SCALER_PATH, 'w') as f:
        json.dump({"mean": float(mu), "std": float(sig)}, f)
    
    X, y = make_sequences(norm, SEQ_LEN, PRED_HORIZON)
    X = X.reshape((X.shape[0], X.shape[1], 1))
    
    split = int(len(X) * 0.8)
    X_tr, X_val = X[:split], X[split:]
    y_tr, y_val = y[:split], y[split:]
    
    print(f"Train: {len(X_tr)}, Val: {len(X_val)}")
    
    model = build_model((SEQ_LEN, 1))
    model.summary()
    
    cbs = [
        keras.callbacks.EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True),
        keras.callbacks.ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=5)
    ]
    
    model.fit(X_tr, y_tr, epochs=EPOCHS, batch_size=BATCH, validation_data=(X_val, y_val), callbacks=cbs)
    
    loss, mae = model.evaluate(X_val, y_val, verbose=0)
    print(f"Val MSE: {loss:.4f}, MAE: {mae:.4f}")
    
    model.save(MODEL_PATH)
    print(f"Saved to {MODEL_PATH}")
    
    return model


def load_model():
    return keras.models.load_model(MODEL_PATH)


def predict(model, seq, scaler):
    norm = (seq - scaler["mean"]) / scaler["std"]
    X = norm.reshape((1, len(norm), 1))
    pred = model.predict(X, verbose=0)[0][0]
    return pred * scaler["std"] + scaler["mean"]


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--prometheus", "-p", action="store_true")
    p.add_argument("--saved", "-s", action="store_true")
    p.add_argument("--hours", "-H", type=int, default=24)
    p.add_argument("--namespace", "-n", type=str, default=None)
    args = p.parse_args()
    
    train(use_prom=args.prometheus, hours=args.hours, ns=args.namespace, use_saved=args.saved)
