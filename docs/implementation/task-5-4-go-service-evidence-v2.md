# SUBTASK 5.4 — Go Service Evidence Engine v2

```text
CONTRACT=GSEV2-CICADAPORT-5.4-001
VERSION=1.0-CANDIDATE
BASE=7bac7fff3c2f0e14db74505923e0e5f64edc7eb7
PUBLIC_CONTRACT_VERSION=1
SERVICE_EVIDENCE_CONTRACT_VERSION=2
NETWORK_TECHNIQUE=TCP_CONNECT_AND_SAFE_BANNER_EVIDENCE
VULNERABILITY_DETECTION=NOT_IMPLEMENTED
```

## Arquitectura de compatibilidad

`banner_request` y `banner_result` permanecen exactamente en versión 1 y stdout
continúa reservado a un registro público por puerto. La evidencia ampliada v2 no
se inyecta en esos objetos: se emite, cuando el orquestador proporciona el
descriptor heredado `CICADAPORT_SERVICE_EVIDENCE_FD`, por un canal JSONL
independiente. La ausencia del descriptor conserva el comportamiento público
anterior.

## Streaming y recursos

El motor deja de acumular y ordenar todos los resultados antes de stdout. Cada
worker entrega un resultado al concluir el endpoint; el consumidor lo codifica
de inmediato. La cola de puertos y la cola de resultados están acotadas al menor
valor entre la concurrencia efectiva y 32. El orden de finalización no forma
parte del contrato; el orden de presentación final corresponde al orquestador.

Un error del consumidor cancela el contexto compartido. Las conexiones activas
se cierran al cancelar, los productores dejan de admitir trabajo y los canales
se drenan hasta finalizar sin goroutines huérfanas.

## Timeouts por fase

La solicitud pública v1 conserva `timeout_ms`. El adaptador interno lo proyecta
sin reinterpretar el contrato a seis presupuestos explícitos:

- conexión;
- negociación TLS;
- escritura;
- primer byte;
- lectura ociosa;
- duración total del probe.

La duración total limita todas las fases. La evidencia registra la fase de
fallo y si ya se habían observado bytes parciales.

## Lectura y sanitización

La lectura es incremental en bloques de 512 bytes y conserva como máximo 4.096
bytes. Finaliza por terminador versionado, EOF, timeout ocioso o truncamiento.
Cada evidencia incluye longitud observada, longitud capturada, indicador de
truncamiento, codificación y SHA-256 del contenido capturado.

`banner_display` se construye desde UTF-8 válido y elimina NUL, C0/C1, ESC,
secuencias CSI/OSC, DEL, controles bidi e invisibles peligrosos. CR, LF y TAB se
normalizan a espacios. Los bytes crudos no se imprimen directamente.

## Evidencia TLS veraz

TLS se negocia en modo de observación para los puertos ya clasificados como TLS.
La salida separa negociación, presencia del certificado y verificación. Como no
se ejecuta una cadena de confianza durante la observación,
`certificate_verified` permanece `false` y
`verification_error=verification_not_performed_observation_mode`. También se
registran versión, suite, ALPN, sujeto, emisor, SAN, vigencia, SHA-256 del
certificado y longitud de la cadena observada.

## Registro de probes

La primera versión incluye únicamente:

- `passive-banner@1`, sin payload;
- `http-head@1`, probe seguro HEAD para los puertos HTTP ya admitidos.

Ambos declaran transporte, hash del payload, límite de lectura, terminadores,
nivel de invasividad, política predeterminada y parser. No existen probes
`active` o `restricted` habilitados por defecto.

## Límites preservados

- no se modifica `rust-core/`;
- no se modifica Session Store v2;
- no se modifica ningún contrato público v1;
- no se añaden detección de vulnerabilidades, explotación ni probes externos;
- las pruebas materiales usan exclusivamente loopback.
