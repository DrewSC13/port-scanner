# Suplemento de recursos de baseline — SUBTASK 5.1

```text
CONTRACT=CEPH-CICADAPORT-5.1-RB-001
VERSION=1.0-CANDIDATE
STATUS=EXECUTION_1_FAILED_INSTRUMENTATION_DEFECT_RETRY_PENDING
NETWORK_SCOPE=LOOPBACK_ONLY
EXTERNAL_NETWORK=DISABLED
```

## Justificación

La baseline primaria mide tiempos, CPU de procesos hijo, throughput, archivos,
bytes y seguridad de reportes. Para cerrar 5.1 con los presupuestos prometidos
faltan RSS máximo, descriptores, hilos, terminación de Rust y tiempo al primer
resultado de Go.

## Casos

- Rust v1: 10.000 puertos cerrados loopback, 256 workers, monitor `/proc`.
- Rust v1: terminación de un proceso activo sobre `localhost`, sin red externa.
- Go v1: 32 servidores banner loopback, RSS/FD/hilos.
- Go v1: siete respuestas inmediatas y una demorada para medir si stdout
  transmite antes de que termine el peer más lento.
- Store v1: proceso aislado que ejecuta el perfil full sin motores nativos.

## Presupuestos candidatos

Los presupuestos quedan en el JSON generado y no se consideran definitivos
hasta el cierre formal de 5.1. Incluyen límites de archivos, bytes, RSS, FDs,
throughput, cancelación y primera evidencia.

## Limitaciones

El muestreo de `/proc` es de 1 ms y puede omitir picos más breves. No se modelan
firewall drop, pérdida WAN ni TLS real; esos escenarios corresponden a las
pruebas deterministas de 5.3 y 5.4.


## Incidencia de instrumentación RB-001

La primera ejecución oficial alcanzó el motor Go con `return_code=0`, pero el
lector del benchmark mezcló `BufferedReader.readline()` con
`Popen.communicate()`. El read-ahead del buffer consumió registros adicionales
y la validación observó incorrectamente un solo registro. No hubo fallo del
motor Go ni cambio funcional. La corrección usa `os.read` sobre el descriptor,
conserva todos los bytes recibidos en el primer chunk y añade una prueba de
regresión antes de repetir la medición oficial.
