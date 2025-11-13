import asyncio
import json
import os
import psutil
import smtplib
import time
from email.mime.text import MIMEText
from datetime import datetime

from pysnmp.entity import engine, config
from pysnmp.entity.rfc3413 import cmdrsp, context, ntforg
from pysnmp.carrier.asyncio.dgram import udp
from pysnmp.proto.api import v2c
from pysnmp.proto import rfc1902, rfc1905


# ===========================
# Configuration Constants
# ===========================

BASE_OID = (1, 3, 6, 1, 3, 28308)

# Object OIDs
OID_MANAGER = BASE_OID + (1, 1, 0)
OID_MANAGER_EMAIL = BASE_OID + (1, 2, 0)
OID_CPU_USAGE = BASE_OID + (1, 3, 0)
OID_CPU_THRESHOLD = BASE_OID + (1, 4, 0)

JSON_FILE = 'mib_state.json'

# TRAP destination
TRAP_HOST = '127.0.0.1'
TRAP_PORT = 162

# SMTP configuration
SMTP_HOST = 'localhost'
SMTP_PORT = 1025

ORDERED_OIDS = [OID_MANAGER, OID_MANAGER_EMAIL, OID_CPU_USAGE, OID_CPU_THRESHOLD]

# ===========================
# Data Store
# ===========================

class MibDataStore:
    def __init__(self):
        self.data = {
            'manager': 'NetworkAdmin',
            'managerEmail': '[email protected]',
            'cpuUsage': 0,
            'cpuThreshold': 80
        }
        self.above_threshold = False  # For edge-triggered detection
        self.start_time = time.time()
        self.load_from_json()
    
    def load_from_json(self):
        '''Load persistent data from JSON file'''
        if os.path.exists(JSON_FILE):
            try:
                with open(JSON_FILE, 'r') as f:
                    loaded = json.load(f)
                    self.data['manager'] = loaded.get('manager', self.data['manager'])
                    self.data['managerEmail'] = loaded.get('managerEmail', self.data['managerEmail'])
                    self.data['cpuThreshold'] = loaded.get('cpuThreshold', self.data['cpuThreshold'])
                print(f'Loaded state from {JSON_FILE}')
            except Exception as e:
                print(f'Error loading JSON: {e}')
        else:
            print(f'File {JSON_FILE} not found. Creating with default values.')
            self.save_to_json()
    
    def save_to_json(self):
        '''Persist data to JSON file'''
        try:
            with open(JSON_FILE, 'w') as f:
                persistent_data = {
                    'manager': self.data['manager'],
                    'managerEmail': self.data['managerEmail'],
                    'cpuThreshold': self.data['cpuThreshold']
                }
                json.dump(persistent_data, f, indent=2)
            print(f'Saved state to {JSON_FILE}')
        except Exception as e:
            print(f'Error saving JSON: {e}')
    
    def oid_to_key(self, oid):
        if oid == OID_MANAGER:
            return 'manager'
        elif oid == OID_MANAGER_EMAIL:
            return 'managerEmail'
        elif oid == OID_CPU_USAGE:
            return 'cpuUsage'
        elif oid == OID_CPU_THRESHOLD:
            return 'cpuThreshold'
        return None
    
    def get_sysuptime(self):
        return int((time.time() - self.start_time) * 100)

mib_store = MibDataStore()

def python_to_snmp(key, value):
    '''Convert Python value to SNMP type'''
    if key in ['manager', 'managerEmail']:
        return v2c.OctetString(str(value).encode('utf-8'))
    elif key in ['cpuUsage', 'cpuThreshold']:
        return v2c.Integer(int(value))
    return v2c.Null()

def snmp_to_python(key, snmp_value):
    '''Convert SNMP value to Python type'''
    if key in ['manager', 'managerEmail']:
        if isinstance(snmp_value, v2c.OctetString):
            return bytes(snmp_value).decode('utf-8')
        else:
            raise ValueError('Expected OctetString')
    elif key in ['cpuUsage', 'cpuThreshold']:
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
# Command Responders
# ===========================

class JsonGetCommandResponder(cmdrsp.GetCommandResponder):
    '''Custom GET responder with JSON backend'''
    
    # 1. Cambia el nombre del método y elimina acInfo
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
                value = mib_store.data[key]
                snmp_value = python_to_snmp(key, value)
                rspVarBinds.append((oid, snmp_value))
        
        if errorStatus:
            rspVarBinds = [(oid, v2c.Null()) for oid, val in varBinds]
        
        self.send_varbinds(snmpEngine, stateReference, errorStatus, errorIndex, rspVarBinds)

class JsonGetNextCommandResponder(cmdrsp.NextCommandResponder):
    def handle_management_operation(self, snmpEngine, stateReference, contextName, PDU):
        varBinds = v2c.apiPDU.get_varbinds(PDU)

        rspVarBinds = []
        errorStatus = 0
        errorIndex = 0
        
        for idx, (oid, val) in enumerate(varBinds, 1):
            oid_tuple = tuple(oid)
            
            next_oid = None
            for candidate in ORDERED_OIDS:
                if candidate > oid_tuple:
                    next_oid = candidate
                    break
            
            if next_oid is None:
                rspVarBinds.append((oid, rfc1905.EndOfMibView()))
            else:
                key = mib_store.oid_to_key(next_oid)
                value = mib_store.data[key]
                snmp_value = python_to_snmp(key, value)
                rspVarBinds.append((next_oid, snmp_value))
        
        if errorStatus:
            rspVarBinds = [(oid, v2c.Null()) for oid, val in varBinds]
        
        self.send_varbinds(snmpEngine, stateReference, errorStatus, errorIndex, rspVarBinds)

class JsonSetCommandResponder(cmdrsp.SetCommandResponder):
    '''Custom SET responder with JSON backend and validation'''
    
    # 1. Cambia el nombre del método y elimina acInfo
    def handle_management_operation(self, snmpEngine, stateReference, contextName, PDU):
        global current_security_name
        
        # Verificar permisos basado en securityName
        if current_security_name == b'public-user':
            print(f"SET rechazado: comunidad 'public' no tiene permisos de escritura")
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
                errorStatus = 5
                errorIndex = idx
                break
            
            try:
                if key in ['manager', 'managerEmail']:
                    if not isinstance(val, v2c.OctetString):
                        errorStatus = 7
                        errorIndex = idx
                        break
                elif key in ['cpuUsage', 'cpuThreshold']:
                    if not isinstance(val, (v2c.Integer, rfc1902.Integer32)):
                        errorStatus = 7
                        errorIndex = idx
                        break
                
                python_value = snmp_to_python(key, val)
                
                if key in ['manager', 'managerEmail']:
                    if len(python_value) > 255:
                        errorStatus = 10
                        errorIndex = idx
                        break
                elif key == 'cpuThreshold':
                    if not (0 <= python_value <= 100):
                        errorStatus = 10
                        errorIndex = idx
                        break
                elif key == 'cpuUsage':
                    errorStatus = 17
                    errorIndex = idx
                    break
                
                mib_store.data[key] = python_value
                rspVarBinds.append((oid, val))
                
            except Exception as e:
                errorStatus = 10
                errorIndex = idx
                break
        
        if errorStatus:
            rspVarBinds = [(oid, v2c.Null()) for oid, val in varBinds]
        else:
            mib_store.save_to_json()
        
        self.send_varbinds(snmpEngine, stateReference, errorStatus, errorIndex, rspVarBinds)

# ===========================
# TRAP and Email
# ===========================

def send_trap(snmpEngine, cpu_usage, cpu_threshold):
    '''Send SNMPv2c TRAP notification'''
    print(f'Sending TRAP: CPU {cpu_usage}% > threshold {cpu_threshold}%')
    ntfOrg = ntforg.NotificationOriginator()
    varBinds = [
        (OID_CPU_USAGE, v2c.Integer(cpu_usage)),
        (OID_CPU_THRESHOLD, v2c.Integer(cpu_threshold)),
        (OID_MANAGER_EMAIL, v2c.OctetString(mib_store.data['managerEmail'].encode('utf-8'))),
        ((1, 3, 6, 1, 2, 1, 1, 3, 0), v2c.TimeTicks(mib_store.get_sysuptime()))
    ]
    ntfOrg.sendVarBinds(snmpEngine, 'trap-target', None, '', varBinds)

def send_email(cpu_usage, cpu_threshold):
    '''Send email notification via SMTP'''
    try:
        recipient = mib_store.data['managerEmail']
        manager = mib_store.data['manager']
        msg = MIMEText(f'''Alert: CPU Usage Threshold Exceeded

Dear {manager},

The CPU usage has exceeded the configured threshold:
- Current CPU Usage: {cpu_usage}%
- Configured Threshold: {cpu_threshold}%
- Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

This is an automated notification from the SNMP Mini Agent.

Best regards,
SNMP Monitoring System''')
        msg['Subject'] = f'ALERT: CPU Usage {cpu_usage}% > Threshold {cpu_threshold}%'
        msg['From'] = '[email protected]'
        msg['To'] = recipient
        
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.sendmail('[email protected]', [recipient], msg.as_string())
        print(f'Email sent to {recipient}')
    except Exception as e:
        print(f'Error sending email: {e}')

# ===========================
# CPU Monitoring
# ===========================

async def cpu_sampler(snmpEngine):
    '''Monitor CPU and send notifications on threshold crossing (edge-triggered)'''
    print('CPU sampler started')
    while True:
        try:
            cpu_usage = int(psutil.cpu_percent(interval=1))
            mib_store.data['cpuUsage'] = cpu_usage
            threshold = mib_store.data['cpuThreshold']
            
            if cpu_usage > threshold and not mib_store.above_threshold:
                mib_store.above_threshold = True
                print(f'\nTHRESHOLD CROSSED: CPU {cpu_usage}% > {threshold}%')
                send_trap(snmpEngine, cpu_usage, threshold)
                send_email(cpu_usage, threshold)
            elif cpu_usage <= threshold and mib_store.above_threshold:
                mib_store.above_threshold = False
                print(f'\nCPU back below threshold: {cpu_usage}% <= {threshold}%')
            
            print(f'CPU: {cpu_usage}% (threshold: {threshold}%)', end='\r')
        except Exception as e:
            print(f'\nError in cpu_sampler: {e}')
        await asyncio.sleep(5)

# ===========================
# Main Agent
# ===========================

def main():
    """Configura y arranca el agente SNMP"""
    print('=== Mini SNMP Agent Starting ===')
    print(f'Base OID: {".".join(map(str, BASE_OID))}')
    
    # ✅ CREAR EL EVENT LOOP PRIMERO (antes de SnmpEngine)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Create SNMP engine
    snmpEngine = engine.SnmpEngine()
    
    # ✅ USAR LA API MODERNA (snake_case)
    # Transport setup (UDP over IPv4, port 161)
    config.add_transport(
        snmpEngine,
        udp.DOMAIN_NAME,
        udp.UdpTransport().open_server_mode(('0.0.0.0', 161))
    )
    
    # SNMPv2c setup
    # Community 'public' -> read-only (security name: 'public-user')
    config.add_v1_system(snmpEngine, 'public-user', 'public')
    config.add_v1_system(snmpEngine, 'private-user', 'private')
    
    # VACM configuration
    # Allow read access for public-user
    config.add_vacm_user(
        snmpEngine,
        2,  # SNMPv2c
        'public-user',
        'noAuthNoPriv',
        readSubTree=BASE_OID,
        writeSubTree=()
    )
    
    # Allow read-write access for private-user
    config.add_vacm_user(
        snmpEngine,
        2,  # SNMPv2c
        'private-user',
        'noAuthNoPriv',
        readSubTree=BASE_OID,
        writeSubTree=BASE_OID
    )
    
    # ✅ TRAP target configuration (API moderna)
    config.add_target_parameters(snmpEngine, 'trap-params', 'public-user', 'noAuthNoPriv', 1)
    config.add_target_address(snmpEngine, 'trap-target', udp.DOMAIN_NAME, (TRAP_HOST, TRAP_PORT), 'trap-params', tagList='trap-tag')
    config.add_notification_target(snmpEngine, 'trap-target', 'trap-filter', 'trap-tag', 'trap')
    
    # Create SNMP context
    snmpContext = context.SnmpContext(snmpEngine)
    
    # Register custom command responders
    JsonGetCommandResponder(snmpEngine, snmpContext)
    JsonGetNextCommandResponder(snmpEngine, snmpContext)
    JsonSetCommandResponder(snmpEngine, snmpContext)
    cmdrsp.BulkCommandResponder(snmpEngine, snmpContext)
    
    print('Agent listening on UDP port 161')
    print('Communities: public (RO), private (RW)')
    print(f'TRAP target: {TRAP_HOST}:{TRAP_PORT}')
    print(f'SMTP server: {SMTP_HOST}:{SMTP_PORT}')
    
    # Start CPU monitoring task
    loop.create_task(cpu_sampler(snmpEngine))

    # Mantén el bucle activo en el hilo principal
    try:
        print('\n=== Agent running - Press Ctrl+C to quit ===\n')
        loop.run_forever()
    except KeyboardInterrupt:
        print('\nShutting down...')
    finally:
        snmpEngine.transport_dispatcher.close_dispatcher()
        print('Agent stopped')

if __name__ == '__main__':
    main()
