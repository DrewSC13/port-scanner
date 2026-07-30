# Sesiones multiobjetivo y TUI v1

```text
CONTRACT_ID=CMTS-CICADAPORT-4.5-001
CONTRACT_VERSION=1.0-DEFINITIVA
STATUS=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
FINAL_COMMIT=77ad51f0751b29b510f574e750c1a3fa65db4a60
REMOTE_CI_RUN=30420081019
REMOTE_CI=PASS
SCOPE=MULTI_TARGET_MULTI_ENDPOINT_CLI_TUI
```

SUBTASK 4.5 añade una capa batch sin modificar `ScanPlan`,
`EndpointProgress`, `SessionCheckpoint`, `SessionManifest`, `CURRENT.json` ni
los eventos públicos v1.

## Reglas funcionales

- todos los objetivos se expanden y resuelven antes de crear la sesión;
- cada endpoint resuelto mantiene progreso independiente dentro de un
  checkpoint global;
- `target_workers` limita la concurrencia global;
- el presupuesto de threads se distribuye entre endpoints activos;
- cada resultado y banner se persiste antes de anunciar su confirmación;
- un fallo de endpoint no cancela los demás;
- una sesión con cualquier error termina en `failed`;
- reanudar omite endpoints, puertos y banners ya completados;
- endpoints fallidos pueden reintentarse sin repetir trabajo confirmado;
- una sesión `completed` es idempotente;
- la cancelación CLI o TUI conserva el último checkpoint y usa código 130;
- CLI lineal y TUI consumen el mismo runtime batch;
- F5 reanuda la misma sesión persistida;
- Ctrl+X solicita cancelación cooperativa;
- los reportes continúan siendo individuales por endpoint;
- TUI y CLI heredados permanecen intactos sin opciones de sesión.

## Componentes

```text
MultiTargetCheckpointStore
MultiTargetSessionRunner
PreparedBatchSession
BatchPublicEventProjector
SessionTuiController
SessionTuiRequest
```

## Seguridad e integridad

- generaciones inmutables;
- `CURRENT.json` atómico;
- SHA-256 de checkpoint y manifiesto;
- rechazo de symlinks y documentos manipulados;
- secuencia global monotónica;
- fingerprint del plan inmutable;
- sin raw scanning, host discovery ni escaneos externos.

## Compatibilidad

```text
SCAN_PLAN_VERSION=1
SESSION_CHECKPOINT_VERSION=1
SESSION_MANIFEST_VERSION=1
PUBLIC_EVENT_VERSION=1
PORT_RESULT_VERSION=1
BANNER_RESULT_VERSION=1
```
