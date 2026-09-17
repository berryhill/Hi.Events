# Hi.Events Helm deployment

Target: `admin.elementafestival.com`, namespace/release `hievents`, context `lke428841-ctx`.

## Delivery

`helm-release.yml` publishes `ghcr.io/berryhill/hi.events:<commit>` on main changes and records the immutable digest in its summary/artifact. Public frontend settings come from GitHub Secrets `VITE_FRONTEND_URL`, `VITE_API_URL_CLIENT`, and `VITE_APP_NAME`. They are build arguments and visible in browser code; never use this mechanism for credentials.

`helm-deploy.yml` is a manual production deployment. Select main and supply the published digest. It requires:

- `LINODE_KUBECONFIG`: base64-encoded UTF-8 YAML kubeconfig with context `lke428841-ctx`, authorized for namespace provisioning and Hi.Events resources. Single-line and line-wrapped base64 are supported. The deploy script decodes it into a temporary owner-only file. Do not copy unrelated credentials into CI.
- `GHCR_TOKEN`: durable credential with read access to this container package.
- `SMTP2GO_USERNAME` and `SMTP2GO_PASSWORD`: a dedicated SMTP user's credentials, not the SMTP2GO API key. These are projected into the `hievents-mail` Kubernetes Secret, never Helm values. The application is restarted after each deployment so configuration and rotated credentials are loaded by both web and queue processes.
- `HIEVENTS_RUNTIME_JSON`: JSON with exactly `APP_KEY`, `JWT_SECRET`, `POSTGRES_PASSWORD`, `DATABASE_URL`. The database URL must be `postgresql://hievents:<password>@hievents-postgres:5432/hievents`. Use a URL-safe generated password. Keep these values stable across deployments.

Secrets are passed on stdin to Kubernetes and are not Helm values. The deploy script suppresses credential-bearing command output. It does not export or copy credentials from other applications.

## Runtime and data

One all-in-one app replica uses Recreate because it also runs a scheduler and queue worker and mounts ReadWriteOnce uploads. Dedicated PostgreSQL 17 and Redis 7 StatefulSets have persistent volumes. The chart uses `linode-block-storage-retain`; it requests three 10 GiB claims. Provisioning these claims incurs provider storage costs. Single replicas are not highly available. Retained volumes are not backups.

The existing startup entrypoint runs migrations before serving and exits if migration fails. PostgreSQL may still be initializing on the first attempt; Kubernetes retries the app. Do not scale this deployment without splitting the scheduler and reviewing migration concurrency. The startup/readiness probe verifies the frontend login page, not database, queue, or complete registration health.

Helm waits for workloads but deliberately does not use automatic rollback: database migrations may make older code incompatible. A failed upgrade requires inspection and a compatible forward fix or a separately planned database restore. Existing secrets and volumes are not deleted automatically.

Public signup defaults to disabled. Bootstrap the first account through an explicitly authorized private setup before opening registration. Email uses SMTP2GO at `mail.smtp2go.com:587` with STARTTLS and certificate verification. The sender defaults to `Elementa Festival <tickets@elementafestival.com>`; verify the domain in SMTP2GO before sending. Non-secret mail settings are under `mail` in `values.yaml`. Confirm actual delivery and account sending limits before ticket sales; a successful rollout does not verify email delivery. Payment keys are absent. The upstream all-in-one image runs its supervisor as root; this initial chart is not a hardened non-root deployment.

## DNS and TLS

Create an A record `admin.elementafestival.com` pointing at `172.233.132.209`. Existing nginx and `letsencrypt-http` handle ingress and certificate issuance. Public DNS must work before HTTP-01 validation can complete. No DNS resources are modified by this chart.

## Verification

```sh
python3 helm/test_chart.py
kubectl --context lke428841-ctx -n hievents get pods,pvc,ingress,certificate
```

After deploying, verify HTTPS, login and API validation, upload persistence after a restart, scheduler/queue execution, and the intended account flow. Helm readiness alone does not prove those behaviors.

The local Docker Compose override is intentionally not part of this deployment.
