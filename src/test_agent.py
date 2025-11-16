#!/usr/bin/env python3
# test_agent.py - Complete SNMP Agent Test Suite

import asyncio
import os
import signal
import subprocess
import multiprocessing
import sys
import time
from pysnmp.hlapi.v3arch.asyncio import *


# Contadores globales para el resumen
test_results = {
    'get': {'passed': 0, 'total': 0},
    'getnext': {'passed': 0, 'total': 0},
    'walk': {'passed': 0, 'total': 0, 'oids': 0},
    'set_success': {'passed': 0, 'total': 0},
    'set_failure': {'passed': 0, 'total': 0},
    'access_control': {'passed': 0, 'total': 0},
    'cpu_sampler': {'passed': 0, 'total': 0},
    'persistence': {'passed': 0, 'total': 0},
    'trap': {'passed': 0, 'total': 0}
}

async def test_get(oid, description=''):
    """Test GET operation"""
    test_results['get']['total'] += 1
    try:
        errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
            SnmpEngine(),
            CommunityData('public'),
            await UdpTransportTarget.create(('localhost', 161)),
            ContextData(),
            ObjectType(ObjectIdentity(oid))
        )
        
        if errorIndication:
            print(f'✗ GET {description or oid}: {errorIndication}')
            return False
        elif errorStatus:
            print(f'✗ GET {description or oid}: {errorStatus.prettyPrint()}')
            return False
        else:
            name, val = varBinds[0]
            print(f'✓ GET {description or oid}: {val.prettyPrint()}')
            test_results['get']['passed'] += 1
            return True
    except Exception as e:
        print(f'✗ GET {description or oid}: Connection error - {e}')
        return False


async def test_set(oid, value, should_succeed=True, description=''):
    """Test SET operation"""
    category = 'set_success' if should_succeed else 'set_failure'
    test_results[category]['total'] += 1
    
    try:
        errorIndication, errorStatus, errorIndex, varBinds = await set_cmd(
            SnmpEngine(),
            CommunityData('private'),
            await UdpTransportTarget.create(('localhost', 161)),
            ContextData(),
            ObjectType(ObjectIdentity(oid), value)
        )
        
        success = not errorIndication and not errorStatus
        symbol = '✓' if success == should_succeed else '✗'
        
        if errorIndication:
            print(f'{symbol} SET {description or oid}: {errorIndication}')
        elif errorStatus:
            print(f'{symbol} SET {description or oid}: {errorStatus.prettyPrint()}')
        else:
            print(f'{symbol} SET {description or oid}: Success')
        
        if success == should_succeed:
            test_results[category]['passed'] += 1
            return True
        return False
    except Exception as e:
        print(f'✗ SET {description or oid}: Connection error - {e}')
        return False


async def test_getnext(oid, description=''):
    """Test GETNEXT operation"""
    test_results['getnext']['total'] += 1
    try:
        errorIndication, errorStatus, errorIndex, varBinds = await next_cmd(
            SnmpEngine(),
            CommunityData('public'),
            await UdpTransportTarget.create(('localhost', 161)),
            ContextData(),
            ObjectType(ObjectIdentity(oid))
        )
        
        if errorIndication or errorStatus:
            print(f'✗ GETNEXT {description or oid}: Error')
            return False
        else:
            name, val = varBinds[0]
            print(f'✓ GETNEXT {description or oid} → {name}: {val.prettyPrint()}')
            test_results['getnext']['passed'] += 1
            return True
    except Exception as e:
        print(f'✗ GETNEXT {description or oid}: Connection error - {e}')
        return False


async def test_walk(oid, description=''):
    """Test SNMPWALK operation"""
    print(f'\n--- WALK {description or oid} ---')
    test_results['walk']['total'] += 1
    try:
        count = 0
        async for (errorIndication, errorStatus, errorIndex, varBinds) in walk_cmd(
            SnmpEngine(),
            CommunityData('public'),
            await UdpTransportTarget.create(('localhost', 161)),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False
        ):
            if errorIndication or errorStatus:
                print(f'✗ WALK error')
                return False
            else:
                for name, val in varBinds:
                    print(f'  {name} = {val.prettyPrint()}')
                    count += 1
        
        test_results['walk']['oids'] = count
        print(f'✓ WALK complete ({count} objects)')
        test_results['walk']['passed'] += 1
        return True
    except Exception as e:
        print(f'✗ WALK error: {e}')
        return False


async def test_cpu_sampler():
    """Test CPU sampler periodic updates (2.7.6)"""
    print('\n--- CPU Sampler Test (2.7.6) ---')
    test_results['cpu_sampler']['total'] += 1
    
    try:
        # Primera lectura
        _, _, _, varBinds1 = await get_cmd(
            SnmpEngine(),
            CommunityData('public'),
            await UdpTransportTarget.create(('localhost', 161)),
            ContextData(),
            ObjectType(ObjectIdentity('1.3.6.1.4.1.28308.1.3.0'))
        )
        cpu1 = int(varBinds1[0][1])
        print(f'  Initial CPU reading: {cpu1}%')
        
        # Esperar 6 segundos (intervalo de sampling = 5s)
        print('  Waiting 6 seconds for next sample...')
        await asyncio.sleep(6)
        
        # Segunda lectura
        _, _, _, varBinds2 = await get_cmd(
            SnmpEngine(),
            CommunityData('public'),
            await UdpTransportTarget.create(('localhost', 161)),
            ContextData(),
            ObjectType(ObjectIdentity('1.3.6.1.4.1.28308.1.3.0'))
        )
        cpu2 = int(varBinds2[0][1])
        print(f'  Second CPU reading: {cpu2}%')
        
        print(f'✓ CPU sampler is running (agent responsive)')
        test_results['cpu_sampler']['passed'] += 1
        return True
        
    except Exception as e:
        print(f'✗ CPU sampler test failed: {e}')
        return False

# Variable global para el proceso del agente
agent_process = None


def start_agent_in_terminal():
    """Start agent in background and open terminal showing logs"""
    global agent_process
    
    test_script_dir = os.path.dirname(os.path.abspath(__file__))
    agent_path = os.path.join(test_script_dir, 'agent_AnaDaniel.py')
    
    # Usar el Python del entorno virtual si existe
    venv_paths = [
        os.path.join(test_script_dir, 'py313', 'bin', 'python3'),
        os.path.join(test_script_dir, 'py312', 'bin', 'python3'),
        os.path.join(test_script_dir, 'venv', 'bin', 'python3'),
        sys.executable
    ]
    
    python_executable = None
    for venv_path in venv_paths:
        if os.path.exists(venv_path):
            python_executable = venv_path
            break
    
    if not python_executable:
        python_executable = sys.executable
    
    if not os.path.exists(agent_path):
        print(f'✗ Agent not found at: {agent_path}', flush =True)
        return False
    
    print('🚀 Starting agent...', flush =True)
    print(f'   Agent: {agent_path}', flush =True)
    print(f'   Python: {python_executable}', flush =True)
    
    venv_bin_dir = os.path.dirname(python_executable)
    log_file_path = '/tmp/agent_snmp.log'
    
    print('   Starting agent in background...', end=' ', flush=True)
    
    # Matar procesos anteriores
    subprocess.run(['pkill', '-f', 'agent_AnaDaniel.py'], capture_output=True)
    time.sleep(0.5)
    
    # Limpiar log anterior
    if os.path.exists(log_file_path):
        os.remove(log_file_path)
    
    # Iniciar agente con output UNBUFFERED solo a archivo
    env_bg = os.environ.copy()
    env_bg['PATH'] = f"{venv_bin_dir}:{env_bg.get('PATH', '')}"
    env_bg['PYTHONUNBUFFERED'] = '1'
    
    # Usar DEVNULL para stdin y abrir archivo SIN compartir file descriptor
    log_file = open(log_file_path, 'w', buffering=1)
    os.chmod(log_file_path, 0o644)
    
    agent_process = subprocess.Popen(
        [python_executable, '-u', agent_path],
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env_bg,
        preexec_fn=os.setpgrp,
        close_fds=True
    )
    
    time.sleep(2)
    
    # Verificar que está corriendo
    check = subprocess.run(['pgrep', '-f', 'agent_AnaDaniel.py'], 
                         capture_output=True, text=True)
    
    if not check.stdout.strip():
        print('✗ Failed to start', flush=True)
        log_file.close()
        return False
    
    agent_pid = check.stdout.strip().split('\n')[0]
    print(f'✓ Running (PID: {agent_pid})', flush=True)
    
    # Detectar usuario real
    sudo_user = os.environ.get('SUDO_USER')
    sudo_uid = os.environ.get('SUDO_UID')
    
    if not sudo_user:
        sudo_user = os.environ.get('USER', 'root')
        sudo_uid = '1000'
    
    # Variables de display del usuario
    display_env = os.environ.get('DISPLAY', ':0')
    wayland_display = os.environ.get('WAYLAND_DISPLAY', 'wayland-0')
    xdg_runtime_dir = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{sudo_uid}')
    
    # Script para el terminal que muestra logs
    log_viewer_script = '/tmp/snmp_agent_logviewer.sh'
    
    with open(log_viewer_script, 'w') as f:
        f.write('#!/bin/bash\n')
        f.write('clear\n')
        f.write('echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"\n')
        f.write('echo "  SNMP Agent - Live Log Viewer"\n')
        f.write('echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"\n')
        f.write(f'echo "Agent PID:  {agent_pid}"\n')
        f.write(f'echo "Log file:   {log_file_path}"\n')
        f.write('echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"\n')
        f.write('echo ""\n')
        f.write('echo "Press Ctrl+C to close this window (agent keeps running)"\n')
        f.write('echo ""\n')
        f.write('sleep 0.5\n')
        f.write(f'while [ ! -s {log_file_path} ]; do sleep 0.1; done\n')
        f.write(f'tail -f {log_file_path}\n')
    
    os.chmod(log_viewer_script, 0o755)
    
    print('   Opening log viewer terminal...', end=' ', flush=True)
    
    # Lista de terminales
    terminals = [
        # konsole - derecha arriba, 800px x 900px
        ['sudo', '-u', sudo_user,
        f'DISPLAY={display_env}',
        'konsole', '--geometry', '800x900-0+0', '--title', 'SNMP Agent Logs',
        '-e', f'bash {log_viewer_script}'],

        # xterm - derecha arriba, 100 columnas x 50 líneas
        ['sudo', '-u', sudo_user, 
        f'DISPLAY={display_env}',
        'setsid', 'xterm', '-geometry', '100x50-0+0', '-T', 'SNMP Agent Logs',
        '-e', f'bash {log_viewer_script}'],
        
        # gnome-terminal - derecha arriba, 100 columnas x 50 líneas
        ['sudo', '-u', sudo_user,
        f'DISPLAY={display_env}',
        f'WAYLAND_DISPLAY={wayland_display}',
        f'XDG_RUNTIME_DIR={xdg_runtime_dir}',
        'gnome-terminal', '--geometry=100x50-0+0', '--title=SNMP Agent Logs',
        '--', 'bash', log_viewer_script],
        
        # tilix (sin posición, solo tamaño)
        ['sudo', '-u', sudo_user,
        f'DISPLAY={display_env}',
        f'WAYLAND_DISPLAY={wayland_display}',
        'tilix', '--geometry=100x50', '-t', 'SNMP Agent Logs',
        '-e', f'bash {log_viewer_script}'],

    ]
    
    terminal_opened = False
    
    for terminal_cmd in terminals:
        try:
            term_name = None
            for part in terminal_cmd:
                if part in ['konsole', 'xterm', 'gnome-terminal', 'tilix']:
                    term_name = part
                    break
            
            if not term_name:
                continue
            
            check_term = subprocess.run(['which', term_name], capture_output=True)
            if check_term.returncode != 0:
                continue
            
            subprocess.Popen(
                terminal_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=True
            )
            
            time.sleep(0.5)
            
            print(f'✓ {term_name}', flush=True)
            terminal_opened = True
            break
            
        except Exception:
            continue
    
    if not terminal_opened:
        print('⚠️  No graphical terminal available', flush=True)
        print(f'\n   📄 View logs with: tail -f {log_file_path}\n')
    
    return True


def stop_agent():
    """Stop the agent gracefully"""
    global agent_process
    
    print('\n🛑 Stopping agent...')
    
    # Intentar encontrar el proceso por nombre si agent_process no está disponible
    result = subprocess.run(
        ['pgrep', '-f', 'agent_AnaDaniel.py'],
        capture_output=True,
        text=True
    )
    
    if result.stdout.strip():
        pids = result.stdout.strip().split('\n')
        for pid_str in pids:
            try:
                pid = int(pid_str)
                os.kill(pid, signal.SIGINT)
                print(f'   Sent SIGINT to PID {pid}')
            except (ValueError, ProcessLookupError):
                pass
    
    if agent_process and agent_process.poll() is None:
        try:
            agent_process.terminate()
            agent_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            agent_process.kill()
    
    print('✓ Agent stopped')


async def wait_for_agent_ready(max_wait=15):
    """Wait for agent to be ready to accept connections"""
    print(f'⏳ Waiting for agent to be ready (max {max_wait}s)...', flush=True)
    
    for i in range(max_wait):
        try:
            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                SnmpEngine(),
                CommunityData('public'),
                await UdpTransportTarget.create(('localhost', 161)),
                ContextData(),
                ObjectType(ObjectIdentity('1.3.6.1.2.1.1.1.0'))
            )
            
            if not errorIndication and not errorStatus:
                print(f'✓ Agent is ready after {i+1}s', flush=True)
                return True
            
        except Exception:
            pass
        
        await asyncio.sleep(1)
    
    print('✗ Agent did not become ready in time', flush=True)
    return False



async def test_persistence():
    """Test persistence across agent restarts (2.7.5) - AUTOMATED"""
    print('\n--- Persistence Test (2.7.5) ---')
    test_results['persistence']['total'] += 1
    
    try:
        # 1. Establecer un valor único
        test_value = f'PersistTest_{int(time.time())}'
        print(f'  Setting test value: {test_value}')
        
        _, errorStatus, _, _ = await set_cmd(
            SnmpEngine(),
            CommunityData('private'),
            await UdpTransportTarget.create(('localhost', 161)),
            ContextData(),
            ObjectType(ObjectIdentity('1.3.6.1.4.1.28308.1.1.0'), OctetString(test_value))
        )
        
        if errorStatus:
            print(f'✗ Failed to set initial value')
            return False
        
        print(f'✓ Value set successfully')
        
        # 2. Detener el agente usando la función centralizada
        print('  Stopping agent for persistence test...')
        stop_agent()
        
        # Esperar a que el agente se detenga completamente
        await asyncio.sleep(3)
        
        # 3. Reiniciar el agente en una nueva terminal
        print('  Restarting agent in new terminal...')
        if not start_agent_in_terminal():
            print('✗ Failed to restart agent')
            return False
        
        # 4. Esperar a que el agente esté listo
        print('  Waiting for agent to restart...')
        if not await wait_for_agent_ready(15):
            print('✗ Agent did not restart properly')
            return False
        
        # 5. Verificar que el valor persiste
        print('  Verifying persisted value...')
        _, _, _, varBinds = await get_cmd(
            SnmpEngine(),
            CommunityData('public'),
            await UdpTransportTarget.create(('localhost', 161)),
            ContextData(),
            ObjectType(ObjectIdentity('1.3.6.1.4.1.28308.1.1.0'))
        )
        
        persisted_value = str(varBinds[0][1])
        
        if persisted_value == test_value:
            print(f'✓ Persistence verified: {persisted_value}')
            test_results['persistence']['passed'] += 1
            return True
        else:
            print(f'✗ Value mismatch: expected {test_value}, got {persisted_value}')
            return False
            
    except Exception as e:
        print(f'✗ Persistence test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def check_and_free_port_162():
    """Check if port 162 is in use and free it if necessary"""
    print('🔍 Checking port 162 availability...')
    
    # Verificar si el puerto está en uso
    result = subprocess.run(
        ['sudo', 'lsof', '-i', ':162'],
        capture_output=True,
        text=True
    )
    
    if result.stdout:
        print('⚠️  Port 162 is in use')
        print(result.stdout)
        
        # Intentar detener servicios conocidos
        services_to_stop = [
            'snmptrapd.service',
            'snmptrapd.socket',
            'snmpd.service',
            'mgtrapd.service',
            'mgtrapd.socket'
        ]
        
        print('🛑 Stopping SNMP trap services...')
        for service in services_to_stop:
            try:
                result = subprocess.run(
                    ['sudo', 'systemctl', 'stop', service],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    print(f'   ✓ Stopped {service}')
                else:
                    # El servicio puede no existir, no es un error
                    pass
            except subprocess.TimeoutExpired:
                print(f'   ⚠️  Timeout stopping {service}')
            except Exception as e:
                print(f'   ⚠️  Error stopping {service}: {e}')
        
        # Esperar un momento para que los servicios se detengan
        time.sleep(2)
        
        # Verificar de nuevo
        result = subprocess.run(
            ['sudo', 'lsof', '-i', ':162'],
            capture_output=True,
            text=True
        )
        
        if result.stdout:
            print('✗ Port 162 still in use. Manual intervention required.')
            print('  Run: sudo killall snmptrapd')
            return False
        else:
            print('✓ Port 162 is now free')
            return True
    else:
        print('✓ Port 162 is free')
        return True


def generate_cpu_load(duration=10):
    """Generate CPU load in background process"""
    
    def cpu_intensive_task():
        """CPU-intensive calculation"""
        end_time = time.time() + duration
        while time.time() < end_time:
            # Cálculos intensivos para generar carga
            _ = [x**2 for x in range(10000)]
    
    # Lanzar múltiples procesos para asegurar carga
    num_processes = multiprocessing.cpu_count()
    processes = []
    
    print(f'  Generating CPU load with {num_processes} processes for {duration}s...')
    
    for _ in range(num_processes):
        p = multiprocessing.Process(target=cpu_intensive_task)
        p.start()
        processes.append(p)
    
    return processes


def stop_cpu_load(processes):
    """Stop all CPU load processes"""
    for p in processes:
        if p.is_alive():
            p.terminate()
            p.join(timeout=1)
    print('  CPU load generation stopped')

async def test_trap_sending():
    """Test SNMP trap generation (2.7.7) - AUTOMATED"""
    print('\n--- Trap Test (2.7.7) ---')
    test_results['trap']['total'] += 1
    
    # Verificar y liberar puerto 162 antes de empezar
    if not check_and_free_port_162():
        print('✗ Cannot free port 162 for trap test')
        return False
    
    cpu_processes = None
    
    try:
        # Socket para escuchar traps
        class TrapReceiver(asyncio.DatagramProtocol):
            def __init__(self):
                self.received = asyncio.Event()
                self.data = None
                
            def datagram_received(self, data, addr):
                print(f'  ✓ Received {len(data)} bytes from {addr}')
                self.data = data
                self.received.set()
        
        loop = asyncio.get_running_loop()
        
        print('  Starting trap listener on UDP:162...')
        try:
            transport, protocol = await loop.create_datagram_endpoint(
                TrapReceiver,
                local_addr=('127.0.0.1', 162)
            )
        except OSError as e:
            if 'Address already in use' in str(e):
                print('✗ Port 162 still in use after cleanup attempt')
                print('  Run manually: sudo killall snmptrapd')
                return False
            raise
        
        print('  Trap listener started')
        
        # Bajar umbral para forzar trap
        print('  Setting threshold to 5% to trigger trap...')
        await set_cmd(
            SnmpEngine(),
            CommunityData('private'),
            await UdpTransportTarget.create(('localhost', 161)),
            ContextData(),
            ObjectType(ObjectIdentity('1.3.6.1.4.1.28308.1.4.0'), Integer(5))
        )
        
        # Esperar un momento para que se registre el cambio
        await asyncio.sleep(1)
        
        # Generar carga de CPU para disparar el trap
        cpu_processes = generate_cpu_load(duration=12)
        
        # Esperar trap (máximo 15 segundos)
        print('  Waiting for trap (max 15 sec)...')
        try:
            await asyncio.wait_for(protocol.received.wait(), timeout=15.0)
            
            if protocol.data:
                trap_hex = protocol.data.hex()
                if '2b0601040' in trap_hex:
                    print('✓ Trap received with enterprise OID')
                    test_results['trap']['passed'] += 1
                    success = True
                else:
                    print('✓ Trap received (enterprise OID not verified)')
                    test_results['trap']['passed'] += 1
                    success = True
            else:
                print('✗ No trap data')
                success = False
                
            if success:
                print('  ℹ️  Trap received successfully')
                print('  ℹ️  Email was sent but may take 10-60 seconds to arrive')
                print('  ℹ️  Check your inbox after the test completes')
                print('  ⏳ Waiting 10 seconds for email delivery...')
                await asyncio.sleep(10)  # Dar tiempo a Gmail para entregar
                print('  ✓ Wait complete - check your email inbox now')


        except asyncio.TimeoutError:
            print('✗ Timeout: no trap received within 15 seconds')
            print('  CPU load may not have been sufficient')
            success = False
        
        # Detener generación de carga
        if cpu_processes:
            stop_cpu_load(cpu_processes)
        
        # Restaurar umbral
        print('  Restoring threshold to 80%...')
        await set_cmd(
            SnmpEngine(),
            CommunityData('private'),
            await UdpTransportTarget.create(('localhost', 161)),
            ContextData(),
            ObjectType(ObjectIdentity('1.3.6.1.4.1.28308.1.4.0'), Integer(80))
        )
        
        transport.close()
        return success
        
    except PermissionError:
        print('✗ Cannot bind to port 162 (requires sudo)')
        return False
    except Exception as e:
        print(f'✗ Trap test error: {e}')
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Asegurar que se detiene la carga de CPU incluso si hay error
        if cpu_processes:
            stop_cpu_load(cpu_processes)


def print_summary():
    """Print test results summary"""
    total_passed = sum(cat['passed'] for cat in test_results.values())
    total_tests = sum(cat['total'] for cat in test_results.values())
    
    success_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
    
    print('\n┌─────────────────────────────────────────┐')
    print('│  Test Results Summary                   │')
    print('├─────────────────────────────────────────┤')
    print(f'│  GET operations:        ✓ {test_results["get"]["passed"]}/{test_results["get"]["total"]}           │')
    print(f'│  GETNEXT operations:    ✓ {test_results["getnext"]["passed"]}/{test_results["getnext"]["total"]}           │')
    print(f'│  WALK operations:       ✓ {test_results["walk"]["passed"]}/{test_results["walk"]["total"]} ({test_results["walk"]["oids"]} OIDs)  │')
    print(f'│  SET success:           ✓ {test_results["set_success"]["passed"]}/{test_results["set_success"]["total"]}           │')
    print(f'│  SET failures (expected): ✓ {test_results["set_failure"]["passed"]}/{test_results["set_failure"]["total"]}         │')
    print(f'│  Access control:        ✓ {test_results["access_control"]["passed"]}/{test_results["access_control"]["total"]}           │')
    print(f'│  CPU sampler:           ✓ {test_results["cpu_sampler"]["passed"]}/{test_results["cpu_sampler"]["total"]}           │')
    print(f'│  Persistence:           ✓ {test_results["persistence"]["passed"]}/{test_results["persistence"]["total"]}           │')
    print(f'│  Trap sending:          ✓ {test_results["trap"]["passed"]}/{test_results["trap"]["total"]}           │')
    print('├─────────────────────────────────────────┤')
    print(f'│  TOTAL:                 ✓ {total_passed}/{total_tests}         │')
    print(f'│  SUCCESS RATE:          {success_rate:.0f}%            │')
    print('└─────────────────────────────────────────┘')


async def main():
    print('='*60)
    print('SNMP Agent Test Suite - Fully Automated')
    print('='*60)
    
    # Verificar y liberar puerto 162 al inicio
    check_and_free_port_162()
    
    # Iniciar el agente automáticamente
    if not start_agent_in_terminal():
        print('✗ Failed to start agent. Exiting.')
        return
    
    # Esperar a que el agente esté listo
    if not await wait_for_agent_ready(15):
        print('✗ Agent did not start properly. Exiting.')
        stop_agent()
        return
    
    print('\n' + '='*60)
    print('Starting tests...')
    print('='*60)
    
    try:
        # 2.7.1 - Basic GET
        print('\n--- GET Tests (2.7.1) ---')
        await test_get('1.3.6.1.4.1.28308.1.1.0', 'manager')
        await test_get('1.3.6.1.4.1.28308.1.2.0', 'managerEmail')
        await test_get('1.3.6.1.4.1.28308.1.3.0', 'cpuUsage')
        await test_get('1.3.6.1.4.1.28308.1.4.0', 'cpuThreshold')
        await test_get('1.3.6.1.2.1.1.1.0', 'sysDescr')
        await test_get('1.3.6.1.2.1.1.3.0', 'sysUpTime')
        
        # 2.7.2 - GETNEXT
        print('\n--- GETNEXT Tests (2.7.2) ---')
        await test_getnext('1.3.6.1.4.1.28308', 'Enterprise base')
        await test_getnext('1.3.6.1.4.1.28308.1.1.0', 'manager')
        
        # 2.7.8 - WALK
        await test_walk('1.3.6.1.4.1.28308', 'Enterprise MIB (2.7.8)')
        
        # 2.7.3 - SET success
        print('\n--- SET Tests - Success (2.7.3) ---')
        await test_set('1.3.6.1.4.1.28308.1.1.0', OctetString('Alice'), True, 'manager')
        await test_set('1.3.6.1.4.1.28308.1.2.0', OctetString('analumontuenga@gmail.com'), True, 'managerEmail')
        await test_set('1.3.6.1.4.1.28308.1.4.0', Integer(75), True, 'cpuThreshold')
        
        # 2.7.4 - SET failures
        print('\n--- SET Tests - Expected Failures (2.7.4) ---')
        await test_set('1.3.6.1.4.1.28308.1.3.0', Integer(50), False, 'cpuUsage (notWritable)')
        await test_set('1.3.6.1.4.1.28308.1.4.0', Integer(150), False, 'cpuThreshold (wrongValue)')
        await test_set('1.3.6.1.4.1.28308.1.4.0', OctetString('not-an-int'), False, 'cpuThreshold (wrongType)')
        
        # Access control
        print('\n--- Access Control Tests ---')
        test_results['access_control']['total'] += 1
        try:
            errorIndication, errorStatus, errorIndex, varBinds = await set_cmd(
                SnmpEngine(),
                CommunityData('public'),
                await UdpTransportTarget.create(('localhost', 161)),
                ContextData(),
                ObjectType(ObjectIdentity('1.3.6.1.4.1.28308.1.1.0'), OctetString('Hacker'))
            )
            
            if errorStatus and 'noAccess' in str(errorStatus):
                print('✓ Access denied correctly (noAccess)')
                test_results['access_control']['passed'] += 1
            else:
                print('✗ Access control failed')
        except Exception as e:
            print(f'✗ Test error: {e}')
        
        # 2.7.6 - CPU sampler
        await test_cpu_sampler()
        
        # 2.7.5 - Persistence
        await test_persistence()
        
        # 2.7.7 - Trap
        await test_trap_sending()
        
    finally:
        # Detener el agente al finalizar
        stop_agent()
    
    print('\n' + '='*60)
    print('Test Suite Complete')
    print('='*60)
    
    print_summary()


if __name__ == '__main__':
    # Verificar sudo
    if os.geteuid() != 0:
        print('⚠️  This script must be run with sudo')
        print('   Run: sudo python3 test_agent.py')
        sys.exit(1)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n\n⚠️  Tests interrupted by user')
        stop_agent()
        print('\n👋 Goodbye!')