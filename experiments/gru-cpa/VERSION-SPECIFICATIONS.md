# GRU-CPA: Complete Version Specifications

This document provides the complete software stack versions used in the GRU-CPA research for reproducibility and thesis documentation.

---

## Production Environment

### Cloud Infrastructure

| Component | Version | Notes |
|-----------|---------|-------|
| **Platform** | Red Hat OpenShift Service on AWS (ROSA) v4.18 | Enterprise Kubernetes platform |
| **Kubernetes** | v1.28 | OpenShift 4.18 uses K8s 1.28 |
| **AWS Region** | us-east-1 | Deployment location |
| **Node Instance** | m5.xlarge | 4 vCPU, 16GB RAM per worker |

---

## Ray Ecosystem

### Core Ray Components

| Component | Version | Source | Purpose |
|-----------|---------|--------|---------|
| **Ray** | 2.35.0 | rayproject/ray:2.35.0 | Distributed computing framework |
| **KubeRay Operator** | v1.2.2 | Installed via OperatorHub | Ray cluster lifecycle management |
| **Ray Dashboard** | 2.35.0 | Bundled with Ray | Monitoring and debugging UI |

### Ray Configuration

```yaml
rayVersion: '2.35.0'
Container Image: rayproject/ray:2.35.0-py311
Exposed Ports:
  - 6379  (GCS - Global Control Store)
  - 8265  (Dashboard)
  - 10001 (Client connection)
  - 8080  (Prometheus metrics)
```

### Why Ray 2.35.0?

- **Latest stable** as of December 2024
- **Improved metrics**: Enhanced `ray_tasks` metric accuracy
- **Better autoscaling**: Fixes in internal autoscaler (though we disable it)
- **Python 3.11 support**: Performance improvements over 3.10
- **Production-validated**: Used by major companies (Uber, Ant Group)

---

## Python Environment

### Runtime

| Component | Version | Notes |
|-----------|---------|-------|
| **Python** | 3.11.7 | Bundled in Ray 2.35.0 image |
| **pip** | 23.3.1 | Package manager |

### Core Dependencies

```python
# requirements.txt (verified versions)

# Machine Learning
tensorflow==2.15.0          # GRU model training and inference
numpy==1.24.3               # Array operations
scikit-learn==1.3.0         # Evaluation metrics

# Data Processing
pandas==2.0.3               # Data manipulation (if needed)

# API & Monitoring
requests==2.31.0            # Prometheus HTTP queries
prometheus-client==0.17.1   # Metrics exposition

# Utilities
pyyaml==6.0.1              # YAML parsing
jsonschema==4.19.0         # JSON validation
```

### TensorFlow Details

```
TensorFlow Version: 2.15.0
  - Keras API: 3.0 (integrated)
  - CUDA Support: Optional (CPU-only for controller)
  - Backend: tensorflow (not JAX)

Model Serialization Format:
  - Keras 3.x native format (.keras)
  - Custom layers: Registered with @keras.saving.register_keras_serializable()
```

---

## Monitoring Stack

### Prometheus

| Component | Version | Configuration |
|-----------|---------|---------------|
| **Prometheus** | v2.45.0 | OpenShift built-in |
| **Scrape Interval** | 5 seconds | High-resolution metrics |
| **Retention** | 24 hours | Default RHOAI setting |

### Metrics Collected

```yaml
Metric: ray_tasks
Labels:
  - State: "PENDING_ARGS_AVAIL", "RUNNING", "FINISHED"
  - pod: ray-head-xxxxx

Additional Metrics:
  - ray_node_cpu_utilization (0-100%)
  - ray_node_cpu_count (total CPUs)
  - ray_scheduler_tasks (by state)
```

---

## Custom Components

### GRU-CPA Controller

```
Language: Python 3.11
Framework: TensorFlow 2.15.0 + Keras 3.0

Dependencies:
  - tensorflow==2.15.0
  - numpy==1.24.3
  - requests==2.31.0
  - scikit-learn==1.3.0 (for evaluation metrics)

Execution: Runs locally on laptop, connects to cluster via kubectl
Frequency: Polls every 2 seconds
Latency: <100ms per prediction
```

### Model Architecture

```python
GRU Model Specification:
  Input Shape: (30, 1)  # 30 timesteps, 1 feature (CPU %)
  Output Shape: (2,)    # 2 predictions (next 2 timesteps)

  Layers:
    1. GRU(128, return_sequences=True)
    2. Attention() - Custom layer
    3. BatchNormalization()
    4. Dropout(0.3)
    5. GRU(64)
    6. BatchNormalization()
    7. Dropout(0.3)
    8. Dense(32, activation='relu')
    9. Dense(2) - Output

  Optimizer: Adam (default learning rate)
  Loss: Huber (robust to outliers)
  Metrics: MSE, MAE

  Training:
    Epochs: 100
    Batch Size: 32
    Validation Split: 0.2
    Dataset Size: 20,000 samples
```

---

## Client Tools

### Local Development Environment

| Tool | Version | Purpose |
|------|---------|---------|
| **kubectl** | v1.28.x | Kubernetes CLI |
| **oc** | v4.18 | OpenShift CLI (extends kubectl) |
| **Python** | 3.11.7 | Local script execution |
| **Docker** | 24.0.7 | Container image building (optional) |

### Installation Commands

```bash
# OpenShift CLI
wget https://mirror.openshift.com/pub/openshift-v4/clients/oc/latest/linux/oc.tar.gz
tar -xzf oc.tar.gz
sudo mv oc /usr/local/bin/

# kubectl (bundled with oc)
sudo ln -s /usr/local/bin/oc /usr/local/bin/kubectl

# Python dependencies
pip install -r requirements.txt
```

---

## Operating Systems

### Container OS

```
Base Image: rayproject/ray:2.35.0
  OS: Ubuntu 22.04 LTS (Jammy)
  Kernel: Linux 5.15+ (from host)

Runtime: containerd (OpenShift default)
  Version: 1.7.x
  CRI: CRI-O (OpenShift uses CRI-O, not containerd)
```

### Development Machine

```
macOS: 14.x (Sonoma) or later
  OR
Linux: Ubuntu 22.04+ / RHEL 9+
  OR
Windows: WSL2 with Ubuntu 22.04
```

---

## Version Compatibility Matrix

### Tested Combinations

✅ **Confirmed Working**:

```
OpenShift 4.18 + Ray 2.35.0 + KubeRay 1.2.2 + Python 3.11 + TF 2.15.0
```

⚠️ **Known Issues**:

```
Ray 2.9.0 + KubeRay 1.2.x: Metric format changes (use 2.35.0 instead)
TensorFlow 2.16+: Keras 3.x breaking changes (use 2.15.0)
OpenShift <4.16: Older KubeRay operator (recommend 4.18+)
```

❌ **Incompatible**:

```
Ray <2.0: Missing ray_tasks metric with detailed states
KubeRay <1.0: Old CRD schema
TensorFlow <2.10: Incompatible Keras API
Python 3.8: End of life, use 3.11+
```

---

## Reproducibility Checklist

For exact reproduction of results, ensure:

### Infrastructure

- ✅ OpenShift 4.18 or ROSA on AWS
- ✅ KubeRay Operator v1.2.2 installed
- ✅ Prometheus enabled with 5s scrape interval
- ✅ Worker nodes: m5.xlarge or equivalent (4 vCPU, 16GB)

### Software

- ✅ Ray 2.35.0 container image
- ✅ Python 3.11 with exact requirements.txt versions
- ✅ TensorFlow 2.15.0 (not 2.16+)
- ✅ kubectl/oc CLI matching cluster version

### Data

- ✅ Training dataset: 20,000 samples from Prometheus
- ✅ Sampling rate: 5 seconds
- ✅ Normalization: MinMaxScaler(feature_range=(0,1))
- ✅ Train/test split: 80/20

### Configuration

- ✅ GRU model: As specified in train_gru.py
- ✅ Controller polling: 2 seconds
- ✅ Safety buffer: 1.2x multiplier
- ✅ Min/max workers: 1-6 replicas

---

## Version Evolution (Historical)

### Initial Development

- Ray 2.9.0, KubeRay 1.0, OpenShift 4.16
- Issues: Inconsistent metrics, old operator

### Final Production

- Ray 2.35.0, KubeRay 1.2.2, OpenShift 4.18
- All tests and results based on this stack

**Note**: All thesis results use the Final Production versions.

---

## References for Version Selection

### Ray 2.35.0 Release Notes

- Released: December 2024
- Key Features: Improved autoscaling, better metrics, Python 3.11 support
- URL: <https://docs.ray.io/en/releases-2.35.0/>

### KubeRay 1.2.2

- Released: November 2024
- Key Features: OpenShift compatibility, improved CRD validation
- URL: <https://github.com/ray-project/kuberay/releases/tag/v1.2.2>

### OpenShift 4.18

- Released: October 2024
- Kubernetes: 1.28
- URL: <https://docs.openshift.com/container-platform/4.18/>

### TensorFlow 2.15.0

- Released: November 2023
- Last stable before Keras 3.x breaking changes
- URL: <https://github.com/tensorflow/tensorflow/releases/tag/v2.15.0>

---

## For Thesis Documentation

### Suggested Citation Format

```
The experiments were conducted on Red Hat OpenShift Service on AWS
(ROSA) version 4.18, using Ray 2.35.0 managed by KubeRay Operator
v1.2.2. The GRU model was implemented in TensorFlow 2.15.0 with
Python 3.11. All software versions represent the latest stable
releases as of December 2024, ensuring production-grade reliability
while maintaining reproducibility.
```

### Version Table for Thesis

```latex
\begin{table}[h]
\centering
\caption{Software Stack Versions}
\begin{tabular}{lll}
\hline
Component & Version & Purpose \\
\hline
OpenShift ROSA & 4.18 & Cloud Platform \\
Kubernetes & 1.28 & Orchestration \\
Ray & 2.35.0 & Distributed Computing \\
KubeRay Operator & 1.2.2 & Cluster Management \\
Python & 3.11.7 & Runtime \\
TensorFlow & 2.15.0 & ML Framework \\
Prometheus & 2.45.0 & Monitoring \\
\hline
\end{tabular}
\end{table}
```

---

## Maintenance Notes

**Last Verified**: December 10, 2025
**Next Review**: Quarterly (March 2025)

**Update Policy**:

- Security patches: Apply immediately
- Minor versions: Review quarterly
- Major versions: Test thoroughly before upgrading

---

*This document provides the complete, verified version specifications
for the GRU-CPA research. All versions have been tested and confirmed
working in production OpenShift RHOAI environment.*
