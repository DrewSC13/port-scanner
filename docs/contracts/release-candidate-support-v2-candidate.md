# RCSV2-CICADAPORT-5.6-002 — RC2 support and publication barrier

```text
CONTRACT=RCSV2-CICADAPORT-5.6-002
VERSION=1.0-CANDIDATE
STATUS=CANDIDATE_UNDER_EIVRC_5_6
RELEASE=3.0.0-rc.2
PYTHON_VERSION=3.0.0rc2
PUBLICATION=NOT_AUTHORIZED
```

RC2 preserves the verified support matrix of RC1:

- Linux x86_64;
- Ubuntu 22.04 and Ubuntu 24.04;
- Python 3.10, 3.11, 3.12 and 3.13;
- Rust 1.97.1;
- Go 1.26.5;
- mandatory Rust and Go engines in the Linux wheel;
- public JSONL contracts v1 and `service_evidence` v2;
- loopback-only acceptance network activity.

Windows, macOS, ARM64 and Python 3.14 remain unsupported. This contract permits
candidate artifact construction, CI upload and attestation only. It does not
permit `main` integration, a release tag, GitHub Release publication or package
publication.
