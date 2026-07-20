p = r"E:/Prometheus-Ultra-MultiTypeKB/src/prometheus_nexus/harness/guardrail.py"
b = open(p, 'rb').read()
null = chr(0).encode()
esc = ("\\" + "x00").encode()   # backslash + x + 0 + 0  (4 bytes)
n = b.count(null)
b2 = b.replace(null, esc)
open(p, 'wb').write(b2)
print("replaced", n)
import ast
ast.parse(b2.decode('utf-8'))
print("COMPILE_OK")
