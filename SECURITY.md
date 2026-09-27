# Security

This is experimental software. Source review and passing tests are not an independent security audit or guarantee of safety.

## Trust boundaries

- Trust the Linux account and host and the Mac account. Malicious same-user code can fabricate services or replace executables. SSH protects transport, not a compromised endpoint.
- The detector is read-only. Only the Mac companion approves and creates forwards. No network service is exposed by the detector.
- Herdr Unix sockets require same-user ownership and peer credentials. Reads have size/time budgets. Linux process ownership, namespace, lineage and socket-inode checks narrow discovery scope.
- Polling is not atomic. Process races cannot be fully eliminated. Namespace filtering may exclude legitimate sandboxes and cannot identify every container sharing host namespaces.
- TCP listening does not prove HTTP or identify the application. A service can be replaced after detection. Ports are not identities.
- Forwarded Mac loopback ports are accessible to other local processes/users. Loopback is not per-user authentication.
- The Mac companion trusts your SSH config, including ProxyCommand. Use key auth and verified host keys; never disable host-key verification for convenience.
- No telemetry, self-updater, root installation, public API, or third-party runtime packages.

## Reporting

Please do not post secrets or exploit details in a public issue. If GitHub's **Security → Report a vulnerability** option is enabled, use it. Otherwise open an issue requesting a private reporting channel without including sensitive details. There is no guaranteed response time or support SLA. Only the current development branch is maintained.

## Checks

The test suite covers scoped detection, invalid response schemas, socket ownership, timeouts, wildcard exclusion, and resource limits. CI runs on Linux. Automated checks do not audit Python/OpenSSH/Herdr themselves. Review changes and pin the revision you deploy. Source archive checksums verify integrity against an expected digest, not publisher identity by themselves.
