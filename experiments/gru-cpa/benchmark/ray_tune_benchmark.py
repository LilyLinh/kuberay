#!/usr/bin/env python3
"""Ray Tune benchmark for autoscaler testing."""

import os
import time
import ray
from ray import tune
from ray.tune.schedulers import ASHAScheduler
import numpy as np

NUM_SAMPLES = int(os.getenv("NUM_SAMPLES", "50"))
MAX_EPOCHS = int(os.getenv("MAX_EPOCHS", "10"))
CPUS_PER_TRIAL = float(os.getenv("CPUS_PER_TRIAL", "1"))
WORKLOAD = os.getenv("WORKLOAD_TYPE", "burst")


def train_fn(config):
    base_t = config.get("base_time", 5)
    for epoch in range(config.get("epochs", MAX_EPOCHS)):
        _ = np.random.randn(1000, 1000) @ np.random.randn(1000, 1000)
        loss = (config["lr"] - 0.01)**2 + (config["momentum"] - 0.9)**2 + np.random.randn()*0.01
        tune.report({"loss": loss, "accuracy": 1-loss, "epoch": epoch})
        time.sleep(base_t + np.random.uniform(-1, 1))


def search_space():
    return {
        "lr": tune.loguniform(1e-4, 1e-1),
        "momentum": tune.uniform(0.1, 0.99),
        "batch_size": tune.choice([16, 32, 64, 128]),
        "hidden_size": tune.choice([32, 64, 128, 256]),
        "epochs": MAX_EPOCHS,
        "base_time": tune.choice([3, 5, 7]),
    }


def run_burst():
    scheduler = ASHAScheduler(max_t=MAX_EPOCHS, grace_period=1, reduction_factor=2)
    tuner = tune.Tuner(
        tune.with_resources(train_fn, {"cpu": CPUS_PER_TRIAL}),
        tune_config=tune.TuneConfig(metric="loss", mode="min", scheduler=scheduler, num_samples=NUM_SAMPLES),
        param_space=search_space(),
    )
    return tuner.fit()


def run_gradual():
    results = []
    waves = [NUM_SAMPLES//4, NUM_SAMPLES//4, NUM_SAMPLES//2]
    for i, n in enumerate(waves):
        print(f"Wave {i+1}: {n} trials")
        tuner = tune.Tuner(
            tune.with_resources(train_fn, {"cpu": CPUS_PER_TRIAL}),
            tune_config=tune.TuneConfig(metric="loss", mode="min", num_samples=n),
            param_space=search_space(),
        )
        results.append(tuner.fit())
        time.sleep(10)
    return results


def run_steady():
    @ray.remote(num_cpus=CPUS_PER_TRIAL)
    def trial(i):
        cfg = {"lr": np.random.uniform(1e-4, 1e-1), "momentum": np.random.uniform(0.1, 0.99)}
        time.sleep(np.random.uniform(5, 15))
        return {"id": i, "loss": (cfg["lr"]-0.01)**2 + (cfg["momentum"]-0.9)**2}
    
    futures = []
    for i in range(NUM_SAMPLES):
        futures.append(trial.remote(i))
        time.sleep(2)
    return ray.get(futures)


def main():
    if not ray.is_initialized():
        ray.init()
    
    print(f"Workload: {WORKLOAD}, Samples: {NUM_SAMPLES}, CPUs/trial: {CPUS_PER_TRIAL}")
    print(f"Cluster: {ray.cluster_resources()}")
    
    t0 = time.time()
    if WORKLOAD == "burst":
        run_burst()
    elif WORKLOAD == "gradual":
        run_gradual()
    else:
        run_steady()
    
    print(f"Done in {time.time()-t0:.2f}s")


if __name__ == "__main__":
    main()
