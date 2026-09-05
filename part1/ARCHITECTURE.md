Data Sync — Architecture
1. High-Level Architecture
```mermaid
flowchart LR
    C[Client] --> LB[Ingress / Load Balancer]
    LB --> S[ClusterIP Service]
    S --> P1[data-sync Pod]
    S --> P2[data-sync Pod]
    S --> P3[data-sync Pod]

    P1 --> R[Redis]
    P2 --> R
    P3 --> R

    P1 --> M[/metrics]
    P2 --> M
    P3 --> M

    M --> PR[Prometheus]
    PR --> G[Grafana]

    P1 --> L[Log Pipeline / Loki]

    HPA[Horizontal Pod Autoscaler] --> P1
    HPA --> P2
    HPA --> P3

    N[Metrics Server] --> HPA
    Z[GKE Node Pools / Cluster Autoscaler] --> P1
    Z --> P2
    Z --> P3
```
2. Application Layer
The `data-sync` service runs as a Kubernetes Deployment.
The application is exposed internally through a ClusterIP Service. An ingress or external load balancer can be placed in front of the Service when external access is required.
Each application pod exposes:
HTTP application endpoint
`/health` for health checks
`/metrics` for Prometheus scraping
3. Redis
Redis is treated as an existing dependency.
The Redis endpoint is supplied through configuration while the password is supplied through a Kubernetes Secret.
The application must not store the Redis password in a ConfigMap or source-control file.
4. Deployment Configuration
Helm is responsible for the reusable workload definition.
The chart contains:
Deployment
Service
ConfigMap
Secret
ExternalSecret integration
HPA
PDB
ServiceMonitor
Environment-specific values are maintained separately for staging and production.
5. Production Policy
Kustomize is used for production-specific workload policy.
The production workload is configured for:
Multi-zone topology spreading
Production replica count
Production resources
Production Redis endpoint
Production autoscaling
Production secret source
This keeps the base Helm chart reusable while allowing production policy to remain explicit.
6. GitOps
Argo CD is the deployment controller.
The desired state is stored in Git and Argo CD continuously reconciles the cluster against that state.
A typical synchronization dependency is:
External Secrets Operator
Secret-store resources
Supporting infrastructure such as Metrics Server / monitoring
Application workload
Production policy
Automated sync and self-healing are enabled for the application.
7. Scaling
The baseline implementation uses CPU-based HPA.
Production starts with 3 replicas and can scale to 20 replicas.
The HPA is intentionally bounded because pod scaling alone cannot solve insufficient node capacity. Cluster/node autoscaling or pre-provisioned capacity must provide enough nodes for pending pods.
For workloads where request rate, queue depth, or another demand metric is a better predictor than CPU, KEDA or a custom/external metric should be considered.
8. Availability
Production availability is improved through:
Minimum 3 replicas
Readiness probes
Liveness probes
PodDisruptionBudget
Rolling update strategy
`maxUnavailable: 0`
Topology spreading across zones
Adequate resource requests
Spare node capacity
Topology spreading prevents all replicas from being concentrated in a single availability zone when the scheduler has enough eligible capacity.
9. Security
Containers should run with a restrictive security context:
Non-root user
Read-only root filesystem where supported
No privilege escalation
Minimal Linux capabilities
Secret values kept outside ConfigMaps
In a production environment, AWS Secrets Manager, Vault, or another managed secret system should be preferred over manually maintained Kubernetes Secret manifests.
10. Observability
The service exposes Prometheus metrics.
A ServiceMonitor configures Prometheus scraping at a regular interval.
Important operational signals include:
Request rate
p50/p95/p99 latency
HTTP 5xx rate
CPU utilization
Memory utilization
Pod restart count
Pending pods
Startup/readiness duration
Redis latency
Redis connection errors
Queue depth where applicable
Logs can be shipped to the organization's centralized logging platform or Loki.
11. CI/CD Validation
CI should validate:
YAML syntax
Helm lint
Helm rendering for default/staging/production
Kubernetes schema compatibility
Kustomize build
Ansible syntax
ansible-lint
Secret scanning
Security/policy checks on rendered manifests
The objective is to fail invalid infrastructure before it reaches the cluster.