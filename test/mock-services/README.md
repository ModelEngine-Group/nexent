# Mock deployment

Run from the repository root with Python 3.10+, Docker, and Docker Compose
(`docker compose` or legacy `docker-compose`). No Python packages are required.
On Windows use `python` in place of `python3`.

```bash
python3 test/mock-services/deploy.py list
python3 test/mock-services/deploy.py up a2a
python3 test/mock-services/deploy.py status a2a
python3 test/mock-services/deploy.py logs a2a
python3 test/mock-services/deploy.py stop a2a
```

`up` builds the selected stack, starts its registered services, and waits for
HTTP readiness and container state checks. For A2A this includes the agent,
Nacos, and the fault proxy. The default Compose project is `nexent-mock-a2a`.
The product must already be deployed on network `nexent_network`.

Options:

```bash
# Preview without accessing Docker or changing anything.
python3 test/mock-services/deploy.py up a2a --dry-run
# Start without attaching to a product network.
python3 test/mock-services/deploy.py up a2a --standalone
# Use a different existing product network and allow more readiness time.
python3 test/mock-services/deploy.py up a2a --product-network my_network --timeout 300
# Read a local Compose configuration file; never modify it.
python3 test/mock-services/deploy.py up a2a --env-file /path/to/local-mock.env
```

Use `--no-build` to reuse images. The readiness timeout begins after Compose
startup; it does not limit image downloads or builds. Failure returns nonzero
and retains containers for diagnosis. `logs` shows the latest 200 lines.
`status` returns nonzero if the stack is not ready. Fault injection may cause
an intentionally unhealthy status; restore injected faults before checking.

## Existing installations

Stacks previously started from `test/compose` may use the project name `compose`.
Do not start a second project on their occupied ports. Select the existing
project explicitly on every command:

```bash
python3 test/mock-services/deploy.py status a2a --project compose
python3 test/mock-services/deploy.py up a2a --project compose
python3 test/mock-services/deploy.py stop a2a --project compose
```

`up` may rebuild/recreate the selected Mock containers. It never calls product
deployment scripts. `stop` only stops the registered Mock services; it does not
delete containers, networks, volumes, or other services in the Compose project.
No existing product configuration or environment file is modified.

Default credentials are test-only. Use this stack only in a trusted test
network; do not expose its ports or control endpoints to the public Internet.

## Register another Mock

Add `<service-directory>/deployment.json` under `test/mock-services` and supply
its Compose files. The CLI discovers registrations automatically; no dispatcher
code changes are needed. All Compose paths are repository-relative.

```json
{
  "schema_version": 1,
  "id": "sample",
  "aliases": [],
  "project": "nexent-mock-sample",
  "compose_files": ["test/compose/compose.sample.yaml"],
  "product_network_files": [],
  "services": ["sample"],
  "oneshot_services": [],
  "networks": [],
  "readiness": [
    {"url": "http://127.0.0.1:18080/readyz", "json_equals": {"status": "ready"}}
  ]
}
```

- `services`: exact Compose services owned by this registration. Compose files
  and their dependencies must contain Mock infrastructure only, never product services.
- `oneshot_services`: optional subset expected to exit with code zero; all other
  services must remain running.
- `product_network_files`: optional overlays attaching Mock services to an
  existing `${NEXENT_PRODUCT_NETWORK}`; omitted with `--standalone`.
- `networks`: optional Mock networks created if absent. Declare these external
  in Compose when the dispatcher owns their creation.
- `readiness`: nonempty list of local HTTP endpoints returning 200. Optional
  `json_equals` uses dotted object keys and exact JSON value/type comparison.
  Published ports must match these URLs. Probes ignore host proxy settings.
- IDs and aliases must be unique; paths outside the repository are rejected.

Run `up sample --dry-run` first, then `up sample`. Keep services, ports, and
networks isolated to avoid collisions with other stacks.

## Dispatcher regression tests

```bash
python3 -m unittest discover -s test/mock-services/tests -v
```
