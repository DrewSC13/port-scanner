# Contrato candidato de observabilidad nativa v1

```text
CONTRACT_ID=CON-CICADAPORT-4.3-001
CONTRACT_VERSION=1.0-CANDIDATA
TASK=4
SUBTASK=4.3
PRIMARY_DELIVERABLE=WORKING_SOFTWARE
RUST_IMPLEMENTATION=REQUIRED
GO_IMPLEMENTATION=REQUIRED
PUBLIC_EVENTS_JSONL=NOT_AVAILABLE
```

Rust y Go conservan stdout para `port_result` y `banner_result` v1. Cuando Python recibe `event_callback`, crea un pipe heredado mediante `CICADAPORT_NATIVE_EVENT_FD`. El canal separado emite `native_event` v1 con campos estrictos: versión, motor, fase, evento, objetivo, secuencia monotónica, tiempo transcurrido, puerto, estado, progreso, total y workers.

Cada ejecución emite `engine_started`, un `port_completed` por puerto y `engine_completed`. Python rechaza campos extra, secuencias rotas, puertos duplicados, cobertura incompleta y correlación incorrecta. La función no habilita CLI, TUI, multiobjetivo, raw ni descubrimiento de hosts.
