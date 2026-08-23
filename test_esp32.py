import socket
import serial
import serial.tools.list_ports
import time
import glob

def monitor():
    print("==========================================================================")
    print("  MONITOR DE PULO E AGACHAMENTO - ESP32 WI-FI UDP & USB")
    print("==========================================================================")
    print("Conecte seu Mac à rede Wi-Fi do ESP32: 'ESP32_COW_GAME' (Senha: 12345678)")
    print("Aguardando impulsos de Salto e Agachamento da cintura...\n")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", 4210))
        sock.settimeout(0.1)
    except Exception as e:
        print(f"[Aviso UDP] {e}")
        sock = None

    ser = None
    try:
        devs = glob.glob('/dev/cu.*')
        for d in devs:
            d_low = d.lower()
            if any(k in d_low for k in ["esp32", "cow", "usbserial", "wchusbserial", "slab_usbtouart", "usbmodem", "cp210", "ch340"]):
                ser = serial.Serial(d, 115200, timeout=0.1)
                break
    except Exception:
        ser = None

    print(f"{'FONTE':^14} | {'ACCEL VERTICAL':^20} | {'AÇÃO DETECTADA':^24} | {'GATILHO PULO'}")
    print("-" * 80)

    last_jump = 0.0
    jump_cooldown = 0.40
    jump_thresh = 0.32
    crouch_thresh = 0.22
    gravity_vert = 1.0

    try:
        while True:
            linha = None
            fonte = ""

            if sock:
                try:
                    data, addr = sock.recvfrom(1024)
                    if data:
                        linha = data.decode('utf-8', errors='ignore').strip()
                        fonte = f"Wi-Fi [{addr[0]}]"
                except (socket.timeout, BlockingIOError):
                    pass

            if not linha and ser:
                try:
                    linha = ser.readline().decode('utf-8', errors='ignore').strip()
                    if linha:
                        fonte = "USB Serial"
                except Exception:
                    pass

            if linha:
                try:
                    partes = [p.strip() for p in linha.split(',') if p.strip()]
                    if len(partes) == 1:
                        az = float(partes[0])
                        ax, ay = 0.0, 0.0
                    elif len(partes) >= 3:
                        ax = float(partes[0])
                        ay = float(partes[1])
                        az = float(partes[2])
                    else:
                        az = float(partes[0])
                        ax, ay = 0.0, 0.0
                    
                    val_vert = az if abs(az) >= abs(ay) else ay
                    gravity_vert = 0.95 * gravity_vert + 0.05 * val_vert
                    dynamic_vert = val_vert - gravity_vert
                    
                    agora = time.time()
                    tempo_passado = agora - last_jump
                    acao = "--- (Correndo)"
                    
                    if (dynamic_vert > jump_thresh) and (tempo_passado >= jump_cooldown):
                        acao = "🚀 >>> PULO! <<<"
                        last_jump = agora
                    elif (dynamic_vert < -crouch_thresh) or (abs(ay) > 0.42 and abs(az) < 0.75):
                        acao = "🛡️ --- AGACHADO ---"

                    pronto = tempo_passado >= jump_cooldown
                    gatilho = "PRONTO PARA PULAR" if pronto else f"COOLDOWN ({(jump_cooldown - tempo_passado):.2f}s)"
                    print(f"{fonte:^14} | {dynamic_vert:>+12.3f} G        | {acao:^24} | {gatilho}")
                except ValueError:
                    pass
            else:
                time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nMonitor encerrado pelo usuário.")
    finally:
        if sock:
            sock.close()
        if ser:
            ser.close()

if __name__ == "__main__":
    monitor()
