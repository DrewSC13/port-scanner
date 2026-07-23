# Contributing to CicadaPort

Thank you for helping improve CicadaPort. Contributions must preserve accurate
results, safe defaults, and parity between the Python and Rust scan engines.

## Safety and authorization

Run network tests only against `127.0.0.1`, systems you own, or systems for
which you have explicit written authorization. Never add CI tests that depend
on public targets.

Security vulnerabilities must follow [SECURITY.md](SECURITY.md) and must not be
submitted through a public issue or pull request.

## Development setup

Required toolchains:

- Python 3.10 or newer;
- stable Rust with `rustfmt` and Clippy;
- the Go version declared in `go-banner/go.mod`;
- Bash and ShellCheck.

Create a virtual environment and install development dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Build the native engines:

```bash
./scripts/build_all.sh
```

## Required validation

Before every commit, run:

```bash
./scripts/test_all.sh
```

The full local validation must cover Python, Rust, Go, Bash, the bridges, and
the localhost parity test. A commit must not be pushed while a required check
is failing.

The focused commands used by CI are:

```bash
python -m pytest -v --cov=src --cov-report=term-missing
cargo fmt --manifest-path rust-core/Cargo.toml -- --check
cargo clippy --manifest-path rust-core/Cargo.toml --all-targets --all-features -- -D warnings
cargo test --manifest-path rust-core/Cargo.toml
go test -race ./...
bash -n scripts/*.sh
shellcheck scripts/*.sh
```

Run the Go commands from `go-banner/`.

## Result contract

- `PortScanner.results` contains one internal result for every requested port.
- Internal results may be open, closed, or filtered.
- Reportable results contain only entries where `is_open is True`.
- TXT, JSON, CSV, and HTML must apply the same reportable filter.
- Python and Rust must agree on open/closed states and statistics for the same
  deterministic localhost fixture.

Any change to this contract requires tests in the same commit.

## Commits and pull requests

- Start from an up-to-date `main`.
- Keep each commit atomic and independently green.
- Add a regression for every corrected defect.
- Do not commit generated reports, binaries, build directories, environments,
  caches, or credentials.
- Describe the behavior before and after the change in the pull request.
- Wait for the complete CI workflow to pass before merging.

Use clear commit messages such as:

```text
fix(scanner): enforce canonical result contract
test(integration): verify Python and Rust localhost parity
docs(project): add security and contribution policies
```
