# Part 1 — Production Design

This document describes the production design considerations for the `data-sync` service, with focus on scaling, workload isolation, and zero-downtime secret rotation.

---

# 1. Scaling Strategy

## 1.1 Baseline Scaling

The production workload starts with three replicas:

```yaml
replicaCount: 3
```

The Horizontal Pod Autoscaler is configured with:

```text
Minimum replicas: 3
Maximum replicas: 20
Target CPU utilization: 70%
```

This provides a baseline level of availability while allowing the workload to scale horizontally as CPU utilization increases.

---

## 1.2 Why CPU-Based HPA

CPU utilization is used as the baseline autoscaling signal for the assignment.

The scaling flow is:

```text
                         Metrics Server
                              |
                              v
                             HPA
                              |
                    ┌─────────┴─────────┐
                    │                   │
                 CPU high            CPU low
                    │                   │
                    v                   v
                Scale up             Scale down
                    │                   │
                    └─────────┬─────────┘
                              v
                       data-sync Pods
```

CPU-based HPA is simple, Kubernetes-native, and directly supported by the standard Resource Metrics API.

---

## 1.3 Scaling Limitations

CPU is not always a direct representation of application demand.

For example, an HTTP workload may experience a significant increase in requests before CPU utilization reaches the HPA threshold.

This can result in scaling lag during sudden traffic bursts.

For a production system with a reliable workload metric, request rate or queue depth could be used as a more direct scaling signal.

An event-driven autoscaling mechanism such as KEDA could be considered when such a metric is available and reliable.

For this assignment, CPU-based HPA provides the baseline implementation without introducing additional scaling dependencies.

---

## 1.4 Pod Startup and Burst Handling

Autoscaling is only useful when Kubernetes can schedule new pods quickly.

The deployment therefore uses:

* small application images
* explicit resource requests
* startup checks
* pre-existing cluster capacity / node autoscaling

The target behavior for a sudden workload increase is:

```text
Traffic increases
      |
      v
CPU utilization increases
      |
      v
Metrics Server reports usage
      |
      v
HPA increases replicas
      |
      v
Kubernetes schedules new pods
      |      |
      v
Readiness probe passes
      |
      v
Service sends traffic to new pods
```

Node capacity must also be sufficient for newly requested pods. Increasing the HPA maximum does not help if there is no available node capacity to schedule the pods.

---

## 1.5 Scaling Signals to Monitor

The following metrics should be monitored:

### Application

* request rate
* p50 latency
* p95 latency
* p99 latency
* HTTP 5xx rate
* application error rate

### Kubernetes

* CPU utilization
* memory utilization
* pod count
* pending pods
* pod startup time
* restart count

### Redis

* connection count
* connection errors
* command latency
* authentication failures

These metrics help determine whether CPU is an appropriate scaling signal and whether the application or one of its dependencies is becoming the bottleneck.

---

# 2. Workload Isolation

## 2.1 Resource Isolation

The application has explicit CPU and memory requests and limits.

Production configuration:

```yaml
resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi
```

Requests provide the scheduler with the expected resource requirement.

Limits provide an upper resource boundary for the container.

---

## 2.2 Availability-Zone Distribution

Production pods are distributed across availability zones using:

```text
topology.kubernetes.io/zone
```

The production Kustomization applies:

```yaml
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: DoNotSchedule
```

This prevents the scheduler from concentrating replicas into a single zone when suitable topology information is available.

With three replicas and multiple zones, the desired distribution is approximately:

```text
Zone A       Zone B       Zone C
  │            │            │
 Pod 1        Pod 2        Pod 3
```

This reduces the impact of an availability-zone failure.

---

## 2.3 Pod Disruption Budget

A PodDisruptionBudget is enabled for the workload.

The purpose is to limit voluntary disruptions during operations such as:

* node maintenance
* node draining
* cluster maintenance

This works together with multiple replicas to reduce the probability of all application instances being voluntarily disrupted at the same time.

---

## 2.4 Scheduling Considerations

The production workload already defines:

* resource requests
* resource limits
* topology spread constraints
* PDB
* rolling deployment strategy

These provide the baseline isolation and availability controls required for the service.

If future production measurements show significant contention with other workloads, dedicated node pools and additional scheduling constraints can be introduced as an operational optimization.

Such isolation should be driven by observed contention rather than added without evidence.

---

# 3. Zero-Downtime Secret Rotation

## 3.1 Secret Architecture

Redis credentials are stored outside Git in AWS Secrets Manager.

External Secrets Operator synchronizes the credential into Kubernetes.

```text
AWS Secrets Manager
        |
        v
External Secrets Operator
        |
        v
Kubernetes Secret
        |
        v
data-sync
```

The application consumes the generated Kubernetes Secret through environment variables.

---

## 3.2 Rotation Sequence

A safe Redis credential rotation should follow an overlapping-credential approach where the Redis authentication mechanism supports it.

### Step 1 — Create New Credential

Create a new Redis credential while the existing credential remains valid.

```text
Old credential: VALID
New credential: VALID
```

This ensures currently running application pods continue working.

---

### Step 2 — Update AWS Secrets Manager

Update the secret in AWS Secrets Manager with the new credential.

```text
AWS Secrets Manager
        |
        v
New REDIS_PASSWORD
```

---

### Step 3 — ESO Synchronizes the Secret

External Secrets Operator detects the changed source secret and updates the Kubernetes Secret.

```text
AWS Secrets Manager
        |
        v
ESO reconciliation
        |
        v
Kubernetes Secret updated
```

---

### Step 4 — Reloader Triggers Deployment Rollout

Stakater Reloader detects the Kubernetes Secret change.

The Deployment is then restarted using its rolling update strategy.

```text
Secret changed
     |
     v
Reloader
     |
     v
Deployment rollout
```

---

### Step 5 — New Pod Starts

The replacement pod receives the new `REDIS_PASSWORD`.

The startup probe allows the application sufficient time to initialize.

The readiness probe ensures the pod is only added to service traffic after it is ready.

```text
New Pod
   |   |
   v
Application initialization
   |
   v
Redis authentication
   |
   v
Readiness Probe
   |
   v
Pod receives traffic
```

---

### Step 6 — Old Pod Terminates

The Deployment uses:

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxUnavailable: 0
    maxSurge: 1
```

Therefore, the new pod becomes available before an existing pod is intentionally removed.

With three replicas, the rollout proceeds incrementally.

```text
Before:

Pod 1   Pod 2   Pod 3
  ✓       ✓       ✓

During rollout:

Pod 1   Pod 2   Pod 3   Pod 4
  ✓       ✓       ✓       ✓
                       ↑
                  New credential

After:

Pod 2   Pod 3   Pod 4
  ✓       ✓       ✓
```

---

## 3.3 Credential Revocation

The old Redis credential should only be revoked after confirming that the replacement pods are successfully authenticating with the new credential.

Operational checks should include:

* pod readiness
* Redis authentication failures
* Redis connection errors
* application 5xx responses
* application logs
* Redis connectivity

Once all application instances are confirmed to use the new credential, the old credential can be revoked.

---

## 3.4 Failure Handling

If new pods fail to authenticate with Redis:

```text
New pod
   |
   v
Redis authentication failure
   |
   v
Readiness fails
   |
   v
Pod does not receive traffic
```

The old healthy pods remain available because:

```yaml
maxUnavailable: 0
```

The old credential should not be revoked until successful authentication using the new credential has been confirmed.

This provides a safe rollback point.

---

# 4. Configuration vs Secret Changes

Configuration and secrets are handled differently.

## ConfigMap

The Deployment includes a ConfigMap checksum annotation.

```text
ConfigMap changes
       |
       v
Checksum changes
       |
       v
Pod template changes
       |
       v
Rolling update
```

## Secret

Secrets are synchronized by External Secrets Operator and watched by Stakater Reloader.

```text
AWS Secret changes
       |
       v
ESO updates K8s Secret
       |
       v
Reloader detects change
       |
       v
Rolling update
```

This ensures that configuration and secret changes are reflected in new application pods.

---

# 5. Production Failure Scenarios

## Scenario 1 — New Pod Cannot Start

If a new pod cannot start:

```text
New Pod
   |
   v
Startup failure
   |
   v
Pod never becomes Ready
```

The existing ready pods continue serving traffic.

---

## Scenario 2 — Redis Authentication Failure

If the new Redis credential is incorrect:

```text
New Pod
   |
   v
Redis authentication failure
   |
   v
Readiness failure
```

Existing healthy pods should remain available until the credential issue is resolved.

The old credential should remain valid during the transition.

---

## Scenario 3 — Zone Failure

If one availability zone becomes unavailable, topology spreading reduces the likelihood that all replicas are located in that zone.

With three replicas distributed across three zones:

```text
Zone A       Zone B       Zone C
 Pod 1        Pod 2        Pod 3
   X           ✓            ✓
```

The remaining replicas can continue serving traffic, subject to the health of the cluster and dependencies.

---

## Scenario 4 — Traffic Spike

```text
Traffic spike
     |
     v
CPU increases
     |
     v
Metrics Server
     |
     v
HPA
     |
     v
Additional replicas
     |
     v
Service distributes traffic
```

If node capacity is insufficient, cluster/node autoscaling must provide additional capacity before all requested replicas can be scheduled.

---

# 6. Summary

The production design uses Kubernetes-native mechanisms wherever possible:

```text id="gj3v4f"
                ┌─────────────────────┐
                │      Argo CD        │
                └──────────┬──────────┘
                           │
                           ▼
                  Helm + Kustomize
                           │
                           ▼
                  Kubernetes Deployment
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
        HPA              PDB        Topology Spread
          │                │                │
          └────────────────┼────────────────┘
                           ▼
                    data-sync Pods
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
            Redis                   Prometheus
```

The primary production objectives are:

1. **Availability** through multiple replicas, PDBs, topology spreading, and controlled rolling updates.
2. **Scalability** through CPU-based HPA and sufficient underlying node capacity.
3. **Security** through external secret management and restricted container privileges.
4. **Safe secret rotation** through ESO, Reloader, overlapping credentials, and rolling updates.
5. **Observability** through Prometheus metrics and ServiceMonitor.
6. **Repeatability** through Helm, Kustomize, and Argo CD.
