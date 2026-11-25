# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Prepare an owned Kubernetes deployment using the actual Nexent entry point."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from ipaddress import ip_address
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
from tempfile import TemporaryDirectory, TemporaryFile
import time
from uuid import uuid4

from jsonschema import Draft202012Validator
import yaml

from shared.case_evidence import write_case_evidence
from shared.runtime_scaling_model import MODEL_MODES


NAMESPACE = "nexent"
RUNTIME = "nexent-runtime"
GATEWAY = "nexent-gateway"
WEB = "nexent-web"
ROUTING_GATEWAY = "nexent-runtime-test-gateway"
MODEL_FIXTURE = "nexent-rs-model"
TRANSPORT_FIXTURE = "nexent-rs-transport"
CLUSTER_OPT_IN = "nexent.io/runtime-scaling-e2e"
RUN_LABEL = "nexent.io/runtime-scaling-e2e-run"
SCHEMA = Path(__file__).resolve().parents[2] / "config/runtime-scaling-k8s.schema.json"
UNCONFIGURED_DIGEST = "sha256:" + "0" * 64
IMAGE_ID_DIGEST = re.compile(r"(?:^|[@/])(sha256:[0-9a-f]{64})\Z")


class IsolationError(RuntimeError):
    """The test cannot prove it owns the deployment and all cleanup targets."""


@dataclass(frozen=True)
class Profile:
    kubeconfig: Path
    context: str
    cluster_uid: str
    storage_class: str
    image_source: str
    app_version: str
    backend_image_digests: tuple[str, ...]
    image_registry_prefix: str | None = None
    wait_seconds: int = 600

    @classmethod
    def load(cls, path: Path) -> "Profile":
        if not path.is_file():
            raise IsolationError("An isolated runtime-scaling-k8s.yaml profile is required")
        settings = yaml.safe_load(path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
        if not validator.is_valid(settings):
            raise IsolationError("Invalid runtime-scaling-k8s.yaml profile")
        if not settings.pop("enabled"):
            raise IsolationError("The Runtime scaling cluster has not been enabled")
        settings["backend_image_digests"] = tuple(settings["backend_image_digests"])
        if UNCONFIGURED_DIGEST in settings["backend_image_digests"]:
            raise IsolationError("Configure the candidate backend image digests in the Runtime scaling profile")
        settings.pop("schema_version")
        settings["kubeconfig"] = (path.parent / settings["kubeconfig"]).resolve(strict=False)
        if not settings["kubeconfig"].is_file():
            raise IsolationError("The profile's explicit kubeconfig does not exist")
        return cls(**settings)


def stage_deployment(repository: Path, destination: Path, *, agent_limit=None, scheduler_case=False,
                     agent_lane_queue_size=None, run_ttl_seconds=None) -> Path:
    """Use current deployment sources without copying active credentials or generated overrides."""
    ignored = shutil.ignore_patterns(".env", "monitoring.env", "deploy.options", "generated-*.yaml", "__pycache__")
    for child in ("k8s", "common", "sql", "docker/assets/official-skills-zip"):
        shutil.copytree(repository / "deploy" / child, destination / "deploy" / child, ignore=ignored)
    env = destination / "deploy/env"
    env.mkdir()
    for name in (".env.example", "monitoring.env.example", "image-source.general.env", "image-source.mainland.env"):
        shutil.copy2(repository / "deploy/env" / name, env / name)
    template = env / ".env.example"
    body = template.read_text(encoding="utf-8")
    if agent_limit is not None:
        if type(agent_limit) is not int or not 1 <= agent_limit <= 100:
            raise ValueError("Expected a bounded test Agent quota")
        body, replacements = re.subn(r"(?m)^RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS=.*$",
                                     f"RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS={agent_limit}",
                                     body)
        if replacements != 1:
            raise IsolationError("Expected one Agent quota assignment in the staging template")
    if agent_lane_queue_size is not None:
        if type(agent_lane_queue_size) is not int or agent_lane_queue_size not in (0, 1):
            raise ValueError("Expected a test Agent lane with zero or one queue slots")
        lane_settings = {"RUNTIME_AGENT_THREAD_MAX_WORKERS": 1,
                         "RUNTIME_AGENT_THREAD_MAX_QUEUE_SIZE": agent_lane_queue_size}
        if agent_lane_queue_size:
            lane_settings["RUNTIME_AGENT_THREAD_QUEUE_TIMEOUT_SECONDS"] = 90
        for key, value in lane_settings.items():
            body, replacements = re.subn(rf"(?m)^{key}=.*$", f"{key}={value}", body)
            if replacements != 1:
                raise IsolationError(f"Expected one {key} assignment in the staging template")
    if scheduler_case:
        for key, value in {"AGENT_AUTOMATION_ENABLED": "false", "AGENT_AUTOMATION_POLL_INTERVAL_SECONDS": "1",
                           "AGENT_AUTOMATION_MAX_CONCURRENT_RUNS": "1", "AGENT_AUTOMATION_LEASE_SECONDS": "30"}.items():
            body, replacements = re.subn(rf"(?m)^{key}=.*$", f"{key}={value}", body)
            if replacements > 1:
                raise IsolationError(f"Duplicate {key} in the staging template")
            if not replacements:
                body = body.rstrip("\n") + f"\n{key}={value}\n"
    if run_ttl_seconds is not None:
        if type(run_ttl_seconds) is not int or not 15 <= run_ttl_seconds <= 120:
            raise ValueError("Expected a bounded test Runtime run TTL")
        for key in ("RUNTIME_RUN_TTL_SECONDS", "RUNTIME_STREAM_TTL_SECONDS"):
            assignment = f"{key}={run_ttl_seconds}"
            body, replacements = re.subn(rf"(?m)^{key}=.*$", assignment, body)
            if replacements > 1:
                raise IsolationError(f"Duplicate {key} in the staging template")
            if not replacements:
                body = body.rstrip("\n") + "\n" + assignment + "\n"
    if agent_limit is not None or scheduler_case or agent_lane_queue_size is not None or run_ttl_seconds is not None:
        template.write_text(body, encoding="utf-8")
    constant = Path("backend/contracts/constants/environment.py")
    (destination / constant).parent.mkdir(parents=True)
    shutil.copy2(repository / constant, destination / constant)
    shutil.copy2(repository / "VERSION", destination / "VERSION")
    return destination / "deploy/k8s/deploy.sh"


@contextmanager
def isolated_runtime_release(repository: Path, profile: Profile, *, separate_workers=False, agent_limit=None,
                             scheduler_case=False, agent_lane_queue_size=None, run_ttl_seconds=None):
    with TemporaryDirectory(prefix="nexent-runtime-scaling-") as directory:
        scratch = Path(directory)
        script = stage_deployment(repository, scratch / "project", agent_limit=agent_limit,
                                  scheduler_case=scheduler_case, agent_lane_queue_size=agent_lane_queue_size,
                                  run_ttl_seconds=run_ttl_seconds)
        cluster = RuntimeScalingCluster(profile, scratch)
        with cluster.owned_namespace(separate_workers=separate_workers):
            yield cluster, script


def _execute(command, environment, timeout, *, stdin=None, cwd=None):
    with subprocess.Popen(
        command, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, cwd=cwd,
        text=True, start_new_session=True,
    ) as process:
        try:
            stdout, stderr = process.communicate(stdin, timeout=timeout)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


class RuntimeScalingCluster:
    def __init__(self, profile: Profile, scratch: Path):
        self.profile = profile
        self.scratch = scratch
        self.run_id = uuid4().hex
        self.namespace_uid = None
        self._command_env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(scratch),
            "LANG": "C.UTF-8",
            "KUBECONFIG": str(scratch / "kubeconfig.json"),
            "DOCKER_HOST": f"unix://{scratch / 'disabled-docker.sock'}",
        }

    def _kubectl_command(self, args, source_config=False):
        kubeconfig = self.profile.kubeconfig if source_config else self._command_env["KUBECONFIG"]
        return ["kubectl", "--kubeconfig", str(kubeconfig), "--context", self.profile.context, *args]

    def _kubectl(self, *args, stdin=None, timeout=30, source_config=False):
        result = _execute(
            self._kubectl_command(args, source_config),
            self._command_env, timeout, stdin=stdin,
        )
        if result.returncode:
            raise IsolationError(f"Kubernetes command {args[0]!r} failed (exit {result.returncode})")
        return result.stdout

    def _freeze_config(self):
        snapshot = self._kubectl("config", "view", "--minify", "--flatten", "--raw", "-o", "json", source_config=True)
        config = json.loads(snapshot)
        if config.get("current-context") != self.profile.context or len(config.get("contexts", ())) != 1:
            raise IsolationError("Could not pin the configured Kubernetes context")
        path = Path(self._command_env["KUBECONFIG"])
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
            stream.write(snapshot)
        return path

    def _read(self, *args):
        output = self._kubectl("get", *args, "-o", "json")
        return json.loads(output) if output.strip() else None

    def _require_test_cluster(self):
        metadata = (self._read("namespace", "kube-system") or {}).get("metadata", {})
        if metadata.get("uid") != self.profile.cluster_uid or metadata.get("labels", {}).get(CLUSTER_OPT_IN) != "true":
            raise IsolationError("Cluster UID or owner opt-in does not match the isolated Runtime profile")

    def _storage_volumes(self):
        return [volume for volume in self._read("pv")["items"]
                if volume["spec"].get("storageClassName") == self.profile.storage_class]

    def preflight(self, *, separate_workers=False):
        self._require_test_cluster()
        if self._read("namespace", NAMESPACE, "--ignore-not-found") is not None:
            raise IsolationError("The nexent namespace already exists; never adopt an existing deployment")
        nodes = self._read("nodes")["items"]
        schedulable = [node for node in nodes if _schedulable_linux_node(node)]
        if len(schedulable) < 2:
            raise IsolationError("The Runtime scaling suite requires two schedulable Ready Linux nodes")
        if separate_workers and not _eligible_worker_hosts(nodes):
            raise IsolationError("Cross-node Runtime proof requires at least two schedulable worker hosts")
        storage = self._read("storageclass", self.profile.storage_class) or {}
        if (not storage.get("provisioner") or storage["provisioner"] == "kubernetes.io/no-provisioner"
                or storage.get("reclaimPolicy", "Delete") != "Delete"):
            raise IsolationError("Use a dynamically provisioned test StorageClass with Delete reclaim policy")
        if self._storage_volumes():
            raise IsolationError("The reserved test StorageClass already contains volumes")

    @contextmanager
    def owned_namespace(self, *, separate_workers=False):
        config_path = self._freeze_config()
        try:
            self.preflight(separate_workers=separate_workers)
            namespace = {"apiVersion": "v1", "kind": "Namespace",
                         "metadata": {"name": NAMESPACE, "labels": {RUN_LABEL: self.run_id}}}
            try:
                created = json.loads(self._kubectl("create", "-f", "-", "-o", "json", stdin=json.dumps(namespace)))
                self.namespace_uid = created["metadata"]["uid"]
                self.require_owned_namespace()
                yield self
            finally:
                self._cleanup()
        finally:
            config_path.unlink()

    def resources(self, *args):
        return self._read(*args, "-n", NAMESPACE)

    def discovered_resources(self):
        return set(self._kubectl("api-resources", "--namespaced=true", "-o", "name").splitlines())

    def create_namespaced_fixture(self, manifest):
        self.require_owned_namespace()
        if manifest.get("kind") not in {"Pod", "Job", "Service", "ServiceAccount", "Role", "RoleBinding"}:
            raise ValueError("Unsupported isolated Runtime fixture kind")
        if manifest["kind"] == "Service":
            spec = manifest["spec"]
            if (spec.get("type", "ClusterIP") != "ClusterIP" or spec.get("externalIPs")
                    or spec.get("selector", {}).get(RUN_LABEL) != self.run_id
                    or any("nodePort" in port for port in spec["ports"])):
                raise IsolationError("A fixture Service must be cluster-internal and select only test-owned Pods")
        manifest = {**manifest, "metadata": {**manifest["metadata"], "namespace": NAMESPACE}}
        return json.loads(self._kubectl("create", "-n", NAMESPACE, "-f", "-", "-o", "json", stdin=json.dumps(manifest)))

    def wait_for_condition(self, resource, condition):
        self._kubectl("wait", "-n", NAMESPACE, f"--for=condition={condition}", resource,
                      f"--timeout={self.profile.wait_seconds}s", timeout=self.profile.wait_seconds + 10)

    def run_fixture_python(self, pod, source, *args, container=None):
        self.require_owned_namespace()
        target = ("-c", container) if container else ()
        return self._kubectl("exec", "-i", "-n", NAMESPACE, pod, *target, "--", "python", "-", *args,
                             stdin=source, timeout=self.profile.wait_seconds)

    def seed_runtime_identities(self, _pod, *, creator=False):
        source = Path(__file__).with_name("runtime_scaling_identity_seed.py").read_text(encoding="utf-8")
        options = ("creator",) if creator else ()
        output = self.run_fixture_python("deployment/nexent-config", source, self.run_id, *options)
        record, = (line.removeprefix("SCALING_IDENTITIES ") for line in output.splitlines()
                   if line.startswith("SCALING_IDENTITIES "))
        return json.loads(record)

    def seed_runtime_agent(self, _pod, *, other_scope=False, storage_pair=False):
        source = Path(__file__).with_name("runtime_scaling_agent_seed.py").read_text(encoding="utf-8")
        if other_scope and storage_pair:
            raise ValueError("Select one Runtime Agent seed scenario")
        options = ("storage-pair",) if storage_pair else ("other-scope",) if other_scope else ()
        output = self.run_fixture_python("deployment/nexent-config", source, self.run_id, *options)
        record, = (line.removeprefix("SCALING_AGENT ") for line in output.splitlines()
                   if line.startswith("SCALING_AGENT "))
        return json.loads(record)

    def seed_runtime_workbench(self, _pod):
        source = Path(__file__).with_name("runtime_scaling_agent_seed.py").read_text(encoding="utf-8")
        output = self.run_fixture_python("deployment/nexent-config", source, self.run_id, "workbench")
        record, = (line.removeprefix("SCALING_WORKBENCH ") for line in output.splitlines()
                   if line.startswith("SCALING_WORKBENCH "))
        return json.loads(record)

    def seed_runtime_creators(self, _pod, kind):
        source = Path(__file__).with_name("runtime_scaling_agent_seed.py").read_text(encoding="utf-8")
        output = self.run_fixture_python("deployment/nexent-config", source, self.run_id, "creator", kind)
        record, = (line.removeprefix("SCALING_CREATORS ") for line in output.splitlines()
                   if line.startswith("SCALING_CREATORS "))
        return json.loads(record)

    def create_runtime_model(self, pod, *, mode="storage"):
        self.require_owned_namespace()
        if mode not in MODEL_MODES:
            raise ValueError("Unsupported Runtime model fixture mode")
        metadata = pod["metadata"]
        if metadata.get("namespace") != NAMESPACE or metadata.get("labels", {}).get("app") != RUNTIME:
            raise IsolationError("The model fixture must use the image of the owned Runtime release")
        source = Path(__file__).with_name("runtime_scaling_model.py").read_text(encoding="utf-8")
        runtime, = (container for container in pod["spec"]["containers"] if container["name"] == RUNTIME)
        labels = {"app": MODEL_FIXTURE, RUN_LABEL: self.run_id}
        self.create_namespaced_fixture({
            "apiVersion": "v1", "kind": "Pod", "metadata": {"name": MODEL_FIXTURE, "labels": labels},
            "spec": {"restartPolicy": "Never", "automountServiceAccountToken": False, "containers": [{
                "name": MODEL_FIXTURE, "image": runtime["image"],
                "imagePullPolicy": runtime.get("imagePullPolicy", "IfNotPresent"),
                "command": ["python", "-u", "-c", source, mode, self.run_id],
                "readinessProbe": {"httpGet": {"path": "/ready", "port": 8090}, "periodSeconds": 2},
            }]},
        })
        self.create_namespaced_fixture({
            "apiVersion": "v1", "kind": "Service", "metadata": {"name": MODEL_FIXTURE, "labels": labels},
            "spec": {"selector": labels, "ports": [{"port": 8090, "targetPort": 8090}]},
        })
        self.wait_for_condition(f"pod/{MODEL_FIXTURE}", "Ready")

    def create_evaluation_worker(self, pod, source):
        _, upstream = self._owned_runtime_origin(pod)
        deployment = self.resources("deployment", "nexent-config")
        if deployment["metadata"].get("annotations", {}).get("meta.helm.sh/release-name") != NAMESPACE:
            raise IsolationError("Evaluation requires the Management image of the owned release")
        template = deepcopy(deployment["spec"]["template"]["spec"])
        container, = template["containers"]
        for field in ("livenessProbe", "startupProbe", "ports", "args"):
            container.pop(field, None)
        container["command"] = ["python", "-u", "-c", source, self.run_id, "serve-evaluation"]
        container["env"] = [entry for entry in container["env"] if entry["name"] != "RUNTIME_SERVICE_URL"]
        container["env"].append({"name": "RUNTIME_SERVICE_URL", "value": upstream})
        container["readinessProbe"] = {"exec": {"command": [
            "python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8091/ready', timeout=1).close()",
        ]}, "periodSeconds": 2}
        template.update(restartPolicy="Never", automountServiceAccountToken=False, nodeName=pod["spec"]["nodeName"])
        name = f"nexent-rs-evaluation-{self.run_id[:8]}-{uuid4().hex[:8]}"
        self.create_namespaced_fixture({"apiVersion": "v1", "kind": "Pod", "metadata": {
            "name": name, "labels": {"app": "nexent-rs-evaluation", RUN_LABEL: self.run_id},
        }, "spec": template})
        self.wait_for_condition(f"pod/{name}", "Ready")
        return name

    def runtime_model_control(self, action):
        if action not in {"probe", "release"} and not re.fullmatch(r"release/[a-z][a-z0-9-]{0,31}", action):
            raise ValueError("Unexpected Runtime model fixture action")
        self.require_owned_namespace()
        labels = self.resources("pod", MODEL_FIXTURE)["metadata"].get("labels", {})
        if labels.get("app") != MODEL_FIXTURE or labels.get(RUN_LABEL) != self.run_id:
            raise IsolationError("Refusing to control an unowned model fixture")
        source = (
            "import sys; from urllib.request import urlopen; "
            "action, = sys.argv[1:]; "
            "print(urlopen('http://127.0.0.1:8090/' + action, data=b'' if action.startswith('release') else None, "
            "timeout=4).read().decode())"
        )
        return json.loads(self.run_fixture_python(MODEL_FIXTURE, source, action))

    def spread_runtime_pair(self):
        """Constrain only this test's two Runtime replicas to separate worker hosts."""
        self.require_owned_namespace()
        deployment = self.resources("deployment", RUNTIME)
        metadata = deployment["metadata"]
        spec = deployment["spec"]
        annotations = metadata.get("annotations", {})
        selector = spec.get("selector", {}).get("matchLabels", {})
        if (metadata.get("namespace") != NAMESPACE or annotations.get("meta.helm.sh/release-name") != NAMESPACE
                or spec.get("replicas") != 2
                or selector.get("app") != RUNTIME):
            raise IsolationError("Placement requires the active, owned two-replica Runtime Deployment")
        pod_spec = spec["template"]["spec"]
        if any(key in pod_spec for key in ("nodeName", "nodeSelector")):
            raise IsolationError("Placement would replace scheduling constraints from the product chart")
        worker_names = _eligible_worker_hosts(self._read("nodes")["items"])
        if len(worker_names) < 2:
            raise IsolationError("Cross-node Runtime proof requires at least two schedulable worker hosts")
        affinity = {
            "nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": [
                {"matchFields": [{"key": "metadata.name", "operator": "In", "values": [worker_name]}]}
                for worker_name in worker_names
            ]}},
            "podAntiAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": [
                {"labelSelector": {"matchLabels": selector}, "topologyKey": "kubernetes.io/hostname"},
            ]},
        }
        if "affinity" in pod_spec:
            if pod_spec["affinity"] != affinity:
                raise IsolationError("Placement would replace scheduling constraints from the product chart")
        else:
            patch = [
                {"op": "test", "path": "/metadata/uid", "value": metadata["uid"]},
                {"op": "test", "path": "/metadata/resourceVersion", "value": metadata["resourceVersion"]},
                {"op": "add", "path": "/spec/template/spec/affinity", "value": affinity},
            ]
            self._kubectl("patch", "deployment", RUNTIME, "-n", NAMESPACE, "--type=json", "--patch", json.dumps(patch))
        self._kubectl("rollout", "status", f"deployment/{RUNTIME}", "-n", NAMESPACE,
                      f"--timeout={self.profile.wait_seconds}s", timeout=self.profile.wait_seconds + 10)
        return set(worker_names)

    def runtime_pods(self):
        pods = self.resources("pods", "-l", f"app={RUNTIME}")["items"]
        for pod in pods:
            if not pod["metadata"].get("deletionTimestamp") and any(
                condition.get("type") == "Ready" and condition.get("status") == "True"
                for condition in pod.get("status", {}).get("conditions", ())
            ):
                self._backend_image_receipt(pod, RUNTIME)
        return pods

    def _backend_image_receipt(self, pod, container):
        metadata = pod["metadata"]
        statuses = pod.get("status", {}).get("containerStatuses", ())
        image_ids = [entry.get("imageID") for entry in statuses if entry.get("name") == container]
        match = (IMAGE_ID_DIGEST.search(image_ids[0])
                 if len(image_ids) == 1 and isinstance(image_ids[0], str) else None)
        if not match or match.group(1) not in self.profile.backend_image_digests:
            raise IsolationError(f"{container} in Pod {metadata['name']} does not report a candidate backend image digest")
        return {"pod": metadata["name"], "uid": metadata["uid"], "digest": match.group(1)}

    def bootstrap_image_receipts(self):
        self.require_owned_namespace()
        jobs = self.resources("jobs", "-l", f"app=nexent-system-bootstrap,app.kubernetes.io/instance={NAMESPACE}")["items"]
        completed = [job for job in jobs if job.get("status", {}).get("succeeded") == 1]
        if len(completed) != 1:
            raise IsolationError("The expected completed bootstrap Job is missing or ambiguous")
        job, = completed
        name = job["metadata"]["name"]
        uid = job["metadata"]["uid"]
        pods = self.resources("pods", "-l", f"job-name={name}")["items"]
        owned = [pod for pod in pods if any(
            ref.get("kind") == "Job" and ref.get("name") == name and ref.get("uid") == uid
            for ref in pod["metadata"].get("ownerReferences", ())
        ) and pod.get("status", {}).get("phase") == "Succeeded"]
        if len(owned) != 1:
            raise IsolationError("The expected successful bootstrap Pod is missing or ambiguous")
        receipts = [self._backend_image_receipt(pod, "nexent-config") for pod in owned]
        write_case_evidence(f"runtime-bootstrap-image-{self.run_id}-{uid}", {"job": name, "pods": receipts})
        return receipts

    def fixed_runtime_deployment(self):
        deployment = self.resources("deployment", RUNTIME)
        containers = deployment["spec"]["template"]["spec"]["containers"]
        container, = (item for item in containers if item["name"] == RUNTIME)
        values = {entry["name"]: entry.get("value") for entry in container.get("env", ())}
        if values.get("NEXENT_RECOVERY_MODE") != "fixed_replicas" or "NEXENT_MAINTENANCE_EPOCH" in values:
            raise IsolationError("Runtime must use fixed-replica startup without a maintenance epoch")
        return deployment

    def _verify_deployed_backend(self, replicas):
        self.require_owned_namespace()
        deployment = self.fixed_runtime_deployment()
        if deployment["spec"]["replicas"] != replicas:
            raise IsolationError("The Runtime Deployment does not have the test's target replica count")
        pods = self.runtime_pods()
        if len(pods) != replicas:
            raise IsolationError("Cannot attribute the expected number of Runtime Pods to this deployment")
        receipts = [self._backend_image_receipt(pod, RUNTIME) for pod in pods]
        revision = deployment["metadata"]["generation"]
        write_case_evidence(f"runtime-images-{self.run_id}-{revision}", {
            "generation": revision, "cluster_uid": self.profile.cluster_uid, "namespace_uid": self.namespace_uid,
            "runtime": receipts,
        })

    def _owned_runtime_origin(self, pod):
        self.require_owned_namespace()
        name = pod["metadata"]["name"]
        live = self.resources("pod", name)
        metadata, status = live["metadata"], live.get("status", {})
        if (metadata.get("namespace") != NAMESPACE or metadata.get("uid") != pod["metadata"]["uid"]
                or metadata.get("labels", {}).get("app") != RUNTIME or metadata.get("deletionTimestamp")
                or not any(item.get("type") == "Ready" and item.get("status") == "True"
                           for item in status.get("conditions", ()))):
            raise IsolationError("Upstream target must be the currently Ready owned Runtime Pod")
        try:
            address = ip_address(status.get("podIP"))
        except ValueError:
            raise IsolationError("Upstream target must have a routable Pod IP") from None
        if address.is_unspecified or address.is_loopback or address.is_link_local or address.is_multicast:
            raise IsolationError("Upstream target must have a routable Pod IP")
        return live, f"http://{address if address.version == 4 else f'[{address}]'}:5014"

    def create_runtime_gateway(self, pod, *, scheduler=False):
        """Use a separate, authenticated Gateway to route to one current Runtime Pod."""
        _, upstream = self._owned_runtime_origin(pod)

        deployment = self.resources("deployment", GATEWAY)
        template = deployment["spec"]["template"]
        pod_spec = deepcopy(template["spec"])
        pod_spec.update(restartPolicy="Never", automountServiceAccountToken=False)
        if (deployment["metadata"].get("namespace") != NAMESPACE
                or deployment["metadata"].get("annotations", {}).get("meta.helm.sh/release-name") != NAMESPACE
                or pod_spec.get("hostNetwork")):
            raise IsolationError("The Gateway template is not from the owned Helm release")
        container, = pod_spec["containers"]
        entries = container["env"]
        runtime_url, = (entry for entry in entries if entry["name"] == "GATEWAY_RUNTIME_URL")
        gateway_auth, = (entry for entry in entries if entry["name"] == "GATEWAY_AUTH_ENABLED")
        if gateway_auth.get("value") != "true" or container["name"] != GATEWAY:
            raise IsolationError("The Runtime routing Gateway must retain production authentication")
        runtime_url.clear()
        runtime_url.update(name="GATEWAY_RUNTIME_URL", value=upstream)
        # Public chat crosses Management before the signed Runtime request.
        management = self.resources("deployment", "nexent-config")
        management_template = deepcopy(management["spec"]["template"]["spec"])
        if (management["metadata"].get("namespace") != NAMESPACE
                or management["metadata"].get("annotations", {}).get("meta.helm.sh/release-name") != NAMESPACE
                or management_template.get("hostNetwork")):
            raise IsolationError("The Management template is not from the owned Helm release")
        management_container, = management_template["containers"]
        settings = {"RUNTIME_SERVICE_URL": upstream, "NEXENT_SQL_STARTUP_MODE": "off",
                    "AGENT_AUTOMATION_ENABLED": "true" if scheduler else "false",
                    "DREAMING_SCHEDULER_ENABLED": "false"}
        management_container["env"] = [
            entry for entry in management_container.get("env", ()) if entry["name"] not in settings
        ] + [{"name": key, "value": value} for key, value in settings.items()]
        for key in ("GATEWAY_MANAGEMENT_URL", "GATEWAY_NORTHBOUND_URL"):
            endpoint, = (entry for entry in entries if entry["name"] == key)
            endpoint.clear()
            endpoint.update(name=key, value="http://127.0.0.1:5010")
        pod_spec["containers"].append(management_container)
        volumes = pod_spec.get("volumes", []) + management_template.get("volumes", [])
        if len({volume["name"] for volume in volumes}) != len(volumes):
            raise IsolationError("Gateway and Management fixture volumes overlap")
        if volumes:
            pod_spec["volumes"] = volumes

        gateway_name = f"nexent-rs-gw-{self.run_id[:8]}-{uuid4().hex[:8]}"
        self.create_namespaced_fixture({"apiVersion": "v1", "kind": "Pod", "metadata": {
            "name": gateway_name, "labels": {"app": ROUTING_GATEWAY, RUN_LABEL: self.run_id},
        }, "spec": pod_spec})
        self.wait_for_condition(f"pod/{gateway_name}", "Ready")
        return gateway_name

    def remove_runtime_gateway(self, name):
        self.require_owned_namespace()
        pod = self.resources("pod", name)
        metadata = pod["metadata"]
        labels = metadata.get("labels", {})
        if (metadata.get("namespace") != NAMESPACE or labels.get("app") != ROUTING_GATEWAY
                or labels.get(RUN_LABEL) != self.run_id):
            raise IsolationError("Refusing to remove an unowned directed Gateway")
        options = {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {"uid": metadata["uid"]}}
        self._kubectl("delete", "--raw", f"/api/v1/namespaces/{NAMESPACE}/pods/{name}", "-f", "-",
                      stdin=json.dumps(options))
        self._kubectl("wait", "-n", NAMESPACE, "--for=delete", f"pod/{name}",
                      f"--timeout={self.profile.wait_seconds}s", timeout=self.profile.wait_seconds + 10)

    def _switch_runtime_service(self, uid, previous, target):
        self.require_owned_namespace()
        patch = [{"op": "test", "path": "/metadata/uid", "value": uid},
                 {"op": "test", "path": "/spec/selector", "value": previous},
                 {"op": "replace", "path": "/spec/selector", "value": target}]
        self._kubectl("patch", "service", RUNTIME, "-n", NAMESPACE, "--type=json", "-p", json.dumps(patch))

    def _wait_runtime_service_targets(self, expected):
        deadline = time.monotonic() + min(self.profile.wait_seconds, 60)
        while time.monotonic() < deadline:
            slices = self.resources("endpointslices", "-l", f"kubernetes.io/service-name={RUNTIME}")["items"]
            active = {endpoint.get("targetRef", {}).get("uid")
                      for item in slices for endpoint in item.get("endpoints", ())
                      if endpoint.get("conditions", {}).get("ready") is True}
            if active == expected:
                return
            time.sleep(0.25)
        raise IsolationError("The stable Runtime Service did not converge to its expected owned Pods")

    @contextmanager
    def route_runtime_through_transport_fixture(self, first_pod, second_pod, *, mode="cut"):
        """Intercept only the isolated release's Runtime Service and restore its selector."""
        if mode not in {"cut", "stream-control", "voice", "northbound-admission"}:
            raise ValueError("Unsupported Runtime transport fixture mode")
        first, first_origin = self._owned_runtime_origin(first_pod)
        second, second_origin = self._owned_runtime_origin(second_pod)
        runtime_uids = {pod["metadata"]["uid"] for pod in (first, second)}
        if len(runtime_uids) != 2:
            raise IsolationError("Transport testing requires two separate owned Runtime Pods")
        service = self.resources("service", RUNTIME)
        metadata, spec = service["metadata"], service["spec"]
        original = {"app": RUNTIME}
        if (metadata.get("namespace") != NAMESPACE or not metadata.get("uid")
                or metadata.get("annotations", {}).get("meta.helm.sh/release-name") != NAMESPACE
                or spec.get("type") != "ClusterIP" or spec.get("externalIPs") or spec.get("selector") != original
                or [(port["port"], port["targetPort"]) for port in spec["ports"]] != [(5014, 5014)]):
            raise IsolationError("Refusing to redirect a Runtime Service outside the disposable Helm release")
        image, = (container for container in first["spec"]["containers"] if container["name"] == RUNTIME)
        source_name = "runtime_scaling_voice_fixture.py" if mode == "voice" else "runtime_scaling_transport.py"
        source = Path(__file__).with_name(source_name).read_text(encoding="utf-8")
        labels = {"app": TRANSPORT_FIXTURE, RUN_LABEL: self.run_id}
        relay = self.create_namespaced_fixture({
            "apiVersion": "v1", "kind": "Pod", "metadata": {"name": TRANSPORT_FIXTURE, "labels": labels},
            "spec": {"restartPolicy": "Never", "automountServiceAccountToken": False, "containers": [{
                "name": TRANSPORT_FIXTURE, "image": image["image"],
                "imagePullPolicy": image.get("imagePullPolicy", "IfNotPresent"),
                "command": ["python", "-u", "-c", source, self.run_id, first_origin, second_origin, "5014", mode],
                "readinessProbe": {"httpGet": {"path": "/test-relay/ready", "port": 5014}, "periodSeconds": 2},
            }]},
        })
        self.wait_for_condition(f"pod/{TRANSPORT_FIXTURE}", "Ready")
        self._switch_runtime_service(metadata["uid"], original, labels)
        try:
            self._wait_runtime_service_targets({relay["metadata"]["uid"]})
            yield {"producer": first_origin, "peer": second_origin}
        finally:
            self._switch_runtime_service(metadata["uid"], labels, original)
            self._wait_runtime_service_targets(runtime_uids)

    def runtime_transport_control(self, action):
        if action not in {"probe", "cut/web-cut", "cut/northbound-cut", "finish/web-cut", "finish/northbound-cut"}:
            raise ValueError("Unexpected Runtime transport fixture action")
        self.require_owned_namespace()
        labels = self.resources("pod", TRANSPORT_FIXTURE)["metadata"].get("labels", {})
        if labels.get("app") != TRANSPORT_FIXTURE or labels.get(RUN_LABEL) != self.run_id:
            raise IsolationError("Refusing to control an unowned transport fixture")
        source = (
            "import sys; from urllib.request import urlopen; action, = sys.argv[1:]; "
            "print(urlopen('http://127.0.0.1:5014/test-relay/' + action, "
            "data=b'' if action != 'probe' else None, timeout=4).read().decode())"
        )
        return json.loads(self.run_fixture_python(TRANSPORT_FIXTURE, source, action))

    def gateway_http(self, pod_name=None):
        self.require_owned_namespace()
        if pod_name is None:
            service = self.resources("service", GATEWAY)
            if (service["metadata"].get("namespace") != NAMESPACE
                    or service["spec"].get("selector", {}).get("app") != GATEWAY):
                raise IsolationError("Expected the stable Gateway Service from the owned namespace")
            target = f"service/{GATEWAY}"
        else:
            metadata = self.resources("pod", pod_name)["metadata"]
            if (metadata.get("namespace") != NAMESPACE or metadata.get("labels", {}).get(RUN_LABEL) != self.run_id
                    or metadata.get("labels", {}).get("app") != ROUTING_GATEWAY):
                raise IsolationError("Port forwarding requires an owned Runtime routing Gateway")
            target = f"pod/{pod_name}"
        return self._http_port_forward(target, 5013)

    def web_http(self):
        self.require_owned_namespace()
        service = self.resources("service", WEB)
        if (service["metadata"].get("namespace") != NAMESPACE
                or service["spec"].get("selector", {}).get("app") != WEB):
            raise IsolationError("Expected the stable Web Service from the owned namespace")
        return self._http_port_forward(f"service/{WEB}", 3000)

    @contextmanager
    def _http_port_forward(self, target, remote_port):
        command = self._kubectl_command(("port-forward", "-n", NAMESPACE, "--address=127.0.0.1",
                                         target, f":{remote_port}"))
        with TemporaryFile(dir=self.scratch) as output, subprocess.Popen(
            command, stdout=output, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            env=self._command_env, start_new_session=True,
        ) as process:
            try:
                port = _forwarded_port(process, output, min(self.profile.wait_seconds, 30), remote_port)
                yield f"http://127.0.0.1:{port}"
            finally:
                _stop_port_forward(process)

    def bound_shared_volume(self, claim_name):
        claim = self.resources("pvc", claim_name)
        claim_spec = claim["spec"]
        volume_name = claim_spec.get("volumeName")
        if (claim["metadata"].get("namespace") != NAMESPACE or claim["status"]["phase"] != "Bound"
                or not volume_name or claim_spec.get("storageClassName") != self.profile.storage_class
                or claim_spec.get("volumeMode", "Filesystem") != "Filesystem"
                or "ReadWriteMany" not in claim_spec.get("accessModes", ())):
            raise IsolationError(f"Runtime claim {claim_name} is not a Bound RWX Filesystem claim in the reserved StorageClass")
        volume = self._read("pv", volume_name)
        volume_spec = volume["spec"]
        volume_mode = volume_spec.get("volumeMode", "Filesystem")
        claim_ref = volume_spec.get("claimRef", {})
        if (volume["status"]["phase"] != "Bound" or volume_spec.get("storageClassName") != self.profile.storage_class
                or volume_mode != "Filesystem" or "ReadWriteMany" not in volume_spec.get("accessModes", ())
                or any(key in volume_spec for key in ("hostPath", "local"))
                or (claim_ref.get("namespace"), claim_ref.get("name"), claim_ref.get("uid")) !=
                (NAMESPACE, claim_name, claim["metadata"]["uid"])):
            raise IsolationError(f"Runtime volume for {claim_name} is not the expected shared binding")
        return {"claim": claim_name, "volume": volume_name, "storage_class": self.profile.storage_class,
                "volume_mode": volume_mode,
                "driver": volume_spec.get("csi", {}).get("driver", "nfs" if "nfs" in volume_spec else "other")}

    def fixture_logs(self, resource):
        return self._kubectl("logs", "-n", NAMESPACE, resource, "--tail=100")

    def restart_owned_runtime_pod(self, pod, *, interrupt=False):
        self.require_owned_namespace()
        metadata = pod["metadata"]
        if metadata.get("namespace") != NAMESPACE or metadata.get("labels", {}).get("app") != "nexent-runtime":
            raise ValueError("Expected a Runtime Pod from the owned namespace")
        options = {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {"uid": metadata["uid"]}}
        if interrupt:
            self._owned_runtime_origin(pod)
            options["gracePeriodSeconds"] = 1
        path = f"/api/v1/namespaces/{NAMESPACE}/pods/{metadata['name']}"
        self._kubectl("delete", "--raw", path, "-f", "-", stdin=json.dumps(options))

    def require_owned_namespace(self):
        self._require_test_cluster()
        current = self._read("namespace", NAMESPACE, "--ignore-not-found") or {}
        metadata = current.get("metadata", {})
        if (not self.namespace_uid or metadata.get("uid") != self.namespace_uid
                or metadata.get("labels", {}).get(RUN_LABEL) != self.run_id):
            raise IsolationError("Namespace UID or run ownership changed")

    def _cleanup(self):
        self._require_test_cluster()
        current = self._read("namespace", NAMESPACE, "--ignore-not-found")
        if current is not None:
            metadata = current.get("metadata", {})
            if metadata.get("labels", {}).get(RUN_LABEL) != self.run_id:
                raise IsolationError("Cleanup refused to delete a namespace not created by this run")
            if self.namespace_uid is None:
                self.namespace_uid = metadata["uid"]
            self.require_owned_namespace()
            options = {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {"uid": self.namespace_uid}}
            self._kubectl("delete", "--raw", f"/api/v1/namespaces/{NAMESPACE}", "-f", "-", stdin=json.dumps(options))
        deadline = time.monotonic() + self.profile.wait_seconds
        while True:
            current = self._read("namespace", NAMESPACE, "--ignore-not-found")
            if current is not None and current["metadata"]["uid"] != self.namespace_uid:
                raise IsolationError("Namespace was replaced during cleanup; replacement was preserved")
            if current is None and not self._storage_volumes():
                return
            if time.monotonic() >= deadline:
                raise IsolationError("Owned namespace or dynamically provisioned storage did not disappear")
            time.sleep(2)

    def deploy(self, script: Path, replicas: int | None = None, *, initial=False, helm_gate=None,
               kubectl_gate=None):
        self.require_owned_namespace()
        valid_target = initial if replicas is None else type(replicas) is int and 1 <= replicas <= 2147483647
        if not valid_target:
            raise ValueError("Invalid test deployment target")
        command = ["bash", str(script), "--defaults", "--release-scope", "all" if initial else "nexent",
                   "--components", "infrastructure,application,data-process", "--persistence-mode", "dynamic",
                   "--storage-class", self.profile.storage_class,
                   "--image-source", self.profile.image_source, "--version", self.profile.app_version,
                   "--wait-timeout", str(self.profile.wait_seconds)]
        if replicas is not None:
            command.extend(["--runtime-replicas", str(replicas)])
        if self.profile.image_registry_prefix:
            command.extend(["--image-registry-prefix", self.profile.image_registry_prefix])
        environment = dict(self._command_env)
        gates = {}
        for tool, gate in (("helm", helm_gate), ("kubectl", kubectl_gate)):
            if gate is not None:
                executable = shutil.which(tool, path=self._command_env["PATH"])
                if not executable:
                    raise IsolationError(f"{tool} is required for the Runtime scaling case")
                environment.update({f"D5_REAL_{tool.upper()}": executable, f"D5_{tool.upper()}_GATE": str(gate)})
                gates[str(gate)] = None
        if gates:
            environment["PATH"] = os.pathsep.join((*gates, self._command_env["PATH"]))
        if kubectl_gate is not None:
            environment["D5_KUBECTL_LOCK_NAME"] = self.deployment_lock_name
        result = _execute(command, environment, timeout=10 * self.profile.wait_seconds, cwd=script.parent)
        if result.returncode == 0:
            self._verify_deployed_backend(1 if replicas is None else replicas)
        return result

    @property
    def deployment_lock_name(self):
        return f"nexent-d5-deployment-{self.run_id}"


def _schedulable_linux_node(node):
    spec = node.get("spec", {})
    status = node.get("status", {})
    labels = node.get("metadata", {}).get("labels", {})
    return (labels.get("kubernetes.io/os") == "linux" and not spec.get("unschedulable", False)
            and not any(taint.get("effect") in {"NoSchedule", "NoExecute"} for taint in spec.get("taints", ()))
            and any(condition.get("type") == "Ready" and condition.get("status") == "True"
                    for condition in status.get("conditions", ())))


def _eligible_worker_hosts(nodes):
    worker_names = []
    hosts = set()
    for node in nodes:
        metadata = node.get("metadata", {})
        labels = metadata.get("labels", {})
        hostname = labels.get("kubernetes.io/hostname")
        if (not _schedulable_linux_node(node) or not hostname or not metadata.get("name")
                or any(role in labels for role in ("node-role.kubernetes.io/control-plane", "node-role.kubernetes.io/master"))):
            continue
        hosts.add(hostname)
        worker_names.append(metadata["name"])
    return sorted(worker_names) if len(hosts) >= 2 else []


def _forwarded_port(process, output, timeout, remote_port):
    deadline = time.monotonic() + timeout
    pattern = rb"(?m)^Forwarding from 127\.0\.0\.1:(\d+) -> %d\s*$" % remote_port
    while process.poll() is None and time.monotonic() < deadline:
        announced = re.search(pattern, os.pread(output.fileno(), 4096, 0))
        if announced and 0 < int(announced[1]) <= 65535:
            return int(announced[1])
        time.sleep(0.05)
    raise IsolationError("The loopback port-forward did not become ready")


def _stop_port_forward(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
    except ProcessLookupError:
        process.wait()
