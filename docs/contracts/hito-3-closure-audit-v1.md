# Contrato provisional de auditoría y cierre del Hito 3

## Identidad

- **Contrato:** `ACCH-CICADAPORT-3.2.12-001`
- **Versión:** `1.0-CANDIDATA`
- **Estado:** `IN_IMPLEMENTATION`
- **Subhito:** `3.2.12 — Auditoría de cierre y congelamiento del Hito 3`
- **Base:** `main@9d3d75112a49e8608c4cb4619b244372c08ae077`
- **Rama:** `feat/subhito-3.2.12-auditoria-cierre-hito-3`
- **Dependencia:** 3.2.8–3.2.11 `CLOSED_FROZEN`
- **Hito 4:** `BLOCKED_NOT_STARTED`

## Objetivo

Auditar contratos, documentación, empaquetado, seguridad, pruebas, CI, deuda
técnica, rutas públicas, procesos nativos y la ausencia de capacidades
reservadas al Hito 4; producir evidencia reproducible y preparar un cierre
lineal firmado con la etiqueta institucional `subhito-3.2.12`.

## Doce controles de salida

1. Todos los subhitos obligatorios están `CLOSED_FROZEN`.
2. No queda deuda crítica sin propietario, decisión o justificación.
3. Los contratos públicos y nativos están versionados y documentados.
4. CLI, TUI, reportes y motores comparten el modelo canónico de resultados.
5. La cancelación no deja procesos activos ni zombis persistentes.
6. Los artefactos se construyen e instalan de forma aislada.
7. Python, Rust, Go, Shell e integración están completamente verdes.
8. Las plataformas declaradas tienen evidencia o límite explícito.
9. README, CONTRIBUTING, SECURITY, CHANGELOG y ROADMAP son coherentes.
10. Los commits de cierre y la etiqueta final están firmados y verificados.
11. Las pruebas de red se limitan a loopback o alcance autorizado.
12. No se incorporó ninguna capacidad reservada al Hito 4.

## Fuentes de verdad preservadas

- Producto: `CicadaPort`.
- Distribución: `portscanner-pro` `3.0.0rc1`.
- Flujo: `Python → Rust → Python → Go → Python`.
- Interoperabilidad: JSONL v1.
- Estado: `state`.
- Razón: `evidence.reason`.
- Proyecciones: `reason` e `is_open`.
- Reportabilidad: únicamente `state == open`.
- Selectores públicos: ausentes.
- Fallback Python: ausente.

## Restricciones

La primera etapa no autoriza staging, commit, push, integración, etiquetado,
modificación de la prerelease, publicación estable, etiqueta `hito-3`,
eliminación de ramas ni inicio del Hito 4.

No autoriza por defecto cambios en código ejecutable. Toda divergencia funcional
debe clasificarse y requerir autorización independiente.

Permanecen fuera de alcance descubrimiento de hosts, ICMP, ARP, sockets o
paquetes raw, SYN scan, nuevas capacidades UDP, identificación activa de
sistemas operativos, vulnerabilidades, explotación, evasión, scripting ofensivo
y escaneo externo o no autorizado.

## Flujo de cierre

Diagnóstico → revisión → autorización → staging → commit firmado → CI de rama →
integración lineal → CI de main → etiqueta firmada `subhito-3.2.12` → cierre
formal. Cerrar el Hito 3 no abre automáticamente el Hito 4.

## Excepción y aceptación histórica controlada

<!-- DECISION-ID: ACCH-3.2.12-HIST-001 -->

Para los fines exclusivos de esta auditoría se aceptan los cierres históricos
de 3.2.1, 3.2.2 y 3.2.3 sin etiquetas retroactivas.

La única excepción aprobada es
`ACCEPTED_HISTORICAL_EXCEPTION_UNSIGNED_PLATFORM_MERGE` para el commit
`2c47f13939b17603ecda3f816293e1ed4cbab50b`, merge histórico del PR `#7`.

Esta excepción:

- no modifica la exigencia vigente de commits y etiquetas firmados;
- no se extiende al Subhito 3.2.12 ni a trabajos posteriores;
- no autoriza reescritura de historial;
- no autoriza etiquetas retroactivas;
- no abre el Hito 4.

<!-- BEGIN ACCH-3.2.12-STAGE2 -->
## Consolidación definitiva de la segunda etapa

La segunda etapa de `ACCH-CICADAPORT-3.2.12-001` se ejecutó sobre `9d3d75112a49e8608c4cb4619b244372c08ae077` y queda
`COMPLETED_READY_FOR_STAGING_AUTHORIZATION`.

Resultado contractual:

- `DT-01..DT-06=CLOSED`;
- `C01..C09=PASS`;
- `C10=PENDING_BY_DESIGN`;
- `C11..C12=PASS`;
- `OPEN_DISCREPANCIES=0`;
- `FUNCTIONAL_DIVERGENCES=0`;
- `HITO4_MATERIAL_CAPABILITIES=0`;
- `PUBLIC_ENGINE_SELECTORS=0`;
- `UNAUTHORIZED_NETWORK_ACTIONS=0`.

La observación de paridad fue clasificada como
`NON_REPRODUCIBLE_TRANSIENT_FAILURE` tras tres reintentos focalizados y una
ejecución completa satisfactoria.

El empaquetado fue verificado mediante PEP 517, wheel, sdist, instalación
aislada, smoke test y prueba de artefactos. La variación de hashes del rebuild
es `NON_BLOCKING` y no afecta la integridad de los activos RC publicados.

C10 solo podrá cambiar a `PASS` después de autorizar y verificar el commit y la
etiqueta firmados del Subhito 3.2.12.
<!-- END ACCH-3.2.12-STAGE2 -->
