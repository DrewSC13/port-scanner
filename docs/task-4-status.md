# Estado prospectivo de TASK 4

Este documento registra únicamente el trabajo posterior al cierre congelado del
Hito 3. No reabre, modifica ni reinterpreta sus Subhitos históricos.

```text
HITO_3=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
TASK_4=IN_IMPLEMENTATION
TASK_4_CONTRACT=CSR-CICADAPORT-TASK-4-001
TASK_4_CONTRACT_VERSION=1.0-CANDIDATA
TASK_4_BRANCH=feat/task-4-resumable-observable-sessions
CURRENT_SUBTASK=4.3
PRIMARY_DELIVERABLE=WORKING_SOFTWARE
DOCUMENTATION_ONLY_COMPLETION=PROHIBITED
```

## SUBTASK 4.1 — estado heredado e inmutable

```text
SUBTASK_4_1=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
SUBTASK_4_1_COMMIT=8229202c5c9ea508961039fdf6de432aeb76f212
SUBTASK_4_1_TREE=bfb3398ccc3c238f6818a016aecf53a98f13d4b4
SUBTASK_4_1_REMOTE_CI=PASS
SUBTASK_4_1_OPEN_DISCREPANCIES=0
```

Superficies contractuales cerradas:

- `ScanPlan` v1;
- `EndpointProgress` v1;
- `SessionCheckpoint` v1;
- `SessionManifest` v1;
- serialización determinista y lectura estricta.

SUBTASK 4.2 consume esos modelos sin modificar sus campos, versiones o
semántica.

## SUBTASK 4.2 — checkpoint y reanudación monoobjetivo

```text
SUBTASK_4_2=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
SUBTASK_4_2_COMMIT=8ae89824b1a5b7d06f6fbb95fd9da19684b48e2e
SUBTASK_4_2_TREE=adbc7e015cd990b1c47fb811631aa22987974523
SUBTASK_4_2_REMOTE_CI_RUN=30402471632
SUBTASK_4_2_REMOTE_CI=PASS
SUBTASK_4_2_CONTRACT=CRMO-CICADAPORT-4.2-001
SUBTASK_4_2_CONTRACT_VERSION=1.0-CANDIDATA
SUBTASK_4_2_IMPLEMENTATION=IMPLEMENTED_IN_GENERATED_WORKING_TREE
SUBTASK_4_2_STAGING=EMPTY_REQUIRED
SUBTASK_4_2_COMMITS=0_REQUIRED
SUBTASK_4_2_PUSH=PROHIBITED_WITHOUT_SEPARATE_AUTHORIZATION
```

Alcance material del patch candidato:

- `SingleTargetCheckpointStore` con generaciones inmutables;
- `CURRENT.json` atómico y estricto;
- hashes SHA-256 de checkpoint y manifiesto;
- secuencia monotónica `n + 1`;
- rechazo de corrupción, symlinks, colisiones y versiones incompatibles;
- `SingleTargetSessionRunner` para crear, ejecutar y reanudar;
- checkpoint después de cada puerto confirmado;
- omisión de puertos ya completados;
- cancelación y fallo con progreso preservado;
- banners Go reanudables por puerto abierto;
- `NativeSingleTargetExecutor` para Rust y Go sin fallback;
- prueba funcional limitada a loopback;
- contrato candidato y actualización veraz del manual.

Archivos candidatos:

```text
src/session_runtime.py
tests/test_single_target_resume.py
docs/contracts/single-target-resume-v1.md
docs/user-manual/README.md
docs/task-4-status.md
```

Validación focalizada ejecutada en el entorno de generación:

```text
INHERITED_SESSION_CONTRACT_TESTS=19
SUBTASK_4_2_FOCUSED_TESTS=24
FOCUSED_TOTAL=43
FOCUSED_RESULT=PASS
NETWORK_SCOPE=LOOPBACK_ONLY
EXTERNAL_SCANS=0
```

La validación focalizada no sustituye la validación integral en el repositorio
real. Antes de cualquier staging deben verificarse:

- base exacta `8229202c5c9ea508961039fdf6de432aeb76f212`;
- superficies congeladas de SUBTASK 4.1;
- aplicación limpia del patch;
- suite Python completa;
- scripts oficiales multilenguaje;
- auditorías de dependencias;
- packaging e instalación aislada cuando corresponda;
- manual y ausencia de opciones CLI prematuras;
- staging vacío y cero commits nuevos.

## Superficie pública

```text
PUBLIC_CLI_RESUME=NOT_AVAILABLE
PUBLIC_SESSION_DIR_OPTION=NOT_AVAILABLE
PUBLIC_EVENTS_JSONL=NOT_AVAILABLE
PUBLIC_PRINT_PLAN=NOT_AVAILABLE
TUI_RESUME=NOT_AVAILABLE
MULTI_TARGET_RESUME=NOT_AVAILABLE
```

## SUBTASK 4.3 — observabilidad nativa Rust y Go

```text
SUBTASK_4_3=IN_IMPLEMENTATION
SUBTASK_4_3_CONTRACT=CON-CICADAPORT-4.3-001
PRIMARY_IMPLEMENTATION=RUST_AND_GO
PUBLIC_EVENTS_JSONL=NOT_AVAILABLE
```

Rust y Go emiten eventos internos versionados mediante descriptor heredado; Python valida secuencia y cobertura. SUBTASK 4.4 y 4.5 permanecen `NOT_STARTED`.
