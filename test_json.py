import json
try:
    json.loads('{\n    "')
except Exception as e:
    print("Test 1:", repr(e))

try:
    json.loads('{\n    "intent')
except Exception as e:
    print("Test 2:", repr(e))

