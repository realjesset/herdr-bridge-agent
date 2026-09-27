# Contributing

Python 3.10+ on Linux is required. Clone the repo and run:

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile agent/herdr-bridge-agent
```

No virtualenv or dependency install is necessary. Tests must not require real Herdr sessions, root, public ports, or existing user credentials. Include a regression test for a bug fix. Never broaden discovery to all machine processes to make one missed service appear.

`agent/herdr-bridge-agent` is a standalone executable; `tests/test_agent.py` loads it directly. Keep this install contract stable. Changes to the versioned NDJSON protocol must be coordinated with [the Mac client](https://github.com/realjesset/herdr-bridge-macos). Keep both repositories' PROTOCOL.md in sync.

Use small Conventional Commits and pull requests explaining the change and actual test results. Do not include home paths, private hostnames, tokens, logs containing credentials, or real account configuration in fixtures. Report security issues through the process in SECURITY.md.
