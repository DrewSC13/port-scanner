# TASK 6.1 — Arquitectura operativa y baseline

- Identificador: `ARCH-CICADAPORT-6.1-001`
- Contrato superior: `OPBASE-CICADAPORT-6.1-001`
- Versión: `1.0-CANDIDATE`
- Base autorizada: `main@30ac1780239abe9a63d6a6dd47f101398b7bb33f`
- Estado: `IN_MATERIAL_IMPLEMENTATION`

## 1. Propósito

Esta arquitectura define la superficie operativa mínima necesaria para medir,
desplegar, diagnosticar y soportar CicadaPort sin ampliar sus capacidades de
red ni alterar los contratos públicos congelados por TASK 5.

El primer bloque de SUBTASK 6.1 es exclusivamente instrumental y documental.
No modifica `src/`, `rust-core/`, `go-banner/`, CLI, TUI, contratos JSONL,
Session Store v2 ni Secure Artifacts v2.

## 2. Principios

1. **Mínimo privilegio:** la operación ordinaria no requiere `root`,
   `CAP_NET_RAW`, contenedores privilegiados ni acceso de escritura global.
2. **Evidencia privada:** directorios `0700` y archivos `0600`.
3. **Red externa deshabilitada:** el baseline operacional no abre sockets ni
   contacta servicios externos.
4. **Identidad reproducible:** rama, commit, árbol, toolchain y host quedan
   registrados en cada ejecución.
5. **Separación entre observación y soporte:** el host observado no amplía por
   sí mismo la matriz de soporte declarada.
6. **No regresión:** TASK 4 y TASK 5 permanecen congeladas.
7. **Recursos acotados:** todas las pruebas usan perfiles finitos y límites
   explícitos.

## 3. Modelos de despliegue candidatos

| Modelo | Propósito | Estado |
| --- | --- | --- |
| Instalación local administrada | Estación técnica autorizada | CANDIDATE |
| Servicio Linux sin privilegios | Host dedicado bajo service manager | CANDIDATE |
| Contenedor aislado no privilegiado | Empaquetado futuro | DOCUMENTARY_ONLY |

Ningún modelo se considera soportado hasta completar mediciones, instalación,
actualización, rollback y aceptación independientes.

## 4. Componentes operativos

| Componente | Responsabilidad | Persistencia |
| --- | --- | --- |
| Python orchestration layer | Sesiones, CLI/TUI y coordinación | Configuración y sesiones |
| Rust TCP Engine v2 | TCP-connect autorizado | Sin persistencia propia |
| Go Service Evidence v2 | Evidencia pasiva de servicio | Sin persistencia propia |
| Session Store v2 | Generaciones, checkpoints y reanudación | Persistente |
| Secure Artifacts v2 | Escritura privada y atómica | Persistente |
| CI y release tooling | Verificación y artefactos reproducibles | Efímera/inmutable |

## 5. Layout operativo candidato

```text
/etc/cicadaport/                 configuración administrada
/var/lib/cicadaport/             estado persistente
/var/lib/cicadaport/artifacts/   artefactos seguros
/var/log/cicadaport/             logs operativos
/run/cicadaport/                 estado efímero
/opt/cicadaport/                 instalación administrada
```

El layout es una propuesta contractual. Este bloque no crea esos directorios.

## 6. Límites de privilegios

```text
ROOT_REQUIRED=false
CAP_NET_RAW_REQUIRED=false
PRIVILEGED_CONTAINER=false
RAW_SOCKET_CAPABILITY=false
TCP_CONNECT_ONLY=true
EXTERNAL_NETWORK_BASELINE=false
```

## 7. Baseline operacional inicial

El benchmark `task_6_1_operational_baseline.py` mide únicamente:

- identidad Git y toolchains;
- CPU, memoria, filesystem, espacio libre y límites de archivos;
- latencia de creación, `fsync`, lectura y reemplazo atómico en un directorio
  temporal privado;
- coste de arranque de un proceso Python aislado;
- coste acotado de apertura y cierre de descriptores sobre `/dev/null`;
- permisos y hashes de la evidencia.

No ejecuta escaneos, motores nativos, DNS, sockets ni tráfico de red.

## 8. Matriz de soporte preservada

La matriz heredada de TASK 5 permanece sin ampliación:

```text
OS_FAMILY=Linux
ARCHITECTURE=x86_64
CI_DISTRIBUTIONS=Ubuntu_22.04+Ubuntu_24.04
PYTHON=3.10-3.13
WINDOWS=NOT_VALIDATED
MACOS=NOT_VALIDATED
ARM64=NOT_VALIDATED
PYTHON_3_14=NOT_VALIDATED
```

La observación de otra distribución o versión se registra como host de prueba,
no como plataforma soportada.

## 9. Riesgos controlados por este bloque

- deriva de configuración;
- permisos inseguros;
- crecimiento no acotado de evidencia;
- falta de diagnóstico del host;
- sobredeclaración de soporte;
- agotamiento de descriptores o almacenamiento;
- mezcla entre benchmark y comportamiento de producción;
- acceso accidental a red externa.

## 10. Barreras

```text
PRODUCTION_CODE_CHANGES=0
PUBLIC_CONTRACT_CHANGES=0
NEW_NETWORK_CAPABILITIES=0
PUSH=NOT_AUTHORIZED
MERGE_TO_MAIN=NOT_AUTHORIZED
TAG_CREATION=NOT_AUTHORIZED
RELEASE_PUBLICATION=NOT_AUTHORIZED
PACKAGE_PUBLICATION=NOT_AUTHORIZED
```
