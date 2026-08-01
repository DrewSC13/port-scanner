# SUBTASK 5.2 — Session Store v2 y artefactos seguros

## Autoridad y alcance

- Base autorizada: `045dabda6eea840e3cbe065407e7132d88ba9963`.
- Contrato Store: `SSV2-CICADAPORT-5.2-001`.
- Contrato artefactos: `SAV2-CICADAPORT-5.2-002`.
- Contratos públicos de sesión, resultados, eventos y motores: versión `1`, sin
  cambios.
- `rust-core/` y `go-banner/`: fuera del changeset.

## Session Store v2

El backend `src/session_store_v2.py` usa SQLite WAL y mantiene un único estado
activo por directorio de sesión. Normaliza:

- estado y plan de sesión;
- endpoints ordenados;
- resultados por `(endpoint, protocol, port)`;
- banners confirmados;
- historial de estados y digest encadenado;
- manifiestos de migración v1.

La persistencia completa continúa disponible para crear, cambiar estado,
finalizar y exportar checkpoints. Durante la fase de escaneo, la API
`append_results()` confirma únicamente el lote nuevo y avanza la secuencia
lógica una unidad por resultado. `complete_banner()` actualiza un único resultado
y su evidencia en O(1).

### Perfiles de durabilidad

| Perfil | Máximo por transacción | Uso |
| --- | ---: | --- |
| `balanced` | 128 resultados o 250 ms | confirma por tamaño o tiempo, lo que ocurra primero |
| `strict` | 1 resultado | máxima durabilidad por observación |

Cancelación, fallo y transición terminal fuerzan el vaciado inmediato del lote
observado. Ambos perfiles usan transacciones `BEGIN IMMEDIATE`, claves foráneas, WAL,
`busy_timeout`, `trusted_schema=OFF`, digest SHA-256 por resultado y política de
permisos `0700/0600`.

## Migración v1 → v2

La migración:

1. valida `CURRENT.json`, checkpoint y manifiesto con sus hashes;
2. carga el contrato v1 mediante el store congelado correspondiente;
3. importa el checkpoint en una transacción v2;
4. registra rutas y hashes de la fuente;
5. conserva todos los archivos v1 sin modificación;
6. es idempotente y rechaza una fuente que cambie tras la importación.

La ruta caliente conserva en memoria el plan ya validado y su conjunto de
puertos, vinculado al `plan_fingerprint`, para evitar reconstruir 65.535 puertos
en cada commit. La comparación temporal usa instantes UTC parseados y no orden
lexicográfico de cadenas ISO-8601.

La base v2 y sus sidecars rechazan symlinks, archivos no regulares, propietarios
distintos y tamaños fuera del límite. `audit()` ejecuta `quick_check` o
`integrity_check`, `foreign_key_check` y verifica versión, application ID, WAL y
modos privados.

## Secure Artifact Writer

`src/secure_artifacts.py` centraliza:

- creación de directorios privados componente por componente;
- contención estricta dentro del root;
- rechazo de symlinks y escapes relativos;
- temporales exclusivos en el mismo filesystem;
- archivos `0600` y directorios `0700`, independientes del `umask`;
- `fsync` del archivo y directorio;
- no sobrescritura por defecto y reemplazo atómico explícito;
- recibos SHA-256, tamaño y modo;
- streams JSONL exclusivos para eventos públicos.

TXT, CSV y HTML neutralizan C0/C1, ESC, BEL, bidi e invisibles. JSON conserva el
contrato semántico y escapa los controles definidos por JSON.

## Compatibilidad y recuperación

Los runners v1 permanecen disponibles y sin cambios de contrato. Los runners
detectan la API incremental v2; con un store v1 conservan la ruta generacional
congelada. Una interrupción abrupta puede descartar únicamente la transacción no
confirmada; todo lote confirmado se recupera desde WAL y el runner reanuda solo
los puertos pendientes. La aceptación incluye terminación real por `SIGKILL`,
rollback de la transacción abierta y continuación hasta completar el plan.

## Exclusiones

- ningún cambio en Rust o Go;
- ninguna capacidad de red nueva;
- ningún cambio de versión pública;
- sin descubrimiento, raw, UDP, SYN, CVE ni escaneo externo en la aceptación;
- sin cierre automático de SUBTASK 5.2.
