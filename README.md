# 🔍 CicadaPort

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey.svg)

Escáner de puertos multi-engine para auditorías de seguridad autorizadas,
desarrollado en Python con motores auxiliares en Rust y Go.

## 🚀 Características Principales

- **Escaneo Multi-hilos**: Alta velocidad con gestión eficiente de hilos
- **Detección de Servicios**: Identificación por puerto sin cargas de aplicación
- **Múltiples Formatos**: Reportes en TXT, JSON, CSV y HTML
- **CLI Profesional**: Interfaz de línea de comandos intuitiva y robusta
- **Banner Grabbing Explícito**: Solo con `--banner-grab`, usando Python o Go
- **Validación Avanzada**: Verificación completa de entradas y configuraciones
- **Estadísticas Detalladas**: Métricas completas del escaneo

## 📦 Instalación Rápida

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
