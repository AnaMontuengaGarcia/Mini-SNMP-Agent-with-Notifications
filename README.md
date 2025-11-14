# Mini-SNMP-Agent-with-Notifications

Un agente SNMPv2c ligero implementado en Python que monitoriza el uso de CPU y envía alertas mediante traps SNMP y correo electrónico cuando se superan los umbrales configurados.

## Características

- **Protocolo SNMPv2c**: Soporte completo para operaciones GET, GETNEXT, SET
- **Grupo System de MIB-II**: Objetos SNMP estándar del sistema (sysDescr, sysName, sysLocation, etc.)
- **MIB Empresarial Personalizada**: Monitorización de CPU con umbrales configurables
- **Monitorización de CPU en Tiempo Real**: Muestreo continuo con alertas configurables
- **Doble Sistema de Alertas**: Traps SNMP + notificaciones por email (Gmail)
- **Estado Persistente**: Configuración guardada en archivo JSON
- **Control de Acceso**: Comunidades de solo lectura (public) y lectura-escritura (private)
- **Arquitectura Asíncrona**: Construido sobre asyncio de Python para uso eficiente de recursos

## Arquitectura

**OID Empresarial**: `1.3.6.1.4.1.28308` (Zaragoza Network Management Research Group)

### Objetos Personalizados

| Objeto | OID | Tipo | Acceso | Descripción |
|--------|-----|------|--------|-------------|
| manager | .1.1.0 | String | RW | Nombre del administrador de red |
| managerEmail | .1.2.0 | String | RW | Email para alertas |
| cpuUsage | .1.3.0 | Integer | RO | Uso actual de CPU (%) |
| cpuThreshold | .1.4.0 | Integer | RW | Umbral de alerta (0-100%) |

### Notificaciones

- **cpuThresholdExceeded** (`.2.1`): Se dispara cuando el uso de CPU supera el umbral

## Requisitos

```bash
pip install pysnmp psutil
```

## Configuración

Edita las siguientes constantes en el script del agente:

```python
# Configuración de Email (Gmail)
EMAIL_SENDER = "tu-email@gmail.com"
EMAIL_PASSWORD = "tu-contraseña-de-aplicación"  # Contraseña de 16 dígitos

# Destino de Traps SNMP
TRAP_HOST = '127.0.0.1'
TRAP_PORT = 162

# Valores por Defecto
BASE_OID = (1, 3, 6, 1, 4, 1, 28308)
```

**Configuración de Gmail**: Activa la verificación en 2 pasos y genera una [Contraseña de Aplicación](https://myaccount.google.com/apppasswords)

## Uso

### Iniciar el Agente

```bash
# Ejecutar como root (el puerto 161 requiere privilegios)
sudo python agent.py
```

### Consultar el Agente

```bash
# Leer uso de CPU (comunidad public)
snmpget -v2c -c public localhost 1.3.6.1.4.1.28308.1.3.0

# Leer nombre del administrador
snmpget -v2c -c public localhost 1.3.6.1.4.1.28308.1.1.0

# Recorrer la MIB empresarial
snmpwalk -v2c -c public localhost 1.3.6.1.4.1.28308
```

### Modificar la Configuración

```bash
# Establecer umbral de CPU al 80% (requiere comunidad private)
snmpset -v2c -c private localhost 1.3.6.1.4.1.28308.1.4.0 i 80

# Actualizar email del administrador
snmpset -v2c -c private localhost 1.3.6.1.4.1.28308.1.2.0 s "admin@ejemplo.com"

# Cambiar ubicación del sistema
snmpset -v2c -c private localhost 1.3.6.1.2.1.1.6.0 s "Centro de Datos A"
```

### Recibir Traps

```bash
# Terminal 1: Iniciar receptor de traps
sudo snmptrapd -f -Lo

# Terminal 2: Disparar alerta reduciendo el umbral
snmpset -v2c -c private localhost 1.3.6.1.4.1.28308.1.4.0 i 5
```

## Control de Acceso

| Comunidad | Acceso | Operaciones |
|-----------|--------|------------|
| `public` | Solo lectura | GET, GETNEXT |
| `private` | Lectura-escritura | GET, GETNEXT, SET |

## Comportamiento de las Alertas

1. **CPU supera el umbral** → Se envía trap SNMP + notificación por email
2. **Alerta activa** → No se envían alertas duplicadas mientras la CPU permanece alta
3. **CPU cae por debajo del umbral** → La alerta se reinicia, lista para el siguiente evento

## Estructura de Archivos

```
.
├── agent.py           # Script principal del agente
├── mib_state.json    # Configuración persistente (auto-generado)
└── MYAGENT-MIB.txt   # Archivo de definición MIB
```

## Limitaciones y Consideraciones para Producción

⚠️ **Este es un agente de demostración. Para uso en producción:**

### Seguridad
- Actualizar a **SNMPv3** con autenticación y cifrado
- Almacenar las credenciales de forma segura (variables de entorno, gestor de secretos)
- Implementar limitación de tasa para operaciones SET
- Validar y sanitizar todas las direcciones de email

### Monitorización
- Añadir logging estructurado (formato JSON)
- Implementar endpoints de health check
- Monitorizar el uso de recursos del agente
- Configurar alertas para fallos del agente

### Fiabilidad
- Añadir recuperación de errores y lógica de reintento
- Implementar cierre graceful con limpieza
- Desplegar como **servicio systemd** con auto-reinicio
- Realizar copias de seguridad de `mib_state.json` regularmente

### Rendimiento
- Optimizar el intervalo de muestreo de CPU para tu carga de trabajo
- Añadir limitación de tasa de peticiones para prevenir DoS
- Monitorizar el uso de memoria en despliegues de larga duración
- Considerar un backend de base de datos para despliegues a gran escala


## Licencia

Licencia MIT - ver archivo LICENSE para detalles

## Contribuciones

¡Las contribuciones son bienvenidas! Por favor, abre un issue o envía un pull request.

***

**Nota**: Este agente implementa SNMPv2c con fines educativos y de desarrollo. Utiliza siempre SNMPv3 con autenticación y cifrado adecuados en entornos de producción.
