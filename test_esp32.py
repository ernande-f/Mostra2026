import serial
import serial.tools.list_ports
import time

def monitor():
    print("==========================================================================")
    print("  MONITOR COMPLETO ESP32 + MPU6050 (ACELERÔMETRO DINÂMICO + GIROSCÓPIO)")
    print("==========================================================================")
    
    ports = list(serial.tools.list_ports.comports())
    porta_alvo = None
    for p in ports:
        nome = p.device.lower()
        if "usb" in nome or "slab" in nome or "wch" in nome or "cu." in nome:
            if "bluetooth" not in nome:
                porta_alvo = p.device
                break
    
    if not porta_alvo and ports:
        porta_alvo = ports[0].device

    if not porta_alvo:
        print("[ERRO] Nenhuma porta USB encontrada. Verifique o cabo.")
        return

    print(f"Conectando na porta: {porta_alvo} ...\n")
    try:
        ser = serial.Serial(porta_alvo, 115200, timeout=1.0)
        print(">>> Lendo dados em tempo real (Pressione Ctrl+C para sair):\n")
        print(f"{'ROLL (E/D)':^12} | {'PITCH (F/T)':^12} | {'ACCEL LAT (Ay)':^16} | {'ACCEL VERT (Az)':^16} | {'AGACHADO?'}")
        print("-" * 78)
        
        while True:
            linha = ser.readline().decode('utf-8', errors='ignore').strip()
            if linha:
                partes = [p.strip() for p in linha.split(',') if p.strip()]
                if len(partes) >= 3:
                    try:
                        roll = float(partes[0])
                        pitch = float(partes[1])
                        crouch = int(partes[2])
                        ay = float(partes[4]) if len(partes) > 4 else 0.0
                        az = float(partes[5]) if len(partes) > 5 else 1.0
                        status_agacho = "SIM [X]" if crouch else "NAO [ ]"
                        print(f"{roll:>8.1f}°     | {pitch:>8.1f}°     | {ay:>10.2f} G      | {az:>10.2f} G      | {status_agacho}")
                    except ValueError:
                        print(f"Bruto: {linha}")
                else:
                    print(f"Bruto: {linha}")
    except KeyboardInterrupt:
        print("\nMonitoramento finalizado.")
    except Exception as e:
        print(f"\nErro: {e}")

if __name__ == "__main__":
    monitor()
