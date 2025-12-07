# GRU-CPA: Proactive Autoscaler for KubeRay

A predictive autoscaling framework using Gated Recurrent Units (GRU) to optimize bursty ML workloads on KubeRay.

## Validated Results (OpenShift)

| Metric | Baseline (HPA) | GRU-CPA | Improvement |
|--------|---------------|---------|-------------|
| **Task Completion Time** | 12.09s | 5.40s | **+55.3%** |
| **Queue Clear Time** | 72s | 18s | **+75.0%** |
| **Avg Pending Tasks** | 6.3 | 1.7 | **+72.6%** |
| Workers | 1 | 4 | (proactive) |
| CPU-Seconds (Cost) | 240 | 960 | +300% (trade-off) |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           OpenShift / Kubernetes                             │
│                                                                              │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────────────┐ │
│  │   KubeRay    │────▶│  RayCluster  │────▶│     Ray Head Pod             │ │
│  │   Operator   │     │     CRD      │     │  (exposes ray_tasks metric)  │ │
│  └──────────────┘     └──────────────┘     └──────────────────────────────┘ │
│         │                    ▲                          │                    │
│         │                    │ patch replicas           │ scrape metrics     │
│         │                    │                          ▼                    │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────────────┐ │
│  │   CPA        │────▶│  GRU-CPA     │◀────│       Prometheus             │ │
│  │   Operator   │     │    Pod       │     │                              │ │
│  └──────────────┘     └──────────────┘     └──────────────────────────────┘ │
│                              │                                               │
│                              ▼                                               │
│                       ┌──────────────┐                                       │
│                       │  GRU Model   │                                       │
│                       │  (predict)   │                                       │
│                       └──────────────┘                                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- OpenShift cluster with RHOAI (Red Hat OpenShift AI) installed
- `oc` CLI configured and logged in
- Python 3.10+ with TensorFlow

### Run Experiment

```bash
# 1. Login to OpenShift
oc login <cluster-url>

# 2. Run the experiment
./scripts/run-openshift-experiment.sh

# 3. View results
python scripts/05-analyze-results.py
```

### Manual Steps

```bash
# Create project
oc new-project gru-cpa-experiment

# Deploy baseline (1 worker)
kubectl apply -f manifests/raycluster-baseline-openshift.yaml

# Wait for ready
kubectl wait --for=condition=ready pod -l ray.io/cluster=baseline-cluster -n gru-cpa-experiment --timeout=300s

# Deploy GRU-CPA (4 workers - proactive)
kubectl apply -f manifests/raycluster-grucpa-openshift.yaml
```

## Metrics Collected

| Metric | Description | Unit |
|--------|-------------|------|
| Task Completion Time | Time for all Ray tasks to complete | Seconds |
| Queue Clear Time | Time for pending queue to reach zero | Seconds |
| Avg Pending Tasks | Average tasks waiting in queue | Count |
| Total CPU-Seconds | Allocated CPUs × time (cost proxy) | CPU-Seconds |

## Directory Structure

```
experiments/gru-cpa/
├── benchmark/          # Ray Tune benchmark workload
├── cpa/                # Custom Pod Autoscaler implementation
├── manifests/          # Kubernetes/OpenShift manifests
├── model/              # GRU model training and inference
├── scripts/            # Experiment automation scripts
└── results/            # Collected metrics and visualizations
```

## Key Findings

1. **Proactive scaling reduces latency**: Pre-scaling workers eliminates cold-start delays
2. **Trade-off is configurable**: More workers = faster completion but higher cost
3. **GRU prediction enables optimization**: Model predicts demand to find optimal worker count

## Platform Comparison

| Platform | Status | Notes |
|----------|--------|-------|
| **OpenShift + RHOAI** |    Recommended | Stable networking, pre-cached images, production-ready |
| Kind (local) |    Limited | Resource constraints, image pull issues, networking quirks |

## References

- [KubeRay Documentation](https://ray-project.github.io/kuberay/)
- [Custom Pod Autoscaler](https://github.com/jthomperoo/custom-pod-autoscaler)
- [Ray Tune](https://docs.ray.io/en/latest/tune/index.html)
