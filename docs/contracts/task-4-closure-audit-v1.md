# Contrato definitivo de auditoría y cierre de TASK 4

```text
CONTRACT_ID=ACCT-CICADAPORT-TASK-4-001
CONTRACT_VERSION=1.0-DEFINITIVA
STATUS=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
TASK=4
PRIMARY_DELIVERABLE=WORKING_SOFTWARE
IMPLEMENTATION_BASE=84dd1f1eafb684b5afccd7ad647781d8a5b4b459
IMPLEMENTATION_HEAD=77ad51f0751b29b510f574e750c1a3fa65db4a60
CLOSURE_REFERENCE=SIGNED_TAG:task-4
TASK_5=BLOCKED_NOT_STARTED
```

## Objeto

Reconciliar el estado documental con el software ya validado; auditar la
integridad de los contratos y superficies públicas de TASK 4; cerrar,
consolidar y congelar las SUBTASKS 4.1 a 4.5 sin modificar materialmente Rust,
Go ni el comportamiento de red.

## Controles de salida

1. `77ad51f0751b29b510f574e750c1a3fa65db4a60` desciende linealmente de la base
   congelada del Hito 3.
2. Las SUBTASKS 4.1 a 4.5 están documentadas como
   `COMPLETED_CONSOLIDATED_CLOSED_FROZEN`.
3. Los contratos `scan_plan`, checkpoint, manifiesto, resultados nativos y
   eventos públicos conservan versión 1.
4. CLI y TUI consumen los mismos runtimes de sesión, sin lógica de red
   duplicada.
5. Rust continúa siendo el motor TCP público obligatorio y Go el motor de
   banners cuando se solicita esa fase.
6. No existe selector público de motores ni fallback Python silencioso.
7. La reanudación preserva plan, identidad, secuencia, hashes y trabajo ya
   confirmado.
8. La ejecución remota #60 sobre el head funcional termina en `Success` y
   aprueba matrices Python, Rust, Go, Shell, auditorías, empaquetado,
   instalación aislada e integración.
9. La auditoría local reproducible no identifica regresiones funcionales en las
   pruebas ejecutables disponibles.
10. El cierre modifica únicamente documentación de gobierno, contratos,
    manuales y evidencia.
11. El commit de cierre y la etiqueta `task-4` son anotados y firmados; el CI de
    rama y de `main` termina en verde.
12. TASK 5 permanece bloqueada y no se implementa ninguna capacidad nueva.

## Regla de materialización del cierre

Este contrato forma parte del commit documental de cierre. El estado definitivo
se materializa cuando se cumplen conjuntamente:

```text
SIGNED_CLOSURE_COMMIT=VERIFIED
BRANCH_CI=PASS
FAST_FORWARD_INTEGRATION_TO_MAIN=VERIFIED
MAIN_CI=PASS
SIGNED_TAG_task-4=VERIFIED
TAG_TARGET=MAIN_HEAD
```

El tag `task-4` es la referencia institucional canónica del cierre. No se
requiere incorporar el SHA del propio commit dentro del documento, evitando
una referencia autorrecursiva; el objetivo verificado de la etiqueta constituye
la fuente de verdad.

## Restricciones

- no modificar `rust-core/**`;
- no modificar `go-banner/**`;
- no modificar `src/**`, `tests/**`, scripts o workflows;
- no cambiar versiones de aplicación o contratos JSONL;
- no publicar una versión estable;
- no abrir TASK 5;
- no introducir descubrimiento, raw scanning, UDP nuevo, vulnerabilidades,
  explotación ni escaneo no autorizado.
