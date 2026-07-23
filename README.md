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
