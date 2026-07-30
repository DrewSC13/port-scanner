# Contratos de sesión v1 — TASK 4

## Estado

```text
CONTRACT=CSR-CICADAPORT-TASK-4-001
CONTRACT_VERSION=1.0-DEFINITIVA
STATUS=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
SUBTASK=4.1
SUBTASK_COMMIT=8229202c5c9ea508961039fdf6de432aeb76f212
SCAN_PLAN_CONTRACT_VERSION=1
SESSION_CHECKPOINT_CONTRACT_VERSION=1
SESSION_MANIFEST_CONTRACT_VERSION=1
IMPLEMENTATION=EXECUTABLE_AND_INTEGRATED
ORCHESTRATOR_INTEGRATION=COMPLETED
```

SUBTASK 4.1 incorporó modelos ejecutables y validación estricta. Su contrato
permanece congelado; la persistencia, reanudación e interfaces públicas se
materializaron posteriormente sin cambiar sus campos ni versiones.

## `scan_plan` v1

`ScanPlan` representa una solicitud ya validada y resuelta antes de cualquier
actividad de red. Conserva objetivos solicitados, endpoints IPv4/IPv6, puertos,
timeout, presupuestos de concurrencia, motores efectivos y configuración de
reportes.

Invariantes principales:

- máximo de 4096 objetivos y endpoints;
- objetivos y endpoints únicos;
- cada objetivo solicitado tiene al menos una resolución;
- puertos únicos entre 1 y 65535;
- `timeout_ms` entre 1 y 3.600.000;
- `threads` entre 1 y 500;
- `target_workers` entre 1 y 32 y no mayor que los endpoints;
- `tcp_engine` es siempre `rust`;
- `banner_engine` es `go` únicamente cuando `banner_grab=true`;
- una ruta `output` exacta solo se admite para un endpoint;
- formatos admitidos: TXT, JSON, CSV y HTML.

El fingerprint del plan es SHA-256 sobre su JSON canónico.

## `session_checkpoint` v1

`SessionCheckpoint` conserva un snapshot autoconsistente:

- UUID canónico de sesión;
- `ScanPlan` completo;
- estado `created`, `running`, `cancelled`, `failed` o `completed`;
- progreso de cada endpoint;
- resultados canónicos completados;
- puertos TCP pendientes;
- banners terminados para puertos abiertos;
- timestamps UTC;
- secuencia monotónica preparada para la integración posterior.

Cada endpoint debe contabilizar exactamente los puertos del plan. Los puertos
completados y pendientes son disjuntos. Los resultados se vuelven a validar
contra el contrato canónico vigente: `state` es la fuente de verdad,
`evidence.reason` sustenta la razón e `is_open` debe ser su proyección exacta.

## `session_manifest` v1

`SessionManifest` deriva métricas verificables de un checkpoint: fingerprint,
estado, tiempos, objetivos, puertos, hallazgos abiertos, secuencia y motores.
Los conteos incompatibles se rechazan.

## JSON determinista y lectura estricta

Los tres documentos principales:

- ordenan las claves;
- usan UTF-8 sin escapes ASCII innecesarios;
- no emiten espacios variables;
- rechazan NaN e infinitos;
- rechazan claves JSON duplicadas;
- rechazan campos ausentes o desconocidos;
- rechazan versiones incompatibles;
- rechazan JSON truncado o corrupto.

## Compatibilidad preservada

No se modifican:

- `scan_request` v1;
- `port_result` v1;
- `banner_request` v1;
- `banner_result` v1;
- el comportamiento de escaneo;
- el flujo `Python → Rust → Python → Go → Python`.
