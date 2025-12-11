#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="$DIR/../results/baseline-vs-gru-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RESULTS_DIR"

NS="gru-cpa-experiment"

echo "======================================"
echo "BASELINE vs GRU-CPA Comparison"
echo "Same workload, measure the difference"
echo "======================================"
echo "Results: $RESULTS_DIR"
echo ""

# Ensure we're on the right project
oc project $NS 2>/dev/null || oc new-project $NS

# Deploy RayCluster manifest
cat > /tmp/raycluster-baseline.yaml << 'YAML'
apiVersion: ray.io/v1
kind: RayCluster
metadata:
  name: test-cluster
spec:
  rayVersion: '2.35.0'
  headGroupSpec:
    rayStartParams:
      dashboard-host: '0.0.0.0'
      block: 'true'
    template:
      spec:
        containers:
        - name: ray-head
          image: rayproject/ray:2.35.0
          ports:
          - containerPort: 6379
            name: gcs
          - containerPort: 8265
            name: dashboard
          - containerPort: 10001
            name: client
          - containerPort: 8080
            name: metrics
          resources:
            limits:
              cpu: "2"
              memory: "4Gi"
            requests:
              cpu: "1"
              memory: "2Gi"
  workerGroupSpecs:
  - groupName: workers
    replicas: 1
    minReplicas: 1
    maxReplicas: 6
    rayStartParams:
      block: 'true'
    template:
      spec:
        containers:
        - name: ray-worker
          image: rayproject/ray:2.35.0
          resources:
            limits:
              cpu: "2"
              memory: "4Gi"
            requests:
              cpu: "1"
              memory: "2Gi"
YAML

echo "======================================"
echo "EXPERIMENT 1: Baseline (No GRU)"
echo "======================================"
echo ""

# Clean up
echo "Cleaning up old resources..."
kubectl delete raycluster test-cluster -n $NS 2>/dev/null || true
sleep 5

# Deploy
echo "Deploying RayCluster (1 worker, no autoscaling)..."
kubectl apply -f /tmp/raycluster-baseline.yaml -n $NS

# Wait for cluster
echo "Waiting for cluster..."
for i in {1..60}; do
    if kubectl get pod -n $NS -l ray.io/node-type=head 2>/dev/null | grep -q Running; then
        echo "Cluster ready!"
        break
    fi
    echo "Waiting... ($i/60)"
    sleep 5
done

sleep 15

echo ""
echo "Running workload (NO GRU, 1 worker)..."
HEAD=$(kubectl get pods -n $NS -l ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}')

BASELINE_TIME=$(kubectl exec -n $NS "$HEAD" -c ray-head -- python3 -c "
import ray
import time
import numpy as np

ray.init(address='auto')

@ray.remote(num_cpus=1)
def task(i):
    # Same tasks as GRU experiment
    for _ in range(3):
        np.dot(np.random.randn(300,300), np.random.randn(300,300))
    time.sleep(2.5)
    return i

print('Running 200 tasks on 1 worker (baseline)...')
t0 = time.time()

# Same workload pattern
refs = [task.remote(i) for i in range(20)]
ray.get(refs)
print(f'Phase 1: {time.time()-t0:.1f}s')

refs = [task.remote(i) for i in range(60)]
ray.get(refs)
print(f'Phase 2: {time.time()-t0:.1f}s')

refs = [task.remote(i) for i in range(120)]
ray.get(refs)

elapsed = time.time() - t0
print(f'BASELINE:{elapsed:.2f}')
")

echo "Baseline result:"
echo "$BASELINE_TIME"
BASELINE_SEC=$(echo "$BASELINE_TIME" | grep "BASELINE:" | cut -d: -f2)
echo "$BASELINE_SEC" > "$RESULTS_DIR/baseline.txt"

echo ""
echo "======================================"
echo "EXPERIMENT 2: GRU-CPA (With Prediction)"
echo "======================================"
echo ""

# Clean up
echo "Cleaning up old resources..."
kubectl delete raycluster test-cluster -n $NS
sleep 10

# Deploy again
echo "Deploying RayCluster (starting with 1 worker)..."
kubectl apply -f /tmp/raycluster-baseline.yaml -n $NS

# Wait
echo "Waiting for cluster..."
for i in {1..60}; do
    if kubectl get pod -n $NS -l ray.io/node-type=head 2>/dev/null | grep -q Running; then
        echo "Cluster ready!"
        break
    fi
    sleep 5
done

sleep 15

echo "Starting GRU Controller..."
export NAMESPACE=$NS
export RAYCLUSTER=test-cluster

python3 "$DIR/run-local-gru-controller.py" > "$RESULTS_DIR/controller.log" 2>&1 &
CONTROLLER_PID=$!

sleep 10
echo "Controller PID: $CONTROLLER_PID"

echo ""
echo "Running workload (WITH GRU)..."
HEAD=$(kubectl get pods -n $NS -l ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}')

GRU_TIME=$(kubectl exec -n $NS "$HEAD" -c ray-head -- python3 -c "
import ray
import time
import numpy as np

ray.init(address='auto')

@ray.remote(num_cpus=1)
def task(i):
    for _ in range(3):
        np.dot(np.random.randn(300,300), np.random.randn(300,300))
    time.sleep(2.5)
    return i

print('Running 200 tasks with GRU controller...')
t0 = time.time()

refs = [task.remote(i) for i in range(20)]
ray.get(refs)
print(f'Phase 1: {time.time()-t0:.1f}s')

refs = [task.remote(i) for i in range(60)]
ray.get(refs)
print(f'Phase 2: {time.time()-t0:.1f}s')

refs = [task.remote(i) for i in range(120)]
ray.get(refs)

elapsed = time.time() - t0
print(f'GRU:{elapsed:.2f}')
")

echo "GRU result:"
echo "$GRU_TIME"
GRU_SEC=$(echo "$GRU_TIME" | grep "GRU:" | cut -d: -f2)
echo "$GRU_SEC" > "$RESULTS_DIR/gru.txt"

# Stop controller
kill $CONTROLLER_PID 2>/dev/null || true

echo ""
echo "======================================"
echo "FINAL COMPARISON"
echo "======================================"

python3 << PYEOF
baseline = float(open("$RESULTS_DIR/baseline.txt").read().strip())
gru = float(open("$RESULTS_DIR/gru.txt").read().strip())

improvement = ((baseline - gru) / baseline) * 100
speedup = baseline / gru

print(f"""
┌────────────────────────────────────────┐
│         PERFORMANCE COMPARISON         │
├────────────────────────────────────────┤
│ Baseline (1 worker):   {baseline:7.2f}s      │
│ GRU-CPA (dynamic):     {gru:7.2f}s      │
├────────────────────────────────────────┤
│ Improvement:           {improvement:6.1f}%       │
│ Speedup:               {speedup:6.2f}x       │
└────────────────────────────────────────┘

How it works:
• Baseline: Stuck at 1 worker, sequential execution
• GRU-CPA: Predicts CPU demand, scales 1→2→3 workers
• Result: {100-100/speedup:.0f}% faster by using predictions!
""")

# Save summary
with open("$RESULTS_DIR/summary.txt", "w") as f:
    f.write(f"Baseline: {baseline}s\n")
    f.write(f"GRU-CPA: {gru}s\n")
    f.write(f"Improvement: {improvement:.1f}%\n")
    f.write(f"Speedup: {speedup:.2f}x\n")

PYEOF

echo ""
echo "Results saved to: $RESULTS_DIR"
echo "Controller log: $RESULTS_DIR/controller.log"
echo ""
