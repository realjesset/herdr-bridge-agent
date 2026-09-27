# Herdr Bridge Agent

**Security note:** Stop cancels new connections only; existing forwarded TCP/WebSocket sessions may remain until you Disconnect or quit the Mac app.

**A small, read-only Linux detector for [Herdr Bridge for macOS](https://github.com/realjesset/herdr-bridge-macos).** Start a development server in Herdr on Linux; approve its SSH forward from your Mac's menu bar.

Experimental software, not an independently certified security product. The detector does not open ports, approve forwarding, modify Herdr, or require root. It uses Python's standard library only.

## Which download do I need?

You need both pieces:

- **On Linux:** this repository's `agent/herdr-bridge-agent` script.
- **On your Mac:** the [menu-bar app and installation guide](https://github.com/realjesset/herdr-bridge-macos).

Download this repository via **Code → Download ZIP**, or clone it as shown below. Public source downloads require no GitHub account. If a release is available, prefer a versioned source archive from [Releases](https://github.com/realjesset/herdr-bridge-agent/releases). Do not confuse GitHub Actions test artifacts with public release installers.

## Quick start: Linux side

Requires Linux, Python 3.10+, OpenSSH server, and a running Herdr session under the same user. API compatibility was checked with Herdr 0.9.0. Other releases are not guaranteed compatible.

```sh
git clone https://github.com/realjesset/herdr-bridge-agent.git
cd herdr-bridge-agent
python3 -m unittest discover -s tests -v
python3 agent/herdr-bridge-agent --once
```

The last command should output `{"version":1,"type":"snapshot","services":[]}` if there are no eligible servers. An `error` frame is not a successful empty result; read its message before installing.

After inspecting the script, install without sudo:

```sh
mkdir -p "$HOME/.local/bin"
# First install only: refuse to silently overwrite an existing copy.
test ! -e "$HOME/.local/bin/herdr-bridge-agent" && \
  install -m 0755 agent/herdr-bridge-agent "$HOME/.local/bin/herdr-bridge-agent"
```

For an intentional upgrade, back up your existing script, review the diff, then run the `install` command without the first-install guard. Disconnect the Mac app before upgrading and reconnect afterward. No Herdr restart is required.

## Connect from your Mac

Configure your own trusted SSH alias in `~/.ssh/config`, for example:

```sshconfig
Host devbox
    HostName your-linux-host.example
    User your-linux-username
    ForwardAgent no
    ForwardX11 no
    StrictHostKeyChecking yes
```

Use your real hostname and username. Establish key-based SSH access and verify the host fingerprint through a trusted channel first. Do not turn off host-key checking to make a connection work.

From Mac Terminal, verify:

```sh
ssh devbox '~/.local/bin/herdr-bridge-agent --once'
```

Then enter **`devbox`**, not `ssh devbox`, in the Mac app and connect. The app starts `--watch` over SSH on demand. You do not need a daemon, cron job, public web API, reverse tunnel, or Herdr plugin installation.

## Test the complete workflow

In a **Herdr pane on Linux**, start a server in an empty temporary directory (Python's HTTP server exposes the chosen directory):

```sh
testdir="$(mktemp -d)"
python3 -m http.server 8765 --bind 127.0.0.1 --directory "$testdir"
```

1. On Mac, confirm port 8765 appears as pending. Enable notifications in the app if desired.
2. Before approval, there should be no Bridge-created listener on the Mac.
3. Click **Forward**. Open `http://127.0.0.1:8765` on the Mac; an empty directory listing is expected.
4. Click **Stop**; a fresh `curl --max-time 3 http://127.0.0.1:8765` should fail, assuming no other local service uses that port. The Linux server should remain running.
5. Press Ctrl+C in the Herdr pane, then `rmdir "$testdir"`.

For real projects, use the framework's loopback binding option (for example Vite's `--host 127.0.0.1`). `bun run dev` alone does not guarantee the correct bind address.

## What is detected?

Only listening TCP sockets owned by same-user processes in the foreground process trees of Herdr panes, bound to exact `127.0.0.1` or `::1`, on ports 1024–65535. A service is a proposal, not automatic approval.

Not detected: wildcard bindings (`0.0.0.0` or `::`), unrelated SSH shells, privileged ports, most containers, detached/reparented processes, other users' processes. This is deliberate scope, not a general network scanner.

## Troubleshooting

- **Nothing appears:** leave the server foregrounded in a Herdr pane; check binding; run `--once`. A normal SSH shell is not a Herdr pane.
- **Missing socket:** Herdr must be running for this Linux user. Default session is simplest. Named-session environment variables must be available to the SSH remote command too; see [agent details](agent/README.md).
- **Connected then disconnected:** read the Mac menu status and test the exact SSH command above. Do not restart Herdr blindly.
- **Permission denied:** configure SSH keys and known hosts in Terminal. The app intentionally cannot prompt for SSH passwords.
- **Local port busy:** stop the conflicting service or use a different remote dev port. No silent remapping.
- **Notifications absent:** check the app's notification status, macOS notification settings, and Focus. Menu approval works independently.

## For developers

- [Implementation and detection limits](agent/README.md)
- [Wire protocol](PROTOCOL.md)
- [Contributing and tests](CONTRIBUTING.md)
- [Security model and reporting](SECURITY.md)

No third-party Python dependencies. Run `python3 -m unittest discover -s tests -v`. Tests use proc fixtures, real local loopback sockets, and fake Herdr API sockets; they never mutate real Herdr panes. Successful detector tests do not establish macOS UI or forwarding correctness.

## Uninstall

Disconnect the Mac app, then remove **only** `~/.local/bin/herdr-bridge-agent`. No service or Herdr configuration needs removal. The separate Mac app can be quit and removed from Applications.

MIT licensed. Independent project; not an official Herdr component.
