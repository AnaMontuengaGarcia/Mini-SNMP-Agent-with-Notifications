import asyncio
import json
import os
import psutil
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import platform
import socket

from pysnmp.entity import engine, config
from pysnmp.entity.rfc3413 import cmdrsp, context
from pysnmp.carrier.asyncio.dgram import udp
from pysnmp.proto.api import v2c

from pysnmp.proto import rfc1902, rfc1905
from pysnmp.proto.rfc1902 import Integer32, OctetString, ObjectIdentifier

from pysnmp.hlapi.v3arch.asyncio import (
    send_notification,
    CommunityData, 
    UdpTransportTarget, 
    ContextData, 
    ObjectIdentity, 
    ObjectType
)

# Para debug
#from pysnmp import debug
#debug.set_logger(debug.Debug('app'))

# ===========================
# Constantes de MIB y Configuración
# ===========================

BASE_OID = BASE_OID = (1, 3, 6, 1, 4, 1, 28308) # OID base de la empresa (Private Enterprise Number)

# OIDs para atributos de los requerimientos del programa
OID_MANAGER = BASE_OID + (1, 1, 0)
OID_MANAGER_EMAIL = BASE_OID + (1, 2, 0)
OID_CPU_USAGE = BASE_OID + (1, 3, 0)
OID_CPU_THRESHOLD = BASE_OID + (1, 4, 0)


# OIDs estándar de MIB -II System 
SYS_DESCR = (1, 3, 6, 1, 2, 1, 1, 1, 0)
SYS_OBJECT_ID = (1, 3, 6, 1, 2, 1, 1, 2, 0)
SYS_UP_TIME = (1, 3, 6, 1, 2, 1, 1, 3, 0)
SYS_CONTACT = (1, 3, 6, 1, 2, 1, 1, 4, 0)
SYS_NAME = (1, 3, 6, 1, 2, 1, 1, 5, 0)
SYS_LOCATION = (1, 3, 6, 1, 2, 1, 1, 6, 0)
SYS_SERVICES = (1, 3, 6, 1, 2, 1, 1, 7, 0)

# Lista de OIDs servidos, en orden
ORDERED_OIDS = sorted([
    SYS_DESCR, SYS_OBJECT_ID, SYS_UP_TIME, SYS_CONTACT, SYS_NAME,
    SYS_LOCATION, SYS_SERVICES,
    OID_MANAGER, OID_MANAGER_EMAIL, OID_CPU_USAGE, OID_CPU_THRESHOLD
])

JSON_FILE = 'mib_state.json'    # Archivo para persistencia del estado
TRAP_HOST = '127.0.0.1'
TRAP_PORT = 162

# ===========================
# Configuración de Email (Gmail)
# ===========================
EMAIL_SENDER = "xxxxx@gmail.com"
EMAIL_PASSWORD = "xxxxxxxxxxxxxxxx"  # Contraseña de aplicación (16 dígitos)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

# ===========================
# Clase para manejo de los datos del agente (MIB)
# ===========================

class MibDataStore:
    def __init__(self):
        # Diccionario con valores iniciales
        self.data = {
            'manager': 'NetworkAdmin',
            'managerEmail': '[email protected]',
            'cpuUsage': 0,
            'cpuThreshold': 80,

            # Atributos estándar SNMP System
            'sysDescr': f'Mini SNMP Agent (Python/pysnmp) on {platform.system()}',
            'sysObjectID': BASE_OID, # Identifica nuestro agente con nuestro OID base
            'sysContact': 'NetworkAdmin', # Se sincronizará con 'manager'
            'sysName': socket.gethostname(),
            'sysLocation': 'Lab System (Settable)',
            'sysServices': 72 # Servicios: Aplicación (bit 2) + End-to-End (bit 6)
        }
        self.above_threshold = False    # Indica si el uso CPU ya superó el umbral
        self.start_time = time.time()   # Tiempo de inicio para sysUpTime
        self.load_from_json()   # Cargar estado JSON

    # Cargar valores almacenados desde el JSON
    def load_from_json(self):
        if os.path.exists(JSON_FILE):
            try:
                with open(JSON_FILE, 'r') as f:
                    loaded = json.load(f)
                    # Cargar valores
                    self.data['manager'] = loaded.get('manager', self.data['manager'])
                    self.data['managerEmail'] = loaded.get('managerEmail', self.data['managerEmail'])
                    self.data['cpuThreshold'] = loaded.get('cpuThreshold', self.data['cpuThreshold'])
                    self.data['sysContact'] = loaded.get('sysContact', self.data['manager'])
                    self.data['sysName'] = loaded.get('sysName', self.data['sysName'])
                    self.data['sysLocation'] = loaded.get('sysLocation', self.data['sysLocation'])

                 # Sincronizar manager y sysContact (por si acaso)
                self.data['sysContact'] = self.data['manager']

                print(f'Loaded state from {JSON_FILE}')
            except Exception as e:
                print(f'Error loading JSON: {e}')
        else:
            print(f'File {JSON_FILE} not found. Creating with default values.')
            self.save_to_json()

    # Guardar datos persistentes relevantes en el JSON
    def save_to_json(self):
        try:
            with open(JSON_FILE, 'w') as f:
                persistent_data = {
                    'manager': self.data['manager'],
                    'managerEmail': self.data['managerEmail'],
                    'cpuThreshold': self.data['cpuThreshold'],
                    'sysContact': self.data['sysContact'],
                    'sysName': self.data['sysName'],
                    'sysLocation': self.data['sysLocation']
                }
                json.dump(persistent_data, f, indent=2)
            print(f'Saved state to {JSON_FILE}')
        except Exception as e:
            print(f'Error saving JSON: {e}')

    # Relacionar un OID a la clave interna del diccionario
    def oid_to_key(self, oid):
        # Grupo System de MIB-II
        if oid == SYS_DESCR:
            return 'sysDescr'
        elif oid == SYS_OBJECT_ID:
            return 'sysObjectID'
        elif oid == SYS_UP_TIME:
            return 'sysUpTime'
        elif oid == SYS_CONTACT:
            return 'sysContact'
        elif oid == SYS_NAME:
            return 'sysName'
        elif oid == SYS_LOCATION:
            return 'sysLocation'
        elif oid == SYS_SERVICES:
            return 'sysServices'
        # OIDs personalizados de empresa
        elif oid == OID_MANAGER:
            return 'manager'
        elif oid == OID_MANAGER_EMAIL:
            return 'managerEmail'
        elif oid == OID_CPU_USAGE:
            return 'cpuUsage'
        elif oid == OID_CPU_THRESHOLD:
            return 'cpuThreshold'
        return None
    
    # Calcular upTime: tiempo (en centésimas de segundo) desde arranque del agente
    def get_sysuptime(self):
        return int((time.time() - self.start_time) * 100)

mib_store = MibDataStore()

# Traducción de valores Python a tipos SNMP
def python_to_snmp(key, value):
    if key in ['manager', 'managerEmail', 'sysDescr', 'sysContact', 'sysName', 'sysLocation']:
        return v2c.OctetString(str(value).encode('utf-8'))
    elif key in ['cpuUsage', 'cpuThreshold', 'sysServices']:
        return v2c.Integer(int(value))
    elif key == 'sysUpTime':
        return v2c.TimeTicks(int(value))
    elif key == 'sysObjectID':
        return v2c.ObjectIdentifier(value)
    return v2c.Null()

# Traducción de valores SNMP a tipos Python
def snmp_to_python(key, snmp_value):
    if key in ['manager', 'managerEmail', 'sysContact', 'sysName', 'sysLocation']:
        if isinstance(snmp_value, v2c.OctetString):
            return bytes(snmp_value).decode('utf-8')
        else:
            raise ValueError('Expected OctetString')
    elif key in ['cpuUsage', 'cpuThreshold', 'sysServices']:
        if isinstance(snmp_value, (v2c.Integer, rfc1902.Integer32)):
            return int(snmp_value)
        else:
            raise ValueError('Expected Integer')
    raise ValueError('Unknown key')

# ===========================
# Observer para capturar securityName
# ===========================

current_security_name = None

def request_observer(snmpEngine, execpoint, variables, cbCtx):
    """Observer que captura el securityName de cada petición"""
    global current_security_name
    if execpoint == 'rfc3412.receiveMessage:request':
        current_security_name = variables.get('securityName', b'')

# ===========================
# Command Responders de Comando SNMP (GET, GETNEXT, SET)
# ===========================

# GET: responde consultas de lectura
class JsonGetCommandResponder(cmdrsp.GetCommandResponder):
    def handle_management_operation(self, snmpEngine, stateReference, contextName, PDU):
        varBinds = v2c.apiPDU.get_varbinds(PDU)
        rspVarBinds = []
        errorStatus = 0
        errorIndex = 0

        for idx, (oid, val) in enumerate(varBinds, 1):
            oid_tuple = tuple(oid)
            key = mib_store.oid_to_key(oid_tuple)

            if key is None:
                rspVarBinds.append((oid, rfc1905.NoSuchObject()))
            else:
                # --- Manejo de OIDs dinámicos --- #
                if key == 'sysUpTime':
                    value = mib_store.get_sysuptime()
                # cpuUsage es actualizado por el sampler, así que se lee de .data
                else:
                    value = mib_store.data[key]
                # --- Fin manejo dinámico ---

                snmp_value = python_to_snmp(key, value)
                rspVarBinds.append((oid, snmp_value))

        if errorStatus:
            rspVarBinds = [(oid, v2c.Null()) for oid, val in varBinds]

        self.send_varbinds(snmpEngine, stateReference, errorStatus, errorIndex, rspVarBinds)

# GETNEXT: responde consulta para recorrer la MIB secuencialmente
class JsonGetNextCommandResponder(cmdrsp.NextCommandResponder):
    def handle_management_operation(self, snmpEngine, stateReference, contextName, PDU):
        varBinds = v2c.apiPDU.get_varbinds(PDU)
        rspVarBinds = []
        errorStatus = 0
        errorIndex = 0

        for idx, (oid, val) in enumerate(varBinds, 1):
            oid_tuple = tuple(oid)

            # Buscar el siguiente OID servido
            next_oid = None
            for candidate in ORDERED_OIDS:
                if candidate > oid_tuple:
                    next_oid = candidate
                    break

            if next_oid is None:
                rspVarBinds.append((oid, rfc1905.EndOfMibView()))
            else:
                key = mib_store.oid_to_key(next_oid)
                # --- Manejo de OIDs dinámicos --- 
                if key == 'sysUpTime':
                    value = mib_store.get_sysuptime()
                else:
                    value = mib_store.data[key]
                # --- Fin manejo dinámico ---
                snmp_value = python_to_snmp(key, value)
                rspVarBinds.append((next_oid, snmp_value))

        if errorStatus:
            rspVarBinds = [(oid, v2c.Null()) for oid, val in varBinds]

        self.send_varbinds(snmpEngine, stateReference, errorStatus, errorIndex, rspVarBinds)

# SET: responde peticiones de escritura (solo para comunidad privada), con validaciones
class JsonSetCommandResponder(cmdrsp.SetCommandResponder):
    def handle_management_operation(self, snmpEngine, stateReference, contextName, PDU):
        global current_security_name

        # Verificar permisos (solo 'private-user' puede escribir)
        if current_security_name != b'private-user':
            varBinds = v2c.apiPDU.get_varbinds(PDU)
            rspVarBinds = [(oid, v2c.Null()) for oid, val in varBinds]
            self.send_varbinds(snmpEngine, stateReference, 6, 1, rspVarBinds)
            return

        varBinds = v2c.apiPDU.get_varbinds(PDU)
        rspVarBinds = []
        errorStatus = 0
        errorIndex = 0

        for idx, (oid, val) in enumerate(varBinds, 1):
            oid_tuple = tuple(oid)
            key = mib_store.oid_to_key(oid_tuple)

            if key is None:
                errorStatus = 18
                errorIndex = idx
                break

            # Proteger contra escritura en OIDs de solo lectura
            if key in ['sysDescr', 'sysObjectID', 'sysUpTime', 'cpuUsage']:
                errorStatus = 17 # notWritable
                errorIndex = idx
                break

            try:
                # Validar tipo de dato acorde con el atributo
                if key in ['manager', 'managerEmail', 'sysContact', 'sysName', 'sysLocation']:
                    if not isinstance(val, v2c.OctetString):
                        errorStatus = 7; errorIndex = idx; break
                elif key in ['cpuThreshold', 'sysServices']:
                    if not isinstance(val, (v2c.Integer, rfc1902.Integer32)):
                        errorStatus = 7; errorIndex = idx; break

                python_value = snmp_to_python(key, val)
                # Validar rango o longitud
                if key in ['manager', 'managerEmail', 'sysContact', 'sysName', 'sysLocation']:
                    if len(python_value) > 255:
                        errorStatus = 10; errorIndex = idx; break
                elif key == 'cpuThreshold':
                    if not (0 <= python_value <= 100):
                        errorStatus = 10; errorIndex = idx; break
                elif key == 'sysServices':
                    if not (0 <= python_value <= 127):
                        errorStatus = 10; errorIndex = idx; break
                # Guardar valor
                mib_store.data[key] = python_value

                # Sincronizar manager y sysContact
                if key == 'manager':
                    mib_store.data['sysContact'] = python_value
                elif key == 'sysContact':
                    mib_store.data['manager'] = python_value

                rspVarBinds.append((oid, val))

            except Exception as e:
                errorStatus = 10
                errorIndex = idx
                break

        if errorStatus:
            rspVarBinds = [(oid, v2c.Null()) for oid, val in varBinds]
        else:
            mib_store.save_to_json()     # Guardar persistente 

        self.send_varbinds(snmpEngine, stateReference, errorStatus, errorIndex, rspVarBinds)

# ===========================
# Envío de TRAP SNMP y Email de Alarma
# ===========================

# Enviar TRAP SNMP (cuando CPU supera umbral)
async def send_trap(cpu_usage, cpu_threshold):
    """Envía trap SNMP - versión con tuplas de OID"""
    print(f'Sending TRAP: CPU {cpu_usage}% > threshold {cpu_threshold}%')

    # Engine temporal: evita conflictos ACL/VACM del agente principal y simplifica el envío usando hlapi (high-level api)
    trapEngine = engine.SnmpEngine()
    
    try:
        # Obtenemos el sysuptime del engine principal, puesto que el del engine temporal será 0 y no tiene sentido enviarlo.
        agent_uptime = mib_store.get_sysuptime()

        # OID para tipo de trampa (standard)
        SNMP_TRAP_OID = (1, 3, 6, 1, 6, 3, 1, 1, 4, 1, 0)
        TRAP_TYPE_OID = BASE_OID + (2, 1)  # Identificador de evento cpuThresholdExceeded
        
        errorIndication, errorStatus, errorIndex, varBinds = await send_notification(
            trapEngine,
            CommunityData('private', mpModel=1),
            await UdpTransportTarget.create((TRAP_HOST, TRAP_PORT)),
            ContextData(),
            'trap',
            # Tuplas directamente
            # Importante incluir sysUpTime explícitamente como primer varbind
            ObjectType(ObjectIdentity(SYS_UP_TIME), v2c.TimeTicks(agent_uptime)),
            ObjectType(ObjectIdentity(SNMP_TRAP_OID), ObjectIdentifier(TRAP_TYPE_OID)),
            ObjectType(ObjectIdentity(OID_CPU_USAGE), Integer32(cpu_usage)),
            ObjectType(ObjectIdentity(OID_CPU_THRESHOLD), Integer32(cpu_threshold)),
            ObjectType(ObjectIdentity(OID_MANAGER_EMAIL), OctetString(mib_store.data['managerEmail']))
        )
        
        if errorIndication:
            print(f'❌ Trap error: {errorIndication}')
        elif errorStatus:
            print(f'❌ SNMP error: {errorStatus.prettyPrint()}')
        else:
            print('✅ Trap sent successfully!')
            
    except Exception as e:
        print(f'❌ Exception: {e}')
        import traceback
        traceback.print_exc()
    finally:
        trapEngine.close_dispatcher()

# Enviar email de alarma si CPU supera el umbral
def send_email(cpu_usage, cpu_threshold):
    """Envía email de alarma con Gmail (SMTP_SSL)"""
    try:
        recipient = mib_store.data['managerEmail']
        manager = mib_store.data['manager']

        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = recipient
        msg['Subject'] = f"⚠️ ALERTA: Uso de CPU {cpu_usage}% > Umbral {cpu_threshold}%"

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        body = f"""
ALERTA DE SEGURIDAD - UMBRAL DE CPU SUPERADO
=============================================

Hola {manager},

El uso de CPU ha superado el umbral configurado:

DETALLES:
---------
Timestamp:            {timestamp}
Uso de CPU actual:    {cpu_usage}%
Umbral configurado:   {cpu_threshold}%

Este es un mensaje automático del Agente SNMP.
        """

        msg.attach(MIMEText(body, 'plain'))

        # SMTP_SSL y login
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, [recipient], msg.as_string())

        print(f'Email de alarma de CPU enviado a {recipient}')

    except Exception as e:
        print(f'Error enviando email: {e}')

# ===========================
# CPU Monitoring (async)
# ===========================

async def cpu_sampler(snmpEngine):
    print('CPU sampler started')
    while True:
        try:
            cpu_usage = int(psutil.cpu_percent(interval=1))
            mib_store.data['cpuUsage'] = cpu_usage
            threshold = mib_store.data['cpuThreshold']

            if cpu_usage > threshold and not mib_store.above_threshold:
                mib_store.above_threshold = True
                print(f'\nTHRESHOLD CROSSED: CPU {cpu_usage}% > {threshold}%')
                
                # Enviar alarma (TRAP & Email)
                await send_trap(cpu_usage, threshold)
                send_email(cpu_usage, threshold)
                
            elif cpu_usage <= threshold and mib_store.above_threshold:
                mib_store.above_threshold = False
                print(f'\nCPU back below threshold: {cpu_usage}% <= {threshold}%')

            print(f'CPU: {cpu_usage}% (threshold: {threshold}%)', end='\r')

        except asyncio.CancelledError:
            print('\nCPU sampler stopping...')
            break

        except Exception as e:
            print(f'\nError in cpu_sampler: {e}')
            import traceback
            traceback.print_exc()
            
        await asyncio.sleep(5)
    print('CPU sampler stopped')

# ===========================
# Main Agent
# ===========================

async def main():
    """Función principal del agente SNMP"""
    print('=== Mini SNMP Agent Starting ===')
    print(f'Base OID: {".".join(map(str, BASE_OID))}')

    snmpEngine = engine.SnmpEngine()

    # Registrar observer para capturar securityName de cada petición
    snmpEngine.observer.register_observer(
        request_observer,
        'rfc3412.receiveMessage:request'
    )

    # Configurar el transporte UDP del agente (puerto estándar SNMP: 161)
    config.add_transport(
        snmpEngine,
        udp.DOMAIN_NAME,
        udp.UdpTransport().open_server_mode(('0.0.0.0', 161))
    )

    snmpContext = context.SnmpContext(snmpEngine)

    # Registrar comunidades SNMPv1/2c (public = sólo lectura, private = lectura-escritura)
    config.add_v1_system(snmpEngine, 'public-user', 'public')
    config.add_v1_system(snmpEngine, 'private-user', 'private')

    # Control de Acceso Basado en Vistas (VACM)
    # Añadir vistas que cubren System y nuestra rama de Empresa
    config.add_vacm_view(snmpEngine, 'read-view', 'included', (1, 3, 6, 1, 2, 1, 1), '')
    config.add_vacm_view(snmpEngine, 'write-view', 'included', (1, 3, 6, 1, 2, 1, 1), '')

    # Añadir vista para nuestra MIB personalizada (lectura y escritura)
    config.add_vacm_view(snmpEngine, 'read-view', 'included', BASE_OID, '')
    config.add_vacm_view(snmpEngine, 'write-view', 'included', BASE_OID, '')

    # Añadir vista que incluya los OIDs que pueden ir en una notificación
    config.add_vacm_view(snmpEngine, 'notify-view', 'included', (1, 3, 6, 1, 2, 1, 1), '')
    config.add_vacm_view(snmpEngine, 'notify-view', 'included', BASE_OID, '')

    # Vista "todo" que incluye internet (1.3.6.1)
    # config.add_vacm_view(snmpEngine, 'read-view', 'included', (1, 3, 6, 1), '')
    # config.add_vacm_view(snmpEngine, 'write-view', 'included', (1, 3, 6, 1), '')
    # config.add_vacm_view(snmpEngine, 'notify-view', 'included', (1, 3, 6, 1), '')

    # Configurar grupos y accesos
    config.add_vacm_group(snmpEngine, 'public-group', 2, 'public-user')
    config.add_vacm_group(snmpEngine, 'private-group', 2, 'private-user')

    # El grupo 'public' solo tiene acceso a 'read-view' y 'notify-view'
    config.add_vacm_access(snmpEngine, 'public-group', '', 2, 'noAuthNoPriv', 'exact', 'read-view', '', 'notify-view')
    # El grupo 'private' tiene acceso a 'read-view', 'write-view' y 'notify-view'
    config.add_vacm_access(snmpEngine, 'private-group', '', 2, 'noAuthNoPriv', 'exact', 'read-view', 'write-view', 'notify-view')

    # Inicializr Command Responders con operaciones SNMP
    JsonGetCommandResponder(snmpEngine, snmpContext)
    JsonGetNextCommandResponder(snmpEngine, snmpContext)
    JsonSetCommandResponder(snmpEngine, snmpContext)
    cmdrsp.BulkCommandResponder(snmpEngine, snmpContext)

    print('Agent listening on UDP port 161')
    print('Serving OIDs from MIB-II System (1.3.6.1.2.1.1) and Enterprise (1.3.6.1.4.1.28308)')
    print('Communities: public (RO), private (RW)')
    print(f'TRAP target: {TRAP_HOST}:{TRAP_PORT}')
    print(f'SMTP server: {SMTP_SERVER}:{SMTP_PORT} (Gmail)')

    # Iniciar el muestreador de CPU y guardar la referencia
    sampler_task = asyncio.create_task(cpu_sampler(snmpEngine))

    # Iniciar el dispatcher
    snmpEngine.transport_dispatcher.job_started(1)

    print('\n=== Agent running - Press Ctrl+C to quit ===\n')

    try:
        # Mantener el programa corriendo indefinidamente
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print('\nShutting down...')
    finally:
        print('Stopping CPU sampler...')
        sampler_task.cancel()
        try:
            await sampler_task
        except asyncio.CancelledError:
            print('CPU sampler cancelled')

        # Guardar estado final
        mib_store.save_to_json()

        # Cerrar dispatcher
        snmpEngine.transport_dispatcher.close_dispatcher()
        print('Agent stopped')

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n👋 Goodbye!')
