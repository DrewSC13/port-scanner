# CicadaPort

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey.svg)

Escáner de puertos con arquitectura especializada para auditorías de seguridad
autorizadas: Python orquesta la sesión, Rust ejecuta el escaneo TCP y Go captura
los banners solicitados.

## Características Principales

- **Escaneo Multi-hilos**: Alta velocidad con gestión eficiente de hilos
- **Detección de Servicios**: Identificación por puerto sin cargas de aplicación
- **Múltiples Formatos**: Reportes en TXT, JSON, CSV y HTML
- **Salida Dual**: Hallazgos ordenados en pantalla y reporte persistente
- **CLI Profesional**: Interfaz de línea de comandos intuitiva y robusta
- **TUI de Consola**: Dashboard terminal en vivo mediante `--tui`, sin lógica de red duplicada
- **Perfiles Reproducibles**: `safe`, `standard`, `deep` y `custom`
- **Orquestación Multiobjetivo**: Rangos, CIDR, archivos y exclusiones con concurrencia acotada
- **Banner Grabbing Explícito**: Solo con `--banner-grab`, mediante el motor Go
- **Cancelación Cooperativa**: Detención controlada de Rust y Go desde Python
- **Validación Avanzada**: Verificación completa de entradas y configuraciones
- **Estadísticas Detalladas**: Métricas completas del escaneo

## Contratos avanzados de objetivos y evidencia

El núcleo define un contrato versionado independiente de la interfaz. Cada
resultado de puerto conserva temporalmente `is_open` para compatibilidad, pero
también registra:

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
La invocación directa histórica con `--host` y `--ports` se conserva
temporalmente para compatibilidad interna, pero el puente Python utiliza siempre
`--request-stdin`.

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

`--engine` y `--banner-engine` se conservan temporalmente para no eliminar aún
la interfaz pública. `auto` y `rust` activan Rust; `auto` y `go` activan Go.
Seleccionar explícitamente `python` produce un error controlado. Las
implementaciones Python de escaneo y banners permanecen en el repositorio como
referencia interna, pero ya no son seleccionables desde el flujo público.

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
interfaz en vivo. El objetivo y todas las opciones se escriben primero en la
consola; después, `--tui` abre el monitor dentro de esa misma terminal e inicia
el escaneo automáticamente:

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

# Rango y salida definidos manualmente con los motores obligatorios
cicadaport 192.168.1.10 --profile custom -p 20-443 \
  --engine rust --banner-grab --banner-engine go --tui
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
evidencia disponible y la ruta exacta del reporte.

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
cicadaport 192.168.1.10 --profile custom -p 22-443 --engine rust
```

Las opciones manuales de puertos, concurrencia, timeout, banners y salida siguen
teniendo prioridad sobre el perfil. Los selectores de motor permanecen solo
durante la transición: `auto` resuelve siempre a Rust para TCP y a Go para
banners, sin fallback. El perfil `deep` amplía la cobertura TCP, pero no
sustituye por sí solo las técnicas de descubrimiento, UDP, SYN, identificación
de sistema operativo o scripting especializado de otras herramientas.

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

El TUI permanece deliberadamente limitado a un objetivo durante este subhito;
las sesiones multiobjetivo usan la salida de consola. Esta restricción evita
mezclar estados visuales mientras el núcleo consolida varios motores Rust y Go.

## Uso seguro del banner grabbing

El escaneo TCP no envía cargas de aplicación por defecto. Para solicitar
banners de forma explícita:

```bash
# Rust obligatorio + Go obligatorio para banners
cicadaport localhost --engine rust --banner-grab --banner-engine go

# Los alias transitorios auto mantienen el mismo flujo
cicadaport localhost --engine auto --banner-grab --banner-engine auto
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
