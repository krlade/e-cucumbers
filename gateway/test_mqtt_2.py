import sys
print("starting", flush=True)

import paho.mqtt.client as mqtt
import ssl
print("imported", flush=True)

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Connected with result code {reason_code}", flush=True)
    sys.exit(0)

print("init client", flush=True)
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
client.username_pw_set("user", "ogorek123!")
client.tls_set()
client.on_connect = on_connect

print("Connecting to ws://mqtt.krlade.dev:443...", flush=True)
try:
    client.connect("mqtt.krlade.dev", 443, 60)
    print("Connected func returned", flush=True)
    client.loop_forever()
except Exception as e:
    print(f"Exception: {e}", flush=True)
