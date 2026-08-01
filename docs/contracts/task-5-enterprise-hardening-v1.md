# CEPH-CICADAPORT-TASK-5-001 — Enterprise Engine and Production Hardening

```text
CONTRACT=CEPH-CICADAPORT-TASK-5-001
VERSION=1.0-CANDIDATE
STATUS=CANDIDATE_UNDER_SUBTASK_5_1
PRIMARY_DELIVERABLE=ENTERPRISE_WORKING_SOFTWARE
AUTHORIZED_BASE=main@bfaa7e6c2989dc923b418862ce9243e68e3f569c
AUTHORIZED_TAG=task-4
```

## 1. Propósito

TASK 5 transforma la release candidate especializada de CicadaPort en una base
operable para evaluaciones empresariales autorizadas. El objetivo no es ampliar
sin control la superficie ofensiva, sino endurecer rendimiento, persistencia,
evidencia, seguridad operativa, supply chain y soporte.

## 2. Invariantes heredadas

1. TASK 4 y sus contratos v1 permanecen cerrados y congelados.
2. Rust continúa siendo el motor TCP público obligatorio.
3. Go continúa siendo el motor de banners cuando la fase está habilitada.
4. Python conserva orquestación, política, presentación y compatibilidad.
5. No existe fallback público silencioso a motores Python.
6. Toda actividad de red requiere alcance autorizado.
7. La evolución v2 debe tener migración o adaptador explícito; nunca reinterpretar
   silenciosamente un documento v1.
8. Los resultados canónicos mantienen `state` y `evidence.reason` como fuentes
   de verdad durante la migración.

## 3. Descomposición

| Subtask | Resultado |
| --- | --- |
| 5.1 | Arquitectura, contratos y baseline reproducible |
| 5.2 | Session Store v2 y artefactos seguros |
| 5.3 | Rust TCP Engine v2 |
| 5.4 | Go Service Evidence Engine v2 |
| 5.5 | Endurecimiento operativo, supply chain y release |
| 5.6 | Validación empresarial integral y nueva release candidate |

5.2, 5.3 y 5.4 solo podrán avanzar en paralelo después de congelar los
contratos y presupuestos de 5.1. La integración se hará por puertas agrupadas.

## 4. Requisitos empresariales transversales

### 4.1 Rendimiento y recursos

- memoria y colas acotadas independientemente del rango total;
- límites globales y por objetivo de sockets y tasa;
- backpressure explícito entre motores, orquestador y persistencia;
- cancelación cooperativa con tiempo máximo verificable;
- ausencia de crecimiento cuadrático de almacenamiento;
- presupuestos medidos para CPU, RSS, descriptores, I/O, archivos y tiempo.

### 4.2 Integridad y trazabilidad

- identidad de build y commit en cada ejecución;
- manifiesto de alcance y plan inmutable;
- evidencia append-only o transaccional;
- hashes de artefactos y cadena de custodia;
- eventos monotónicos y correlacionables;
- migraciones versionadas, reanudables e idempotentes.

### 4.3 Seguridad operativa

- permisos restrictivos por defecto;
- resistencia a symlinks, TOCTOU y sobrescritura accidental;
- neutralización de controles terminales y fórmulas;
- límites de tamaño en todas las entradas y salidas;
- secretos y datos sensibles fuera de logs por defecto;
- políticas de alcance, tasa, retención y eliminación segura.

### 4.4 Supply chain

- dependencias y actions fijadas de forma inmutable;
- SBOM CycloneDX actual;
- provenance SLSA para artefactos de release;
- firma y verificación de binarios y paquetes;
- SAST, auditoría de dependencias, secret scanning y pruebas reproducibles.

## 5. Referencias normativas de diseño

- NIST SP 800-218 SSDF 1.1 como marco de desarrollo seguro.
- SLSA 1.2 Build Track para provenance de artefactos.
- CycloneDX 1.7 para inventario y BOM.
- OpenTelemetry Semantic Conventions para nombres estables de telemetría.
- SQLite WAL como candidato de persistencia transaccional local, sujeto a las
  restricciones de filesystem y recuperación definidas en 5.2.

Estas referencias orientan la arquitectura; no sustituyen los contratos
específicos ni convierten una capacidad candidata en implementada.

## 6. Puertas de calidad

Cada subtask requiere como mínimo:

1. contrato y amenaza asociados;
2. pruebas unitarias y contractuales;
3. pruebas de integración deterministas;
4. benchmark contra la baseline de 5.1;
5. auditorías de dependencias;
6. evidencia de no regresión de contratos v1;
7. commit firmado y CI verde;
8. cierre formal antes de abrir la siguiente dependencia.

La validación costosa se agrupa en un solo ciclo por subtask, salvo divergencia
material, fallo de seguridad o regresión de rendimiento.
