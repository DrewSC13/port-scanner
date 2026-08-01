# SUBTASK 6.3 — Health, readiness, métricas y logging

- Contrato: `HRML-CICADAPORT-6.3-001`
- Versión: `1.0-CANDIDATE`
- Estado: `IMPLEMENTATION_CANDIDATE_FIRST_BLOCK`
- Base autorizada: `ccee480d6826b50d5911ef7c99adc127b9ab7349`
- Árbol autorizado: `c23ba162463a08823dd9c272d1216dc8de48f66f`

## Alcance

Este primer bloque implementa exclusivamente primitivas locales e in-process:

1. health y liveness;
2. readiness fail-closed;
3. métricas con catálogo fijo y cardinalidad acotada;
4. logging JSON estructurado, limitado y redactado;
5. una fachada local sin transporte ni endpoint.

No modifica los contratos congelados de SUBTASK 6.1 o SUBTASK 6.2.

## HRML-6.3-R001 — Health y liveness

Estados contractuales:

- `STARTING`;
- `HEALTHY`;
- `DEGRADED`;
- `UNHEALTHY`.

Los snapshots son inmutables. El timestamp usa UTC timezone-aware y la edad usa
un reloj monotónico separado e inyectable. `UNHEALTHY` no está vivo;
`STARTING`, `HEALTHY` y `DEGRADED` sí lo están.

Los reason codes:

- son mayúsculos y estables;
- se deduplican;
- se ordenan determinísticamente;
- no incorporan texto libre ni excepciones.

## HRML-6.3-R002 — Readiness fail-closed

`ready=false` es el comportamiento por defecto. La evaluación separa:

- configuración válida;
- entorno válido;
- layout contractual preparado;
- dependencias requeridas disponibles;
- health/liveness.

La composición con SUBTASK 6.2 consume únicamente campos booleanos del
diagnóstico seguro. Nunca copia valores de configuración, rutas, versiones,
excepciones ni secretos al reason set.

## HRML-6.3-R003 — Métricas acotadas

El catálogo es cerrado y no admite registro dinámico:

- `cicadaport_operations_started_total`;
- `cicadaport_operations_completed_total`;
- `cicadaport_active_operations`;
- `cicadaport_operation_duration_seconds`;
- `cicadaport_health_status`;
- `cicadaport_readiness`.

Las etiquetas y sus valores usan allowlists fijas. No se aceptan target, IP,
hostname, ruta, mensaje de error ni texto arbitrario como etiqueta.

El registro:

- es thread-safe;
- rechaza NaN e infinito;
- rechaza counters negativos;
- usa buckets fijos;
- produce snapshots ordenados;
- no exporta ni transmite datos.

## HRML-6.3-R004 — Logging estructurado seguro

Los eventos usan `cicadaport-log-event-v1` y contienen:

- severidad cerrada;
- `event_name` validado;
- timestamp UTC;
- `correlation_id` opcional y acotado;
- mensaje limitado;
- máximo 24 campos escalares;
- serialización JSON determinista.

La redacción reutiliza `src.security_values.redact_text` de SUBTASK 6.2 y añade
controles locales para correo, rutas personales, direcciones IP, credenciales
embebidas en URL y caracteres de control.

Los nombres de campo con `secret`, `token`, `password`, `credential`,
`api_key` o `private_key` se rechazan. Un fallo del sink devuelve `false` y no
interrumpe el flujo principal ni activa recursión.

## HRML-6.3-R005 — Superficie exclusivamente local

Queda prohibido implementar:

- servidores HTTP;
- listeners;
- `bind`;
- `listen`;
- rutas `/health`, `/ready` o `/metrics`;
- sockets nuevos;
- exporters o transporte de telemetría.

## HRML-6.3-R006 — Sin integraciones externas

No se integran OpenTelemetry, Prometheus, Sentry, StatsD, Datadog, Grafana,
OTLP ni SDK equivalentes.

## Concurrencia y atomicidad

Health y métricas usan `RLock`. Los snapshots se construyen desde copias
consistentes. Los gauges activos se ajustan bajo lock y no descienden de cero.
La validación de resultado ocurre antes de modificar métricas de finalización.

## Límites

- evento serializado: 8192 bytes;
- mensaje: 1024 caracteres;
- valor de campo: 512 caracteres;
- traceback sanitizado: 4096 caracteres;
- campos por evento: 24;
- nombre de evento: 64 caracteres;
- correlation ID: 64 caracteres;
- catálogo de métricas: fijo;
- buckets de duración: fijos.

## Efectos prohibidos

```text
NETWORK_ENDPOINT_IMPLEMENTATION=NOT_PERFORMED
EXTERNAL_OBSERVABILITY_INTEGRATION=NOT_PERFORMED
EXTERNAL_NETWORK=NOT_REQUESTED
FILESYSTEM_MUTATION_BY_LIBRARY=NOT_PERFORMED
SECRET_STORAGE=NOT_PERFORMED
SECRET_GENERATION=NOT_PERFORMED
PUSH=NOT_PERFORMED
UPSTREAM=NOT_CONFIGURED
REMOTE_BRANCH=NOT_CREATED
SUBTASK_6_3_CLOSURE=NOT_PERFORMED
```
