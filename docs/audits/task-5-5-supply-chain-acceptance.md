# TASK 5.5 supply-chain acceptance procedure

The acceptance runner is `scripts/run_task_5_5_acceptance.sh`. It is bound to
`feat/task-5-enterprise-engine-production-hardening@845ba78330d969685b15895d05040abfaa8cfd86`
and consumes the corrected audit-v2 evidence.

It validates:

1. immutable GitHub Action SHAs and the Node.js 24 migration;
2. Python 3.13 release lock stability and hash-checking mode;
3. deterministic CycloneDX 1.6 SBOM and release manifest generation;
4. SLSA/Sigstore attestation and verification workflow configuration;
5. reproducible wheel, normalized sdist, inventory, SBOM and manifest bytes;
6. Bandit SAST, Gitleaks workflow policy and dependency audits;
7. complete build/test regression coverage;
8. absence of changes to frozen Rust, Go, Session Store and contract surfaces.

The runner creates private JSON, Markdown, log and `SHA256SUMS` evidence under
`task-5-5-evidence/<UTC timestamp>` and does not publish a release.
