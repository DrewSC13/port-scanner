# CicadaPort

![Python](https://img.shields.io/badge/Python-3.10--3.13-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Linux%20x86_64-lightgrey.svg)\n![Release](https://img.shields.io/badge/Release-3.0.0--rc.1-orange.svg)

Escáner de puertos con arquitectura especializada para auditorías de seguridad
autorizadas: Python orquesta la sesión, Rust ejecuta el escaneo TCP y Go captura
los banners solicitados.

## Release candidate y soporte verificable

CicadaPort `3.0.0-rc.1` (`3.0.0rc1` en metadatos Python) es una
prerelease, no una declaración de producción. RC1 está soportada únicamente en
Linux x86_64, Ubuntu 22.04/24.04 y Python 3.10-3.13. Windows, macOS, ARM64 y
Python 3.14 permanecen no soportados. Rust 1.97.1 y Go 1.26.5 son las
toolchains fijadas; los contratos JSONL permanecen en versión 1.

El wheel Linux contiene los motores obligatorios Rust y Go. La construcción y
prueba aislada de wheel/sdist se ejecuta con:

```bash
python -m pip install -r requirements-release.txt
./scripts/build_release_artifacts.sh
./scripts/test_release_artifacts.sh dist
```

## Estado de TASK 4

TASK 4 — sesiones reproducibles, reanudables y observables — está consolidada,
cerrada y congelada sobre la implementación funcional
`77ad51f0751b29b510f574e750c1a3fa65db4a60`. Este cierre no convierte por sí
solo a `3.0.0-rc.1` en una versión estable ni autoriza capacidades fuera del
alcance TCP-connect y banner grabbing documentado.

## Estado de TASK 5

TASK 5 — Enterprise Engine and Production Hardening — está formalmente abierta
sobre `main@bfaa7e6c2989dc923b418862ce9243e68e3f569c`. SUBTASK 5.1 define
la arquitectura, contratos candidatos, modelo de amenazas e instrumentación de
baseline. Todavía no modifica materialmente el Session Store, Rust, Go, CLI,
TUI ni los contratos públicos v1. Consulta [docs/task-5-status.md](docs/task-5-status.md).

## Características Principales

- **Escaneo Multi-hilos**: Alta velocidad con gestión eficiente de hilos
- **Detección de Servicios**: Identificación por puerto sin cargas de aplicación
- **Múltiples Formatos**: Reportes en TXT, JSON, CSV y HTML
- **Salida Dual**: Hallazgos ordenados en pantalla y reporte persistente
- **CLI Profesional**: Interfaz de línea de comandos intuitiva y robusta
- **TUI Multiobjetivo**: Dashboard terminal en vivo para sesiones simples o por lotes, sin lógica de red duplicada
- **Perfiles Reproducibles**: `safe`, `standard`, `deep` y `custom`
- **Orquestación Multiobjetivo**: Rangos, CIDR, archivos y exclusiones con concurrencia acotada
- **Banner Grabbing Explícito**: Solo con `--banner-grab`, mediante el motor Go
- **Cancelación Cooperativa**: Detención controlada de Rust y Go desde Python
- **Validación Avanzada**: Verificación completa de entradas y configuraciones
- **Estadísticas Detalladas**: Métricas completas del escaneo

## Estado técnico y hoja de ruta

El estado congelado, la deuda transitoria clasificada, los subhitos restantes
del Hito 3 y su puerta formal de cierre se mantienen en
[ROADMAP.md](ROADMAP.md). La presencia de un subhito futuro en esa hoja lo deja
`DEFINED`, pero no autoriza su implementación: cada apertura requiere un
contrato provisional y una aprobación expresa.

## Contratos avanzados de objetivos y evidencia

El núcleo define un contrato versionado independiente de la interfaz. Cada
resultado de puerto conserva `is_open` como proyección derivada de compatibilidad
del estado canónico. `state` es la fuente de verdad, `evidence.reason` sustenta
la razón y el campo superior `reason` debe coincidir con ella. Además registra:

- estado canónico `open`, `closed`, `filtered`, `unfiltered`,
  `open|filtered` o `closed|filtered`;
- razón técnica y evidencia que sustentan ese estado;
- objetivo solicitado, dirección resuelta y familia IPv4/IPv6;
- estado observado del host y técnica de escaneo utilizada;
- versión del contrato usada por la comunicación JSON Lines con Rust y Go.

El parser acepta especificaciones individuales, varias entradas,
CIDR, rangos IP completos y archivos con comentarios. Deduplica preservando el
orden, permite exclusiones y aplica un límite explícito de 4096 objetivos para
evitar expansiones masivas accidentales. La resolución usa `getaddrinfo()` y
puede conservar todas las direcciones IPv4 e IPv6 de un hostname.

La CLI conecta este contrato con el orquestador multiobjetivo. Cada dirección
resuelta ejecuta su propio flujo especializado, conserva identidad y evidencia,
genera un reporte independiente y puede fallar sin descartar los resultados
correctos de otros objetivos. El progreso se consolida para toda la sesión y la
cancelación cooperativa alcanza todos los motores activos.

`--target-workers` limita cuántos objetivos se procesan simultáneamente.
`--threads` es un presupuesto global: el orquestador lo reparte entre los
objetivos activos y nunca lo multiplica silenciosamente. El descubrimiento de
hosts, las técnicas raw y los escaneos no autorizados continúan fuera del
alcance.

## Contratos nativos v1 de Rust y Go

Python entrega a Rust por `stdin` una solicitud `scan_request` v1 completa:
objetivo resuelto, puertos normalizados, timeout en milisegundos y concurrencia
efectiva. Ningún dato contractual viaja fragmentado en argumentos del proceso.
`--request-stdin` es la única interfaz operativa admitida por los binarios Rust
y Go. `--help` es la única operación informativa adicional. Cualquier argumento
histórico, desconocido, posicional o mezclado termina con código `2` antes de
leer `stdin` o iniciar actividad de red.

Rust emite por `stdout` un registro `port_result` v1 por línea en el orden real
de finalización y fuerza un `flush` después de cada resultado. Los diagnósticos
se reservan para `stderr`. El puente valida versión, tipo de registro, estado,
evidencia, puertos inesperados, duplicados y streams incompletos antes de
incorporar cada observación al núcleo.

El progreso de la CLI y del TUI procede ahora de puertos realmente completados:
cada línea válida actualiza inmediatamente la cobertura y los hallazgos
abiertos. El orden de llegada no se altera durante el stream; los resultados
solo se ordenan al consolidar la sesión y generar los reportes.

Protocolo de entrada utilizado por Python para Rust:

```json
{"contract_version":1,"record_type":"scan_request","target":"127.0.0.1","ports":[22,80,443],"timeout_ms":2000,"workers":3}
```

La salida contiene objetos JSON independientes, uno por línea:

```json
{"contract_version":1,"record_type":"port_result","target":"127.0.0.1","address":"127.0.0.1","address_family":"ipv4","host_state":"up","port":80,"protocol":"tcp","state":"open","reason":"connection_accepted","technique":"tcp_connect","service":"HTTP","banner":null,"response_time":0.001,"is_open":true,"evidence":{"reason":"connection_accepted","source":"rust","errno":0}}
```

Go usa el mismo aislamiento: recibe un `banner_request` v1 completo mediante
`--request-stdin` y emite un `banner_result` v1 por cada puerto abierto
solicitado. Cada resultado declara explícitamente `captured`, `empty` o `error`;
los resultados vacíos y los fallos no desaparecen silenciosamente.

```json
{"contract_version":1,"record_type":"banner_request","target":"127.0.0.1","ports":[80,443],"timeout_ms":3000}
```

```json
{"contract_version":1,"record_type":"banner_result","target":"127.0.0.1","port":80,"status":"captured","service":"HTTP","banner":"HTTP/1.0 200 OK","error":null,"source":"go"}
```

### Migración de invocaciones nativas directas

Las rutas históricas se retiraron en el Subhito 3.2.9. Los binarios son
componentes internos; la interfaz pública continúa siendo `cicadaport`. La
etiqueta firmada `subhito-3.2.8` conserva el último estado que admitía estas
formas, que ya no están soportadas:

```bash
rust-core --host 127.0.0.1 --ports 80,443
rust-core --host 127.0.0.1 --ports-stdin --timeout 1 --workers 2
go-banner --host 127.0.0.1 --ports 80,443 --timeout 1
```

La migración consiste en enviar una solicitud v1 completa por `stdin`:

```bash
printf '%s\n' \
  '{"contract_version":1,"record_type":"scan_request","target":"127.0.0.1","ports":[80,443],"timeout_ms":1000,"workers":2}' | \
  rust-core --request-stdin

printf '%s\n' \
  '{"contract_version":1,"record_type":"banner_request","target":"127.0.0.1","ports":[80,443],"timeout_ms":1000}' | \
  go-banner --request-stdin
```

Esta consolidación no cambia las versiones, los campos ni la semántica de los
contratos JSONL v1.

Antes de incorporar registros al núcleo, Python rechaza versiones o tipos
incorrectos, campos ausentes o desconocidos, objetivos y puertos no
solicitados, duplicados, respuestas incompletas y combinaciones incoherentes de
estado, banner y error.

## Flujo especializado obligatorio

El flujo público activo es siempre `Python → Rust → Python → Go → Python`:

1. Python valida la solicitud, resuelve el objetivo y prepara el contrato.
2. Rust ejecuta obligatoriamente el escaneo TCP y transmite resultados JSONL.
3. Python valida y normaliza cada resultado.
4. Go recibe únicamente los puertos confirmados como abiertos cuando
   `--banner-grab` está habilitado.
5. Python integra los banners y genera la salida, las estadísticas y el reporte.

Antes de resolver el objetivo o iniciar el escaneo, el orquestador comprueba el
binario Rust y, si se solicitaron banners, también el binario Go. Si falta un
motor requerido, la sesión falla con un diagnóstico claro y recomienda ejecutar
`./scripts/build_all.sh`; nunca cambia silenciosamente a Python.

La CLI no expone selectores de motor: Rust es siempre el motor TCP público y
Go es el único motor de banners cuando `--banner-grab` está habilitado. Las
opciones históricas `--engine` y `--banner-engine` ya no se reconocen y terminan
con código `2` antes de resolver objetivos o iniciar actividad de red. Para
migrar automatizaciones existentes, elimina esos argumentos; el flujo efectivo
permanece invariable y nunca utiliza fallback Python.

Las implementaciones Python de escaneo y banners permanecen en el repositorio
como referencia interna y soporte de pruebas, pero no son seleccionables desde
la interfaz pública.

## Instalación Rápida

```bash
# Clonar el repositorio
git clone https://github.com/DrewSC13/port-scanner.git
cd port-scanner

# Crear un entorno virtual e instalar la aplicación
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .

# Compilar los motores obligatorios
./scripts/build_all.sh

# Mostrar la ayuda de la CLI instalada
cicadaport --help
```

## TUI y perfiles

La CLI es la fuente de configuración tanto para automatización como para la
interfaz en vivo. Los objetivos y todas las opciones se escriben primero en la
consola; después, `--tui` abre el monitor dentro de esa misma terminal e inicia
la solicitud inmutable automáticamente. El TUI consume `ScanOrchestrator.run()`
para una dirección y `ScanOrchestrator.run_many()` para sesiones multiobjetivo;
no reimplementa resolución, concurrencia, escaneo, banners ni reportes:

```bash
cicadaport 192.168.1.10 --profile standard --tui
```

El monitor usa un diseño terminal moderno inspirado en herramientas como
`btop`, con una estética de glasmorfismo adaptada a las capacidades reales de
la consola: fondo negro azulado, superficies azul petróleo, bordes de bajo
contraste y acentos cian, violeta y ámbar. Los paneles mantienen separación
visual y no emplean botones, formularios, desplegables ni una segunda línea de
comandos.

La telemetría distribuye la información por jerarquía: señal RTT y respuesta de
puertos, tarjetas de velocidad y estados, cobertura con ETA, plan de ejecución,
endpoints abiertos, eventos del motor y evidencia del último servicio. Todos
los valores proceden del núcleo de escaneo; la interfaz no genera progreso ni
resultados ficticios.

El TUI conserva el fondo predeterminado del emulador en lugar de rellenar la
pantalla con un color opaco. Esto permite usar transparencia y desenfoque reales
cuando el emulador y el compositor los ofrecen. En Konsole, el efecto se activa
en el perfil utilizado por CicadaPort: edita su esquema de colores, reduce
moderadamente la opacidad del fondo y habilita **Desenfocar fondo**. Si esas
opciones no están disponibles, el monitor mantiene un fondo terminal normal sin
afectar su legibilidad ni su funcionamiento.

```bash
# Perfil conservador y reporte de texto
cicadaport 192.168.1.10 --profile safe --tui

# TCP completo, enumeración de servicios y reporte JSON
cicadaport 192.168.1.10 --profile deep --format json --tui

# Rango de puertos definido manualmente y banners Go explícitos
cicadaport 192.168.1.10 --profile custom -p 20-443 \
  --banner-grab --tui

# Dos objetivos locales con progreso global y reportes independientes
cicadaport 127.0.0.1 --target 127.0.0.2 \
  -p 4444 --threads 4 --target-workers 2 --tui

# Rango de objetivos con exclusión monitorizado desde el dashboard
cicadaport 127.0.0.1-127.0.0.4 --exclude 127.0.0.3 \
  -p 20-25 --threads 6 --target-workers 2 --tui
```

Atajos disponibles dentro del monitor:

| Atajo | Acción |
|---|---|
| `F1` | Muestra el contexto operativo |
| `F5` | Repite la misma solicitud ya validada |
| `Ctrl+X` | Cancela los motores de forma cooperativa |
| `Ctrl+L` | Limpia únicamente el flujo de eventos |
| `Q` o `F10` | Sale del monitor |

Al terminar, la pantalla conserva los hallazgos ordenados, estadísticas,
evidencia disponible y las rutas de los reportes. En sesiones multiobjetivo,
cada endpoint muestra el objetivo solicitado y la dirección resuelta; el panel
de ejecución mantiene contadores de objetivos activos, completados y fallidos,
y el resumen final conserva los resultados correctos aunque otro objetivo falle.

Los perfiles fijan valores reproducibles, pero las opciones manuales siguen
teniendo prioridad:

```bash
# Puertos comunes, baja concurrencia y sin banners
cicadaport 192.168.1.10 --profile safe

# TCP 1-1000 con Rust y banners Go
cicadaport 192.168.1.10 --profile standard

# TCP 1-65535 y enumeración de servicios abiertos
cicadaport 192.168.1.10 --profile deep

# Configuración manual conservando el flujo especializado
cicadaport 192.168.1.10 --profile custom -p 22-443
```

Las opciones manuales de puertos, concurrencia, timeout, banners y salida siguen
teniendo prioridad sobre el perfil. El motor TCP permanece fijado en Rust y la
fase de banners, cuando está activa, permanece fijada en Go, sin selectores ni
fallback. El perfil `deep` amplía la cobertura TCP, pero no sustituye por sí
solo las técnicas de descubrimiento, UDP, SYN, identificación de sistema
operativo o scripting especializado de otras herramientas.

## Orquestación multiobjetivo

El objetivo posicional puede contener una IP, un hostname, un CIDR, un rango o
una lista separada por comas. `--target` añade especificaciones y puede
repetirse. `--target-file` incorpora archivos UTF-8 con comentarios iniciados
por `#`; `--exclude` elimina objetivos antes de resolverlos.

```bash
# Dos direcciones explícitas del laboratorio local
cicadaport 127.0.0.1 --target 127.0.0.2 \
  -p 20-25 --threads 8 --target-workers 2

# Rango local con una exclusión
cicadaport 127.0.0.1-127.0.0.4 \
  --exclude 127.0.0.3 \
  -p 20-25 --threads 12 --target-workers 3

# Archivo de objetivos autorizados
cicadaport --target-file objetivos.txt \
  --exclude 127.0.0.2 \
  --report-dir reports/laboratorio
```

Con varios objetivos, cada dirección resuelta recibe un nombre de reporte
único dentro de `--report-dir`. `--output` se reserva para sesiones con un solo
objetivo porque representa una ruta exacta. La salida de consola resume
objetivos solicitados, direcciones resueltas, éxitos, fallos, hallazgos y
presupuesto efectivo de concurrencia. Si al menos un objetivo falla, los
reportes correctos se conservan y la CLI termina con código `2`.

El TUI admite el mismo contrato multiobjetivo que la salida lineal. El
progreso global, los fallos parciales y la identidad de cada endpoint proceden
de los eventos emitidos por `ScanOrchestrator.run_many()`. `F5` repite el lote
inmutable completo y `Ctrl+X` propaga la cancelación cooperativa a todos los
motores activos. Los parámetros continúan bloqueados desde la CLI: el dashboard
monitoriza la sesión, pero no edita objetivos ni opciones durante la ejecución.

```bash
# Monitor multiobjetivo con presupuesto global de cuatro hilos
cicadaport 127.0.0.1 --target 127.0.0.2 \
  -p 4444 --threads 4 --target-workers 2 --tui
```

## Uso seguro del banner grabbing

El escaneo TCP no envía cargas de aplicación por defecto. Para solicitar
banners de forma explícita:

```bash
# Rust ejecuta TCP y Go captura los banners solicitados
cicadaport localhost --banner-grab

# Un perfil con banners puede desactivarlos explícitamente
cicadaport localhost --profile standard --no-banner-grab
```

Go negocia TLS en los puertos cifrados conocidos, envía un único `HEAD` solo a
una lista cerrada de puertos HTTP/HTTPS y se limita a lectura pasiva en los
demás servicios.

## Resultados y reportes

Cada escaneo muestra en la terminal todos los puertos abiertos, ordenados por
protocolo y número de puerto. Para cada hallazgo se incluyen el servicio, el
banner disponible y el tiempo de respuesta. El mismo escaneo guarda además un
reporte dentro de `reports/`.

```bash
# Muestra los hallazgos y crea automáticamente reports/scan_report_*.txt
cicadaport localhost -p 1-1000

# Muestra los mismos hallazgos y guarda el reporte persistente como JSON
cicadaport localhost -p 1-1000 --format json

# Un nombre simple se guarda dentro de reports/
cicadaport localhost -p 1-1000 --output auditoria --format html

# Cambiar la carpeta predeterminada
cicadaport localhost -p 1-1000 --report-dir resultados

# Una ruta explícita se respeta y sus carpetas se crean si no existen
cicadaport localhost -p 1-1000 --output resultados/cliente/reporte.csv --format csv
```

Las extensiones automáticas son `.txt`, `.json`, `.csv` y `.html`. Los nombres
automáticos nunca sobrescriben un reporte existente: cuando coinciden objetivo
y segundo de ejecución, se añade un sufijo como `_2` o `_3`. Si el escaneo no
detecta puertos abiertos, la terminal y el reporte TXT lo indican expresamente.
Los reportes añaden de forma compatible el estado, la razón, la dirección y la
técnica. TXT, JSON, CSV y HTML identifican también los motores efectivos
`rust` y `go` —o `no usado` cuando la fase de banners está desactivada—; JSON
incluye además la versión del contrato.
