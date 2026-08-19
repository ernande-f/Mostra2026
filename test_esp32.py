import socket
import serial
import serial.tools.list_ports
import time
import glob

def monitor():
    print("==========================================================================")
    print("  MONITOR DE ALTA PRECISÃO - ESP32 WI-FI UDP (Porta 4210) & USB")
    print("==========================================================================")
    print("Conecte seu Mac à rede Wi-Fi criada pelo ESP32: 'ESP32_COW_GAME' (Senha: 12345678)")
    print("Aguardando pacotes UDP na porta 4210 ou Cabo USB...\n")

    # Tenta abrir socket UDP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", 4210))
        sock.settimeout(0.1)
    except Exception as e:
        print(f"[Aviso UDP] {e}")
        sock = None

    # Tenta abrir porta USB como fallback
    ser = None
    try:
        devs = glob.glob('/dev/cu.*')
        for d in devs:
            d_low = d.lower()
            if any(k in d_low for k in ["esp32", "cow", "usbserial", "wchusbserial", "slab_usbtouart", "usbmodem", "cp210", "ch340"]):
                ser = serial.Serial(d, 115200, timeout=0.1)
                print(f"[USB] Aberto na porta {d}")
                break
    except Exception:
        ser = None

    print(f"{'FONTE':^14} | {'ACCEL LATERAL (Ay)':^20} | {'AÇÃO DETECTADA':^20} | {'STATUS GATILHO'}")
    print("-" * 75)

    armed = True
    last_shift = 0.0
    cooldown = 0.25
    trigger_thresh = 0.28
    gravity_lateral = 0.0

    try:
        while True:
            linha = None
            fonte = ""

            # 1. Tenta receber via Wi-Fi UDP
            if sock:
                try:
                    data, addr = sock.recvfrom(1024)
                    if data:
                        linha = data.decode('utf-8', errors='ignore').strip()
                        fonte = f"Wi-Fi [{addr[0]}]"
                except (socket.timeout, BlockingIOError):
                    pass

            # 2. Se não recebeu via Wi-Fi, tenta USB
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
                        ay = float(partes[0])
                        ax = 0.0
                    elif len(partes) >= 3:
                        ax = float(partes[0])
                        ay = float(partes[1])
                    else:
                        ay = float(partes[0])
                        ax = 0.0
                    
                    val_raw = ay if abs(ay) >= abs(ax) else ax
                    gravity_lateral = 0.95 * gravity_lateral + 0.05 * val_raw
                    dynamic_ay = val_raw - gravity_lateral
                    
                    agora = time.time()
                    tempo_passado = agora - last_shift
                    acao = "--- (Neutro)"
                    
                    if tempo_passado >= cooldown:
                        armed = True

                    if armed and tempo_passado >= cooldown:
                        if dynamic_ay > trigger_thresh:
                            acao = ">>> DIREITA (+1)"
                            armed = False
                            last_shift = agora
                        elif dynamic_ay < -trigger_thresh:
                            acao = "<<< ESQUERDA (-1)"
                            armed = False
                            last_shift = agora

                    gatilho = "ARMADO (Pronto)" if armed else f"COOLDOWN ({(cooldown - tempo_passado):.2f}s)"
                    print(f"{fonte:^14} | {dynamic_ay:>+12.3f} G        | {acao:^20} | {gatilho}")
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
