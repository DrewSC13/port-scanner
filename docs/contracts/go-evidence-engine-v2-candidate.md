# GSEV2-CICADAPORT-5.4-001 — Go Service Evidence Engine v2

```text
VERSION=1.0-CANDIDATE
STATUS=NON_EXECUTABLE_PENDING_5.1_CLOSURE
PURPOSE=SERVICE_EVIDENCE_NOT_VULNERABILITY_ASSERTION
```

## 1. Objetivo

Producir evidencia de servicio incremental y segura. Un puerto conocido es solo
un `service_hint`; la identificación observada requiere respuesta y confianza.

## 2. Streaming

- un `banner_result` se emite al terminar cada puerto;
- no acumular ni ordenar todos los resultados antes de stdout;
- canal bounded y backpressure;
- orden final fuera del motor;
- cancelación y cierre de conexiones en curso.

## 3. Timeouts por fase

```text
connect_timeout_ms
tls_handshake_timeout_ms
write_timeout_ms
first_byte_timeout_ms
idle_read_timeout_ms
total_probe_timeout_ms
```

La evidencia registra la fase exacta del fallo y si existieron bytes parciales.

## 4. Lectura y payload

- lectura incremental hasta límite, terminador, EOF o idle timeout;
- `io.WriteFull` o equivalente para probes;
- `raw_length`, `captured_length`, `truncated`, `encoding` y SHA-256;
- bytes crudos nunca se imprimen directamente;
- `banner_display` elimina C0/C1, ESC/OSC/CSI, bidi e invisibles peligrosos.

## 5. TLS

Conectarse sin confianza puede ser necesario para observar un servicio, pero la
salida debe separar:

```text
tls_negotiated
certificate_present
certificate_verified
verification_error
protocol_version
cipher_suite
alpn
subject
issuer
san_dns
san_ip
not_before
not_after
certificate_sha256
chain_length
```

`InsecureSkipVerify` no puede equivaler a `verified=true`.

## 6. Registro de probes

Cada probe tendrá identificador y versión:

```text
identifier
transport
payload_hash
maximum_bytes
terminators
invasiveness
allowed_by_default
parser
```

Niveles: `passive`, `safe`, `active`, `restricted`. La primera versión
empresarial habilita únicamente `passive` y `safe` por defecto.

## 7. Resultado de servicio

```text
service_hint
service_observed
service_confidence
product
version
protocol_evidence
```

No se generará CPE, CVE ni hallazgo de vulnerabilidad sin evidencia y contrato
posteriores.
