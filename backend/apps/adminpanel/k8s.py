"""A tiny read-only Kubernetes API reader for the admin System view (R14 §14).

In-cluster only: the pod's ServiceAccount token and CA from
/var/run/secrets/kubernetes.io/serviceaccount, plain HTTPS through httpx (already a
dependency). Outside a cluster, or when RBAC says no, every call returns a reason
instead of raising, so the page degrades to `available: false`.

RBAC it needs (deploy/k8s/base/admin-rbac.yaml):
  Role (namespace): ""/pods get,list · batch/jobs,cronjobs get,list
  ClusterRole:      ""/nodes get,list · metrics.k8s.io/nodes get,list
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
TIMEOUT_S = 4.0


class K8sUnavailable(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason            # not_in_cluster | forbidden | error


def _sa_dir() -> Path:
    return Path(os.environ.get("K8S_SA_DIR", str(SA_DIR)))


def in_cluster() -> bool:
    return bool(os.environ.get("KUBERNETES_SERVICE_HOST")) and (_sa_dir() / "token").exists()


def namespace() -> str:
    try:
        return (_sa_dir() / "namespace").read_text().strip() or "default"
    except OSError:
        return os.environ.get("POD_NAMESPACE", "default")


def get(path: str) -> dict:
    """GET an API path ("/api/v1/nodes"). Raises K8sUnavailable with a reason."""
    if not in_cluster():
        raise K8sUnavailable("not_in_cluster")
    host = os.environ["KUBERNETES_SERVICE_HOST"]
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"            # IPv6 service address
    try:
        token = (_sa_dir() / "token").read_text().strip()
        response = httpx.get(f"https://{host}:{port}{path}",
                             headers={"Authorization": f"Bearer {token}",
                                      "Accept": "application/json"},
                             verify=str(_sa_dir() / "ca.crt"), timeout=TIMEOUT_S)
    except (OSError, httpx.HTTPError) as exc:
        raise K8sUnavailable("error", str(exc)[:200]) from exc
    if response.status_code in (401, 403):
        raise K8sUnavailable("forbidden", f"{response.status_code} on {path}")
    if response.status_code >= 400:
        raise K8sUnavailable("error", f"{response.status_code} on {path}")
    try:
        return response.json()
    except ValueError as exc:
        raise K8sUnavailable("error", "not JSON") from exc


# --- quantities ---------------------------------------------------------------------------

_BIN = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40, "Pi": 2**50, "Ei": 2**60}
_DEC = {"n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12,
        "P": 1e15, "E": 1e18}


def quantity(value) -> float | None:
    """Kubernetes resource quantity -> float ("250m" -> 0.25, "2Gi" -> 2147483648)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for suffix, factor in _BIN.items():
        if text.endswith(suffix):
            return float(text[:-2]) * factor
    if text[-1] in _DEC:
        return float(text[:-1]) * _DEC[text[-1]]
    try:
        return float(text)
    except ValueError:
        return None


def nodes() -> list[dict]:
    items = get("/api/v1/nodes").get("items") or []
    usage = {}
    try:
        for m in get("/apis/metrics.k8s.io/v1beta1/nodes").get("items") or []:
            usage[m["metadata"]["name"]] = m.get("usage") or {}
    except K8sUnavailable:
        usage = {}          # metrics-server missing or not permitted: capacity only
    out = []
    for n in items:
        name = n["metadata"]["name"]
        status = n.get("status") or {}
        capacity, allocatable = status.get("capacity") or {}, status.get("allocatable") or {}
        ready = any(c.get("type") == "Ready" and c.get("status") == "True"
                    for c in status.get("conditions") or [])
        cpu = quantity(capacity.get("cpu")) or 0.0
        mem = quantity(capacity.get("memory")) or 0.0
        used = usage.get(name, {})
        cpu_used, mem_used = quantity(used.get("cpu")), quantity(used.get("memory"))
        disk = quantity(capacity.get("ephemeral-storage"))
        disk_alloc = quantity(allocatable.get("ephemeral-storage"))
        out.append({
            "name": name, "ready": ready, "cpu_cores": round(cpu, 2),
            "cpu_used_cores": round(cpu_used, 2) if cpu_used is not None else None,
            "cpu_pct": round(cpu_used / cpu * 100) if cpu_used is not None and cpu else None,
            "memory_bytes": int(mem),
            "memory_used_bytes": int(mem_used) if mem_used is not None else None,
            "memory_pct": round(mem_used / mem * 100) if mem_used is not None and mem else None,
            "disk_bytes": int(disk) if disk is not None else None,
            "disk_allocatable_bytes": int(disk_alloc) if disk_alloc is not None else None,
        })
    return out


def pods() -> list[dict]:
    items = get(f"/api/v1/namespaces/{namespace()}/pods").get("items") or []
    out = []
    for p in items:
        meta, status = p.get("metadata") or {}, p.get("status") or {}
        containers = status.get("containerStatuses") or []
        out.append({
            "name": meta.get("name"),
            "app": (meta.get("labels") or {}).get("app.kubernetes.io/name"),
            "phase": status.get("phase"),
            "ready": bool(containers) and all(c.get("ready") for c in containers),
            "restarts": sum(int(c.get("restartCount") or 0) for c in containers),
            "started_at": status.get("startTime"),
            "node": (p.get("spec") or {}).get("nodeName"),
        })
    return sorted(out, key=lambda p: (p["app"] or "", p["name"] or ""))


def own_image() -> str | None:
    """This pod's backend image (the deploy pins the tag to the git sha)."""
    name = os.environ.get("HOSTNAME")
    if not name:
        return None
    pod = get(f"/api/v1/namespaces/{namespace()}/pods/{name}")
    for c in (pod.get("spec") or {}).get("containers") or []:
        if c.get("name") == "backend" or "backend" in (c.get("image") or ""):
            return c.get("image")
    return None


def backup_status(cronjob: str = "postgres-backup") -> dict:
    ns = namespace()
    cj = get(f"/apis/batch/v1/namespaces/{ns}/cronjobs/{cronjob}")
    status, spec = cj.get("status") or {}, cj.get("spec") or {}
    jobs = []
    for j in get(f"/apis/batch/v1/namespaces/{ns}/jobs").get("items") or []:
        owners = (j.get("metadata") or {}).get("ownerReferences") or []
        if not any(o.get("kind") == "CronJob" and o.get("name") == cronjob for o in owners):
            continue
        js = j.get("status") or {}
        state = ("succeeded" if js.get("succeeded") else
                 "failed" if js.get("failed") and not js.get("active") else "running")
        jobs.append({"name": j["metadata"]["name"], "status": state,
                     "started_at": js.get("startTime"), "finished_at": js.get("completionTime")})
    jobs.sort(key=lambda j: j["started_at"] or "", reverse=True)
    return {"schedule": spec.get("schedule"),
            "last_success_at": status.get("lastSuccessfulTime"),
            "last_schedule_at": status.get("lastScheduleTime"), "jobs": jobs[:5]}
