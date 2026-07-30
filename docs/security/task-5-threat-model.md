# TM-CICADAPORT-5.1-001 — Modelo de amenazas empresarial

```text
VERSION=1.0-CANDIDATE
METHOD=ASSET_TRUST_BOUNDARY_ABUSE_CASE
STATUS=REVIEW_REQUIRED_BEFORE_5.2
```

## 1. Activos protegidos

- autorización y alcance del escaneo;
- identidad del operador y de la organización;
- plan inmutable y exclusiones;
- resultados, banners y metadatos sensibles;
- continuidad y reanudabilidad de la sesión;
- integridad de motores, paquetes y artefactos;
- disponibilidad del host ejecutor y de la red evaluada;
- evidencia de auditoría y cadena de custodia.

## 2. Adversarios y fallos considerados

- operador autorizado que comete un error de alcance;
- usuario local sin privilegios que intenta leer o sustituir evidencia;
- servicio remoto hostil que responde con payloads malformados;
- dependencia, Action o binario sustituido;
- proceso interrumpido, disco lleno o filesystem degradado;
- corrupción accidental o edición manual de una sesión;
- consumidor que interpreta un reporte como HTML, CSV o terminal;
- configuración que excede recursos del host y provoca auto-DoS.

No se asume que CicadaPort deba resistir a un administrador root comprometido en
el mismo host. Ese riesgo se trata mediante aislamiento operativo y verificación
externa de artefactos.

## 3. Amenazas prioritarias

| ID | Amenaza | Impacto | Control candidato |
| --- | --- | --- | --- |
| TM-01 | Expansión de objetivo fuera de alcance | Escaneo no autorizado | manifiesto firmado, exclusiones y fail-closed |
| TM-02 | Tasa/concurrencia excesiva | Auto-DoS o impacto remoto | token bucket y límites globales/por objetivo |
| TM-03 | Reemplazo del binario Rust/Go | resultados falsos o ejecución arbitraria | hash, firma, propietario y build identity |
| TM-04 | JSONL malicioso o ilimitado | memoria, parser o contrato | límites de bytes, profundidad y campos estrictos |
| TM-05 | Banner con ESC/OSC/bidi | manipulación de terminal o reporte | raw bytes separados de display neutralizado |
| TM-06 | CSV formula injection | ejecución al abrir evidencia | neutralización y formatos seguros |
| TM-07 | Symlink/TOCTOU en artefactos | sobrescritura o exfiltración | `O_NOFOLLOW`, `O_EXCL`, temp privado y rename |
| TM-08 | Reportes world-readable | fuga de topología y servicios | `0700/0600` independientes del umask |
| TM-09 | Interrupción durante commit | pérdida o doble ejecución | transacciones, WAL y secuencias monotónicas |
| TM-10 | Crecimiento no acotado | agotamiento de disco/inodos | lotes, retención, compactación y cuotas |
| TM-11 | Telemetría bloqueante | caída del escaneo por observabilidad | cola acotada y modo best-effort |
| TM-12 | TLS no verificado interpretado como válido | evidencia engañosa | separar negotiated/verified/error y cadena |
| TM-13 | Identificación por puerto asumida como servicio | falso positivo | hint separado de evidencia observada/confianza |
| TM-14 | Acción CI mutable o dependencia comprometida | release adulterada | SHA pinning, SBOM, SLSA y firma |
| TM-15 | Migración v1 incompleta | pérdida de trazabilidad | dry-run, hash source, transacción e idempotencia |

## 4. Requisitos de prueba derivados

- namespaces de red para open/closed/drop/reject/unreachable;
- fuzzing de JSON, eventos, banners y archivos corruptos;
- pruebas de `SIGTERM`, `SIGKILL`, disco lleno y permisos;
- colisiones, symlinks y cambios entre check/open;
- límites de descriptores, memoria, cola y tasa;
- reanudación tras cada frontera transaccional;
- verificación de firma, hash y provenance;
- salida de terminal con C0, C1, ESC, OSC, bidi e invisibles;
- migración repetida v1→v2 sin duplicación.

## 5. Riesgo residual aceptable para primera versión empresarial

La primera versión puede limitarse a Linux x86_64, ejecución local y
TCP-connect siempre que:

- el alcance comercial sea explícito;
- los límites y permisos sean seguros por defecto;
- la evidencia sea íntegra y reproducible;
- no se presenten hints de puerto como identificación confirmada;
- el producto no se declare scanner integral de vulnerabilidades.
