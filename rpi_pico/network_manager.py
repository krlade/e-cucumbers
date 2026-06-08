import network
import uasyncio as asyncio
import json
import machine
import config as app_config

WIFI_CONFIG_FILE = "wifi_config.json"

def load_wifi_config():
    """Ładuje konfigurację sieciową z pliku JSON, z wartościami domyślnymi z config.py."""
    cfg = {
        "sta_ssid":     app_config.DEFAULT_STA_SSID,
        "sta_password": app_config.DEFAULT_STA_PASSWORD,
        "ap_ssid":      app_config.DEFAULT_AP_SSID,
        "ap_password":  app_config.DEFAULT_AP_PASSWORD,
        # Dane brokera MQTT (możliwe do nadpisania przez panel AP)
        "mqtt_broker":  app_config.MQTT_BROKER,
        "mqtt_port":    app_config.MQTT_PORT,
        "mqtt_user":    app_config.MQTT_USER,
        "mqtt_password": app_config.MQTT_PASSWORD,
    }
    try:
        with open(WIFI_CONFIG_FILE, "r") as f:
            file_cfg = json.load(f)
            cfg.update(file_cfg)
    except Exception:
        pass
    return cfg

def save_wifi_config(cfg):
    """Zapisuje konfigurację sieciową do pliku JSON."""
    with open(WIFI_CONFIG_FILE, "w") as f:
        json.dump(cfg, f)

async def ap_web_server():
    """
    Uruchamia Access Point i prosty serwer HTTP do konfiguracji urządzenia.
    Tryb AP jest uruchamiany wyłącznie przez wciśnięcie przycisku (GP15),
    nie jest już automatycznym fallbackiem po timeout połączenia Wi-Fi.
    """
    cfg = load_wifi_config()

    ap = network.WLAN(network.AP_IF)
    ap.active(True)

    ap_ssid = cfg.get("ap_ssid", "PICO_CONFIG")
    ap_pass = cfg.get("ap_password", "")

    if not ap_pass:
        ap.config(essid=ap_ssid, security=0)
    else:
        ap.config(essid=ap_ssid, password=ap_pass, security=3)

    ap_ip = ap.ifconfig()[0]

    def escape(s):
        return str(s).replace('"', '&quot;')

    html = f"""<!DOCTYPE html>
    <html><head><meta charset="UTF-8">
    <style>body{{font-family:sans-serif;max-width:480px;margin:20px auto;padding:0 12px}}
    h2{{color:#333}}h3{{margin-top:1.5em;border-bottom:1px solid #ccc}}
    label{{display:block;margin-top:.8em;font-size:.9em;color:#555}}
    input[type=text],input[type=password],input[type=number]{{width:100%;box-sizing:border-box;padding:6px;margin-top:3px}}
    input[type=submit]{{margin-top:1.5em;padding:10px 24px;background:#2196F3;color:#fff;border:none;cursor:pointer}}
    </style></head><body>
    <h2>Konfiguracja urzadzenia PICO</h2>
    <form action="/" method="GET">

    <h3>Siec domowa (Klient Wi-Fi)</h3>
    <label>SSID sieci<input type="text" name="sta_ssid" value="{escape(cfg['sta_ssid'])}"></label>
    <label>Haslo<input type="password" name="sta_password" value="{escape(cfg['sta_password'])}"></label>

    <h3>Broker MQTT</h3>
    <label>Adres brokera<input type="text" name="mqtt_broker" value="{escape(cfg['mqtt_broker'])}"></label>
    <label>Port<input type="number" name="mqtt_port" value="{escape(cfg['mqtt_port'])}"></label>
    <label>Uzytkownik<input type="text" name="mqtt_user" value="{escape(cfg['mqtt_user'])}"></label>
    <label>Haslo<input type="password" name="mqtt_password" value="{escape(cfg['mqtt_password'])}"></label>

    <h3>Access Point (ten panel)</h3>
    <label>AP SSID<input type="text" name="ap_ssid" value="{escape(cfg['ap_ssid'])}"></label>
    <label>AP Haslo<input type="password" name="ap_password" value="{escape(cfg['ap_password'])}"></label>

    <input type="submit" value="Zapisz i restartuj">
    </form>
    </body></html>
    """

    async def handle_client(reader, writer):
        try:
            request = await reader.read(2048)
            req_str = request.decode('utf-8')

            if "GET /?" in req_str:
                # Parsowanie parametrów formularza
                parts = req_str.split("GET /?")[1].split(" HTTP")[0].split("&")
                new_cfg = {}
                for part in parts:
                    if "=" in part:
                        k, v = part.split("=", 1)
                        v = (v.replace("+", " ")
                              .replace("%20", " ")
                              .replace("%21", "!")
                              .replace("%40", "@")
                              .replace("%23", "#")
                              .replace("%3A", ":"))
                        # Port musi być int
                        if k == "mqtt_port":
                            try:
                                v = int(v)
                            except ValueError:
                                pass
                        new_cfg[k] = v

                final_cfg = load_wifi_config()
                final_cfg.update(new_cfg)
                save_wifi_config(final_cfg)

                response = "HTTP/1.1 200 OK\r\n\r\nKonfiguracja zapisana. Restart urzadzenia..."
                writer.write(response.encode('utf-8'))
                await writer.drain()
                await asyncio.sleep(2)
                machine.reset()
            else:
                response = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + html
                writer.write(response.encode('utf-8'))
                await writer.drain()
        except Exception as e:
            print("[AP] Server error:", e)
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "0.0.0.0", 80)
    print(f"[AP] Uruchomiono. Polacz sie z '{ap_ssid}' i wejdz na http://{ap_ip}")
    while True:
        await asyncio.sleep(1)

async def connect_wifi(leds):
    """
    Próbuje połączyć się z siecią Wi-Fi z zapisaną konfiguracją.
    Nie startuje trybu AP automatycznie po timeout – tryb AP uruchamiany
    jest wyłącznie przez wciśnięcie przycisku konfiguracyjnego (patrz main.py).
    Zwraca True gdy połączenie udane, False gdy nieudane.
    """
    config = load_wifi_config()
    ssid = config.get("sta_ssid", "")
    password = config.get("sta_password", "")

    sta = network.WLAN(network.STA_IF)
    sta.active(True)

    if not ssid:
        print("[WiFi] Brak skonfigurowanego SSID. Wcisnij przycisk aby skonfigurowac.")
        return False

    print(f"[WiFi] Laczenie z {ssid}...")
    sta.connect(ssid, password)

    timeout = 20
    while not sta.isconnected() and timeout > 0:
        await asyncio.sleep(1)
        timeout -= 1

    if sta.isconnected():
        print("[WiFi] Polaczono. IP:", sta.ifconfig()[0])
        leds.set_status('connecting_mqtt')
        return True
    else:
        print("[WiFi] Nie udalo sie polaczyc. Wcisnij przycisk aby skonfigurowac.")
        return False
