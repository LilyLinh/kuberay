#!/usr/bin/env python3
"""
Ray Tune Benchmark Workload for GRU-CPA Experiments

This script generates a bursty ML workload using Ray Tune hyperparameter tuning.
It creates sudden spikes in logical resource demand (pending tasks) to test
the responsiveness of different autoscaling strategies.

Based on: https://docs.ray.io/en/latest/tune/getting-started.html
"""

import os
import time
import ray
from ray import tune
from ray.tune.schedulers import ASHAScheduler
import numpy as np

# Configuration from environment variables
NUM_SAMPLES = int(os.getenv("NUM_SAMPLES", "50"))
MAX_EPOCHS = int(os.getenv("MAX_EPOCHS", "10"))
CPUS_PER_TRIAL = float(os.getenv("CPUS_PER_TRIAL", "1"))
WORKLOAD_TYPE = os.getenv("WORKLOAD_TYPE", "burst")  # burst, gradual, steady


def training_function(config: dict):
    """
    Simulated training function for hyperparameter tuning.
    Each trial represents a single hyperparameter configuration.
    """
    # Simulate model training with configurable duration
    base_time = config.get("base_training_time", 5)
    variance = config.get("time_variance", 2)
    
    for epoch in range(config.get("epochs", MAX_EPOCHS)):
        # Simulate training step with some compute
        _ = np.random.randn(1000, 1000) @ np.random.randn(1000, 1000)
        
        # Simulated loss that depends on hyperparameters
        loss = (
            (config["lr"] - 0.01) ** 2 +
            (config["momentum"] - 0.9) ** 2 +
            np.random.randn() * 0.01
        )
        accuracy = 1.0 - loss
        
        # Report metrics to Ray Tune
        tune.report({"loss": loss, "accuracy": accuracy, "epoch": epoch})
        
        # Simulate epoch duration
        time.sleep(base_time + np.random.uniform(-variance, variance))


def create_search_space():
    """Define the hyperparameter search space."""
    return {
        "lr": tune.loguniform(1e-4, 1e-1),
        "momentum": tune.uniform(0.1, 0.99),
        "batch_size": tune.choice([16, 32, 64, 128]),
        "hidden_size": tune.choice([32, 64, 128, 256]),
        "epochs": MAX_EPOCHS,
        "base_training_time": tune.choice([3, 5, 7]),
        "time_variance": 1,
    }


def run_burst_workload():
    """
    Run a bursty workload that creates sudden demand spikes.
    This simulates real-world ML tuning jobs.
    """
    print(f"Starting BURST workload: {NUM_SAMPLES} trials, {CPUS_PER_TRIAL} CPUs each")
    
    scheduler = ASHAScheduler(
        max_t=MAX_EPOCHS,
        grace_period=1,
        reduction_factor=2,
    )
    
    tuner = tune.Tuner(
        tune.with_resources(
            training_function,
            resources={"cpu": CPUS_PER_TRIAL}
        ),
        tune_config=tune.TuneConfig(
            metric="loss",
            mode="min",
            scheduler=scheduler,
            num_samples=NUM_SAMPLES,
        ),
        param_space=create_search_space(),
    )
    
    results = tuner.fit()
    
    best_result = results.get_best_result(metric="loss", mode="min")
    print(f"Best trial config: {best_result.config}")
    print(f"Best trial final loss: {best_result.metrics['loss']}")
    
    return results


def run_gradual_workload():
    """
    Run a gradual workload that slowly increases demand.
    """
    print(f"Starting GRADUAL workload: {NUM_SAMPLES} trials in waves")
    
    all_results = []
    wave_sizes = [NUM_SAMPLES // 4, NUM_SAMPLES // 4, NUM_SAMPLES // 2]
    
    for i, wave_size in enumerate(wave_sizes):
        print(f"Wave {i+1}: {wave_size} trials")
        
        tuner = tune.Tuner(
            tune.with_resources(
                training_function,
                resources={"cpu": CPUS_PER_TRIAL}
            ),
            tune_config=tune.TuneConfig(
                metric="loss",
                mode="min",
                num_samples=wave_size,
            ),
            param_space=create_search_space(),
        )
        
        results = tuner.fit()
        all_results.append(results)
        
        # Brief pause between waves
        time.sleep(10)
    
    return all_results


def run_steady_workload():
    """
    Run a steady-state workload for comparison.
    """
    print(f"Starting STEADY workload: {NUM_SAMPLES} trials over time")
    
    # Submit trials one at a time with delays
    @ray.remote(num_cpus=CPUS_PER_TRIAL)
    def single_trial(trial_id: int):
        config = {
            "lr": np.random.uniform(1e-4, 1e-1),
            "momentum": np.random.uniform(0.1, 0.99),
        }
        # Simulate training
        time.sleep(np.random.uniform(5, 15))
        loss = (config["lr"] - 0.01) ** 2 + (config["momentum"] - 0.9) ** 2
        return {"trial_id": trial_id, "loss": loss, "config": config}
    
    futures = []
    for i in range(NUM_SAMPLES):
        futures.append(single_trial.remote(i))
        time.sleep(2)  # Stagger submissions
    
    results = ray.get(futures)
    best = min(results, key=lambda x: x["loss"])
    print(f"Best trial: {best}")
    
    return results


def main():
    """Main entry point for the benchmark."""
    # Initialize Ray (connects to existing cluster)
    if not ray.is_initialized():
        ray.init()
    
    print("=" * 60)
    print("GRU-CPA Benchmark Workload")
    print("=" * 60)
    print(f"Workload Type: {WORKLOAD_TYPE}")
    print(f"Number of Samples: {NUM_SAMPLES}")
    print(f"Max Epochs: {MAX_EPOCHS}")
    print(f"CPUs per Trial: {CPUS_PER_TRIAL}")
    print(f"Cluster Resources: {ray.cluster_resources()}")
    print("=" * 60)
    
    start_time = time.time()
    
    if WORKLOAD_TYPE == "burst":
        results = run_burst_workload()
    elif WORKLOAD_TYPE == "gradual":
        results = run_gradual_workload()
    elif WORKLOAD_TYPE == "steady":
        results = run_steady_workload()
    else:
        raise ValueError(f"Unknown workload type: {WORKLOAD_TYPE}")
    
    end_time = time.time()
    total_time = end_time - start_time
    
    print("=" * 60)
    print(f"Benchmark Complete!")
    print(f"Total Job Completion Time: {total_time:.2f} seconds")
    print("=" * 60)


if __name__ == "__main__":
    main()

