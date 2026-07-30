# SUBTASK 5.6 — Enterprise validation and RC2 preparation

Contract: `EIVRC-CICADAPORT-5.6-001`
Version: `1.0-CANDIDATE`
Base: `af6ccaeb45394a837f7277b6a6e8508683eda032`
Candidate release: `3.0.0-rc.2` / `3.0.0rc2`

## Implemented scope

- reconcile the formal TASK 5 status after the frozen SUBTASK 5.5 closure;
- derive package, SBOM, manifest and CI artifact versions from RC2 identity;
- add an enterprise acceptance runner and release inventory;
- verify the hashed evidence chain of SUBTASKS 5.1–5.5;
- preserve JSONL v1, `service_evidence` v2 and the Rust/Go/Python architecture;
- keep all acceptance network activity on loopback;
- produce candidate CI artifacts without publication.

## Preserved barriers

This implementation does not merge `main`, create tags, publish GitHub Releases
or packages, declare stability, add network techniques, perform external scans
or close TASK 5 automatically. Phase F remains blocked.
