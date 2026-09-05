# Part 1 — Architecture Decisions

This document records the key implementation decisions for the production deployment of the `data-sync` service.

The decisions are focused on the requirements of the assignment and the current implementation.

---

## 1. Helm for Reusable Workload Definition

### Decision

Use Helm as the primary packaging mechanism for the `data-sync` Kubernetes workload.

The Helm chart contains the reusable Kubernetes resources:

* Deployment
* Service
* ConfigMap
* ExternalSecret
* HPA
* PodDisruptionBudget
* ServiceMonitor

Environment-specific configuration is supplied through values files.

### Rationale

Helm provides:

* reusable templates
* configurable deployments
* environment-specific values
* consistent resource naming
* straightforward validation using `helm lint` and `helm template`

This keeps the common application definition in one place.

---

## 2. Kustomize for Production-Specific Policy

### Decision

Use Kustomize for production-specific Kubernetes configuration.

The current production Kustomization uses Kustomize's Helm integration to render the Helm chart and applies production-specific patches.

The main production policy added through Kustomize is topology spreading across availability zones.

### Rationale

Helm is responsible for the reusable application configuration, while Kustomize provides a convenient layer for environment-specific Kubernetes workload policy.

This avoids putting production-only scheduling policy directly into the generic Helm chart.

### Trade-off

Using Kustomize's Helm integration means Helm rendering is performed as part of the Kustomize build.

The benefit is that the production configuration can be built as a single declarative Kustomization without requiring a separate manually maintained rendered-manifest directory.

---

## 3. External Secrets Operator for Secret Delivery

### Decision

Use External Secrets Operator to synchronize the Redis credential from AWS Secrets Manager into a Kubernetes Secret.

The application does not contain the actual Redis password in Git.

The flow is:

```text id="q9a4ru"
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

### Rationale

This provides separation between application configuration and sensitive credentials.

AWS Secrets Manager remains the source of truth, while Kubernetes receives only the Secret required by the workload.

EKS Pod Identity is used to provide AWS permissions to External Secrets Operator.

### Trade-off

This introduces an additional controller and dependency in the cluster, but provides a significantly better secret-management model than storing credentials directly in Helm values or Git.

---

## 4. No Kubernetes Secret Manifest for the Redis Password

### Decision

Do not maintain a conventional Helm-generated Kubernetes Secret containing the actual Redis password.

The Kubernetes Secret is created and managed by External Secrets Operator.

### Rationale

A regular Helm Secret would require the credential to be supplied through Helm values or another deployment mechanism.

Using External Secrets Operator keeps the sensitive value outside the Git repository and allows AWS Secrets Manager to remain the source of truth.

---

## 5. Stakater Reloader for Secret Changes

### Decision

Use Stakater Reloader to restart the `data-sync` Deployment when the Kubernetes Secret changes.

The Deployment contains:

```yaml id="gj7tqf"
reloader.stakater.com/auto: "true"
```

### Rationale

Updating a Kubernetes Secret does not automatically restart existing application pods.

The application consumes the Redis credential as an environment variable, so a new pod is required to load the updated value.

Reloader provides this restart mechanism.

### Secret Rotation Flow

```text id="w6d3ne"
AWS Secrets Manager
       |
       v
ESO updates Kubernetes Secret
       |
       v
Reloader detects change
       |
       v
Deployment rolling update
       |
       v
New pods consume updated credential
```

---

## 6. RollingUpdate Strategy

### Decision

Use a controlled Kubernetes rolling update:

```yaml id="x7r2jh"
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxUnavailable: 0
    maxSurge: 1
```

### Rationale

The production service should remain available during normal deployments and Secret-triggered restarts.

`maxUnavailable: 0` ensures existing pods are not intentionally made unavailable before replacement capacity is available.

`maxSurge: 1` allows one additional pod during the update.

Readiness checks ensure that a replacement pod is considered ready before it receives traffic.

### Trade-off

During an update, the workload may temporarily use additional cluster capacity because of the surge pod.

This is an intentional trade-off for availability.

---

## 7. Startup, Readiness and Liveness Probes

### Decision

Use all three Kubernetes probe types.

### Startup Probe

The startup probe provides additional time for the application to initialize.

### Readiness Probe

The readiness probe controls whether the pod receives traffic.

### Liveness Probe

The liveness probe detects an unhealthy running application.

### Rationale

Using separate probes avoids treating slow startup as an application failure while still allowing Kubernetes to detect unhealthy containers after startup.

---

## 8. Production Replica Count

### Decision

Production starts with three replicas.

```yaml id="k73h1k"
replicaCount: 3
```

### Rationale

A single replica creates a single point of failure.

Three replicas provide basic redundancy and allow the service to remain available during normal pod replacement and node-level disruption.

The HPA can increase the number of replicas when CPU utilization increases.

---

## 9. Horizontal Pod Autoscaler

### Decision

Use CPU-based Horizontal Pod Autoscaling for the assignment.

Production configuration:

```text id="s6vlcq"
Minimum replicas: 3
Maximum replicas: 20
Target CPU: 70%
```

### Rationale

CPU-based HPA is simple, supported directly by Kubernetes, and appropriate as a baseline scaling mechanism for the service.

Metrics Server provides the Kubernetes Resource Metrics API required by the HPA.

### Trade-off

CPU utilization is an indirect measure of application demand.

For workloads where request rate, queue depth, or another workload-specific metric is a better predictor of demand, a custom or event-driven scaling mechanism could provide faster scaling.

For this assignment, CPU-based HPA keeps the implementation simple and directly testable.

---

## 10. Metrics Server and Prometheus Have Different Roles

### Decision

Use Metrics Server for Kubernetes resource metrics and Prometheus for application observability.

### Metrics Server

Provides metrics through the Kubernetes Resource Metrics API used by:

```text id="g4kz9s"
HPA
kubectl top
```

### Prometheus

Collects application and infrastructure metrics for monitoring and visualization.

### Rationale

These components solve different problems.

Prometheus does not replace the standard Metrics API required by a normal CPU-based HPA.

---

## 11. PodDisruptionBudget

### Decision

Enable a PodDisruptionBudget for the production workload.

### Rationale

A PDB limits the number of application pods that can be voluntarily disrupted at the same time.

This provides additional protection during operations such as node maintenance or cluster maintenance.

The application already runs multiple replicas, making a PDB useful for maintaining availability during voluntary disruptions.

---

## 12. Topology Spread Across Availability Zones

### Decision

Spread production `data-sync` pods across:

```text id="atj2xh"
topology.kubernetes.io/zone
```

with:

```text id="hgj0er"
maxSkew: 1
whenUnsatisfiable: DoNotSchedule
```

### Rationale

Without topology spreading, Kubernetes may place multiple replicas in the same availability zone.

A zone-level failure could therefore affect a large portion of the service.

Topology spreading encourages an even distribution of replicas across available zones.

### Trade-off

`DoNotSchedule` can prevent a pod from being scheduled when the required topology distribution cannot be satisfied.

This prioritizes the availability-zone distribution requirement over placing a pod in an otherwise unsuitable topology.

---

## 13. Resource Requests and Limits

### Decision

Define explicit CPU and memory requests and limits.

Production:

```yaml id="p3skj5"
requests:
  cpu: 500m
  memory: 512Mi

limits:
  cpu: 1000m
  memory: 1Gi
```

### Rationale

Resource requests allow Kubernetes to make informed scheduling decisions.

Limits prevent a container from consuming unlimited resources and provide resource boundaries between workloads.

Resource requests also provide the CPU utilization baseline used by the HPA.

---

## 14. Container Security Context

### Decision

Run the application with a restricted security context.

The workload uses:

```text id="ax6g9x"
runAsNonRoot: true
seccompProfile: RuntimeDefault
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities: ALL dropped
```

### Rationale

The application does not require privileged container capabilities.

Removing unnecessary privileges reduces the potential impact of a container compromise.

The read-only root filesystem further limits the ability of the application to modify the container filesystem.

---

## 15. ConfigMap Checksum

### Decision

Include a checksum of the ConfigMap in the Deployment Pod template.

### Rationale

A ConfigMap update does not automatically cause a Deployment rollout when its values are consumed through environment variables.

The checksum changes when the rendered ConfigMap changes:

```text id="h9cqki"
ConfigMap changes
      |
      v
Checksum changes
      |
      v
Pod template changes
      |
      v
Deployment rollout
```

This ensures that updated non-sensitive configuration is loaded by newly created pods.

---

## 16. ServiceMonitor for Prometheus

### Decision

Expose application metrics through a ServiceMonitor.

The ServiceMonitor uses a 30-second scrape interval.

### Rationale

The application exposes a Prometheus-compatible `/metrics` endpoint.

Using a ServiceMonitor integrates the workload with the existing Prometheus Operator deployment without requiring Prometheus configuration to be manually modified for each application.

---

## 17. Argo CD for Deployment Management

### Decision

Use Argo CD to deploy and reconcile the Kubernetes resources.

Production uses automated:

* synchronization
* pruning
* self-healing

### Rationale

Argo CD provides a GitOps deployment model where Git represents the desired state.

If a managed resource is changed manually in the cluster, Argo CD can reconcile it back to the state defined in Git.

---

## 18. Decision Summary

| Decision                    | Choice                      | Reason                                 |
| --------------------------- | --------------------------- | -------------------------------------- |
| Workload packaging          | Helm                        | Reusable templates                     |
| Production policy           | Kustomize                   | Environment-specific Kubernetes policy |
| Secret source               | AWS Secrets Manager         | Centralized secret storage             |
| Secret synchronization      | External Secrets Operator   | Avoid credentials in Git               |
| Secret-triggered restart    | Stakater Reloader           | Reload environment variables           |
| Deployment strategy         | RollingUpdate               | Minimize planned downtime              |
| Minimum production replicas | 3                           | Basic redundancy                       |
| Autoscaling                 | CPU HPA                     | Simple Kubernetes-native scaling       |
| HPA metrics                 | Metrics Server              | Kubernetes Resource Metrics API        |
| Monitoring                  | Prometheus + ServiceMonitor | Application observability              |
| Availability                | PDB + topology spreading    | Reduce disruption impact               |
| Security                    | Restricted security context | Reduce container privileges            |
| Configuration rollout       | ConfigMap checksum          | Trigger rollout on config changes      |
| Deployment management       | Argo CD                     | GitOps and reconciliation              |

These decisions intentionally focus on the production requirements of the assignment rather than introducing additional platform components that are not required.
