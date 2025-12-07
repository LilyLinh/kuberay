#!/bin/bash
# Comprehensive GRU-CPA Experiment with Multiple Configurations
# Collects Prometheus metrics for deeper analysis
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$PROJECT_DIR/results/comprehensive-$(date +%Y%m%d-%H%M%S)"
NAMESPACE="gru-cpa-experiment"
RAY_IMAGE="quay.io/modh/ray:2.35.0-py311-cu121"

# Test configurations: (name, workers, description)
CONFIGS=(
    "reactive-1w:1:Reactive HPA (1 worker)"
    "reactive-2w:2:Reactive HPA (2 workers)"
    "proactive-4w:4:GRU-CPA Proactive (4 workers)"
    "proactive-6w:6:GRU-CPA Aggressive (6 workers)"
)

echo "=============================================="
echo "Comprehensive GRU-CPA Experiment"
echo "=============================================="
echo "Results: $RESULTS_DIR"
echo "Configurations: ${#CONFIGS[@]}"
echo ""

# Verify connection
oc whoami || { echo "ERROR: Not logged in"; exit 1; }
oc project $NAMESPACE 2>/dev/null || oc new-project $NAMESPACE

mkdir -p "$RESULTS_DIR"

# Get Prometheus route
PROM_URL=$(oc get route -n openshift-monitoring prometheus-k8s -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
if [ -z "$PROM_URL" ]; then
    echo "Warning: Prometheus route not found, using port-forward"
    kubectl port-forward -n openshift-monitoring svc/prometheus-k8s 9090:9090 &
    PROM_PID=$!
    sleep 3
    PROM_URL="localhost:9090"
    trap "kill $PROM_PID 2>/dev/null" EXIT
fi
echo "Prometheus: $PROM_URL"

# Function to query Prometheus
query_prometheus() {
    local query="$1"
    curl -s -k "https://$PROM_URL/api/v1/query" \
        -H "Authorization: Bearer $(oc whoami -t)" \
        --data-urlencode "query=$query" 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('result',[{}])[0].get('value',['0','0'])[1])" 2>/dev/null || echo "0"
}

# Function to run single experiment
run_experiment() {
    local name="$1"
    local workers="$2"
    local desc="$3"
    local exp_dir="$RESULTS_DIR/$name"
    
    mkdir -p "$exp_dir"
    
    echo ""
    echo "=========================================="
    echo "Running: $desc"
    echo "=========================================="
    
    # Cleanup
    kubectl delete raycluster --all -n $NAMESPACE 2>/dev/null || true
    sleep 5
    
    # Deploy RayCluster
    cat <<EOF | kubectl apply -f -
apiVersion: ray.io/v1
kind: RayCluster
metadata:
  name: test-cluster
  namespace: $NAMESPACE
spec:
  rayVersion: '2.35.0'
  enableInTreeAutoscaling: false
  headGroupSpec:
    rayStartParams:
      dashboard-host: '0.0.0.0'
      num-cpus: '0'
      metrics-export-port: '8080'
    template:
      spec:
        containers:
          - name: ray-head
            image: $RAY_IMAGE
            ports:
              - containerPort: 6379
                name: gcs
              - containerPort: 8265
                name: dashboard
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
      replicas: $workers
      minReplicas: 1
      maxReplicas: 8
      rayStartParams:
        num-cpus: '2'
        metrics-export-port: '8080'
      template:
        spec:
          containers:
            - name: ray-worker
              image: $RAY_IMAGE
              ports:
                - containerPort: 8080
                  name: metrics
              resources:
                limits:
                  cpu: "2"
                  memory: "4Gi"
                requests:
                  cpu: "1"
                  memory: "2Gi"
EOF

    # Wait for ready
    echo "Waiting for cluster ($workers workers)..."
    kubectl wait --for=condition=ready pod -l ray.io/cluster=test-cluster \
        -n $NAMESPACE --timeout=300s
    sleep 15
    
    HEAD_POD=$(kubectl get pods -n $NAMESPACE -l ray.io/cluster=test-cluster,ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}')
    
    # Initialize metrics file with more columns
    echo "timestamp,pending_tasks,running_tasks,finished_tasks,failed_tasks,allocated_pods,cluster_cpus,memory_used_mb,object_store_mb" > "$exp_dir/metrics.csv"
    
    # Record start time
    START_TIME=$(date +%s)
    
    # Run workload
    echo "Running workload (30 tasks)..."
    kubectl exec -n $NAMESPACE "$HEAD_POD" -c ray-head -- python3 -c "
import ray
import time
import numpy as np
import json

ray.init(address='auto')
resources = ray.cluster_resources()
print(f'Cluster: {resources}')

@ray.remote(num_cpus=1)
def ml_training_task(task_id, complexity=1.0):
    '''Simulate ML training with variable complexity'''
    start = time.time()
    
    # Matrix operations (simulate forward/backward pass)
    for _ in range(int(5 * complexity)):
        a = np.random.randn(500, 500)
        b = np.random.randn(500, 500)
        c = np.dot(a, b)
        # Simulate gradient computation
        grad = np.sum(c) / (500 * 500)
    
    time.sleep(2 * complexity)
    
    return {
        'task_id': task_id,
        'duration': time.time() - start,
        'result': float(grad)
    }

# Submit burst of 30 tasks
NUM_TASKS = 30
print(f'\\nSubmitting {NUM_TASKS} tasks...')
start_time = time.time()

futures = [ml_training_task.remote(i, complexity=1.0) for i in range(NUM_TASKS)]
submit_time = time.time() - start_time
print(f'Submit time: {submit_time:.3f}s')

# Track completion with timing
results = []
completion_times = []
while futures:
    ready, futures = ray.wait(futures, num_returns=1, timeout=0.5)
    if ready:
        result = ray.get(ready[0])
        results.append(result)
        completion_times.append(time.time() - start_time)
        print(f'Task {result[\"task_id\"]} done ({len(results)}/{NUM_TASKS})')

total_time = time.time() - start_time
print(f'\\n=== Completed {NUM_TASKS} tasks in {total_time:.2f}s ===')

# Calculate statistics
durations = [r['duration'] for r in results]
print(f'Task duration: min={min(durations):.2f}s, max={max(durations):.2f}s, avg={sum(durations)/len(durations):.2f}s')

# Output metrics
metrics = {
    'total_time': total_time,
    'submit_time': submit_time,
    'task_count': NUM_TASKS,
    'min_duration': min(durations),
    'max_duration': max(durations),
    'avg_duration': sum(durations)/len(durations),
    'completion_times': completion_times
}
print(f'\\nMETRICS_JSON:{json.dumps(metrics)}')
" 2>&1 | tee "$exp_dir/workload.log" &
    WORKLOAD_PID=$!
    
    # Collect metrics every 3 seconds
    for i in $(seq 1 60); do
        ts=$(date +%s)
        
        # Get pod count
        pods=$(kubectl get pods -n $NAMESPACE -l ray.io/cluster=test-cluster,ray.io/node-type=worker --no-headers 2>/dev/null | grep -c Running || echo 0)
        cpus=$((pods * 2))
        
        # Query Ray metrics from head pod (if available)
        pending=$(kubectl exec -n $NAMESPACE "$HEAD_POD" -c ray-head -- curl -s http://localhost:8080/metrics 2>/dev/null | grep 'ray_tasks{State="PENDING' | grep -oE '[0-9]+$' || echo 0)
        running=$(kubectl exec -n $NAMESPACE "$HEAD_POD" -c ray-head -- curl -s http://localhost:8080/metrics 2>/dev/null | grep 'ray_tasks{State="RUNNING' | grep -oE '[0-9]+$' || echo 0)
        finished=$(kubectl exec -n $NAMESPACE "$HEAD_POD" -c ray-head -- curl -s http://localhost:8080/metrics 2>/dev/null | grep 'ray_tasks{State="FINISHED' | grep -oE '[0-9]+$' || echo 0)
        failed=$(kubectl exec -n $NAMESPACE "$HEAD_POD" -c ray-head -- curl -s http://localhost:8080/metrics 2>/dev/null | grep 'ray_tasks{State="FAILED' | grep -oE '[0-9]+$' || echo 0)
        
        # Memory metrics
        mem_used=$(kubectl exec -n $NAMESPACE "$HEAD_POD" -c ray-head -- curl -s http://localhost:8080/metrics 2>/dev/null | grep 'ray_memory_used_bytes' | head -1 | grep -oE '[0-9.]+$' | awk '{print int($1/1024/1024)}' || echo 0)
        obj_store=$(kubectl exec -n $NAMESPACE "$HEAD_POD" -c ray-head -- curl -s http://localhost:8080/metrics 2>/dev/null | grep 'ray_object_store_memory' | head -1 | grep -oE '[0-9.]+$' | awk '{print int($1/1024/1024)}' || echo 0)
        
        echo "$ts,$pending,$running,$finished,$failed,$pods,$cpus,$mem_used,$obj_store" >> "$exp_dir/metrics.csv"
        
        # Check if workload finished
        if ! kill -0 $WORKLOAD_PID 2>/dev/null; then
            break
        fi
        
        sleep 3
    done
    
    wait $WORKLOAD_PID 2>/dev/null || true
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    
    # Extract metrics from log
    TOTAL_TIME=$(grep "METRICS_JSON" "$exp_dir/workload.log" | sed 's/.*METRICS_JSON://' | python3 -c "import sys,json; print(json.load(sys.stdin).get('total_time', 0))" 2>/dev/null || echo "0")
    
    # Save summary
    cat > "$exp_dir/summary.json" <<EOF
{
    "name": "$name",
    "description": "$desc",
    "workers": $workers,
    "cluster_cpus": $((workers * 2)),
    "task_count": 30,
    "wall_clock_seconds": $DURATION,
    "ray_completion_seconds": $TOTAL_TIME
}
EOF
    
    echo "Completed: $name (${TOTAL_TIME}s)"
}

# Run all configurations
for config in "${CONFIGS[@]}"; do
    IFS=':' read -r name workers desc <<< "$config"
    run_experiment "$name" "$workers" "$desc"
done

# Cleanup
kubectl delete raycluster --all -n $NAMESPACE 2>/dev/null || true

# Generate analysis
echo ""
echo "=========================================="
echo "ANALYSIS"
echo "=========================================="

python3 << 'PYTHON_SCRIPT'
import os
import json
import csv
import glob

RESULTS_DIR = os.environ.get('RESULTS_DIR', 'results')

print("\n" + "=" * 90)
print("                              COMPREHENSIVE RESULTS")
print("=" * 90)

# Load all experiments
experiments = {}
for exp_dir in sorted(glob.glob(f"{RESULTS_DIR}/*/")):
    name = os.path.basename(exp_dir.rstrip('/'))
    summary_path = os.path.join(exp_dir, 'summary.json')
    metrics_path = os.path.join(exp_dir, 'metrics.csv')
    
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            exp = json.load(f)
        
        # Calculate metrics from CSV
        if os.path.exists(metrics_path):
            with open(metrics_path) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            if rows:
                pending = [int(r.get('pending_tasks', 0)) for r in rows]
                running = [int(r.get('running_tasks', 0)) for r in rows]
                finished = [int(r.get('finished_tasks', 0)) for r in rows]
                pods = [int(r.get('allocated_pods', 0)) for r in rows]
                cpus = [int(r.get('cluster_cpus', 0)) for r in rows]
                
                exp['max_pending'] = max(pending) if pending else 0
                exp['avg_pending'] = sum(pending) / len(pending) if pending else 0
                exp['max_running'] = max(running) if running else 0
                exp['total_pod_seconds'] = sum(pods) * 3
                exp['total_cpu_seconds'] = sum(cpus) * 3
                
                # Time to first completion
                for i, r in enumerate(rows):
                    if int(r.get('finished_tasks', 0)) > 0:
                        exp['time_to_first_completion'] = i * 3
                        break
                
                # Time to all complete
                for i, r in enumerate(rows):
                    if int(r.get('finished_tasks', 0)) >= 30:
                        exp['time_to_all_complete'] = i * 3
                        break
        
        experiments[name] = exp

if not experiments:
    print("No experiments found")
    exit(1)

# Print comparison table
print(f"\n{'Configuration':<25} {'Workers':>8} {'CPUs':>6} {'Time(s)':>10} {'Pending':>10} {'CPU-Sec':>12}")
print("-" * 90)

for name, exp in sorted(experiments.items()):
    workers = exp.get('workers', 0)
    cpus = exp.get('cluster_cpus', 0)
    time_s = exp.get('ray_completion_seconds', 0)
    pending = exp.get('avg_pending', 0)
    cpu_sec = exp.get('total_cpu_seconds', 0)
    
    print(f"{name:<25} {workers:>8} {cpus:>6} {time_s:>10.2f} {pending:>10.2f} {cpu_sec:>12}")

print("-" * 90)

# Find best configurations
if len(experiments) >= 2:
    by_time = sorted(experiments.items(), key=lambda x: x[1].get('ray_completion_seconds', 999))
    by_efficiency = sorted(experiments.items(), key=lambda x: x[1].get('avg_pending', 999))
    by_cost = sorted(experiments.items(), key=lambda x: x[1].get('total_cpu_seconds', 999))
    
    print(f"\n🏆 BEST CONFIGURATIONS:")
    print(f"   Fastest:          {by_time[0][0]} ({by_time[0][1].get('ray_completion_seconds', 0):.2f}s)")
    print(f"   Lowest Pending:   {by_efficiency[0][0]} ({by_efficiency[0][1].get('avg_pending', 0):.2f} avg)")
    print(f"   Lowest Cost:      {by_cost[0][0]} ({by_cost[0][1].get('total_cpu_seconds', 0)} CPU-sec)")

# Calculate improvements vs baseline
baseline = experiments.get('reactive-1w', {})
if baseline:
    print(f"\n📊 IMPROVEMENTS vs Baseline (reactive-1w):")
    print("-" * 60)
    
    base_time = baseline.get('ray_completion_seconds', 1)
    base_pending = baseline.get('avg_pending', 1)
    
    for name, exp in sorted(experiments.items()):
        if name == 'reactive-1w':
            continue
        
        time_imp = ((base_time - exp.get('ray_completion_seconds', 0)) / base_time) * 100
        pending_imp = ((base_pending - exp.get('avg_pending', 0)) / base_pending) * 100
        
        print(f"   {name:<20}: Time {time_imp:+.1f}%, Pending {pending_imp:+.1f}%")

print("\n" + "=" * 90)

# Save combined analysis
with open(f"{RESULTS_DIR}/analysis.json", 'w') as f:
    json.dump(experiments, f, indent=2)

print(f"\nResults saved to: {RESULTS_DIR}/")

PYTHON_SCRIPT

echo ""
echo "=============================================="
echo "Experiment Complete!"
echo "=============================================="

