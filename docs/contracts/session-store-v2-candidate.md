# SSV2-CICADAPORT-5.2-001 — Session Store v2

```text
VERSION=1.0-CANDIDATE
STATUS=NON_EXECUTABLE_PENDING_5.1_CLOSURE
DEFAULT_BACKEND=SQLite_WAL
```

## 1. Problema que resuelve

El Store v1 conserva snapshots JSON completos e inmutables para checkpoint y
manifiesto en cada secuencia. Esa estrategia prioriza integridad simple, pero el
runtime confirma una secuencia por resultado y en batch carga y vuelve a
serializar el estado global. El resultado esperado es amplificación de I/O,
archivos e inodos cercana a O(n²) en bytes acumulados.

## 2. Modelo lógico mínimo

```text
session
scan_plan
endpoint
port_result
banner_evidence
event
artifact
migration
metadata
```

Claves e invariantes:

- `session_id` UUID y único;
- plan inmutable por `plan_fingerprint`;
- endpoint único por `(requested,address,family)`;
- resultado único por `(session_id,endpoint_id,protocol,port)`;
- secuencia de evento monotónica por sesión;
- progreso derivado de filas confirmadas, no de contadores libres;
- banners separados del resultado TCP;
- estado terminal consistente con cobertura y errores.

## 3. Transacciones y lotes

- un escritor lógico por sesión;
- cola bounded desde el orquestador;
- commit por `N` resultados o intervalo `T`, lo que ocurra primero;
- commit inmediato para cancelación, fallo y transición terminal;
- `N` y `T` sujetos a benchmark y política de durabilidad;
- ninguna reescritura de resultados ya confirmados;
- consumidores leen snapshots consistentes.

## 4. Durabilidad

Perfiles candidatos:

| Perfil | Uso | Requisito |
| --- | --- | --- |
| strict | evidencia regulada | `synchronous=FULL`, commit pequeño |
| balanced | valor por defecto | `synchronous=NORMAL`, WAL acotado |
| throughput | laboratorio controlado | requiere opt-in y advertencia |

La implementación debe verificar el valor efectivo de PRAGMAs y fallar si el
backend no cumple el perfil solicitado.

## 5. Seguridad del archivo

- directorio `0700`, database/WAL/SHM `0600`;
- rechazo de symlink y ruta fuera del root;
- no aceptar base de datos preexistente sin header y ownership válidos;
- límites de tamaño y cuota mínima libre;
- `PRAGMA trusted_schema=OFF` cuando sea compatible;
- consultas parametrizadas;
- `integrity_check` y `foreign_key_check` en auditoría/recuperación;
- exportación portable a bundle cerrado y hasheado.

## 6. Retención y compactación

- política por edad, estado y tamaño;
- checkpoint WAL explícito al cerrar;
- `VACUUM INTO` o exportación controlada, nunca compactación destructiva sin
  espacio suficiente;
- conservar metadatos de auditoría aunque se purguen payloads permitidos;
- registrar toda eliminación y su política.

## 7. Migración v1

- solo lectura de la fuente;
- verificación de `CURRENT.json`, hashes, generaciones y contrato;
- importación transaccional a un destino nuevo;
- manifiesto con hashes de todos los archivos fuente usados;
- comparación de cobertura, estados, banners y secuencia;
- reejecución idempotente;
- rollback por descarte del destino, nunca por modificar el v1.

## 8. Criterios de aceptación preliminares

- crecimiento de almacenamiento lineal con resultados;
- no más de un conjunto acotado de archivos por sesión;
- reanudación después de `SIGKILL` sin duplicar resultados;
- 65.535 resultados soportados dentro del presupuesto aprobado;
- p95 de confirmación de lote y tiempo de cancelación medidos;
- pruebas de disco lleno, WAL corrupto, permisos y migración.
