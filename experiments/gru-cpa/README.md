# GRU-CPA: Proactive Autoscaler for KubeRay

**ML-based proactive autoscaling for bursty Ray workloads on Kubernetes**

Gated Recurrent Unit (GRU) based Custom Pod Autoscaler (CPA) that predicts Ray task demand to eliminate cold-start penalties and optimize resource allocation.

---

## Results (Production OpenShift RHOAI)

**Average Performance**: 20.0% faster than reactive autoscaling
**Platform**: Red Hat OpenShift Service on AWS (ROSA) v4.18

| Scenario | Tasks | HPA/Baseline | GRU-CPA | Improvement |
|----------|-------|--------------|---------|-------------|
| **Baseline** | 200 | 131.06s | 115.87s | **11.6%**  |
| **Periodic** | 240 | 431.96s | 350.93s | **18.8%**  |
| **Flash Crowd** | 300 | 402.87s | 283.66s | **29.6%**  |

---

## Quick Start

### Prerequisites

- OpenShift 4.18+ cluster with RHOAI or Kubernetes 1.28+
- KubeRay operator installed
- `kubectl`/`oc` CLI configured

### Run a Test

```bash
# Login to your cluster
oc login --token=xxx --server=https://api.xxx.openshiftapps.com:443

# Create namespace
oc create namespace gru-cpa-experiment

# Run baseline test (simplest)
cd /Users/lhacaoth/kuberay/experiments/gru-cpa
./scripts/run-baseline-comparison.sh

# Results in: results/baseline-vs-gru-TIMESTAMP/
```

### Train the Model

```bash
# Model is pre-trained, but to retrain:
pip install -r requirements.txt
python model/train_gru.py

# Model saved to: model/gru_model.keras
# Metrics saved to: model/evaluation_metrics.json
```

---

## Model Performance

The GRU model achieves production-grade accuracy across multiple dimensions:

| Dimension | Metric | Value |
|-----------|--------|-------|
| **Regression** | R² Score | 0.880 |
| **Directional** | Trend Accuracy | 87.3% | 
| **Scaling Decisions** | F1 (Scale-Up) | 0.935 |
| **Peak Detection** | F1 Score | 0.930 |
| **Tolerance** | Within ±10 tasks | 88.9% |

---

##  Dataset

**20,000 samples** collected from production OpenShift RHOAI cluster:

- Source: Prometheus scraping of `ray_tasks` metrics
- Sampling Rate: 5 seconds (high-resolution)
- Duration: ~14 hours of continuous workload execution
- Patterns: Burst, periodic, exponential, idle periods

Location: `model/dataset_20k.json`

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│              GRU-CPA Control Loop                       │
│                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐        │
│  │Prometheus│───>│   GRU    │───>│ Scaling  │        │
│  │  Metrics │    │  Model   │    │ Actuator │        │
│  └──────────┘    └──────────┘    └─────┬────┘        │
│                                         │              │
└─────────────────────────────────────────┼─────────────┘
                                          │
                                          ▼
                            ┌─────────────────────────┐
                            │   Kubernetes API        │
                            │   (Patch RayCluster)    │
                            └─────────────────────────┘
                                          │
                                          ▼
                            ┌─────────────────────────┐
                            │   Ray Worker Pods       │
                            │   (Auto-scaled 1-6)     │
                            └─────────────────────────┘
```

---

##  Software Stack

| Component | Version |
|-----------|---------|
| **Platform** | Red Hat OpenShift Service on AWS (ROSA) v4.18 |
| **Kubernetes** | v1.28 |
| **Ray** | 2.35.0 |
| **KubeRay Operator** | v1.2.2 |
| **Python** | 3.11.7 |
| **TensorFlow** | 2.15.0 |
| **Prometheus** | v2.45.0 |

---


## License

Research project for Master's thesis. Code and documentation available for academic use.

---
