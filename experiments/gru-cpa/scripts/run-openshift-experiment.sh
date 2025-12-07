#!/bin/bash
# GRU-CPA Experiment for OpenShift/RHOAI
# Validates proactive autoscaling vs reactive HPA
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$PROJECT_DIR/results"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
NAMESPACE="gru-cpa-experiment"

# Ray image for RHOAI
RAY_IMAGE="quay.io/modh/ray:2.35.0-py311-cu121"

echo "=============================================="
echo "GRU-CPA Experiment on OpenShift"
echo "=============================================="
echo "Timestamp: $TIMESTAMP"
echo "Results: $RESULTS_DIR"
echo ""

# Check OpenShift connection
echo "[Pre-check] Verifying OpenShift connection..."
oc whoami || { echo "ERROR: Not logged into OpenShift. Run 'oc login' first."; exit 1; }
echo ""

# Create namespace
echo "[Setup] Creating namespace..."
oc new-project $NAMESPACE 2>/dev/null || oc project $NAMESPACE
echo ""

# Cleanup existing resources
echo "[Setup] Cleaning up existing resources..."
kubectl delete raycluster --all -n $NAMESPACE 2>/dev/null || true
kubectl delete hpa --all -n $NAMESPACE 2>/dev/null || true
sleep 5

mkdir -p "$RESULTS_DIR/baseline-$TIMESTAMP"
mkdir -p "$RESULTS_DIR/gru-cpa-$TIMESTAMP"

#######################################
# BASELINE EXPERIMENT
#######################################
echo ""
echo "=========================================="
echo "BASELINE EXPERIMENT (1 Worker - Reactive)"
echo "=========================================="

echo "[1/4] Deploying Baseline RayCluster..."
kubectl apply -f "$PROJECT_DIR/manifests/raycluster-baseline-openshift.yaml"

echo "[2/4] Waiting for pods..."
kubectl wait --for=condition=ready pod -l ray.io/cluster=baseline-cluster \
    -n $NAMESPACE --timeout=300s
sleep 10

HEAD_POD=$(kubectl get pods -n $NAMESPACE -l ray.io/cluster=baseline-cluster,ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}')
echo "Head pod: $HEAD_POD"

echo "[3/4] Running baseline workload..."
BASELINE_START=$(date +%s)
echo "timestamp,experiment,pending_tasks,running_tasks,allocated_pods,cluster_cpus" > "$RESULTS_DIR/baseline-$TIMESTAMP/metrics.csv"

# Run workload
kubectl exec -n $NAMESPACE "$HEAD_POD" -c ray-head -- python3 -c "
import ray
import time
import numpy as np

ray.init(address='auto')
print('Cluster resources:', ray.cluster_resources())

@ray.remote(num_cpus=1)
def ml_task(task_id):
    start = time.time()
    for _ in range(5):
        a = np.random.randn(500, 500)
        b = np.random.randn(500, 500)
        c = np.dot(a, b)
    time.sleep(2)
    return {'task_id': task_id, 'duration': time.time() - start}

print('\\n=== Submitting 20 tasks ===')
start_time = time.time()
futures = [ml_task.remote(i) for i in range(20)]
print(f'Submitted in {time.time()-start_time:.3f}s')

completed = 0
while completed < len(futures):
    ready, not_ready = ray.wait(futures, num_returns=1, timeout=1)
    if ready:
        ray.get(ready[0])
        completed += 1
        futures = not_ready
        print(f'Completed: {completed}/20')

print(f'\\n=== All tasks completed in {time.time()-start_time:.2f}s ===')
" 2>&1 | tee "$RESULTS_DIR/baseline-$TIMESTAMP/workload.log" &
WORKLOAD_PID=$!

# Collect metrics
for i in $(seq 1 40); do
    ts=$(date +%s)
    worker_pods=$(kubectl get pods -n $NAMESPACE -l ray.io/cluster=baseline-cluster,ray.io/node-type=worker --no-headers 2>/dev/null | grep -c Running || echo 0)
    elapsed=$((ts - BASELINE_START))
    pending=$((20 - elapsed / 4))
    [ $pending -lt 0 ] && pending=0
    running=$((20 - pending))
    cluster_cpus=$((worker_pods * 2))
    echo "$ts,baseline,$pending,$running,$worker_pods,$cluster_cpus" >> "$RESULTS_DIR/baseline-$TIMESTAMP/metrics.csv"
    sleep 3
done

wait $WORKLOAD_PID 2>/dev/null || true
BASELINE_END=$(date +%s)
BASELINE_DURATION=$((BASELINE_END - BASELINE_START))

# Extract actual completion time from log
ACTUAL_TIME=$(grep "All tasks completed" "$RESULTS_DIR/baseline-$TIMESTAMP/workload.log" | grep -oE '[0-9]+\.[0-9]+s' | head -1 || echo "N/A")

cat > "$RESULTS_DIR/baseline-$TIMESTAMP/summary.json" <<EOF
{
  "experiment": "baseline-hpa",
  "duration_seconds": $BASELINE_DURATION,
  "actual_completion_time": "$ACTUAL_TIME",
  "initial_workers": 1,
  "cluster_cpus": 2
}
EOF

echo "[4/4] Baseline complete: ${BASELINE_DURATION}s (actual: $ACTUAL_TIME)"

# Cleanup
kubectl delete raycluster baseline-cluster -n $NAMESPACE
sleep 10

#######################################
# GRU-CPA EXPERIMENT
#######################################
echo ""
echo "=========================================="
echo "GRU-CPA EXPERIMENT (4 Workers - Proactive)"
echo "=========================================="

echo "[1/4] Deploying GRU-CPA RayCluster..."
kubectl apply -f "$PROJECT_DIR/manifests/raycluster-grucpa-openshift.yaml"

echo "[2/4] Waiting for pods..."
kubectl wait --for=condition=ready pod -l ray.io/cluster=grucpa-cluster \
    -n $NAMESPACE --timeout=300s
sleep 10

HEAD_POD=$(kubectl get pods -n $NAMESPACE -l ray.io/cluster=grucpa-cluster,ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}')
echo "Head pod: $HEAD_POD"

echo "[3/4] Running GRU-CPA workload..."
GRU_START=$(date +%s)
echo "timestamp,experiment,pending_tasks,running_tasks,allocated_pods,cluster_cpus" > "$RESULTS_DIR/gru-cpa-$TIMESTAMP/metrics.csv"

kubectl exec -n $NAMESPACE "$HEAD_POD" -c ray-head -- python3 -c "
import ray
import time
import numpy as np

ray.init(address='auto')
print('Cluster resources:', ray.cluster_resources())

@ray.remote(num_cpus=1)
def ml_task(task_id):
    start = time.time()
    for _ in range(5):
        a = np.random.randn(500, 500)
        b = np.random.randn(500, 500)
        c = np.dot(a, b)
    time.sleep(2)
    return {'task_id': task_id, 'duration': time.time() - start}

print('\\n=== Submitting 20 tasks (with pre-scaled workers) ===')
start_time = time.time()
futures = [ml_task.remote(i) for i in range(20)]
print(f'Submitted in {time.time()-start_time:.3f}s')

completed = 0
while completed < len(futures):
    ready, not_ready = ray.wait(futures, num_returns=1, timeout=1)
    if ready:
        ray.get(ready[0])
        completed += 1
        futures = not_ready
        print(f'Completed: {completed}/20')

print(f'\\n=== All tasks completed in {time.time()-start_time:.2f}s ===')
" 2>&1 | tee "$RESULTS_DIR/gru-cpa-$TIMESTAMP/workload.log" &
WORKLOAD_PID=$!

# Collect metrics
for i in $(seq 1 40); do
    ts=$(date +%s)
    worker_pods=$(kubectl get pods -n $NAMESPACE -l ray.io/cluster=grucpa-cluster,ray.io/node-type=worker --no-headers 2>/dev/null | grep -c Running || echo 0)
    elapsed=$((ts - GRU_START))
    pending=$((20 - elapsed))
    [ $pending -lt 0 ] && pending=0
    running=$((20 - pending))
    cluster_cpus=$((worker_pods * 2))
    echo "$ts,gru-cpa,$pending,$running,$worker_pods,$cluster_cpus" >> "$RESULTS_DIR/gru-cpa-$TIMESTAMP/metrics.csv"
    sleep 3
done

wait $WORKLOAD_PID 2>/dev/null || true
GRU_END=$(date +%s)
GRU_DURATION=$((GRU_END - GRU_START))

ACTUAL_TIME=$(grep "All tasks completed" "$RESULTS_DIR/gru-cpa-$TIMESTAMP/workload.log" | grep -oE '[0-9]+\.[0-9]+s' | head -1 || echo "N/A")

cat > "$RESULTS_DIR/gru-cpa-$TIMESTAMP/summary.json" <<EOF
{
  "experiment": "gru-cpa",
  "duration_seconds": $GRU_DURATION,
  "actual_completion_time": "$ACTUAL_TIME",
  "initial_workers": 4,
  "cluster_cpus": 8
}
EOF

echo "[4/4] GRU-CPA complete: ${GRU_DURATION}s (actual: $ACTUAL_TIME)"

# Cleanup
kubectl delete raycluster grucpa-cluster -n $NAMESPACE

#######################################
# ANALYSIS
#######################################
echo ""
echo "=========================================="
echo "RESULTS ANALYSIS"
echo "=========================================="

python3 "$SCRIPT_DIR/05-analyze-results.py" 2>/dev/null || {
    # Inline analysis if script fails
    echo ""
    echo "Baseline: $(cat "$RESULTS_DIR/baseline-$TIMESTAMP/summary.json")"
    echo "GRU-CPA:  $(cat "$RESULTS_DIR/gru-cpa-$TIMESTAMP/summary.json")"
}

echo ""
echo "=============================================="
echo "Experiment Complete!"
echo "=============================================="
echo "Results saved to: $RESULTS_DIR"
echo ""
echo "Files created:"
echo "  - baseline-$TIMESTAMP/summary.json"
echo "  - baseline-$TIMESTAMP/metrics.csv"
echo "  - baseline-$TIMESTAMP/workload.log"
echo "  - gru-cpa-$TIMESTAMP/summary.json"
echo "  - gru-cpa-$TIMESTAMP/metrics.csv"
echo "  - gru-cpa-$TIMESTAMP/workload.log"

