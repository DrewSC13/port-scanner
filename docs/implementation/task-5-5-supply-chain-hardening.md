# SUBTASK 5.5 — Operational, supply-chain and release hardening

Contract: `OSCR-CICADAPORT-5.5-001`
Version: `1.0-CANDIDATE`
Base: `845ba78330d969685b15895d05040abfaa8cfd86`

## Implemented controls

- Every external GitHub Action is pinned to a reviewed full commit SHA.
- Node.js 20 artifact actions are replaced by Node.js 24-compatible releases.
- Release/security Python tools are installed from a Python 3.13 lock using
  pip hash-checking mode.
- A deterministic CycloneDX 1.6 SBOM covers the Python release toolchain,
  Cargo lock and Go module.
- A deterministic release manifest binds the Git commit, Git tree, tracked
  source index, toolchains and artifact digests.
- GitHub OIDC and Sigstore-backed `actions/attest` create signed SLSA build
  provenance and a signed SBOM attestation for non-pull-request builds.
- A separate CI job downloads the artifact set and verifies its attestations.
- Bandit, Rust Clippy, Go Vet and Gitleaks provide language and secret scanning.
- Release builds are executed twice under the same `SOURCE_DATE_EPOCH`; the
  sdist is deterministically repacked with sorted entries, normalized ownership
  and timestamps, and a timestamp-free gzip header before byte comparison.
- Dependabot may propose updates, but immutable SHAs and the hash lock remain
  mandatory review boundaries.

## Preserved surfaces

This subtask does not materially modify `rust-core/`, `go-banner/`, Session
Store v2, public contracts v1, or `service_evidence` v2. It does not publish a
new release candidate, merge to `main`, create a release tag, perform external
network scanning, or introduce new network techniques.
