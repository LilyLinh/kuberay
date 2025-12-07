#!/bin/bash
# Multi-config experiment: 1, 2, 4, 6 workers
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(dirname "$DIR")"
RESULTS="$PROJECT/results/comprehensive-$(date +%Y%m%d-%H%M%S)"
NS="gru-cpa-experiment"
RAY_IMG="quay.io/modh/ray:2.35.0-py311-cu121"

CONFIGS="reactive-1w:1 reactive-2w:2 proactive-4w:4 proactive-6w:6"

echo "Comprehensive Experiment"
oc whoami || { echo "oc login first"; exit 1; }
oc new-project $NS 2>/dev/null || oc project $NS

mkdir -p "$RESULTS"

run_config() {
    local name=$1 workers=$2
    local exp_dir="$RESULTS/$name"
    mkdir -p "$exp_dir"
    
    echo ""
    echo "=== $name ($workers workers) ==="
    
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
      maxReplicas: 8
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
print('Resources:', ray.cluster_resources())

@ray.remote(num_cpus=1)
def task(i):
    for _ in range(5):
        np.dot(np.random.randn(500,500), np.random.randn(500,500))
    time.sleep(2)
    return i

t0 = time.time()
futures = [task.remote(i) for i in range(20)]
ray.get(futures)
elapsed = time.time() - t0
print(f'RESULT:{elapsed:.2f}')
" 2>&1 | tee "$exp_dir/output.log"
    
    TIME=$(grep "RESULT:" "$exp_dir/output.log" | cut -d: -f2 || echo "0")
    CPU_SEC=$(echo "$workers * 2 * $TIME" | bc 2>/dev/null || echo "0")
    
    cat > "$exp_dir/summary.json" <<EOF
{"name":"$name","workers":$workers,"cpus":$((workers*2)),"time_s":$TIME,"cpu_seconds":$CPU_SEC}
EOF
}

for cfg in $CONFIGS; do
    name=${cfg%:*}
    workers=${cfg#*:}
    run_config "$name" "$workers"
done

kubectl delete raycluster --all -n $NS 2>/dev/null || true

echo ""
echo "=== Results ==="
for d in "$RESULTS"/*/; do
    [ -f "$d/summary.json" ] && cat "$d/summary.json" && echo ""
done

# Analysis
python3 << 'PY'
import os, json, glob

d = os.environ.get('RESULTS', 'results')
exps = {}
for f in glob.glob(f"{d}/*/summary.json"):
    with open(f) as fp:
        e = json.load(fp)
        exps[e['name']] = e

if exps:
    print("\n" + "="*70)
    print(f"{'Config':<20} {'Workers':>8} {'Time(s)':>10} {'Speedup':>10} {'CPU-Sec':>12}")
    print("-"*70)
    
    base_time = exps.get('reactive-1w', {}).get('time_s', 1)
    for name in sorted(exps.keys()):
        e = exps[name]
        t = float(e.get('time_s', 0))
        speedup = base_time / t if t > 0 else 0
        print(f"{name:<20} {e['workers']:>8} {t:>10.2f} {speedup:>10.2f}x {e.get('cpu_seconds',0):>12.1f}")
    print("="*70)

with open(f"{d}/comprehensive_analysis.json", 'w') as f:
    json.dump(exps, f, indent=2)
PY

echo ""
echo "Done. Results in $RESULTS/"
