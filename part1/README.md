# Part 1 — Production-Ready Data Sync Service

## Overview

This part implements a production-oriented deployment setup for the `data-sync` microservice using:

* Kubernetes
* Helm
* Kustomize
* Argo CD
* External Secrets Operator
* AWS Secrets Manager
* Stakater Reloader
* Prometheus / ServiceMonitor
* Metrics Server
* Ansible

The implementation focuses on secure configuration, controlled deployments, autoscaling, observability, secret management, and production workload placement.

---

## Repository Structure

```text
part1/
├── app/
│
├── helm/
│   └── charts/
│       └── data-sync/
│           ├── Chart.yaml
│           ├── values.yaml
│           ├── values.schema.json
│           └── templates/
│               ├── deployment.yaml
│               ├── service.yaml
│               ├── configmap.yaml
│               ├── eso.yaml
│               ├── hpa.yaml
│               ├── pdb.yaml
│               ├── servicemonitor.yaml
│               └── _helpers.tpl
│
├── standard/
│   └── datasync/
│       └── production/
│           ├── kustomization.yaml
│           └── values.production.yaml
│
├── argocd/
│   └── apps/
│
├── eso/
│
└── reloader/
```

---

## Helm

Helm provides the reusable Kubernetes workload definition.

The chart contains the common application resources:

* Deployment
* Service
* ConfigMap
* ExternalSecret
* HPA
* PodDisruptionBudget
* ServiceMonitor

Environment-specific configuration is provided through Helm values.

For example, production overrides:

```yaml
replicaCount: 3

config:
  appEnv: "production"

resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 20
```

---

## Kustomize

Kustomize is used for production-specific Kubernetes workload policy.

The production Kustomization consumes the Helm chart using Kustomize's Helm integration and applies production-specific changes such as topology spreading.

This keeps reusable application configuration in Helm while keeping production workload policy in the production Kustomization.

The production topology policy spreads `data-sync` pods across availability zones:

```yaml
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: DoNotSchedule
```

---

## Secrets

Redis credentials are not stored directly in the Helm chart.

The production flow is:

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
data-sync Pod
```

The application consumes the generated Kubernetes Secret through:

```yaml
envFrom:
  - secretRef:
      name: data-sync-secret
```

This keeps the actual Redis password outside Git.

---

## Secret Rotation

External Secrets Operator periodically reconciles the Kubernetes Secret with AWS Secrets Manager.

Stakater Reloader watches the generated Secret and triggers a workload restart when the Secret changes.

The resulting flow is:

```text
AWS Secrets Manager
        |
        v
External Secrets Operator
        |
        v
Kubernetes Secret changes
        |
        v
Stakater Reloader
        |
        v
Rolling restart of data-sync
```

The Deployment uses a controlled rolling update strategy:

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxUnavailable: 0
    maxSurge: 1
```

This ensures existing healthy pods remain available while updated pods become ready.

---

## Security

The application Deployment is configured with Kubernetes security controls including:

* non-root container execution
* RuntimeDefault seccomp profile
* disabled privilege escalation
* dropped Linux capabilities
* read-only root filesystem

The Deployment also defines resource requests and limits to provide predictable scheduling and resource isolation.

---

## Health Checks

The application exposes `/health`.

Three probe mechanisms are used:

* Startup probe
* Readiness probe
* Liveness probe

The startup probe prevents liveness checks from restarting the container while the application is still starting.

Readiness controls whether a pod receives traffic.

Liveness detects an unhealthy application and allows Kubernetes to restart it.

---

## Autoscaling

Production uses Horizontal Pod Autoscaling:

```text
Minimum replicas: 3
Maximum replicas: 20
Target CPU utilization: 70%
```

Metrics Server provides the Kubernetes Resource Metrics API required by the CPU-based HPA.

Prometheus is used separately for application and infrastructure observability.

---

## Observability

The application exposes Prometheus metrics.

A ServiceMonitor is provided for Prometheus Operator-based monitoring.

The monitoring flow is:

```text
data-sync
    |
    +---- /metrics
            |
            v
       Prometheus
            |
            v
          Grafana
```

The ServiceMonitor is configured with a 30-second scrape interval.

---

## High Availability

Production runs at least three replicas.

The Deployment uses:

* rolling updates
* `maxUnavailable: 0`
* `maxSurge: 1`
* readiness checks
* PodDisruptionBudget
* topology spread constraints

Together these reduce planned downtime and improve availability during deployments and node disruptions.

---

## GitOps

Argo CD manages the Kubernetes resources from this repository.

Production follows:

```text
Git repository
      |
      v
    Argo CD
      |
      v
Kustomize / Helm
      |
      v
 Kubernetes
```

Argo CD is configured for automated synchronization, pruning, and self-healing for the production application.

---

## Validation

### Helm

```bash
helm lint part1/helm/charts/data-sync

helm template data-sync \
  part1/helm/charts/data-sync

helm template data-sync \
  part1/helm/charts/data-sync \
  -f part1/standard/datasync/production/values.production.yaml
```

### Kustomize

```bash
kubectl kustomize part1/standard/datasync/production
```

### Kubernetes

```bash
kubectl -n data-sync-production get deploy,svc,hpa,pdb,servicemonitor

kubectl -n data-sync-production rollout status deployment/data-sync

kubectl -n data-sync-production get pods -o wide
```

---

## Production Design Goals

The implementation addresses the primary production concerns for the assignment:

| Area                     | Implementation                                   |
| ------------------------ | ------------------------------------------------ |
| Deployment               | Helm + Kustomize                                 |
| GitOps                   | Argo CD                                          |
| Secrets                  | AWS Secrets Manager + ESO                        |
| Secret-triggered restart | Stakater Reloader                                |
| Availability             | 3+ replicas + PDB                                |
| Deployment safety        | RollingUpdate                                    |
| Health                   | Startup/readiness/liveness probes                |
| Scaling                  | HPA + Metrics Server                             |
| Resource control         | Requests and limits                              |
| Workload placement       | Zone topology spreading                          |
| Monitoring               | Prometheus + ServiceMonitor                      |
| Security                 | Non-root + restricted container security context |

The design intentionally keeps reusable application configuration in Helm and production-specific workload policy in Kustomize.
