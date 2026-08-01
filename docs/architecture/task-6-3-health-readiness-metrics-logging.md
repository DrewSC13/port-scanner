# Arquitectura de observabilidad local — SUBTASK 6.3

## Decisión

CicadaPort implementará observabilidad como una superficie **in-process**.
Los consumidores internos reciben snapshots o JSON ya sanitizado. La subtask
no crea endpoints ni conecta exporters.

## Componentes

### `src/health.py`

Responsabilidades:

- estado health thread-safe;
- snapshots inmutables;
- separación liveness/readiness;
- reason codes estables;
- UTC y monotonic separados;
- composición fail-closed con el diagnóstico seguro de SUBTASK 6.2.

### `src/metrics.py`

Responsabilidades:

- catálogo fijo;
- tipos COUNTER, GAUGE e HISTOGRAM;
- allowlists de etiquetas;
- cardinalidad máxima calculable;
- actualización thread-safe;
- snapshot determinista sin exporter.

### `src/structured_logging.py`

Responsabilidades:

- esquema JSON versionado;
- límites de tamaño;
- valores escalares;
- redacción antes de serializar;
- sanitización de traceback;
- sink best-effort sin recursión.

### `src/observability.py`

Responsabilidades:

- fachada local;
- sincronizar health con gauges;
- registrar inicio y finalización de operaciones;
- construir un snapshot compuesto;
- declarar explícitamente que no hubo export ni endpoint.

## Flujo

```text
SUBTASK 6.1 operations layout ─┐
                              ├─> diagnostics 6.2 ─> readiness 6.3
SUBTASK 6.2 configuration ─────┘

runtime event ─> local facade ─> bounded metrics snapshot
             └> safe structured event ─> caller-provided local sink
```

## Límites de confianza

La fachada no recibe secretos por diseño. Cuando el caller conoce un valor
protegido, debe entregarlo explícitamente como `ProtectedValue` al logger para
redacción exacta. Las excepciones se sanitizan y acotan antes de serializarse.

## Thread safety

- `HealthState` protege transición y snapshot con `RLock`.
- `BoundedMetricsRegistry` protege series y snapshots con `RLock`.
- el sink de logging pertenece al caller; el adaptador no presupone que sea
  thread-safe y nunca propaga sus fallos.

## No red

Los módulos no importan bibliotecas de red, no abren sockets, no ejecutan
servidores y no implementan `bind` o `listen`. Las palabras asociadas a
endpoints externos solo aparecen en documentación contractual y validadores
negativos.

## Compatibilidad

- Python 3.10–3.13;
- solo biblioteca estándar;
- composición con `src.security_values` congelado en SUBTASK 6.2;
- sin nuevas dependencias;
- sin modificación de los archivos de SUBTASK 6.1 o 6.2.
