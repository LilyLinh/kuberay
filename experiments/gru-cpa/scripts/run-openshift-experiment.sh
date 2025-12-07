#!/bin/bash
# GRU-CPA vs HPA experiment on OpenShift
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(dirname "$DIR")"
RESULTS="$PROJECT/results"
TS=$(date +%Y%m%d-%H%M%S)
NS="gru-cpa-experiment"
RAY_IMG="quay.io/modh/ray:2.35.0-py311-cu121"

echo "GRU-CPA Experiment ($TS)"

oc whoami || { echo "Run 'oc login' first"; exit 1; }
oc new-project $NS 2>/dev/null || oc project $NS

kubectl delete raycluster --all -n $NS 2>/dev/null || true
sleep 5

mkdir -p "$RESULTS/baseline-$TS" "$RESULTS/gru-cpa-$TS"

run_test() {
    local name=$1 workers=$2 cfg=$3
    local dir="$RESULTS/$name-$TS"
    
    echo ""
    echo "=== $name ($workers workers) ==="
    
    kubectl apply -f "$PROJECT/manifests/$cfg"
    kubectl wait --for=condition=ready pod -l "ray.io/cluster" -n $NS --timeout=300s
    sleep 10
    
    HEAD=$(kubectl get pods -n $NS -l ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}')
    
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
print(f'Done in {time.time()-t0:.2f}s')
" 2>&1 | tee "$dir/output.log"
    
    TIME=$(grep "Done in" "$dir/output.log" | grep -oE '[0-9]+\.[0-9]+' || echo "N/A")
    echo "{\"name\":\"$name\",\"workers\":$workers,\"time\":\"$TIME\"}" > "$dir/summary.json"
    
    kubectl delete raycluster --all -n $NS 2>/dev/null || true
    sleep 5
}

run_test "baseline" 1 "raycluster-baseline-openshift.yaml"
run_test "gru-cpa" 4 "raycluster-grucpa-openshift.yaml"

echo ""
echo "=== Results ==="
cat "$RESULTS/baseline-$TS/summary.json"
cat "$RESULTS/gru-cpa-$TS/summary.json"
echo ""
echo "Saved to $RESULTS/"
