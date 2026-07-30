# ARCH-CICADAPORT-5.1-001 — Arquitectura objetivo empresarial

```text
VERSION=1.0-CANDIDATE
STATUS=NON_EXECUTABLE_ARCHITECTURE
BASE=task-4@bfaa7e6c2989dc923b418862ce9243e68e3f569c
```

## 1. Principio rector

El flujo de datos debe ser incremental, acotado y transaccional. Ningún
componente puede exigir mantener en memoria o reescribir la totalidad de una
sesión después de cada resultado.

```text
Scope Authorization + Immutable Scan Plan
                    |
                    v
         Python Policy Orchestrator
          /          |           \
         v           v            v
 Rust TCP Engine  Go Evidence   Telemetry
    bounded         bounded       bounded
      stream          stream        stream
          \             |           /
           \            v          /
            ---> Session Store v2 <---
                    SQLite WAL
                         |
                         v
             Secure Artifact Writer
                         |
           findings / evidence / summary
```

## 2. Límites de confianza

1. **Entrada del operador:** no confiable hasta validación de alcance y límites.
2. **Python → motores:** contrato versionado, tamaño limitado e identidad de
   binario verificada.
3. **Motores → Python:** JSONL/eventos no confiables hasta validación estricta.
4. **Persistencia local:** directorio privado; filesystem no asumido como seguro.
5. **Reportes:** contenido hostil procedente de servicios remotos.
6. **CI/release:** runners y dependencias son parte de la cadena de suministro.

## 3. Flujo de ejecución objetivo

1. Resolver y congelar el plan.
2. Validar autorización, exclusiones y presupuesto.
3. Crear transacción de sesión y registrar identidad de build.
4. Despachar trabajo mediante colas acotadas.
5. Recibir resultados incrementales con backpressure.
6. Confirmar lotes transaccionales y avance monotónico.
7. Reanudar únicamente trabajo no confirmado.
8. Consolidar reportes mediante snapshots consistentes.
9. Firmar/hashar el bundle de evidencia.
10. Aplicar retención y compactación conforme a política.

## 4. Persistencia

Session Store v2 se propone sobre SQLite WAL porque permite separar el registro
incremental del snapshot final, usar transacciones por lote y evitar dos archivos
completos por puerto. La implementación deberá verificar:

- filesystem local compatible y writable;
- `journal_mode=WAL` efectivo;
- política `synchronous` documentada;
- límites de WAL y checkpoint;
- comportamiento ante disco lleno, `SIGKILL` y corrupción;
- acceso de un solo escritor lógico por sesión;
- exportación portable independiente de los archivos `-wal` y `-shm`.

## 5. Compatibilidad

Los documentos v1 siguen siendo legibles. El camino permitido es:

```text
v1 immutable directory
        |
        v
validated importer --dry-run
        |
        v
v2 transaction + migration manifest
        |
        v
integrity verification
```

Nunca se modifica in-place un almacén v1. El importador debe ser idempotente,
registrar hashes de origen y poder abandonar sin afectar la fuente.

## 6. Observabilidad

La telemetría se separa del resultado funcional:

- resultado y persistencia: camino crítico;
- eventos/metrics: best-effort con contador de pérdida;
- modo estricto: opt-in y explícito;
- atributos estables para sesión, endpoint, motor, fase, secuencia y build;
- cardinalidad acotada: no usar banners ni errores completos como etiquetas.

## 7. Despliegue inicial

La primera meta empresarial continúa siendo un agente local Linux x86_64 para
escaneo TCP-connect autorizado. La ejecución distribuida, el servicio central,
RBAC federado y nuevas técnicas de red quedan fuera de 5.1 y requieren contratos
posteriores.
