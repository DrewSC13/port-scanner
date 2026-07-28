# Estado prospectivo de TASK 4

Este documento registra únicamente el trabajo posterior al cierre congelado del
Hito 3. No reabre, modifica ni reinterpreta sus Subhitos históricos.

```text
HITO_3=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
TASK_4=IN_IMPLEMENTATION
TASK_4_CONTRACT=CSR-CICADAPORT-TASK-4-001
TASK_4_CONTRACT_VERSION=1.0-CANDIDATA
TASK_4_BRANCH=feat/task-4-resumable-observable-sessions
CURRENT_SUBTASK=4.1
PRIMARY_DELIVERABLE=WORKING_SOFTWARE
DOCUMENTATION_ONLY_COMPLETION=PROHIBITED
```

## SUBTASK 4.1

Alcance material del primer patch:

- `ScanPlan` v1 ejecutable;
- `SessionCheckpoint` v1 ejecutable;
- `SessionManifest` v1 ejecutable;
- progreso por endpoint;
- serialización JSON determinista;
- lectura estricta y rechazo de campos desconocidos;
- validación de resultados canónicos;
- pruebas sin actividad de red;
- estructura inicial del Manual de Usuario.

Permanecen pendientes y fuera de este patch:

- persistencia incremental en disco;
- integración con el orquestador;
- reanudación real;
- opciones públicas de CLI;
- cambios en TUI, Rust o Go;
- SUBTASK 4.2 y posteriores.
