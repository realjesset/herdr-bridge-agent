# Linux detector

`herdr-bridge-agent` is an original, Python-standard-library-only Linux executable.
It does not install, configure, restart, or mutate Herdr, start a server, forward a
port, or approve a service. The Mac app owns all approvals and SSH forwarding.

```sh
./agent/herdr-bridge-agent --once
./agent/herdr-bridge-agent --watch
python3 -m unittest discover -s tests -v
```

Default mode is `--once`. `--watch` emits unchanged/empty full snapshots too, on a
3-second cadence. Any discovery or serialization failure emits one sanitized
`error` frame and exits 1, rather than clearing services with a fake empty snapshot.
The executable must be installed explicitly by the user at the fixed path expected
by the Mac client, `~/.local/bin/herdr-bridge-agent`; nothing here auto-installs it.

## Socket and API

Socket precedence: `HERDR_SOCKET_PATH`, then
`${XDG_CONFIG_HOME:-~/.config}/herdr/sessions/$HERDR_SESSION/herdr.sock` when a
validated session name is set, otherwise
`${XDG_CONFIG_HOME:-~/.config}/herdr/herdr.sock`. The SSH remote environment may
not inherit your interactive shell's environment: the default session is simplest;
set the remote environment explicitly for named sessions. There is no session scan.

The socket must be a non-symlink Unix socket owned by the current UID. Linux
`SO_PEERCRED` must identify a same-UID peer before sending any request. The client
has a hard-coded read-only method allowlist, a 1-second absolute deadline per
request (including trickled responses), a 1 MiB response limit, and a shared
2.5-second discovery deadline. No CLI subprocesses or shell commands are used.

Confirmed against the installed Herdr's `herdr api schema --json`, and read-only
`herdr pane list` / `herdr pane process-info --current`:

- Request: `{"id":"bridge","method":"pane.list","params":{}}`.
- Success: `{"id":"bridge","result":{"type":"pane_list","panes":[...]}}`.
- Each pane's `pane_id` goes to `pane.process_info` via `{"pane_id":"..."}`.
- Success uses `result.type = "pane_process_info"` and nested
  `result.process_info.foreground_processes[].pid`, **not** top-level `processes`.
- Failure uses `{"id":"bridge","error":{"code":"...","message":"..."}}`.
- The schema permits absent `foreground_processes` (empty); null or a wrong type
  is rejected. API errors, wrong response IDs/types, and malformed consumed fields
  are discovery failures, never successful emptiness.

## Scope and fail-closed limits

Only supplied foreground PIDs and their descendants are candidates. Descendants
come from `/proc/PID/task/TID/children` for every thread, never an arbitrary process
scan. Each visited process must have matching directory ownership and all four
real/effective/saved/filesystem UIDs. Parent PID and start time are checked again
across the lineage before attributing sockets. PID, mount, and network namespaces
must match the detector; common container cgroup markers are also excluded.

`/proc/net/tcp` and `tcp6` are matched by inode to the candidates' `fd` symlinks.
Only exact `127.0.0.1` or `::1` LISTEN endpoints with same-UID socket ownership and
ports 1024–65535 qualify. Wildcards, other interfaces, mapped addresses, privileged
ports, non-listeners, unrelated processes, and containers in distinct namespaces
are excluded. No project allowlist is required for this MVP; pane scope plus
explicit current-snapshot Mac approval is the boundary.

IDs hash the original pane ID, host, and port, not PID or project label, so ordinary
hot reloads preserve them. Duplicate host+port endpoints are attributed to the
lexicographically first pane. Labels are control/format-character-free and bounded
to 128 Unicode characters. Project is the basename of pane foreground CWD (or CWD,
then pane label/ID), not a repository identity or trust claim.

Limits: 256 panes, 4096 process visits, 65536 fd/task entries per discovery,
1 MiB per ordinary proc file, 8 MiB per TCP table, 128 services, and 65536 UTF-8
bytes per output frame including newline. Exceeding a limit reports an error;
services are not silently truncated. Kernel-disabled IPv6 (absent tcp6) is allowed.

## Limits of the model

- This is polling, not an atomic process/socket snapshot. Very short-lived servers
  can be missed; PID/start-time/parent rechecks reduce but cannot eliminate races.
- Daemonized/reparented processes outside foreground trees are deliberately missed.
- Namespace filtering can exclude sandboxed non-container processes. Containers
  deliberately sharing all host namespaces and disguising their cgroup are not
  reliably distinguishable by a userspace detector; same-UID code is trusted.
- Restrictive proc mounts/permissions cause errors rather than widening scope.
- No remote application-content or HTTP check is performed. A listening port is
  a proposal for explicit approval, not proof that its application is trustworthy.

Tests include temporary proc fixtures, mocked socket error/ownership/size cases,
a real same-UID Unix socket with two 3-second watch heartbeats, an actual stalled
socket timeout, and a locally spawned loopback-only TCP server matched through
real `/proc`. The latter supplies its PID through a fixture Herdr API and does not
create or mutate any real Herdr pane.
