#!/bin/bash
# Multi-config experiment with 200 tasks for meaningful comparison
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(dirname "$DIR")"
RESULTS="$PROJECT/results/comprehensive-$(date +%Y%m%d-%H%M%S)"
NS="gru-cpa-experiment"
RAY_IMG="quay.io/modh/ray:2.35.0-py311-cu121"

# 200 tasks to reduce overhead impact
TASK_COUNT=200

# Include reactive-4w for fair comparison with proactive-4w
CONFIGS="reactive-1w:1 reactive-2w:2 reactive-4w:4 proactive-4w:4 proactive-6w:6"

echo "=============================================="
echo "Comprehensive Experiment (200 tasks)"
echo "=============================================="
echo "Results: $RESULTS"
echo "Task count: $TASK_COUNT"
echo ""

oc whoami || { echo "oc login first"; exit 1; }
oc new-project $NS 2>/dev/null || oc project $NS

mkdir -p "$RESULTS"

run_config() {
    local name=$1 workers=$2
    local exp_dir="$RESULTS/$name"
    mkdir -p "$exp_dir"
    
    echo ""
    echo "=== $name ($workers workers, $TASK_COUNT tasks) ==="
    
    kubectl delete raycluster --all -n $NS 2>/dev/null || true
    sleep 5
    
    cat <<EOF | kubectl apply -f -
apiVersion: ray.io/v1
kind: RayCluster
metadata:
  name: test-cluster
  namespace: $NS
spec:
  rayVersion: '2.35.0'
  headGroupSpec:
    rayStartParams: {dashboard-host: '0.0.0.0', num-cpus: '0'}
    template:
      spec:
        containers:
          - name: ray-head
            image: $RAY_IMG
            resources: {limits: {cpu: "2", memory: "4Gi"}, requests: {cpu: "1", memory: "2Gi"}}
  workerGroupSpecs:
    - groupName: workers
      replicas: $workers
      minReplicas: 1
      maxReplicas: 10
      rayStartParams: {num-cpus: '2'}
      template:
        spec:
          containers:
            - name: ray-worker
              image: $RAY_IMG
              resources: {limits: {cpu: "2", memory: "4Gi"}, requests: {cpu: "1", memory: "2Gi"}}
EOF

    kubectl wait --for=condition=ready pod -l ray.io/cluster=test-cluster -n $NS --timeout=300s
    sleep 15
    
    HEAD=$(kubectl get pods -n $NS -l ray.io/cluster=test-cluster,ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}')
    
    kubectl exec -n $NS "$HEAD" -c ray-head -- python3 -c "
import ray, time, numpy as np

ray.init(address='auto')
res = ray.cluster_resources()
print(f'Resources: {res}')

@ray.remote(num_cpus=1)
def task(i):
    # Matrix ops to simulate ML workload
    for _ in range(3):
        np.dot(np.random.randn(300,300), np.random.randn(300,300))
    time.sleep(1)
    return i

TASKS = $TASK_COUNT
print(f'Submitting {TASKS} tasks...')

t0 = time.time()
futures = [task.remote(i) for i in range(TASKS)]
submit_time = time.time() - t0
print(f'Submit time: {submit_time:.2f}s')

# Wait for all
ray.get(futures)
total = time.time() - t0

throughput = TASKS / total
print(f'RESULT:{total:.2f}')
print(f'Throughput: {throughput:.2f} tasks/sec')
" 2>&1 | tee "$exp_dir/output.log"
    
    TIME=$(grep "RESULT:" "$exp_dir/output.log" | cut -d: -f2 || echo "0")
    CPU_SEC=$(echo "$workers * 2 * $TIME" | bc 2>/dev/null || echo "0")
    THROUGHPUT=$(grep "Throughput:" "$exp_dir/output.log" | awk '{print $2}' || echo "0")
    
    cat > "$exp_dir/summary.json" <<EOF
{"name":"$name","workers":$workers,"cpus":$((workers*2)),"tasks":$TASK_COUNT,"time_s":$TIME,"cpu_seconds":$CPU_SEC,"throughput":$THROUGHPUT}
EOF
}

for cfg in $CONFIGS; do
    name=${cfg%:*}
    workers=${cfg#*:}
    run_config "$name" "$workers"
done

kubectl delete raycluster --all -n $NS 2>/dev/null || true

echo ""
echo "=============================================="
echo "ANALYSIS"
echo "=============================================="

python3 << 'PY'
import os, json, glob

d = os.environ.get('RESULTS', 'results')
exps = {}
for f in glob.glob(f"{d}/*/summary.json"):
    with open(f) as fp:
        e = json.load(fp)
        exps[e['name']] = e

if exps:
    print("\n" + "="*90)
    print(f"{'Config':<15} {'Workers':>8} {'Tasks':>7} {'Time(s)':>10} {'Speedup':>10} {'Efficiency':>12} {'Tput':>10}")
    print("-"*90)
    
    base_time = exps.get('reactive-1w', {}).get('time_s', 1)
    for name in ['reactive-1w', 'reactive-2w', 'reactive-4w', 'proactive-4w', 'proactive-6w']:
        if name not in exps:
            continue
        e = exps[name]
        t = float(e.get('time_s', 0))
        w = e['workers']
        speedup = base_time / t if t > 0 else 0
        efficiency = (speedup / w) * 100 if w > 0 else 0
        tput = e.get('throughput', 0)
        print(f"{name:<15} {w:>8} {e['tasks']:>7} {t:>10.2f} {speedup:>10.2f}x {efficiency:>11.1f}% {tput:>10.2f}")
    
    print("-"*90)
    
    # Compare reactive-4w vs proactive-4w
    r4 = exps.get('reactive-4w', {})
    p4 = exps.get('proactive-4w', {})
    if r4 and p4:
        r4_t = float(r4.get('time_s', 1))
        p4_t = float(p4.get('time_s', 1))
        diff = ((r4_t - p4_t) / r4_t) * 100
        print(f"\n** Proactive-4w vs Reactive-4w: {diff:+.1f}% {'faster' if diff > 0 else 'slower'} **")
        print("   (Same workers, tests if prediction beats reaction)")
    
    print("="*90)

with open(f"{d}/comprehensive_analysis.json", 'w') as f:
    json.dump(exps, f, indent=2)

print(f"\nResults saved to: {d}/")
PY

echo ""
echo "Done!"
