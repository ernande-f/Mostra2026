"""Monitor manual do pacote Wi-Fi usado pelo Nucleo de Abducao."""

import glob
import math
import socket
import time

import serial

from esp32_power import parse_sensor_packet

def _abrir_udp():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", 4210))
        sock.settimeout(0.1)
        return sock
    except OSError as exc:
        print(f"[Aviso UDP] {exc}")
        sock.close()
        return None


def _abrir_serial():
    try:
        for device in glob.glob("/dev/cu.*"):
            device_lower = device.lower()
            identifiers = (
                "esp32", "cow", "usbserial", "wchusbserial",
                "slab_usbtouart", "usbmodem", "cp210", "ch340",
            )
            if any(identifier in device_lower for identifier in identifiers):
                return serial.Serial(device, 115200, timeout=0.1)
    except (OSError, serial.SerialException):
        pass
    return None


def monitor():
    print("========================================================================")
    print("  DIAGNOSTICO ISOLADO DO ESP32 / MPU6050")
    print("========================================================================")
    print("Conecte o Mac a ESP32_COW_GAME (senha 12345678) ou use o cabo USB.")
    print("Feche este monitor antes de abrir o jogo: ambos usam a porta UDP 4210.")
    print("Ctrl+C encerra.\n")

    sock = _abrir_udp()
    ser = _abrir_serial()
    last_status = None
    last_status_time = 0.0

    try:
        while True:
            line = None
            source = ""

            if sock:
                try:
                    data, address = sock.recvfrom(1024)
                    line = data.decode("utf-8", errors="ignore").strip()
                    source = f"Wi-Fi {address[0]}"
                except (socket.timeout, BlockingIOError):
                    pass

            if not line and ser:
                try:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        source = "USB Serial"
                except (OSError, serial.SerialException):
                    pass

            if not line:
                time.sleep(0.01)
                continue

            sample = parse_sensor_packet(line)
            if sample is None:
                continue

            ax, ay, az = sample.ax, sample.ay, sample.az
            modulo = math.sqrt(ax * ax + ay * ay + az * az)
            giro = math.sqrt(
                sample.gx * sample.gx
                + sample.gy * sample.gy
                + sample.gz * sample.gz
            )
            status = (round(ax, 1), round(ay, 1), round(az, 1))
            now = time.monotonic()
            if status != last_status or now - last_status_time >= 0.5:
                print(
                    f"{source:<20} X={ax:+.3f} Y={ay:+.3f} Z={az:+.3f} "
                    f"| modulo={modulo:4.2f} g | giro={giro:5.1f} graus/s"
                )
                last_status = status
                last_status_time = now
    except KeyboardInterrupt:
        print("\nMonitor encerrado.")
    finally:
        if sock:
            sock.close()
        if ser:
            ser.close()


if __name__ == "__main__":
    monitor()
