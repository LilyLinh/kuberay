# GRU-CPA: Proactive Autoscaler for KubeRay

Predictive autoscaling using GRU to optimize bursty ML workloads.

## Results (200 tasks, OpenShift)

| Config | Workers | Time | Speedup | Efficiency |
|--------|---------|------|---------|------------|
| reactive-1w | 1 | 104.0s | 1.0x | 100% |
| reactive-4w | 4 | 28.6s | 3.6x | 91% |
| reactive-4w-hpa | 1→4 | 104.0s | 1.0x | - |
| proactive-4w | 4 | 28.6s | 3.6x | 91% |
| proactive-6w | 6 | 19.9s | 5.2x | 87% |

**Key finding**: Proactive-4w is **72.5% faster** than Reactive-HPA because HPA can't scale fast enough.

## Dataset

10,000 samples collected from Ray cluster via Prometheus metrics:
- `ray_scheduler_tasks` - pending/running task counts
- `ray_node_cpu_utilization` - node CPU usage

## Quick Start

```bash
oc login <cluster>
./scripts/run-comprehensive-experiment.sh
python model/train_gru.py
```

## Structure

```
benchmark/   - workload generator
cpa/         - custom pod autoscaler
manifests/   - k8s/openshift yamls  
model/       - GRU training (dataset + model)
scripts/     - automation
results/     - experiment outputs
docs/        - detailed results
```
