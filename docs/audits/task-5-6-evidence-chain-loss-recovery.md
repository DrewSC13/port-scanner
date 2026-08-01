# TASK 5.6 — Recovery attestation for lost local predecessor evidence

```text
LOSS_ATTESTATION_VERSION=1
LOSS_ATTESTATION_STATUS=ACTIVE_RECOVERY_CONTRACT
CONTRACT=IPRCC-CICADAPORT-5.F-001
INCIDENT=SC_ACCEPTANCE_PHASE_F_006
SC_ACCEPTANCE_PHASE_F_006=DIAGNOSED_TOTAL_LOCAL_EVIDENCE_LOSS
```

## Scope

This attestation records the complete local loss of the hashed evidence roots
used by the original TASK 5.6 enterprise acceptance for SUBTASKS 5.1–5.5.
It does not recreate, replace or claim byte-for-byte restoration of those
historical files.

```text
HISTORICAL_EVIDENCE_RECREATED=NO
HISTORICAL_EVIDENCE_PARTIAL_PRESENCE=0
SYNTHETIC_EVIDENCE_ROOTS_CREATED=NO
FROZEN_SUBTASKS_REEXECUTED=NO
```

## Historically accepted result

The original successful TASK 5.6 acceptance recorded:

```text
EVIDENCE_DIR_COUNT=6
EVIDENCE_FILES=32
SHA256SUMS_PASS=7
SHA256SUMS_FAIL_OR_PARTIAL=0
HISTORICAL_RESULT_6_32_7_0=ATTESTED
SUBTASKS_5_1_TO_5_5_EVIDENCE_CHAIN=PASS
```

The associated material preflight package was identified as:

```text
ARCHIVE=task-5-6-material-preflight-20260730T214052Z.tar.gz
ARCHIVE_SHA256=dea25c7a8739e11d8c09ba656562c16b54ce98255cde19d839024301d4019cb6
ARCHIVE_CURRENT_LOCAL_STATUS=NOT_FOUND
```

## Signed predecessor identities

```text
SUBTASK_5_1=045dabda6eea840e3cbe065407e7132d88ba9963
SUBTASK_5_2=8ce44caebf90519867d0da7a53a0ec71372cd741
SUBTASK_5_3=7bac7fff3c2f0e14db74505923e0e5f64edc7eb7
SUBTASK_5_4=845ba78330d969685b15895d05040abfaa8cfd86
SUBTASK_5_5=af6ccaeb45394a837f7277b6a6e8508683eda032
SIGNED_PREDECESSOR_COMMITS=5
```

Recovery mode is valid only when the local evidence chain is completely absent.
Each predecessor commit must exist, have a valid signature, preserve linear
ancestry and expose its contractual runner, implementation or test surfaces.

## Dual-mode policy

When local predecessor evidence exists, the unchanged legacy thresholds apply:

```text
EVIDENCE_CHAIN_MODE=LOCAL_HASHED_ROOTS
EVIDENCE_DIR_COUNT>=6
EVIDENCE_FILES>=32
SHA256SUMS_PASS>=7
SHA256SUMS_FAIL=0
```

When and only when all local counters are zero, the runner may use:

```text
EVIDENCE_CHAIN_MODE=SIGNED_PREDECESSOR_CHAIN_WITH_LOSS_ATTESTATION
LOSS_ATTESTATION_SHA256=REQUIRED
SIGNED_PREDECESSOR_CHAIN=REQUIRED
CONTRACT_BASE_ANCESTRY=REQUIRED
```

Any partial local presence must fail closed.

## Preserved barriers

```text
NEW_NETWORK_CAPABILITIES=0
EXTERNAL_NETWORK_SCANNING=0
MAIN_INTEGRATION=NOT_AUTHORIZED
TAG_CREATION=NOT_AUTHORIZED
RELEASE_PUBLICATION=NOT_AUTHORIZED
PACKAGE_PUBLICATION=NOT_AUTHORIZED
TASK_5_CLOSURE=NOT_AUTHORIZED
```
