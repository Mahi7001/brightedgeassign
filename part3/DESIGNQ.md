# Part 3 – Design

## 1. Scaling Strategy

The main reason for the current scale-out delay is that CPU-based HPA reacts after
CPU utilization has already increased, while new pods also require startup time.
For a burst of roughly 2,000 requests/second, I would use a combination of
request-driven/event-driven scaling, HPA tuning, and pre-warming.

KEDA would be my preferred approach when a suitable application metric is
available. Instead of waiting for CPU utilization to become high, KEDA can scale
the workload based on a metric that represents incoming work, such as request
rate, queue depth, or pending work. This allows scaling to begin earlier during a
traffic burst.

I would also tune the HPA/KEDA configuration to reduce reaction time by lowering
the polling/sampling interval where appropriate and setting an appropriate
scale-up policy. The deployment should maintain a small number of warm replicas
rather than scaling from zero or a very small baseline. For example, maintaining
a minimum number of ready pods during peak periods reduces the time spent waiting
for pod startup.

The primary metrics I would monitor are:

- Requests per second
- Request latency, particularly p95/p99
- Number of pending/queued requests
- Pod readiness/startup time
- CPU and memory utilization
- Redis connection count and connection errors
- HPA/KEDA desired versus current replicas

The target would be to start scaling before existing pods become saturated and
keep scale-out plus readiness below 20 seconds.

The trade-off is that pre-warming additional replicas increases resource cost.
KEDA also introduces another scaling component and requires a reliable scaling
metric. CPU-based HPA is simpler, but it reacts later because CPU saturation is a
consequence of traffic rather than an early indication of incoming load.

## 2. Workload Isolation

I would first use Kubernetes scheduling primitives to prevent `data-sync` from
being placed on nodes dominated by ClickHouse workloads.

I would create a dedicated node pool for data-sync when the workload's latency
requirements justify stronger isolation. Nodes in this pool would have a label
such as:

`workload=data-sync`

and a taint such as:

`workload=data-sync:NoSchedule`

The data-sync Deployment would then use node affinity to prefer or require nodes
with the appropriate label, together with a toleration for the taint. This gives
the scheduler an explicit placement rule and prevents unrelated workloads from
being scheduled onto those nodes.

PriorityClass can be used to ensure data-sync receives scheduling preference
over lower-priority workloads when resources become constrained. However,
priority should not be treated as CPU isolation by itself.

I would also define appropriate CPU and memory requests and limits for data-sync.
ResourceQuota can be applied at the namespace level to prevent the workload from
consuming unlimited resources. These controls make resource consumption
predictable and help the scheduler make better placement decisions.

For a moderate level of isolation, affinity, taints/tolerations, requests/limits,
PriorityClass, and ResourceQuota may be sufficient. I would move to a dedicated
GKE node pool when latency becomes business-critical, ClickHouse continues to
create resource contention, or the workload needs predictable CPU capacity.
Dedicated nodes provide stronger isolation but increase cost and reduce overall
cluster utilization.

## 3. Zero-Downtime Secret Rotation

For `REDIS_PASSWORD`, I would use an external secret-management system rather
than storing the password directly in the Deployment manifest or Git repository.
The secret would be delivered to Kubernetes as a Secret and consumed by the
application.

Rotation should use a rolling deployment rather than restarting all replicas at
once. A new password would first be made available to the application through
the secret-delivery mechanism. The Deployment would then gradually replace old
pods with new pods using a rolling update strategy.

The rollout should maintain availability by ensuring that enough replicas remain
ready while old pods are terminated. Readiness probes should only mark a new pod
ready after it has successfully initialized and established the required Redis
connectivity.

I would verify the rotation by checking:

- The new Secret value is present in the expected workloads.
- Newly started pods successfully authenticate to Redis.
- The Deployment rollout completes successfully.
- Redis authentication failures do not increase.
- Request error rate and p95/p99 latency remain normal.
- Existing connections drain normally during pod replacement.

The rotation should therefore be treated as a controlled rolling change rather
than a cluster-wide restart. If the application supports reloading credentials
without restarting, that would further reduce disruption, but the rollout
approach provides a straightforward and observable fallback when credentials
are only loaded during application startup.