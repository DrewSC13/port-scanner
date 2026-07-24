# CicadaPort

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey.svg)

Escáner de puertos multi-engine para auditorías de seguridad autorizadas,
desarrollado en Python con motores auxiliares en Rust y Go.

## Características Principales

- **Escaneo Multi-hilos**: Alta velocidad con gestión eficiente de hilos
- **Detección de Servicios**: Identificación por puerto sin cargas de aplicación
- **Múltiples Formatos**: Reportes en TXT, JSON, CSV y HTML
- **Salida Dual**: Hallazgos ordenados en pantalla y reporte persistente
- **CLI Profesional**: Interfaz de línea de comandos intuitiva y robusta
- **TUI de Consola**: Dashboard terminal en vivo mediante `--tui`, sin lógica de red duplicada
- **Perfiles Reproducibles**: `safe`, `standard`, `deep` y `custom`
- **Banner Grabbing Explícito**: Solo con `--banner-grab`, usando Python o Go
- **Cancelación Cooperativa**: Detención controlada de Python, Rust y Go
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
- versión del contrato para la futura comunicación JSON Lines con Rust.

El parser fundacional acepta especificaciones individuales, varias entradas,
CIDR, rangos IP completos y archivos con comentarios. Deduplica preservando el
orden, permite exclusiones y aplica un límite explícito de 4096 objetivos para
evitar expansiones masivas accidentales. La resolución usa `getaddrinfo()` y
puede conservar todas las direcciones IPv4 e IPv6 de un hostname.

Esta capa todavía no convierte la CLI en un orquestador multiobjetivo: la
ejecución concurrente de varios hosts, el descubrimiento y las técnicas raw se
incorporarán en subhitos posteriores. La CLI actual continúa ejecutando TCP
Connect sobre un único objetivo validado.

## Streaming JSONL del motor Rust

El puente Python ya no construye un argumento gigante con todos los puertos.
Envía por `stdin` una solicitud JSON v1 con la lista estructurada, incluso para
el perfil `deep` de 65.535 puertos. La invocación directa histórica con
`--ports` se conserva temporalmente, pero Python utiliza siempre
`--ports-stdin`.

Rust emite por `stdout` un registro `port_result` v1 por línea en el orden real
de finalización y fuerza un `flush` después de cada resultado. Los diagnósticos
se reservan para `stderr`. El puente valida versión, tipo de registro, estado,
evidencia, puertos inesperados, duplicados y streams incompletos antes de
incorporar cada observación al núcleo.

El progreso de la CLI y del TUI procede ahora de puertos realmente completados:
cada línea válida actualiza inmediatamente la cobertura y los hallazgos
abiertos. El orden de llegada no se altera durante el stream; los resultados
solo se ordenan al consolidar la sesión y generar los reportes.

Protocolo de entrada utilizado por Python:

```json
{"contract_version":1,"record_type":"scan_request","ports":[22,80,443]}
```

La salida contiene objetos JSON independientes, uno por línea:

```json
{"contract_version":1,"record_type":"port_result","target":"127.0.0.1","address":"127.0.0.1","address_family":"ipv4","host_state":"up","port":80,"protocol":"tcp","state":"open","reason":"connection_accepted","technique":"tcp_connect","service":"HTTP","banner":null,"response_time":0.001,"is_open":true,"evidence":{"reason":"connection_accepted","source":"rust","errno":0}}
```

## Instalación Rápida

```bash
# Clonar el repositorio
git clone https://github.com/DrewSC13/port-scanner.git
cd port-scanner

# Crear un entorno virtual e instalar la aplicación
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .

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

# Rango, motor y salida definidos manualmente
cicadaport 192.168.1.10 --profile custom -p 20-443 \
  --engine python --banner-grab --banner-engine go --tui
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

# TCP 1-1000 y motores nativos disponibles
cicadaport 192.168.1.10 --profile standard

# TCP 1-65535 y enumeración de servicios abiertos
cicadaport 192.168.1.10 --profile deep

# Comportamiento histórico o configuración totalmente manual
cicadaport 192.168.1.10 --profile custom -p 22-443 --engine python
```

`auto` prefiere Rust para el escaneo TCP y Go para banners cuando sus binarios
están compilados; en caso contrario usa los motores Python. El perfil `deep`
amplía la cobertura TCP, pero no sustituye por sí solo las técnicas de
descubrimiento, UDP, SYN, identificación de sistema operativo o scripting
especializado de otras herramientas.

## Uso seguro del banner grabbing

El escaneo TCP no envía cargas de aplicación por defecto. Para solicitar
banners de forma explícita:

```bash
# Motor de escaneo Python + banners Python
cicadaport localhost --engine python --banner-grab

# Motor de escaneo Rust + banners Python
cicadaport localhost --engine rust --banner-grab

# Cualquier motor de escaneo + banners Go
cicadaport localhost --engine rust --banner-grab --banner-engine go
```

Python y Go negocian TLS en los puertos cifrados conocidos, envían un único
`HEAD` solo a una lista cerrada de puertos HTTP/HTTPS y se limitan a lectura
pasiva en los demás servicios.

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
técnica; JSON identifica además la versión del contrato.
