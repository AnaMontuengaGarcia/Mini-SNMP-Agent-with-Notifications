# Mini SNMP Agent - Documentation and Testing Guide

## Quick Start

```
# 1. Install dependencies
pip install pysnmp==7.1.17 psutil==5.9.5 aiosmtpd

# 2. Start SMTP server (Terminal 1)
python -m aiosmtpd -n -l localhost:1025

# 3. Start TRAP receiver (Terminal 2)
# Iniciar el servicio
sudo systemctl start snmptrapd

# Ver el estado
sudo systemctl status snmptrapd

# Ver los logs
sudo journalctl -u snmptrapd -f


# 4. Start agent (Terminal 3)

sudo ~/Documents/github-repositories/Mini-SNMP-Agent-with-Notifications/py314/bin/python agent_AnaDaniel.py
# 5. Test (Terminal 4)
snmpget -v2c -c public localhost 1.3.6.1.3.28308.1.1.0
```

## Complete Testing Suite

### GET Operations

```
# Get single object
snmpget -v2c -c public localhost 1.3.6.1.3.28308.1.1.0
# Expected: iso.3.6.1.3.28308.1.1.0 = STRING: "NetworkAdmin"

# Get multiple objects
snmpget -v2c -c public localhost \
  1.3.6.1.3.28308.1.1.0 \
  1.3.6.1.3.28308.1.2.0 \
  1.3.6.1.3.28308.1.3.0 \
  1.3.6.1.3.28308.1.4.0

# Get nonexistent OID (should return noSuchObject)
snmpget -v2c -c public localhost 1.3.6.1.3.28308.1.99.0

# Get with wrong community (should still work for read)
snmpget -v2c -c wrongcommunity localhost 1.3.6.1.3.28308.1.1.0
```

### GETNEXT Operations

```
# Get next from base OID
snmpgetnext -v2c -c public localhost 1.3.6.1.3.28308
# Should return manager (1.3.6.1.3.28308.1.1.0)

# Walk entire subtree
snmpwalk -v2c -c public localhost 1.3.6.1.3.28308

# Verify lexicographic order
snmpgetnext -v2c -c public localhost 1.3.6.1.3.28308.1.1.0
# Should return managerEmail (1.3.6.1.3.28308.1.2.0)

snmpgetnext -v2c -c public localhost 1.3.6.1.3.28308.1.4.0
# Should return EndOfMibView
```

### SET Operations - Success Cases

```
# SET manager name
snmpset -v2c -c private localhost \
  1.3.6.1.3.28308.1.1.0 s "Daniel Modrego"

# Verify change
snmpget -v2c -c public localhost 1.3.6.1.3.28308.1.1.0

# SET email
snmpset -v2c -c private localhost \
  1.3.6.1.3.28308.1.2.0 s "[email protected]"

# SET threshold
snmpset -v2c -c private localhost \
  1.3.6.1.3.28308.1.4.0 i 75

# SET multiple objects
snmpset -v2c -c private localhost \
  1.3.6.1.3.28308.1.1.0 s "Alice Smith" \
  1.3.6.1.3.28308.1.2.0 s "[email protected]" \
  1.3.6.1.3.28308.1.4.0 i 85

# Verify persistence
cat mib_state.json
```

### SET Operations - Error Cases

```
# Error: Wrong community (notWritable)
snmpset -v2c -c public localhost \
  1.3.6.1.3.28308.1.1.0 s "Test"
# Expected error: notWritable (17)

# Error: Wrong type (wrongType)
snmpset -v2c -c private localhost \
  1.3.6.1.3.28308.1.4.0 s "eighty"
# Expected error: wrongType (7)

# Error: Out of range (wrongValue)
snmpset -v2c -c private localhost \
  1.3.6.1.3.28308.1.4.0 i 150
# Expected error: wrongValue (10)

# Error: Negative value (wrongValue)
snmpset -v2c -c private localhost \
  1.3.6.1.3.28308.1.4.0 i -10
# Expected error: wrongValue (10)

# Error: String too long (wrongValue)
snmpset -v2c -c private localhost \
  1.3.6.1.3.28308.1.1.0 s "$(python3 -c 'print("A"*256)')"
# Expected error: wrongValue (10)

# Error: Read-only object (notWritable)
snmpset -v2c -c private localhost \
  1.3.6.1.3.28308.1.3.0 i 50
# Expected error: notWritable (17)

# Error: Nonexistent OID (noCreation)
snmpset -v2c -c private localhost \
  1.3.6.1.3.28308.1.99.0 i 100
# Expected error: noCreation (5)
```

### GETBULK Operations

```
# Bulk walk
snmpbulkwalk -v2c -c public localhost 1.3.6.1.3.28308

# Bulk get with specific parameters
snmpbulkget -v2c -c public -Cn0 -Cr4 localhost \
  1.3.6.1.3.28308.1.1
```

### Threshold Alert Testing

#### Method 1: Set Low Threshold

```
# 1. Set very low threshold
snmpset -v2c -c private localhost \
  1.3.6.1.3.28308.1.4.0 i 5

# 2. Wait 5-10 seconds for CPU sampling
# 3. Check agent output for "THRESHOLD CROSSED" message
# 4. Check SMTP server output for email
# 5. Check TRAP receiver for notification

# 6. Set threshold back to normal
snmpset -v2c -c private localhost \
  1.3.6.1.3.28308.1.4.0 i 80
```

#### Method 2: Generate CPU Load

```
# 1. Set reasonable threshold
snmpset -v2c -c private localhost \
  1.3.6.1.3.28308.1.4.0 i 50

# 2. Generate CPU load
# Option A: Simple Python loop
python3 -c "while True: pass" &
PID=$!

# Option B: stress tool
stress --cpu 4 --timeout 30

# Option C: dd command
dd if=/dev/zero of=/dev/null &
PID=$!

# 3. Monitor agent output
# Should see: "THRESHOLD CROSSED: CPU XX% > 50%"

# 4. Wait for notifications
# - TRAP should be sent to 127.0.0.1:162
# - Email should be sent to localhost:1025

# 5. Kill CPU load
kill $PID

# 6. Verify edge-triggered behavior
# Agent should log: "CPU back below threshold: XX% <= 50%"

# 7. Generate load again
python3 -c "while True: pass" &
PID2=$!

# 8. Verify second alert is sent
# This proves edge-triggering works correctly

# 9. Cleanup
kill $PID2
```

### Edge-Triggered Verification Script

```
#!/bin/bash
# test_edge_triggered.sh

echo "Testing edge-triggered alerts..."

# Set low threshold
snmpset -v2c -c private localhost 1.3.6.1.3.28308.1.4.0 i 30

echo "Generating CPU load..."
python3 -c "while True: pass" &
PID=$!

echo "Wait 10 seconds for first alert..."
sleep 10

echo "Alert should have fired. Now waiting while above threshold..."
echo "No additional alerts should appear for 20 seconds..."
sleep 20

echo "Killing CPU load..."
kill $PID

echo "Wait 10 seconds for CPU to drop..."
sleep 10

echo "Generating CPU load again..."
python3 -c "while True: pass" &
PID2=$!

echo "Wait 10 seconds for second alert..."
sleep 10

echo "Second alert should have fired now."
kill $PID2

echo "Test complete. Check agent logs for exactly 2 TRAP messages."
```

### Persistence Testing

```
# 1. Set custom values
snmpset -v2c -c private localhost \
  1.3.6.1.3.28308.1.1.0 s "TestUser" \
  1.3.6.1.3.28308.1.2.0 s "[email protected]" \
  1.3.6.1.3.28308.1.4.0 i 65

# 2. Verify JSON file
cat mib_state.json

# 3. Stop agent (Ctrl+C)

# 4. Restart agent
sudo python3 agent_AnaDaniel.py

# 5. Verify values persisted
snmpget -v2c -c public localhost \
  1.3.6.1.3.28308.1.1.0 \
  1.3.6.1.3.28308.1.2.0 \
  1.3.6.1.3.28308.1.4.0

# 6. Note: cpuUsage should reset to 0, not persist
```

## Python Test Scripts

### Simple TRAP Receiver

```
#!/usr/bin/env python3
# trap_receiver.py

from pysnmp.entity import engine, config
from pysnmp.carrier.asyncio.dgram import udp
from pysnmp.entity.rfc3413 import ntfrcv

snmpEngine = engine.SnmpEngine()

config.addTransport(
    snmpEngine,
    udp.domainName,
    udp.UdpTransport().openServerMode(('0.0.0.0', 162))
)

config.addV1System(snmpEngine, 'trap-user', 'public')

def cbFun(snmpEngine, stateReference, contextEngineId, 
          contextName, varBinds, cbCtx):
    print('\\n' + '='*60)
    print('TRAP RECEIVED')
    print('='*60)
    for oid, val in varBinds:
        print(f'{oid.prettyPrint()} = {val.prettyPrint()}')
    print('='*60 + '\\n')

ntfrcv.NotificationReceiver(snmpEngine, cbFun)
snmpEngine.transportDispatcher.jobStarted(1)

print('TRAP Receiver listening on port 162...')
print('Press Ctrl+C to quit\\n')

try:
    snmpEngine.transportDispatcher.runDispatcher()
except KeyboardInterrupt:
    snmpEngine.transportDispatcher.closeDispatcher()
    print('\\nReceiver stopped')
```

### Automated Test Suite

```
#!/usr/bin/env python3
# test_agent.py

from pysnmp.hlapi import *
import time

def test_get(oid, expected_type=None):
    """Test GET operation"""
    iterator = getCmd(
        SnmpEngine(),
        CommunityData('public'),
        UdpTransportTarget(('localhost', 161)),
        ContextData(),
        ObjectType(ObjectIdentity(oid))
    )
    
    errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
    
    if errorIndication:
        print(f'✗ GET {oid}: {errorIndication}')
        return False
    elif errorStatus:
        print(f'✗ GET {oid}: {errorStatus.prettyPrint()}')
        return False
    else:
        oid, val = varBinds
        print(f'✓ GET {oid}: {val.prettyPrint()}')
        return True

def test_set(oid, value, should_succeed=True):
    """Test SET operation"""
    iterator = setCmd(
        SnmpEngine(),
        CommunityData('private'),
        UdpTransportTarget(('localhost', 161)),
        ContextData(),
        ObjectType(ObjectIdentity(oid), value)
    )
    
    errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
    
    success = not errorIndication and not errorStatus
    symbol = '✓' if success == should_succeed else '✗'
    
    if errorIndication:
        print(f'{symbol} SET {oid}: {errorIndication}')
    elif errorStatus:
        print(f'{symbol} SET {oid}: {errorStatus.prettyPrint()}')
    else:
        print(f'{symbol} SET {oid}: Success')
    
    return success == should_succeed

def test_getnext(oid):
    """Test GETNEXT operation"""
    iterator = nextCmd(
        SnmpEngine(),
        CommunityData('public'),
        UdpTransportTarget(('localhost', 161)),
        ContextData(),
        ObjectType(ObjectIdentity(oid))
    )
    
    errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
    
    if errorIndication or errorStatus:
        print(f'✗ GETNEXT {oid}: Error')
        return False
    else:
        oid, val = varBinds
        print(f'✓ GETNEXT returned {oid}: {val.prettyPrint()}')
        return True

print('='*60)
print('SNMP Agent Test Suite')
print('='*60)

# Test GET operations
print('\\n--- GET Tests ---')
test_get('1.3.6.1.3.28308.1.1.0')  # manager
test_get('1.3.6.1.3.28308.1.2.0')  # managerEmail
test_get('1.3.6.1.3.28308.1.3.0')  # cpuUsage
test_get('1.3.6.1.3.28308.1.4.0')  # cpuThreshold

# Test GETNEXT operations
print('\\n--- GETNEXT Tests ---')
test_getnext('1.3.6.1.3.28308')
test_getnext('1.3.6.1.3.28308.1.1.0')

# Test successful SET operations
print('\\n--- SET Tests (Success) ---')
test_set('1.3.6.1.3.28308.1.1.0', OctetString('TestAdmin'), True)
test_set('1.3.6.1.3.28308.1.4.0', Integer(75), True)

# Test failed SET operations
print('\\n--- SET Tests (Expected Failures) ---')
test_set('1.3.6.1.3.28308.1.3.0', Integer(50), False)  # Read-only
test_set('1.3.6.1.3.28308.1.4.0', Integer(150), False)  # Out of range

print('\\n' + '='*60)
print('Test Suite Complete')
print('='*60)
```

## Troubleshooting Guide

### Problem: "Permission denied" on port 161

**Solution:**
```
# Option 1: Run with sudo
sudo python3 mini_agent.py

# Option 2: Use capability (Linux)
sudo setcap cap_net_bind_service=+ep /usr/bin/python3.X
python3 agent_AnaDaniel.py

# Option 3: Use high port for testing
# Edit agent_AnaDaniel.py: Change port 161 to 1161
# Then test with: snmpget -v2c -c public localhost:1161 ...
```

### Problem: TRAP not received

**Checklist:**
```
# 1. Verify TRAP receiver is running
sudo netstat -nlup | grep 162

# 2. Check firewall
sudo iptables -L -n | grep 162

# 3. Use tcpdump to see packets
sudo tcpdump -i lo -n port 162 -v

# 4. Test TRAP separately
snmptrap -v2c -c public localhost:162 '' \
  1.3.6.1.6.3.1.1.5.1 \
  1.3.6.1.3.28308.1.3.0 i 95
```

### Problem: Email not sent

**Debug steps:**
```
# 1. Verify SMTP server running
python3 -m aiosmtpd -n -l localhost:1025

# 2. Test SMTP separately
python3 << EOF
import smtplib
server = smtplib.SMTP('localhost', 1025)
server.sendmail('test@test', ['[email protected]'], 'Test message')
server.quit()
print('Email sent successfully')
EOF

# 3. Check agent logs for errors
# Look for "Error sending email:" messages
```

### Problem: Values not persisting

**Debug:**
```
# 1. Check file permissions
ls -la mib_state.json

# 2. Manually verify JSON
cat mib_state.json | python3 -m json.tool

# 3. Check agent logs
# Should see "Saved state to mib_state.json" after SET

# 4. Verify using correct community
# Only 'private' community can write
```

## Performance Monitoring

```
# Monitor agent CPU usage
while true; do
  ps aux | grep mini_agent.py | grep -v grep
  sleep 1
done

# Monitor SNMP traffic
sudo tcpdump -i lo -n port 161 -v

# Test response time
time snmpget -v2c -c public localhost 1.3.6.1.3.28308.1.1.0
```

## Complete Deployment Checklist

- [ ] Python 3.7+ installed
- [ ] pysnmp, psutil, and aiosmtpd installed
- [ ] Root privileges available for port 161
- [ ] SMTP server configured (if using email)
- [ ] TRAP receiver configured (if testing notifications)
- [ ] Firewall rules allow UDP/161 and UDP/162
- [ ] MIB file copied to /usr/share/snmp/mibs/ (optional)
- [ ] Initial mib_state.json created or will be auto-generated
- [ ] Test all GET/SET/GETNEXT operations
- [ ] Verify persistence across restarts
- [ ] Test threshold alerting
- [ ] Verify edge-triggered behavior

## Production Recommendations

⚠️ **This is a demonstration agent. For production use:**

1. **Security**
   - Upgrade to SNMPv3 with authentication/encryption
   - Implement secure credential storage
   - Add rate limiting for SET operations
   - Validate email addresses before sending

2. **Monitoring**
   - Add comprehensive logging
   - Implement health checks
   - Monitor agent resource usage
   - Set up alerting for agent failures

3. **Reliability**
   - Add error recovery
   - Implement graceful shutdown
   - Use systemd service for automatic restart
   - Add backup for mib_state.json

4. **Performance**
   - Optimize CPU sampling interval
   - Add request rate limiting
   - Monitor memory usage
   - Consider database backend for large deployments
```