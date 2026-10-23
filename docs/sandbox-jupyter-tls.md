# Sandbox Jupyter TLS

Docker sandbox control traffic uses HTTPS for kernel health, creation and deletion,
and WSS for execution, readiness and reconnection. Each container creates its own
ECDSA certificate before Jupyter starts. The private key stays inside the container
under `/home/sandbox/.nexent-jupyter-tls` (directory `0700`, key `0600`).
The bootstrap checks ancestor ownership and write permissions, rejects symlinks,
and uses directory-relative file descriptors and exclusive creation. Private key
permissions apply before writing. Existing identities must be complete, privately
owned, currently valid and have matching keys; unsafe files are never repaired in
place. These filesystem controls do not isolate processes sharing the same UID.

The runtime reads only the public certificate through its existing trusted Docker
connection. Each container owner has a separate trust file and SSL context, shared
by its kernel leases and cleaned up with the owner. Certificate and hostname checks
remain enabled. HTTPS requests do not use environment proxies or follow redirects.
No global CA installation or manual certificate configuration is required.

The certificate covers the container name, localhost and loopback.
Native runtimes continue to use dynamically allocated
loopback ports; containerized runtimes use Docker networking. Workspace mapping,
kernel isolation, execution and cancellation contracts remain unchanged.

## Deployment and migration

- Images must contain `cryptography >= 42` and Jupyter Kernel Gateway with
  `certfile`/`keyfile` support. The SDK now declares the cryptography dependency;
  both repository Dockerfiles install the SDK. A custom older image without it
  must be rebuilt. The configured user must own the private TLS directory and be
  able to create it under a trusted, non-publicly-writable `/home/sandbox` parent.
  Both repository images already provide this layout. Startup does not download dependencies.
- Before upgrading an existing system sandbox, drain active runs and explicitly
  stop its old HTTP or TLS-version-1 container. Version 2 uses the private identity
  directory; it does not read or migrate files from the old public temporary path.
  The runtime refuses to recover or automatically
  delete a running legacy container. On the next acquisition it can remove the
  stopped owned container and create a TLS container.
- Certificates are valid for 365 days and retained on container restart. Drain
  and recreate a system container before expiry; merely restarting it does not
  renew the certificate. There is no hot certificate rotation in this change.
- If recovery cannot load or verify a running container's certificate, it reports
  an error and preserves that container. Investigate the certificate/time/Docker
  connection, then drain and explicitly stop the owner before recreating it.

Client contexts and the test HTTPS server explicitly require TLS 1.2 or newer.
The repository's Sonar configuration declares Python 3.11, matching the SDK runtime.

This change addresses the Jupyter TLS findings in PR #3985. The separate host
tool callback bridge is outside this change. SonarCloud and Codecov results still
need to be checked on the pushed commit; no findings are suppressed or accepted
automatically.
