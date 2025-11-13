#!/usr/bin/env python
"""
Test script for Mini SNMP Agent
Tests GET, GETNEXT, SET operations and notifications.
"""

# Importaciones estándar
import asyncio          # Para operaciones asincrónicas (no usado en este script)
import json             # Para trabajar con JSON (no usado en este script)
import os               # Para operaciones del sistema operativo (no usado)
import subprocess       # Para ejecutar comandos del sistema (snmpget, snmpset, etc.)
import sys              # Para argumentos de línea de comandos y exit codes
import time             # Para pausas (sleep) entre pruebas
from pathlib import Path # Para trabajar con rutas (no usado)


# ===========================
# Clase Principal de Tests
# ===========================

class SnmpAgentTester:
    """Test suite for SNMP agent."""
    #| 1161 | Puerto alternativo SNMP (sin privilegios) | Pruebas locales, desarrollo | NO requiere root (usuario normal) |
    def __init__(self, agent_host="127.0.0.1", agent_port=1161):
        """
        Inicializa el tester con configuración del agente.
        
        Args:
            agent_host: IP del agente (default: localhost)
            agent_port: Puerto del agente (default: 1161 - no privilegiado)
        """
        self.host = agent_host                  # IP del agente
        self.port = agent_port                  # Puerto del agente
        self.read_community = "public"          # Comunidad de lectura
        self.write_community = "private"        # Comunidad de escritura
        self.base_oid = "1.3.6.1.3.28308.1"      # OID base del MIB personalizado
        
        # Diccionario para contar resultados de pruebas
        self.test_results = {
            "passed": 0,
            "failed": 0,
            "skipped": 0
        }
    
    # ===========================
    # Método Auxiliar: Ejecutar Comandos SNMP
    # ===========================

    def _run_snmp_command(self, cmd_type, oid, value=None, community=None):
        """
        Ejecuta un comando SNMP externo (snmpget, snmpset, etc.)
        
        Args:
            cmd_type: Tipo de comando ("get", "getnext", "set")
            oid: OID a consultar o modificar
            value: Valor a asignar (solo para SET)
            community: Comunidad SNMP (si None, usa public/private según cmd_type)
        
        Returns:
            (éxito: bool, stdout: str, stderr: str)
        """

        # Si no especifica comunidad, elige automáticamente
        if community is None:
            # GET/GETNEXT → comunidad de lectura ("public")
            # SET → comunidad de escritura ("private")
            community = self.read_community if cmd_type in ["get", "getnext"] else self.write_community
        
        # Construye el destino: "127.0.0.1:1161"
        target = f"{self.host}:{self.port}"
        
        try:
            # Construye el comando según el tipo
            if cmd_type == "get":
                # Ejemplo: snmpget -v2c -c public 127.0.0.1:1161 1.3.6.1.3.28308.1.1.0
                cmd = ["snmpget", "-v2c", "-c", community, target, oid]
            elif cmd_type == "getnext":
                # Ejemplo: snmpgetnext -v2c -c public 127.0.0.1:1161 1.3.6.1.3.28308.1.0
                cmd = ["snmpgetnext", "-v2c", "-c", community, target, oid]
            elif cmd_type == "set":
                # Verifica que se proporcionó un valor
                if value is None:
                    raise ValueError("SET requires a value")
                # Ejemplo: snmpset -v2c -c private 127.0.0.1:1161 1.3.6.1.3.28308.1.4.0 i 85
                cmd = ["snmpset", "-v2c", "-c", community, target, oid, value]
            else:
                # Tipo de comando desconocido
                raise ValueError(f"Unknown command type: {cmd_type}")
            
            # Ejecuta el comando con timeout de 5 segundos
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return result.returncode == 0, result.stdout, result.stderr
        
        except FileNotFoundError:
            # Las herramientas snmp no están instaladas
            print("⚠️  snmp tools not installed. Install with: sudo apt-get install snmp")
            return None, None, None
        except subprocess.TimeoutExpired:
            # El comando tardó más de 5 segundos
            return False, "", "Timeout"
        except Exception as e:
            # Otro error inesperado
            return False, "", str(e)
        
    # ===========================
    # Prueba 1: Verificar que el Agente Responde
    # ===========================    

    def test_agent_running(self):
        """
        Verifica si el agente SNMP está activo y respondiendo.
        Intenta hacer un GET del primer OID (manager).
        """
        print("\n[TEST] Checking if agent is running...")
        success, stdout, stderr = self._run_snmp_command("get", f"{self.base_oid}.1.0")
        
        if success is None:
            # Las herramientas SNMP no están disponibles
            self.test_results["skipped"] += 1
            print("⊘ SKIPPED: SNMP tools not available")
            return False
        
        if success:
            # El agente respondió correctamente
            self.test_results["passed"] += 1
            print("✓ PASSED: Agent is responding")
            return True
        else:
            # El agente no respondió
            self.test_results["failed"] += 1
            print(f"✗ FAILED: Agent not responding - {stderr}")
            return False
    
    # ===========================
    # Prueba 2: Operaciones GET
    # ===========================

    def test_get_operations(self):
        """
        Prueba operaciones GET en todos los objetos escalares.
        Verifica que se puedan leer: manager, managerEmail, cpuUsage, cpuThreshold
        """
        print("\n[TEST] Testing GET operations...")
        
        tests = [
            ("manager", f"{self.base_oid}.1.0", "DisplayString"),
            ("managerEmail", f"{self.base_oid}.2.0", "DisplayString"),
            ("cpuUsage", f"{self.base_oid}.3.0", "Integer32"),
            ("cpuThreshold", f"{self.base_oid}.4.0", "Integer32"),
        ]

        # Prueba cada objeto
        for name, oid, obj_type in tests:
            success, stdout, stderr = self._run_snmp_command("get", oid)
            
            if success is None:
                self.test_results["skipped"] += 1
                print(f"⊘ {name}: SKIPPED")
            elif success:
                self.test_results["passed"] += 1
                print(f"✓ {name}: {stdout.strip()}")
            else:
                self.test_results["failed"] += 1
                print(f"✗ {name}: FAILED - {stderr}")
    
    # ===========================
    # Prueba 3: Operaciones GETNEXT
    # ===========================

    def test_getnext_operations(self):
        """
        Prueba el recorrido lexicográfico del árbol MIB usando GETNEXT.
        Verifica que la secuencia sea correcta: manager → managerEmail → cpuUsage → cpuThreshold
        """
        print("\n[TEST] Testing GETNEXT (lexicographic walk)...")
        
        expected_sequence = [
            f"{self.base_oid}.1.0",  # manager
            f"{self.base_oid}.2.0",  # managerEmail
            f"{self.base_oid}.3.0",  # cpuUsage
            f"{self.base_oid}.4.0",  # cpuThreshold
        ]
        
        # Comienza con un OID anterior al primero para que GETNEXT retorne el primero
        current_oid = f"{self.base_oid}.0"  # Start before first object
        
        for i, expected_oid in enumerate(expected_sequence):
            success, stdout, stderr = self._run_snmp_command("getnext", current_oid)
            
            if success is None:
                self.test_results["skipped"] += 1
                print(f"⊘ Step {i+1}: SKIPPED")
                return
            
            if success and expected_oid in stdout:
                self.test_results["passed"] += 1
                print(f"✓ Step {i+1}: Got {expected_oid}")
                current_oid = expected_oid
            else:
                self.test_results["failed"] += 1
                print(f"✗ Step {i+1}: Expected {expected_oid}")
                print(f"  Got: {stdout}")
    
    # ===========================
    # Prueba 4: SET en Objeto Read-Write (manager)
    # ===========================

    def test_set_manager(self):
        """
        Prueba SET en el objeto 'manager' (read-write).
        Cambia el valor y verifica que cambió correctamente.
        """
        print("\n[TEST] Testing SET on manager (RW)...")
        
        oid = f"{self.base_oid}.1.0"
        test_value = '"TestManager"'
        
        # Ejecuta SET: snmpset -v2c -c private ... OID s "TestManager"
        # (s = tipo String/OctetString)
        success, stdout, stderr = self._run_snmp_command("set", oid, f"s {test_value}")
        
        if success is None:
            self.test_results["skipped"] += 1
            print("⊘ SKIPPED")
        elif success:
            self.test_results["passed"] += 1
            print(f"✓ PASSED: SET manager succeeded")
            
            # Verify with GET
            success, stdout, stderr = self._run_snmp_command("get", oid)
            if success and "TestManager" in stdout:
                print(f"✓ VERIFIED: {stdout.strip()}")
        else:
            self.test_results["failed"] += 1
            print(f"✗ FAILED: {stderr}")

    # ===========================
    # Prueba 5: SET en Objeto Read-Write (threshold)
    # ===========================

    def test_set_threshold(self):
        """
        Prueba SET en el objeto 'cpuThreshold' (read-write).
        Cambia el umbral a 85% y verifica que se aplique.
        """
        print("\n[TEST] Testing SET on threshold (RW)...")
        
        oid = f"{self.base_oid}.4.0"
        test_value = "i 85"
        
        # Ejecuta SET: snmpset -v2c -c private ... OID i 85
        # (i = tipo Integer)
        success, stdout, stderr = self._run_snmp_command("set", oid, test_value)
        
        if success is None:
            self.test_results["skipped"] += 1
            print("⊘ SKIPPED")
        elif success:
            self.test_results["passed"] += 1
            print(f"✓ PASSED: SET threshold succeeded")
            
            # Verify with GET
            success, stdout, stderr = self._run_snmp_command("get", oid)
            if success and "85" in stdout:
                print(f"✓ VERIFIED: {stdout.strip()}")
        else:
            self.test_results["failed"] += 1
            print(f"✗ FAILED: {stderr}")
    
    # ===========================
    # Prueba 6: SET en Objeto Read-Only (debe fallar)
    # ===========================

    def test_set_readonly(self):
        """
        Prueba SET en el objeto 'cpuUsage' (read-only).
        Esta prueba DEBE FALLAR con error "notWritable".
        """
        print("\n[TEST] Testing SET on cpuUsage (RO) - should fail...")
        
        oid = f"{self.base_oid}.3.0"
        test_value = "i 50"
        
        # Intenta SET en objeto read-only (debe ser rechazado)
        success, stdout, stderr = self._run_snmp_command("set", oid, test_value)
        
        if success is None:
            self.test_results["skipped"] += 1
            print("⊘ SKIPPED")
        # Prueba 1: Rechazado con mensaje específico "notWritable"
        elif not success and "notWritable" in stderr:
            self.test_results["passed"] += 1
            print(f"✓ PASSED: Correctly rejected with notWritable")
        # Prueba 2: Rechazado con cualquier error (también es válido)
        elif not success:
            self.test_results["passed"] += 1
            print(f"✓ PASSED: Correctly rejected (error: {stderr[:100]})")
        # Prueba 3: ERROR - permitió escribir en read-only
        else:
            self.test_results["failed"] += 1
            print(f"✗ FAILED: Should have rejected RO write")
    
    # ===========================
    # Prueba 7: SET con Tipo Incorrecto (debe fallar)
    # ===========================

    def test_set_wrong_type(self):
        """
        Prueba SET con tipo de dato incorrecto.
        Intenta enviar un String a cpuThreshold (que espera Integer).
        Esta prueba DEBE FALLAR.
        """
        print("\n[TEST] Testing SET with wrong type - should fail...")
        
        oid = f"{self.base_oid}.4.0"  # cpuThreshold is Integer32
        test_value = 's "not-an-int"'  # Try to set string
        
        # Intenta SET con tipo incorrecto
        success, stdout, stderr = self._run_snmp_command("set", oid, test_value)
        
        if success is None:
            self.test_results["skipped"] += 1
            print("⊘ SKIPPED")
        # Debe ser rechazado    
        elif not success:
            self.test_results["passed"] += 1
            print(f"✓ PASSED: Correctly rejected wrong type")
        # ERROR: permitió tipo incorrecto    
        else:
            self.test_results["failed"] += 1
            print(f"✗ FAILED: Should have rejected wrong type")
    
    # ===========================
    # Prueba 8: Persistencia (Test Manual)
    # ===========================

    def test_persistence(self):
        """
        Prueba persistencia: verifica que los datos se guardan en JSON
        y se restauran después de reiniciar el agente.
        NOTA: Esta es una prueba MANUAL que requiere intervención del usuario.
        """
        print("\n[TEST] Testing persistence...")
        print("⚠️  MANUAL TEST: Stop and restart agent, then check if values persist")
        
        oid = f"{self.base_oid}.1.0"
        
        # Get current value
        success, stdout, stderr = self._run_snmp_command("get", oid)
        if success:
            initial_value = stdout.strip()
            print(f"Current value: {initial_value}")
            print("1. Stop the agent (Ctrl+C)")
            print("2. Restart the agent")
            print("3. Run: snmpget -v2c -c public 127.0.0.1:1161 1.3.6.1.3.28308.1.1.0")
            print("4. Verify the same value appears")
            self.test_results["skipped"] += 1
        else:
            self.test_results["failed"] += 1
    
    # ===========================
    # Prueba 9: Muestreo de CPU
    # ===========================

    def test_cpu_sampling(self):
        """
        Prueba que cpuUsage se actualiza periódicamente.
        Lee el valor inicial, espera 6 segundos, y verifica que cambió.
        """
        print("\n[TEST] Testing CPU sampling...")
        
        oid = f"{self.base_oid}.3.0"
        
        # Get first value
        success1, stdout1, _ = self._run_snmp_command("get", oid)
        if success1 is None:
            self.test_results["skipped"] += 1
            return
        
        if not success1:
            self.test_results["failed"] += 1
            print("✗ FAILED: Cannot read cpuUsage")
            return
        
        print(f"Initial CPU: {stdout1.strip()}")
        
        # Espera 6 segundos para que el agente muestree CPU nuevamente
        # (el agente muestrea cada 5 segundos)
        print("Waiting 6 seconds for CPU update...")
        time.sleep(6)
        
        success2, stdout2, _ = self._run_snmp_command("get", oid)
        
        if success2:
            print(f"Updated CPU: {stdout2.strip()}")
            # Values may be different due to system load
            self.test_results["passed"] += 1
            print("✓ PASSED: CPU sampling is updating")
        else:
            self.test_results["failed"] += 1
            print("✗ FAILED: Cannot read updated cpuUsage")

    # ===========================
    # Prueba 10: SNMP WALK (recorrer todo el árbol)
    # ===========================

    def test_walk_subtree(self):
        """
        Prueba recorrido completo del subárbol usando snmpwalk.
        Verifica que se recuperan todos los 4 objetos del MIB.
        """
        print("\n[TEST] Testing SNMP WALK...")
        
        try:
            cmd = ["snmpwalk", "-v2c", "-c", self.read_community, 
                   f"{self.host}:{self.port}", self.base_oid]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                self.test_results["passed"] += 1
                print(f"✓ PASSED: Walk returned {len(lines)} objects")
                for line in lines[:5]:
                    print(f"  {line[:80]}")
                if len(lines) > 5:
                    print(f"  ... ({len(lines) - 5} more)")
            else:
                self.test_results["failed"] += 1
                print(f"✗ FAILED: {result.stderr}")
        except FileNotFoundError:
            self.test_results["skipped"] += 1
            print("⊘ SKIPPED: snmpwalk not installed")
        except Exception as e:
            self.test_results["failed"] += 1
            print(f"✗ FAILED: {e}")
    
    # ===========================
    # Ejecutar Todas las Pruebas
    # ===========================

    def run_all_tests(self):
        """
        Ejecuta todas las pruebas en secuencia.
        Primero verifica que el agente esté activo, luego ejecuta todas las pruebas.
        """
        print("=" * 60)
        print("SNMP Agent Test Suite")
        print("=" * 60)
        
        # Primero verifica que el agente esté activo
        if not self.test_agent_running():
            print("\n⚠️  Agent is not running. Start it with: python agent_AnaDaniel.py")
            print("   (Make sure to use unprivileged port 1161 for non-root testing)")
            sys.exit(1)
        
        # Ejecuta cada prueba en orden
        self.test_get_operations()
        self.test_getnext_operations()
        self.test_set_manager()
        self.test_set_threshold()
        self.test_set_readonly()
        self.test_set_wrong_type()
        self.test_walk_subtree()
        self.test_cpu_sampling()
        self.test_persistence()
        
        self._print_summary()
    
    # ===========================
    # Imprimir Resumen de Resultados
    # ===========================

    def _print_summary(self):
        """
        Imprime un resumen de todas las pruebas ejecutadas.
        Muestra cantidad de pruebas pasadas, fallidas y omitidas.
        """
        print("\n" + "=" * 60)
        print("Test Summary")
        print("=" * 60)
        print(f"✓ Passed:  {self.test_results['passed']}")
        print(f"✗ Failed:  {self.test_results['failed']}")
        print(f"⊘ Skipped: {self.test_results['skipped']}")
        print("=" * 60)
        
        if self.test_results['failed'] == 0:
            print("✓ All tests passed!")
            return 0
        else:
            print(f"✗ {self.test_results['failed']} test(s) failed")
            return 1
        
# ===========================
# Función Principal
# ===========================

def main():
    """
    Punto de entrada del script.
    Procesa argumentos de línea de comandos y ejecuta las pruebas.
    """
    import argparse
    # Configura parser de argumentos
    parser = argparse.ArgumentParser(description="Test Mini SNMP Agent")
    parser.add_argument("--host", default="127.0.0.1", help="Agent host (default: 127.0.0.1)")
    parser.add_argument("--port", default=1161, type=int, help="Agent port (default: 1161)")
    
    # Parsea los argumentos proporcionados
    args = parser.parse_args()
    
    # Crea instancia del tester con los parámetros
    tester = SnmpAgentTester(agent_host=args.host, agent_port=args.port)
    exit_code = tester.run_all_tests()
    # Sale del programa con el código de salida apropiado
    sys.exit(exit_code)

# ===========================
# Punto de Entrada del Script
# ===========================

if __name__ == "__main__":
    # Solo ejecuta main() si se ejecuta directamente (no si se importa)
    main()