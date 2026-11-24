# Repository Guidelines

## Project Structure & Module Organization

LabOnDemand is a Dockerized FastAPI platform with a React/Vite frontend. Backend source lives in `backend/` and is served as `backend.main:app` by the `api` service. The main frontend application lives in `frontend-app/` and is built into an Nginx image by the `frontend` service. The former static `frontend/` directory has been removed.

Integration and regression tests belong in `backend/tests/` (unit/API suite, `pytest.ini` lives in `backend/`). The top-level `tests/` directory holds load and integration scripts (for example `load_test_deployments.py`), not the main suite. Deployment and operations assets are split across `compose.yaml` (dev + `tests` profile), `compose.prod.yaml` (production override), `Dockerfile` (API image: `test` and `runtime` targets), `.github/workflows/`, `frontend-app/Dockerfile`, `nginx/`, `dockerfiles/`, `deploy/` (Kubernetes manifests), `kubeconfig.yaml`, and `documentation/`. Shared images and diagrams are stored under `Diagrammes/Images/`.

## Before Starting Work

Several environment facts are stable and documented; re-discovering them is wasted work.

- Check the live state first instead of assuming: `docker compose ps`, `docker compose logs api --since 10m`, and
  `kubectl --kubeconfig kubeconfig.yaml get pods -A | grep -v -E "kube-system|traefik"`.
- Read the relevant docs before touching a subsystem: `documentation/*.md` (resource limits, storage, admin guide)
  and `dockerfiles/<image>/README.md` (image contents, ports, credentials, build/push procedure).
- Do not rebuild or re-push a lab image unless its Dockerfile (or a `--build-arg` input) changed. amd64 builds run
  under emulation on Apple Silicon and take 10–20 minutes; BuildKit reuses cached layers after an interrupt.
- Do not run node image prune/pre-pull unless the task explicitly asks for it (it is slow and re-downloads images).
- Docker Hub credentials for `tutanka01` are already in the local credential store; no `docker login` is needed.

## Lab Kubernetes Cluster

User labs run on a k3s cluster, outside Docker Compose. `kubeconfig.yaml` at the repo root is the cluster credential;
always pass it explicitly (`kubectl --kubeconfig kubeconfig.yaml ...`).

- Nodes: `lod-k3s-1`, `lod-k3s-2` and `lod-k3s-cp` (control-plane, also runs workloads), each 8 vCPU / ~15.6 GiB
  ⇒ ~24 vCPU / ~47 GiB total. The API container mounts `kubeconfig.yaml` and talks to this cluster.
- One namespace per user (`labondemand-user-<id>`) with `baseline-quota` (ResourceQuota) and `baseline-limits`
  (LimitRange) applied by `ensure_namespace_baseline()`.
- Capacity guidance, per-runtime memory footprints and OOMKill checks: `documentation/resource-limits.md` §9.
- Node image maintenance uses a privileged debug pod (only when the task asks for it):
  ```bash
  kubectl --kubeconfig kubeconfig.yaml debug node/<node> --profile=sysadmin --image=alpine:3.20 -it -- \
    chroot /host /usr/local/bin/k3s ctr images prune --all
  kubectl --kubeconfig kubeconfig.yaml debug node/<node> --profile=sysadmin --image=alpine:3.20 -it -- \
    chroot /host /usr/local/bin/k3s ctr images pull docker.io/tutanka01/labondemand:<tag>
  ```
  Debug pods linger as `Completed`; clean them up afterwards with
  `kubectl --kubeconfig kubeconfig.yaml delete pods -n default --all`.

## Lab Images & Runtime Defaults

Lab desktop images (Eclipse, NetBeans, VNC base...) are published on Docker Hub under `tutanka01/labondemand`.
Cluster nodes are **amd64** while Apple Silicon defaults to arm64: build with buildx and push directly
(never a host `docker build` for these images):

```bash
docker buildx build --platform linux/amd64 --pull --provenance=false \
  -t tutanka01/labondemand:<immutable-tag> -t tutanka01/labondemand:<moving-tag> \
  --push dockerfiles/<image>
```

Hard-won rules:

- **Never reuse a tag for changed content.** kubelet uses `imagePullPolicy: IfNotPresent` for tagged images, so
  nodes keep the cached old image forever. Publish a dated immutable tag (`eclipsejava-ee-YYYYMMDD`), update the
  app defaults, then point the human-friendly tag at the same digest.
- **The published image can be older than the Dockerfile.** Verify the deployed image before diagnosing behavior
  (Docker Hub tag dates, `docker manifest inspect`, or inspect the file inside the pod). Example: the old Eclipse
  image still hard-coded `-Xmx2048m` inside a 2 Gi container, which caused OOMKilled (exit 137).
- Default images and resource floors live in `backend/templates.py` (static fallback) and `backend/seed.py`
  (`RuntimeConfig` defaults, synced to the DB at API startup; `uvicorn --reload` triggers the sync in dev). Keep
  `frontend-app/src/lib/format.ts` in sync for UI fallbacks.
- `_ensure_runtime_config()` only raises floors below the platform default, never lowers admin values, and migrates
  known legacy tags. When adding a new tag, add the superseded tag to its `legacy_images` set, otherwise existing
  DB rows keep the old image.
- **Existing deployments are not updated automatically**: `resume_application()` only scales replicas. After
  changing a default, patch the running Deployments (image + resources) or delete and recreate them. New Service
  ports must be patched on existing Services too.
- Resource floors declared by a RuntimeConfig beat the role clamp in `clamp_resources_for_role()`; the hard ceiling
  remains the namespace ResourceQuota (`_assert_user_quota`, `_preflight_k8s_quota`). Check what a new deployment
  will receive with `apply_deployment_config()` instead of guessing.

## Docker-First Development

This project runs under Docker Compose. Do not use host-level `npm`, `node`, `uvicorn`, `pip`, or local virtualenv commands for normal development tasks. Prefer commands that start with `docker compose` so dependency versions match the containers.

Use these examples:

- `cp .env.exemple .env`: create local configuration before running services.
- `docker compose up --build`: build and run the dev stack (API with `--reload` and `backend/` mounted, frontend, MariaDB, Redis).
- `docker compose up -d --build`: run the dev stack in the background.
- `docker compose -f compose.yaml -f compose.prod.yaml up -d --build`: production (baked code, no reload, only the frontend published, required secrets, healthchecks, log rotation).
- `docker compose down`: stop local containers while preserving named volumes.
- `docker compose logs -f api`: follow backend logs.
- `docker compose logs -f frontend`: follow frontend/Nginx logs.
- `docker compose --profile test run --rm --build tests`: run the backend test suite (Dockerfile `test` target; needs no `.env`, kubeconfig, MariaDB or Redis).
- `docker compose exec api python -m backend.reset_admin`: reset (or create) a local admin password.
- `docker compose build frontend`: validate the production frontend build through the Dockerfile.
- `docker compose build api`: rebuild the backend image after dependency or Dockerfile changes.

The `frontend-app/package.json` scripts are for the Docker image build and should not be run directly on the host with `npm`. If a frontend check requires Node tooling, run it through Docker or add an explicit Compose-supported workflow instead of introducing host dependency assumptions.

## Backend Guidelines

Use Python 3.13-compatible code for the container runtime. Follow PEP 8 with 4-space indentation, `snake_case` for functions and variables, `PascalCase` for classes, and explicit type hints on new FastAPI handlers and service functions. Keep backend logic inside `backend/` modules rather than embedding behavior in route handlers.

In dev the API container mounts `./backend`, `./kubeconfig.yaml` (at `/etc/labondemand/kubeconfig`, the image's `KUBECONFIG`) and `./logs`; `.env` is injected with `env_file`. The image runs as the non-root user `app` (UID 1000, build args `APP_UID`/`APP_GID`). Treat `kubeconfig.yaml` and `.env` as local secrets.

The API must stay a single uvicorn process (in-process cleanup loop and in-memory rate limiter): do not add `--workers`. Route handlers that do DB or Kubernetes work are plain `def` (FastAPI threadpool); keep `async def` for WebSockets, streaming and background loops, and move blocking calls there into a thread. Kubernetes calls have default timeouts (`K8S_CONNECT_TIMEOUT_SECONDS`, `K8S_READ_TIMEOUT_SECONDS`); when the cluster is unreachable, list/read endpoints return HTTP 503, never an empty 200. Avoid tests or code paths that require a live Kubernetes cluster unless clearly marked as integration-level.

## Frontend Guidelines

The active frontend is `frontend-app/`, built with React, TypeScript, Vite, Tailwind CSS, Radix UI, TanStack Query/Table, Xterm.js, and `lucide-react`. Prefer existing components and helpers in `frontend-app/src/components`, `frontend-app/src/lib`, and `frontend-app/src/hooks` before adding new abstractions.

Keep UI code typed and component-focused. Use descriptive filenames and colocate domain-specific UI under existing folders such as `components/admin`, `components/dashboard`, and `components/teacher`. Update locale files in `frontend-app/src/locales/` when adding user-facing text.

`docker compose build frontend` only rebuilds the image: recreate the service (`docker compose up -d --no-deps frontend`) to actually serve the new build.

## Testing Guidelines

Place backend tests in `backend/tests/` using `test_*.py` filenames and descriptive test function names such as `test_teacher_quota_is_enforced`. Prefer focused unit tests for authorization, session handling, template validation, Kubernetes object generation, and API regressions.

Run tests through Docker Compose (the same command runs in CI, `.github/workflows/ci.yml`):

```bash
docker compose --profile test run --rm --build tests
docker compose --profile test run --rm --build tests python -m pytest tests/test_auth.py -q   # cwd is backend/
```

The tests image bakes the code at build time: keep `--build`. The runtime API image has no pytest, so `docker compose exec api python -m pytest` does not work.

The suite is expected to be fully green; a failing test is a real regression, not a known failure.

If a test dependency is genuinely needed, add it to `backend/requirements-test.txt` (installed by the Dockerfile `test` stage) rather than relying on a host virtualenv.

For frontend changes, at minimum run `docker compose build frontend` to verify the TypeScript/Vite production build. For UI behavior changes, include screenshots or manual verification notes in the pull request.

## Commit & Pull Request Guidelines

Use short, imperative commit subjects, for example `Add Redis session cleanup` or `Fix deployment quota check`. Keep each commit scoped to one logical change. Pull requests should include a concise summary, test results, configuration changes, and screenshots for frontend UI changes. Link related issues when available and call out any changes to `.env`, Kubernetes manifests, database schema, Dockerfiles, Compose services, or security-sensitive behavior.

## Security & Configuration Tips

Never commit real `.env` files, kubeconfigs, logs, database dumps, or credentials. Use environment example files for documented defaults only. Keep `kubeconfig.yaml` local, review RBAC-sensitive changes carefully, and avoid logging session tokens, passwords, OIDC secrets, Redis passwords, database credentials, or Kubernetes bearer tokens.

MariaDB data is stored in the `mariadb_data` named volume. Do not remove volumes or reset data unless the user explicitly asks for a destructive cleanup.
