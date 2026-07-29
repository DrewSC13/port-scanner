# Estado de TASK 4

```text
HITO_3=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
TASK_4=IN_IMPLEMENTATION
TASK_4_BRANCH=feat/task-4-resumable-observable-sessions
CURRENT_SUBTASK=4.4
PRIMARY_DELIVERABLE=WORKING_SOFTWARE
```

## SUBTASK 4.1

```text
SUBTASK_4_1=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
SUBTASK_4_1_COMMIT=8229202c5c9ea508961039fdf6de432aeb76f212
```

Contratos congelados: `ScanPlan`, `EndpointProgress`,
`SessionCheckpoint`, `SessionManifest` y JSON determinista.

## SUBTASK 4.2

```text
SUBTASK_4_2=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
SUBTASK_4_2_COMMIT=8ae89824b1a5b7d06f6fbb95fd9da19684b48e2e
SUBTASK_4_2_REMOTE_CI_RUN=30402471632
```

Persistencia generacional, `CURRENT.json`, reanudación monoobjetivo y
`NativeSingleTargetExecutor` permanecen congelados.

## SUBTASK 4.3

```text
SUBTASK_4_3=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
SUBTASK_4_3_COMMIT=c27eecde9bd1227ad108367f55d74abf950d6587
SUBTASK_4_3_REMOTE_CI_RUN=30408734696
SUBTASK_4_3_REMOTE_CI=PASS
```

Observabilidad interna Rust y Go mediante descriptor heredado, sin modificar
`port_result` v1 ni `banner_result` v1.

## SUBTASK 4.4

```text
SUBTASK_4_4=IN_MATERIAL_IMPLEMENTATION
SUBTASK_4_4_CONTRACT=CCSMO-CICADAPORT-4.4-001
PUBLIC_CLI_RESUME=AVAILABLE_CANDIDATE
PUBLIC_SESSION_DIR_OPTION=AVAILABLE_CANDIDATE
PUBLIC_EVENTS_JSONL=AVAILABLE_CANDIDATE
PUBLIC_PRINT_PLAN=AVAILABLE_CANDIDATE
TUI_RESUME=NOT_AVAILABLE
MULTI_TARGET_RESUME=NOT_AVAILABLE
SUBTASK_4_5=NOT_STARTED
```

Rutas materiales autorizadas:

```text
src/session_cli.py
src/cli.py
tests/test_session_cli.py
docs/contracts/cli-single-target-session-v1.md
docs/task-4-status.md
docs/user-manual/README.md
```

La implementación debe detenerse con staging vacío, cero commits, cero push y
todas las superficies congeladas no reabiertas intactas.
