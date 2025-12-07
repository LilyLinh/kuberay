# GRU-CPA: Proactive Autoscaler for KubeRay

Predictive autoscaling using GRU to optimize bursty ML workloads.

## Results (OpenShift)

| Config | Time | Speedup | Cost |
|--------|------|---------|------|
| baseline (1w) | 21.7s | 1.0x | 43 CPU-s |
| proactive (4w) | 7.4s | 2.9x | 59 CPU-s |
| proactive (6w) | 5.5s | 3.9x | 66 CPU-s |

## Quick Start

```bash
# login
oc login <cluster>

# run experiment
./scripts/run-openshift-experiment.sh

# or train model with real data
python scripts/collect-ray-metrics.py -n gru-cpa-experiment -d 30
python model/train_gru.py --saved
```

## Structure

```
benchmark/   - workload generator
cpa/         - custom pod autoscaler
manifests/   - k8s/openshift yamls  
model/       - GRU training/inference
scripts/     - automation
results/     - experiment outputs
```

## Train on Real Data

Option 1: Direct collection (recommended)
```bash
python scripts/collect-ray-metrics.py -n <namespace> -d 30
python model/train_gru.py --saved
```

Option 2: Prometheus (if configured)
```bash
python model/train_gru.py --prometheus --hours 24
```

## References

- [KubeRay](https://ray-project.github.io/kuberay/)
- [CPA](https://github.com/jthomperoo/custom-pod-autoscaler)
