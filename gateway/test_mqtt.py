import paho.mqtt.client as mqtt
import ssl
import sys

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Connected with result code {reason_code}")
    sys.exit(0)

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set("user", "ogorek123!")
client.tls_set()
client.on_connect = on_connect

print("Connecting...")
try:
    client.connect("mqtt.krlade.dev", 443, 60)
    print("Connected func returned")
    client.loop_forever()
except Exception as e:
    print(f"Exception: {e}")
