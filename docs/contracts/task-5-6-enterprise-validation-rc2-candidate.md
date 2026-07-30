# EIVRC-CICADAPORT-5.6-001 — Validación empresarial integral y nueva Release Candidate

```text
CONTRACT=EIVRC-CICADAPORT-5.6-001
VERSION=1.0-CANDIDATE
STATUS=CANDIDATE_PENDING_FORMAL_APPROVAL
TASK=TASK_5
SUBTASK=SUBTASK_5_6
PRIMARY_DELIVERABLE=ENTERPRISE_VALIDATED_RELEASE_CANDIDATE
AUTHORIZED_BRANCH=feat/task-5-enterprise-engine-production-hardening
AUTHORIZED_BASE=af6ccaeb45394a837f7277b6a6e8508683eda032
PROPOSED_RELEASE=3.0.0-rc.2
IMPLEMENTATION_MATERIAL=NOT_AUTHORIZED
MAIN_INTEGRATION=NOT_AUTHORIZED
TAG_CREATION=NOT_AUTHORIZED
RELEASE_PUBLICATION=NOT_AUTHORIZED
```

## 1. Propósito

SUBTASK 5.6 constituye la puerta final de integración de TASK 5. Su propósito es
validar de forma integral, reproducible y auditable la convergencia de las
capacidades cerradas y congeladas en SUBTASKS 5.1–5.5, preparar una nueva
Release Candidate empresarial y demostrar que los artefactos producidos son
instalables, trazables, reproducibles, firmados y compatibles con las
invariantes heredadas de TASK 4.

La subtask no amplía la superficie ofensiva de CicadaPort. La denominación
“nueva Release Candidate” no autoriza por sí sola integración a `main`,
creación de etiqueta ni publicación. Esas operaciones permanecen sujetas a una
puerta formal posterior y separada.

## 2. Base y predecesores congelados

La implementación, cuando sea autorizada, partirá exclusivamente de:

- rama `feat/task-5-enterprise-engine-production-hardening`;
- commit firmado `af6ccaeb45394a837f7277b6a6e8508683eda032`;
- árbol `4125d93d1d4575f73db1f4703fa0c906a74fe619`;
- `origin/main@bfaa7e6c2989dc923b418862ce9243e68e3f569c`;
- etiqueta institucional firmada `task-4`.

Se preservan como predecesores cerrados y congelados:

- SUBTASK 5.1 — arquitectura, contratos y baseline;
- SUBTASK 5.2 — Session Store v2 y artefactos seguros;
- SUBTASK 5.3 — Rust TCP Engine v2;
- SUBTASK 5.4 — Go Service Evidence Engine v2;
- SUBTASK 5.5 — endurecimiento operacional de supply chain y release.

## 3. Invariantes obligatorias

1. Rust continúa siendo el motor TCP público obligatorio.
2. Go continúa siendo el motor de banners y evidencia de servicio cuando la
   fase está habilitada.
3. Python conserva orquestación, política, presentación y compatibilidad.
4. No existe fallback público silencioso a motores Python.
5. Los contratos públicos JSONL permanecen en versión 1.
6. `service_evidence` permanece en versión 2.
7. Toda actividad de red de aceptación se limita a loopback o a un alcance
   autorizado explícito.
8. No se introducen técnicas raw, SYN, UDP, descubrimiento de hosts,
   identificación activa de sistemas operativos, detección de
   vulnerabilidades, explotación ni evasión.
9. Las superficies congeladas solo podrán modificarse mediante una incidencia
   formal, evidencia reproducible y autorización específica.
10. No se reescribe historial ni se utiliza push forzado.

## 4. Alcance material propuesto

Tras la aprobación formal del contrato, SUBTASK 5.6 podrá:

### 4.1 Reconciliar el estado documental

- actualizar `docs/task-5-status.md`, `README.md`, `ROADMAP.md` y `CHANGELOG.md`;
- registrar SUBTASK 5.5 como cerrada y congelada;
- registrar SUBTASK 5.6 como abierta en implementación;
- eliminar referencias operativas obsoletas sin reescribir la evidencia
  histórica.

### 4.2 Definir la nueva Release Candidate

- proponer y aplicar la versión `3.0.0-rc.2` / `3.0.0rc2`;
- actualizar de forma coherente la fuente única de versión, metadatos de
  empaquetado, documentación, nombre de artefactos y manifiestos;
- mantener sin cambios la versión de los contratos públicos;
- documentar la diferencia funcional y operativa entre RC1 y RC2.

### 4.3 Construir una aceptación empresarial integral

- encadenar la evidencia hasheada de SUBTASKS 5.1–5.5;
- verificar commits firmados, ancestría y estados congelados;
- ejecutar la suite completa Python, Rust, Go y Shell;
- validar Session Store v2, migración v1→v2, recuperación transaccional y
  artefactos seguros;
- validar Rust TCP Engine v2 y Go Service Evidence Engine v2;
- ejecutar escenarios end-to-end de CLI, TUI, sesiones simples, multiobjetivo,
  reanudación, cancelación, persistencia y reportes;
- ejecutar exclusivamente pruebas de red sobre loopback;
- comparar rendimiento y recursos contra las baselines congeladas;
- validar wheel y sdist instalados fuera del checkout;
- construir dos veces y comparar byte a byte los artefactos reproducibles;
- verificar SBOM CycloneDX, manifiesto de build, hashes, SLSA provenance y
  attestations Sigstore;
- validar la matriz Ubuntu 22.04/24.04 y Python 3.10–3.13.

### 4.4 Preparar evidencia de release

- generar log completo, JSON, Markdown y `SHA256SUMS`;
- producir inventario de artefactos y hashes;
- registrar commit, árbol, toolchains, plataforma y versión;
- generar un paquete candidato local y artefactos CI sin publicación pública;
- elaborar una auditoría candidata de cierre de TASK 5.

## 5. Exclusiones

Quedan fuera de SUBTASK 5.6:

- nuevas capacidades de red;
- cambios funcionales no necesarios en Rust, Go, Session Store v2 o contratos;
- soporte no verificado para Windows, macOS, ARM64 o Python 3.14;
- arquitectura distribuida, servicio central o RBAC federado;
- CVE scanning funcional, explotación o scripting ofensivo;
- escaneo de objetivos externos durante la aceptación;
- integración automática a `main`;
- creación automática de etiqueta;
- publicación automática de GitHub Release o paquetes;
- declaración de versión estable;
- cierre automático de TASK 5.

## 6. Manifiesto canónico de superficies congeladas

La huella contractual deberá generarse únicamente desde contenido versionado en
Git para el commit autorizado. Debe excluir expresamente:

- `rust-core/target/`;
- `__pycache__/` y `*.pyc`;
- `dist/`, `build/` y caches;
- reportes y evidencia local;
- binarios u objetos compilados no versionados.

El manifiesto debe ser determinista, estar ordenado por ruta y registrar
SHA-256 del contenido de `HEAD:<ruta>`.

## 7. Criterios de aceptación

SUBTASK 5.6 solo podrá declararse candidata a cierre cuando todos los controles
siguientes estén en PASS:

1. cadena de custodia válida para SUBTASKS 5.1–5.5;
2. commits y etiquetas institucionales requeridos con firma válida;
3. estado documental reconciliado;
4. versión RC2 coherente en todas las fuentes autorizadas;
5. contratos públicos v1 y `service_evidence` v2 preservados;
6. suite Python completa PASS;
7. Rust fmt, clippy, tests y release build PASS;
8. Go fmt, vet, race tests y build reproducible PASS;
9. ShellCheck PASS;
10. pruebas integrales de CLI/TUI/sesiones/reportes PASS;
11. recuperación, migración, cancelación y persistencia PASS;
12. presupuestos de rendimiento y recursos PASS frente a baseline;
13. lock hasheado, SAST, secret scanning y auditorías PASS;
14. wheel y sdist instalables fuera del checkout en toda la matriz soportada;
15. builds reproducibles byte a byte;
16. CycloneDX, manifiesto, hashes, SLSA y Sigstore PASS;
17. escaneo externo ejecutado: `0`;
18. nuevas capacidades de red: `0`;
19. mutaciones no autorizadas de superficies congeladas: `0`;
20. commit final firmado, push no forzado y CI remoto completo PASS.

## 8. Evidencia obligatoria

La aceptación deberá generar como mínimo:

- `task-5-6-enterprise-acceptance-run.log`;
- `task-5-6-enterprise-acceptance.json`;
- `task-5-6-enterprise-acceptance.md`;
- `task-5-6-release-inventory.json`;
- `task-5-6-frozen-surface-sha256.txt`;
- `SHA256SUMS`.

El JSON deberá vincular:

- contrato y versión;
- base y HEAD aceptado;
- árbol Git;
- versión RC propuesta;
- commits congelados de SUBTASKS 5.1–5.5;
- resultados de cada puerta;
- hashes de todos los artefactos;
- declaración explícita de ausencia de publicación.

## 9. Plan de implementación

### Fase A — Corrección y reconciliación

1. ejecutar auditoría inicial v2;
2. sustituir el manifiesto contaminado por una huella canónica;
3. reconciliar el estado formal y el estado documental;
4. presentar el changeset autorizado.

### Fase B — Contratos y versión

1. incorporar este contrato tras aprobación;
2. definir `3.0.0-rc.2` como versión candidata;
3. actualizar metadatos y documentación;
4. añadir contratos estáticos de coherencia.

### Fase C — Runner integral

1. implementar runner de aceptación 5.6;
2. encadenar evidencias 5.1–5.5;
3. ejecutar pruebas funcionales, operativas y de recursos;
4. generar evidencia hasheada.

### Fase D — Validación local

1. ejecutar aceptación completa;
2. resolver incidencias sin reescribir evidencia;
3. verificar superficies congeladas;
4. preparar staging limitado.

### Fase E — Commit y CI de rama

1. commit firmado;
2. push no forzado;
3. CI completo;
4. attestations y artefactos candidatos;
5. auditoría candidata de cierre.

### Fase F — Puerta de release separada

Solo una autorización posterior podrá permitir:

1. integración a `main`;
2. CI de `main`;
3. etiqueta firmada de gobierno;
4. etiqueta de release `v3.0.0-rc.2`;
5. publicación de la nueva Release Candidate;
6. cierre y congelamiento de SUBTASK 5.6 y TASK 5.

## 10. Estado del contrato

```text
CONTRACT_STATUS=CANDIDATE_PENDING_FORMAL_APPROVAL
SUBTASK_5_6=OPENED_DELIMITATION_IN_PROGRESS
IMPLEMENTATION_MATERIAL=NOT_STARTED
SUBTASK_5_5=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
TASK_5=IN_IMPLEMENTATION
```

La aprobación de este contrato autorizará únicamente la implementación material
definida en las fases A–E. No autorizará por sí misma integración a `main`,
etiquetado ni publicación.
