# GRU-CPA: Proactive Autoscaling Results

## Summary

Tested proactive vs reactive autoscaling on OpenShift (RHOAI) with 4 configs.

| Config | Workers | Time (s) | Speedup | CPU-s | Efficiency |
|--------|---------|----------|---------|-------|------------|
| reactive-1w | 1 | 21.71 | 1.00x | 43.4 | 100% |
| reactive-2w | 2 | 11.74 | 1.85x | 47.0 | 92.5% |
| proactive-4w | 4 | 7.40 | 2.94x | 59.2 | 73.5% |
| proactive-6w | 6 | 5.53 | 3.93x | 66.3 | 65.5% |

## Metrics

| Metric | Description |
|--------|-------------|
| Completion Time | Wall-clock for all tasks |
| Speedup | Baseline / config time |
| CPU-Seconds | CPUs * time (cost proxy) |
| Efficiency | Speedup / workers |

## Test Setup

- Platform: OpenShift 4.18 (ROSA)
- Ray: 2.35.0 (quay.io/modh/ray:2.35.0-py311-cu121)
- Workload: 20 tasks, 1 CPU each, ~2.5s duration

```python
@ray.remote(num_cpus=1)
def task(i):
    for _ in range(3):
        np.dot(np.random.randn(400,400), np.random.randn(400,400))
    time.sleep(2)
    return i
```

## Key Results

1. **proactive-6w**: 74.5% faster than baseline (3.93x speedup)
2. **Best trade-off**: 4 workers (2.94x speedup, 73.5% efficiency)
3. Diminishing returns above 4 workers for this workload size

## Recommendations

| Use Case | Config | Reason |
|----------|--------|--------|
| Latency-critical | 6w | Fastest (5.5s) |
| Balanced | 4w | Good speedup, moderate cost |
| Cost-sensitive | 2w | Decent speedup (1.85x), low cost |

## Reproduce

```bash
cd experiments/gru-cpa
./scripts/run-comprehensive-experiment.sh
```

Results in `results/comprehensive-YYYYMMDD-HHMMSS/`

---
*OpenShift experiments, December 2025*
