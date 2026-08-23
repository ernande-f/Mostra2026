import pygame
import random
import math
import sys
import threading
import time
import json
import os

from datetime import datetime
from pathlib import Path

from vision_controller import VisionController

# ==========================================
# CONFIGURAÇÕES GERAIS E RESOLUÇÃO VIRTUAL
# ==========================================
LARGURA_VIRTUAL = 1280
ALTURA_VIRTUAL = 720
FPS = 60
PASTA_PROJETO = Path(__file__).resolve().parent
ARQUIVO_RANKING = PASTA_PROJETO / "dados" / "ranking.json"

# Cada modo altera de verdade a velocidade dos obstaculos que se aproximam.
# O intervalo tambem acompanha o modo para a pista continuar equilibrada.
DIFICULDADES = {
    "FACIL": {
        "nome": "FÁCIL",
        "velocidade": 0.78,
        "spawn": 64,
        "cor": (88, 236, 150),
    },
    "NORMAL": {
        "nome": "NORMAL",
        "velocidade": 1.00,
        "spawn": 55,
        "cor": (255, 218, 92),
    },
    "DIFICIL": {
        "nome": "DIFÍCIL",
        "velocidade": 1.28,
        "spawn": 48,
        "cor": (255, 105, 105),
    },
}
ORDEM_DIFICULDADES = tuple(DIFICULDADES)

# O obstaculo agora surge no alto da tela, antes do horizonte da pista.
PROGRESSO_SPAWN = -0.24
PROGRESSO_MINIMO_VISIVEL = -0.22

# ==========================================
# CONSTANTES DA PISTA (ANÉIS DE SATURNO - 3 FAIXAS)
# ==========================================
# Os anéis de Saturno ficam na metade direita da imagem
HORIZON_Y = 120
HORIZON_X_MIN = 750
HORIZON_X_MAX = 1110
HORIZON_CENTER_X = (HORIZON_X_MIN + HORIZON_X_MAX) / 2
HORIZON_LARGURA = HORIZON_X_MAX - HORIZON_X_MIN

BASE_Y = 580
BASE_X_MIN = 740
BASE_X_MAX = 1130
BASE_CENTER_X = (BASE_X_MIN + BASE_X_MAX) / 2
BASE_LARGURA = BASE_X_MAX - BASE_X_MIN

# Faixas esquerda, central e direita. A visao computacional mapeia a posicao
# horizontal do corpo diretamente para uma destas tres faixas.
LANE_RATIOS = [0.18, 0.50, 0.82]
NUM_LANES = len(LANE_RATIOS)
NOME_LANES = ["ESQUERDA", "CENTRO", "DIREITA"]

# Dimensões da Vaca nos Anéis
LARGURA_VACA_NORMAL = 105
ALTURA_VACA_NORMAL = 135
LARGURA_VACA_AGACHADA = 105
ALTURA_VACA_AGACHADA = 85

# A camera reconhece o abaixar do tronco e mantem a pose enquanto o jogador
# estiver agachado.
ENABLE_CROUCH = True

# Dimensões dos Obstáculos
TAMANHO_OBSTACULO_MIN = 20
TAMANHO_OBSTACULO_MAX = 74


# =========================================================
# RANKING LOCAL PERSISTENTE
# =========================================================
def normalizar_nome_jogador(nome):
    """Limpa o nome exibido e salvo sem impedir letras acentuadas."""
    nome_limpo = "".join(ch for ch in str(nome).strip() if ch.isalnum() or ch in "-_ ")
    return (nome_limpo[:12].strip() or "JOGADOR").upper()


class RankingPersistente:
    """Mantem o top 5 em JSON, inclusive entre execucoes do jogo."""

    def __init__(self, caminho=ARQUIVO_RANKING, limite=5):
        self.caminho = Path(caminho)
        self.limite = limite
        self.entradas = self._carregar()

    def _carregar(self):
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []

        if not isinstance(dados, list):
            return []

        entradas_validas = []
        for item in dados:
            if not isinstance(item, dict):
                continue
            try:
                pontos = max(0, int(item.get("pontos", 0)))
            except (TypeError, ValueError):
                continue
            dificuldade = str(item.get("dificuldade", "NORMAL")).upper()
            if dificuldade not in DIFICULDADES:
                dificuldade = "NORMAL"
            entradas_validas.append({
                "nome": normalizar_nome_jogador(item.get("nome", "JOGADOR")),
                "pontos": pontos,
                "dificuldade": dificuldade,
                "data": str(item.get("data", "")),
            })

        entradas_validas.sort(key=lambda item: item["pontos"], reverse=True)
        return entradas_validas[:self.limite]

    def registrar(self, nome, pontos, dificuldade):
        entrada = {
            "nome": normalizar_nome_jogador(nome),
            "pontos": max(0, int(pontos)),
            "dificuldade": dificuldade if dificuldade in DIFICULDADES else "NORMAL",
            "data": datetime.now().isoformat(timespec="seconds"),
        }
        candidatas = self.entradas + [entrada]
        candidatas.sort(key=lambda item: item["pontos"], reverse=True)
        self.entradas = candidatas[:self.limite]
        self._salvar()

        # Retorna a colocacao apenas se esta partida permaneceu no top 5.
        for indice, item in enumerate(self.entradas):
            if item is entrada:
                return indice + 1
        return None

    def _salvar(self):
        try:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            temporario = self.caminho.with_suffix(self.caminho.suffix + ".tmp")
            temporario.write_text(
                json.dumps(self.entradas, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporario, self.caminho)
        except OSError as exc:
            # Uma falha de escrita nao pode derrubar a partida.
            print(f"[RANKING] Nao foi possivel salvar {self.caminho}: {exc}")


# =========================================================
# CONTROLADOR DE ENTRADA (CAMERA + TECLADO + ESP32)
# =========================================================
class InputController:
    """
    Unifica teclado, camera e ESP32 sem acoplar essas fontes a VacaPlayer.
    """
    def __init__(self):
        self.jump_event = False    # True quando detecta impulso de salto
        self.lane_shift_event = 0  # -1 esquerda | +1 direita
        self.target_lane_event = None
        self.is_crouching = False
        self.last_control_source = "teclado"
        self._event_lock = threading.Lock()
        self._crouch_sources = {"keyboard": False, "vision": False, "esp32": False}
        self.vision_recalibrate_callback = None

        # Telemetria para Debug
        self.raw_ax = 0.0
        self.raw_ay = 0.0
        self.raw_az = 1.0          # Aceleração Vertical Z (gravidade ~1.0 G em repouso)
        self.sensor_base_ax = 0.0
        self.sensor_base_ay = 0.0
        self.sensor_base_az = 1.0
        self.sensor_lateral = 0.0
        self.sensor_frontal = 0.0
        self.sensor_crouching = False
        self.sensor_lane_armed = True
        self.sensor_lane_threshold = 0.30
        self.sensor_lane_neutral = 0.14
        self.sensor_crouch_until = 0.0

        self.active_port_name = "Nenhuma"
        self.show_debug = False    # [TAB] exibe telemetria sem cobrir a pista
        self.show_camera = True    # [V] alterna a pre-visualizacao da webcam

        # Variáveis para integração com ESP32
        self.esp32_connected = False
        self.esp32_thread = None
        self.esp32_running = False
        self.esp32_port = "auto"
        self.esp32_baudrate = 115200

        # Calibração e Filtro Dinâmico Vertical de Pulo
        self.jump_trigger_thresh = 0.32    # Gs dinâmicos acima de 1G para disparar pulo
        self.jump_cooldown = 0.40          # Cooldown de 400ms entre pulos
        self.last_jump_time = 0.0

        # Supressão de Desaceleração / Anti-Rebote de Pouso
        self.jump_lockout_until = 0.0      # Bloqueia repetições falsas durante o pouso

        self.gravity_vert = 1.0            # Linha de base da gravidade vertical em repouso
        self.dynamic_vert = 0.0            # Aceleração puramente dinâmica vertical
        self.peak_jump = 0.0               # Rastreia o pico dinâmico recente

        self.last_packet_time = 0.0
        self.wifi_thread = None

        self.feedback_msg = ""             # Mensagem de notificação na tela
        self.feedback_timer = 0.0          # Timer para apagar a notificação

        # Debounce do teclado
        self.prev_k_up = False
        self.prev_k_left = False
        self.prev_k_right = False
        self.prev_k_c = False
        self.prev_k_plus = False
        self.prev_k_minus = False

    def trigger_jump(self, source="entrada"):
        """Publica um pulo de forma segura a partir de qualquer thread."""
        with self._event_lock:
            self.jump_event = True
            self.last_control_source = source

    def consume_jump(self):
        with self._event_lock:
            event = self.jump_event
            self.jump_event = False
            return event

    def request_lane_shift(self, direction, source="entrada"):
        with self._event_lock:
            self.lane_shift_event = -1 if direction < 0 else 1
            self.last_control_source = source

    def request_target_lane(self, lane, source="entrada"):
        with self._event_lock:
            self.target_lane_event = max(0, min(NUM_LANES - 1, int(lane)))
            self.last_control_source = source

    def consume_lane_commands(self):
        with self._event_lock:
            target = self.target_lane_event
            shift = self.lane_shift_event
            self.target_lane_event = None
            self.lane_shift_event = 0
            return target, shift

    def set_crouching(self, source, active):
        with self._event_lock:
            self._crouch_sources[source] = bool(active)
            self.is_crouching = any(self._crouch_sources.values()) if ENABLE_CROUCH else False
            if active:
                self.last_control_source = source

    def calibrate_center(self):
        """Zera o ESP32 e solicita uma nova tara da posicao corporal."""
        val_vert = self.raw_az if abs(self.raw_az) > 0.6 else self.raw_ay
        self.gravity_vert = val_vert
        self.dynamic_vert = 0.0
        self.sensor_base_ax = self.raw_ax
        self.sensor_base_ay = self.raw_ay
        self.sensor_base_az = self.raw_az
        self.sensor_lateral = 0.0
        self.sensor_frontal = 0.0
        self.sensor_lane_armed = True
        self.sensor_crouching = False
        self.sensor_crouch_until = 0.0
        self.set_crouching("esp32", False)
        if self.vision_recalibrate_callback:
            self.vision_recalibrate_callback()
        self.feedback_msg = "● RECALIBRANDO CAMERA E SENSOR..."
        self.feedback_timer = time.time() + 2.5
        print(f"[CALIBRAÇÃO] Gravidade base: {self.gravity_vert:+.3f} G; camera recalibrada")

    def adjust_sensitivity(self, delta):
        """Ajusta o limiar de pulo em tempo real."""
        self.jump_trigger_thresh = max(0.18, min(0.65, round(self.jump_trigger_thresh + delta, 2)))
        self.feedback_msg = f"SENSIBILIDADE PULO: ±{self.jump_trigger_thresh:.2f} G"
        self.feedback_timer = time.time() + 2.0
        print(f"[SENSIBILIDADE] Limiar de pulo ajustado para ±{self.jump_trigger_thresh:.2f} G")

    def update_from_keyboard(self, keys):
        """Teclado continua disponivel como fallback e para testes."""
        k_up = keys[pygame.K_UP] or keys[pygame.K_w] or keys[pygame.K_SPACE]

        # Pulo no teclado (disparo único por clique)
        if k_up and not self.prev_k_up:
            self.trigger_jump("teclado")
        self.prev_k_up = k_up

        k_left = keys[pygame.K_LEFT] or keys[pygame.K_a]
        k_right = keys[pygame.K_RIGHT] or keys[pygame.K_d]
        if k_left and not self.prev_k_left:
            self.request_lane_shift(-1, "teclado")
        elif k_right and not self.prev_k_right:
            self.request_lane_shift(1, "teclado")
        self.prev_k_left = k_left
        self.prev_k_right = k_right

        k_down = keys[pygame.K_DOWN] or keys[pygame.K_s] or keys[pygame.K_LSHIFT]
        self.set_crouching("keyboard", k_down)

        # Tecla [C] para Calibrar Centro da Cintura
        k_c = keys[pygame.K_c]
        if k_c and not self.prev_k_c:
            self.calibrate_center()
        self.prev_k_c = k_c

        # Teclas [+] e [-] para Ajuste Fino de Sensibilidade
        k_plus = keys[pygame.K_PLUS] or keys[pygame.K_KP_PLUS] or keys[pygame.K_EQUALS]
        k_minus = keys[pygame.K_MINUS] or keys[pygame.K_KP_MINUS]
        if k_plus and not self.prev_k_plus:
            self.adjust_sensitivity(-0.02)
        elif k_minus and not self.prev_k_minus:
            self.adjust_sensitivity(+0.02)
        self.prev_k_plus = k_plus
        self.prev_k_minus = k_minus

    def start_esp32_connection(self, port="auto", baudrate=115200):
        """Inicia a escuta sem fio via Wi-Fi UDP e USB Serial simultaneamente."""
        self.esp32_port = port
        self.esp32_baudrate = baudrate
        self.esp32_running = True

        # 1. Thread Wi-Fi UDP (Ultra rápida < 2ms)
        self.wifi_thread = threading.Thread(target=self._wifi_worker, daemon=True)
        self.wifi_thread.start()

        # 2. Thread USB Serial (Fallback)
        self.esp32_thread = threading.Thread(target=self._esp32_worker, daemon=True)
        self.esp32_thread.start()

    def _process_sensor_line(self, linha, source_name="ESP32"):
        """Transforma aceleracao em pulo, agachamento e troca de faixa."""
        partes = [p.strip() for p in linha.split(',') if p.strip()]
        if len(partes) >= 1:
            try:
                if len(partes) == 1:
                    az = float(partes[0])
                    ax, ay = 0.0, 0.0
                    pacote_completo = False
                elif len(partes) >= 3:
                    ax = float(partes[0])
                    ay = float(partes[1])
                    az = float(partes[2])
                    pacote_completo = True
                else:
                    az = float(partes[0])
                    ax, ay = 0.0, 0.0
                    pacote_completo = False

                self.raw_ax = ax
                self.raw_ay = ay
                self.raw_az = az

                self.esp32_connected = True
                self.active_port_name = source_name
                self.last_packet_time = time.time()

                # Eixo vertical predominante (Z padrão, ou Y se o sensor estiver de lado)
                val_vert = az if abs(az) >= abs(ay) else ay

                # Filtro Passa-Alta vertical
                self.gravity_vert = 0.95 * self.gravity_vert + 0.05 * val_vert
                self.dynamic_vert = val_vert - self.gravity_vert
                self.peak_jump = max(self.peak_jump * 0.96, abs(self.dynamic_vert))

                agora = time.time()

                # O MPU6050 preso a cintura agora tambem funciona como manche:
                # inclinar para os lados troca de faixa; inclinar para frente
                # mantem a vaca agachada. A histerese impede repeticoes.
                if pacote_completo:
                    self.sensor_lateral = ax - self.sensor_base_ax
                    self.sensor_frontal = ay - self.sensor_base_ay

                    if abs(self.sensor_lateral) <= self.sensor_lane_neutral:
                        self.sensor_lane_armed = True
                    elif self.sensor_lane_armed and abs(self.sensor_lateral) >= self.sensor_lane_threshold:
                        self.request_lane_shift(-1 if self.sensor_lateral < 0 else 1, "esp32")
                        self.sensor_lane_armed = False

                    inclinacao_agachar = (
                        abs(self.sensor_frontal) >= 0.34
                        and abs(az) <= max(0.86, abs(self.sensor_base_az) * 0.88)
                    )
                    impulso_agachar = self.dynamic_vert <= -0.28
                    if inclinacao_agachar or impulso_agachar:
                        self.sensor_crouch_until = agora + 0.32
                    self.sensor_crouching = inclinacao_agachar or agora < self.sensor_crouch_until
                    self.set_crouching("esp32", self.sensor_crouching)

                # Detecção de PULO (Impulso Vertical Positivo do Salto)
                # Só dispara se não estiver no ar ou aterrissando de um pulo (jump_lockout_until)
                pode_pular = (agora >= self.jump_lockout_until)

                if pode_pular and (self.dynamic_vert > self.jump_trigger_thresh) and (agora - self.last_jump_time >= self.jump_cooldown):
                    self.trigger_jump("esp32")
                    self.last_jump_time = agora
                    # Bloqueia rebote de aterrissagem durante todo o salto e pouso (600ms)
                    self.jump_lockout_until = agora + 0.60

            except ValueError:
                pass

    def _wifi_worker(self):
        """Escuta pacotes de acelerômetro transmitidos via Wi-Fi UDP Broadcast (Porta 4210)."""
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", 4210))
            sock.settimeout(0.5)
            print("[WI-FI] Receptor UDP iniciado na porta 4210...")
        except Exception as e:
            print(f"[WI-FI] Aviso: Porta 4210: {e}")
            return

        while self.esp32_running:
            try:
                data, addr = sock.recvfrom(1024)
                if data:
                    linha = data.decode('utf-8', errors='ignore').strip()
                    if linha:
                        self._process_sensor_line(linha, source_name=f"Wi-Fi [{addr[0]}]")
            except socket.timeout:
                if self.active_port_name.startswith("Wi-Fi") and (time.time() - self.last_packet_time > 2.5):
                    self.esp32_connected = False
                    self.active_port_name = "Procurando Wi-Fi..."
                    self.sensor_crouching = False
                    self.set_crouching("esp32", False)
            except Exception:
                time.sleep(0.05)

    def _get_candidate_ports(self):
        """Retorna uma lista de portas seriais USB válidas."""
        candidatas = []
        blacklist = ["incoming-port", "wlan-debug", "debug-console", "airpods", "headset", "iphone", "watch", "soc"]

        try:
            import glob
            devs = glob.glob('/dev/cu.*')
            for d in devs:
                d_low = d.lower()
                if any(b in d_low for b in blacklist):
                    continue
                if any(k in d_low for k in ["esp32", "cow", "usbserial", "wchusbserial", "slab_usbtouart", "usbmodem", "cp210", "ch340", "ftdi"]):
                    if d not in candidatas:
                        candidatas.append(d)
        except Exception as e:
            print(f"[DEBUG] Erro scan glob: {e}")

        return candidatas

    def _esp32_worker(self):
        """Thread para conexão com ESP32 via Cabo USB Serial."""
        try:
            import serial
        except ImportError:
            return

        while self.esp32_running:
            if self.esp32_connected and self.active_port_name.startswith("Wi-Fi"):
                time.sleep(1.0)
                continue

            if self.esp32_port and self.esp32_port != "auto":
                portas = [self.esp32_port]
            else:
                portas = self._get_candidate_ports()

            if not portas:
                if not self.esp32_connected:
                    self.active_port_name = "Aguardando Wi-Fi ou USB..."
                time.sleep(1.0)
                continue

            conectado = False
            for target_port in portas:
                if not self.esp32_running or (self.esp32_connected and self.active_port_name.startswith("Wi-Fi")):
                    break
                try:
                    with serial.Serial(target_port, self.esp32_baudrate, timeout=1.0) as ser:
                        while self.esp32_running:
                            if self.esp32_connected and self.active_port_name.startswith("Wi-Fi"):
                                break
                            try:
                                if ser.in_waiting > 120:
                                    ser.reset_input_buffer()
                            except Exception:
                                pass

                            linha = ser.readline().decode('utf-8', errors='ignore').strip()
                            if linha:
                                self._process_sensor_line(linha, source_name=f"USB ({target_port.split('/')[-1]})")
                                conectado = True
                except Exception:
                    continue

            if not conectado and not self.esp32_connected:
                time.sleep(1.0)


# =========================================================
# CARREGAMENTO E ALINHAMENTO PRECISO DOS SPRITES DA VACA
# =========================================================
def carregar_asset(candidatos, com_alpha=False):
    """Busca a imagem entre vários caminhos possíveis para evitar erros de arquivo não encontrado."""
    import os
    for caminho in candidatos:
        if os.path.exists(caminho):
            try:
                img = pygame.image.load(caminho)
                return img.convert_alpha() if com_alpha else img.convert()
            except Exception as e:
                print(f"[DEBUG] Erro ao carregar {caminho}: {e}")
    # Cria uma superfície reserva segura
    surf = pygame.Surface((1280, 720), pygame.SRCALPHA if com_alpha else 0)
    surf.fill((30, 20, 50))
    return surf


def carregar_sprites_vaca():
    """
    Carrega a sprite sheet 'Imagens/sprite1.png' com recorte exato
    das 6 poses, centralizando o centro de massa e alinhando os pés.
    """
    sprite_sheet = carregar_asset(["Imagens/sprite1.png", "sprite1.png"], com_alpha=True)

    boxes_andar = [
        (33, 77, 297, 748),
        (374, 77, 356, 748),
        (720, 77, 292, 748),
    ]
    boxes_agachar = [
        (33, 825, 297, 627),
        (374, 825, 356, 627),
        (720, 825, 292, 627),
    ]

    frames_andar = []
    frames_agachar = []

    for x, y, w, h in boxes_andar:
        sub = sprite_sheet.subsurface(pygame.Rect(x, y, w, h))
        canvas = pygame.Surface((360, 750), pygame.SRCALPHA)
        dest_x = (360 - w) // 2
        dest_y = 750 - h
        canvas.blit(sub, (dest_x, dest_y))
        scaled = pygame.transform.smoothscale(canvas, (LARGURA_VACA_NORMAL, ALTURA_VACA_NORMAL))
        frames_andar.append(scaled)

    for x, y, w, h in boxes_agachar:
        sub = sprite_sheet.subsurface(pygame.Rect(x, y, w, h))
        canvas = pygame.Surface((360, 750), pygame.SRCALPHA)
        dest_x = (360 - w) // 2
        dest_y = 750 - h
        canvas.blit(sub, (dest_x, dest_y))
        # O frame agachado precisa ser realmente baixo; antes ele era escalado
        # quase como a pose em pe e nao correspondia a hitbox reduzida.
        scaled = pygame.transform.smoothscale(canvas, (LARGURA_VACA_AGACHADA, ALTURA_VACA_AGACHADA))
        frames_agachar.append(scaled)

    return frames_andar, frames_agachar


# =========================================================
# FUNÇÕES DE PERSPECTIVA E CURVATURA DOS ANÉIS DE SATURNO
# =========================================================
def calcular_posicao_pista(progresso_y, lane_ratio=0.50):
    """
    Calcula a posição (x, y) e o tamanho do obstáculo seguindo
    a curvatura e perspectiva dos anéis de Saturno no lado direito.
    """
    y = HORIZON_Y + progresso_y * (BASE_Y - HORIZON_Y + 120)

    t = max(0.0, min(1.2, progresso_y))
    t_profundidade = t ** 1.3

    largura_atual = HORIZON_LARGURA + (BASE_LARGURA - HORIZON_LARGURA) * t_profundidade
    curvatura_offset = math.sin(t * math.pi) * 35.0
    centro_x = HORIZON_CENTER_X + (BASE_CENTER_X - HORIZON_CENTER_X) * t + curvatura_offset

    x = (centro_x - largura_atual / 2.0) + lane_ratio * largura_atual

    tamanho = int(TAMANHO_OBSTACULO_MIN + (TAMANHO_OBSTACULO_MAX - TAMANHO_OBSTACULO_MIN) * t_profundidade)
    if tamanho < TAMANHO_OBSTACULO_MIN:
        tamanho = TAMANHO_OBSTACULO_MIN

    return x, y, tamanho


def criar_obstaculo(velocidade_base=1.0):
    """Gera obstaculo em uma faixa: caixa para pular ou barreira para agachar."""
    lane_idx = random.randrange(NUM_LANES)
    return {
        'tipo': 'alto' if random.random() < 0.28 else 'chao',
        'lane_idx': lane_idx,
        'lane': LANE_RATIOS[lane_idx],
        'progresso_y': PROGRESSO_SPAWN,
        'velocidade': random.uniform(0.010, 0.016) * velocidade_base,
    }


def carregar_assets_obstaculos():
    """Carrega sprites legiveis e mantem os assets antigos como fallback."""
    return {
        'chao': carregar_asset([
            "Imagens/obstaculos/caixa_energia.png",
            "caixa.png",
        ], com_alpha=True),
        'alto': carregar_asset([
            "Imagens/obstaculos/portal_agachar.png",
            "p_atras.png",
        ], com_alpha=True),
    }


def calcular_rect_obstaculo(obs):
    """Retorna o retangulo visual do sprite respeitando a perspectiva."""
    cx, cy, tamanho = calcular_posicao_pista(obs['progresso_y'], obs['lane'])
    if obs['tipo'] == 'chao':
        largura = max(8, int(tamanho * 1.18))
        altura = largura
    else:
        largura = max(12, int(tamanho * 1.80))
        altura = max(16, int(tamanho * 2.00))
    rect = pygame.Rect(0, 0, largura, altura)
    rect.midbottom = (int(cx), int(cy))
    return rect, cx, cy, tamanho


def calcular_hitbox_obstaculo(obs):
    """Hitboxes alinhadas ao volume da caixa ou ao feixe do portal."""
    rect, cx, cy, tamanho = calcular_rect_obstaculo(obs)
    if obs['tipo'] == 'chao':
        return pygame.Rect(
            rect.x + rect.width * 0.12,
            rect.y + rect.height * 0.16,
            rect.width * 0.76,
            rect.height * 0.76,
        )

    # O feixe fica no quarto superior do sprite; a passagem inferior fica livre.
    return pygame.Rect(
        cx - tamanho * 0.70,
        cy - tamanho * 1.62,
        tamanho * 1.40,
        tamanho * 0.38,
    )


def desenhar_guias_faixas(canvas):
    """Desenha limites discretos para as tres faixas sobre os aneis."""
    overlay = pygame.Surface((LARGURA_VIRTUAL, ALTURA_VIRTUAL), pygame.SRCALPHA)

    # Bordas externas douradas e divisorias ciano tracejadas.
    for ratio, cor in ((0.04, (255, 211, 95, 105)), (0.96, (255, 211, 95, 105))):
        pontos = [calcular_posicao_pista(i / 24, ratio)[:2] for i in range(3, 23)]
        pygame.draw.aalines(overlay, cor, False, pontos)

    for ratio in (0.34, 0.66):
        for i in range(3, 22, 2):
            p1 = calcular_posicao_pista(i / 24, ratio)
            p2 = calcular_posicao_pista((i + 1) / 24, ratio)
            largura = max(1, int(1 + i / 10))
            pygame.draw.line(overlay, (80, 225, 255, 120), p1[:2], p2[:2], largura)

    canvas.blit(overlay, (0, 0))


def desenhar_obstaculo(canvas, obs, imagens_obstaculos):
    """Renderiza o sprite gerado em vez de formas brancas provisórias."""
    rect, _, _, tamanho = calcular_rect_obstaculo(obs)
    imagem = imagens_obstaculos[obs['tipo']]

    if obs['tipo'] == 'chao':
        sombra = pygame.Surface((rect.width, max(4, int(tamanho * 0.25))), pygame.SRCALPHA)
        pygame.draw.ellipse(sombra, (5, 8, 18, 115), sombra.get_rect())
        canvas.blit(sombra, (rect.x, rect.bottom - sombra.get_height() // 2))

    sprite = pygame.transform.smoothscale(imagem, rect.size)
    canvas.blit(sprite, rect)


def desenhar_icone_dificuldade(canvas, dificuldade, centro, tamanho=18):
    """Pequenos desenhos pixel-art usados no menu e no HUD."""
    cx, cy = centro
    cor = DIFICULDADES[dificuldade]["cor"]
    contorno = (35, 40, 58)

    if dificuldade == "FACIL":
        pygame.draw.circle(canvas, contorno, (cx, cy), tamanho + 2)
        pygame.draw.circle(canvas, cor, (cx, cy), tamanho)
        pygame.draw.circle(canvas, (36, 145, 112), (cx - 6, cy - 4), max(3, tamanho // 4))
        pygame.draw.circle(canvas, (170, 255, 205), (cx + 5, cy + 5), max(2, tamanho // 5))
    elif dificuldade == "NORMAL":
        pontos = []
        for indice in range(10):
            raio = tamanho if indice % 2 == 0 else tamanho * 0.44
            angulo = -math.pi / 2 + indice * math.pi / 5
            pontos.append((cx + math.cos(angulo) * raio, cy + math.sin(angulo) * raio))
        pygame.draw.polygon(canvas, contorno, pontos)
        internos = [
            (cx + (x - cx) * 0.78, cy + (y - cy) * 0.78)
            for x, y in pontos
        ]
        pygame.draw.polygon(canvas, cor, internos)
    else:
        pontos = [
            (cx - tamanho, cy - 3), (cx - 9, cy - tamanho),
            (cx + 8, cy - tamanho + 3), (cx + tamanho, cy + 2),
            (cx + 7, cy + tamanho), (cx - 12, cy + tamanho - 4),
        ]
        pygame.draw.polygon(canvas, contorno, pontos)
        internos = [
            (cx + (x - cx) * 0.82, cy + (y - cy) * 0.82)
            for x, y in pontos
        ]
        pygame.draw.polygon(canvas, cor, internos)
        pygame.draw.circle(canvas, (170, 65, 75), (cx - 5, cy - 2), max(2, tamanho // 4))
        pygame.draw.circle(canvas, (255, 155, 120), (cx + 7, cy + 6), max(2, tamanho // 5))


def desenhar_ranking(canvas, ranking, destaque_posicao=None):
    """Preenche o quadro de ranking que ja faz parte da arte do menu."""
    fonte_nome = pygame.font.SysFont("Arial", 19, bold=True)
    fonte_pontos = pygame.font.SysFont("Arial", 18, bold=True)
    fonte_vazio = pygame.font.SysFont("Arial", 17, italic=True)
    cores_medalha = [(255, 199, 62), (190, 205, 220), (206, 132, 80)]

    painel = pygame.Rect(758, 151, 300, 458)
    for indice in range(ranking.limite):
        y = painel.y + indice * 82
        preenchimento = (255, 250, 205, 205) if destaque_posicao == indice + 1 else (245, 247, 250, 178)
        linha = pygame.Surface((painel.width, 68), pygame.SRCALPHA)
        linha.fill(preenchimento)
        pygame.draw.rect(linha, (95, 104, 118, 210), linha.get_rect(), 2, border_radius=7)
        canvas.blit(linha, (painel.x, y))

        medalha_cor = cores_medalha[indice] if indice < 3 else (135, 145, 160)
        pygame.draw.circle(canvas, (70, 75, 86), (painel.x + 26, y + 34), 20)
        pygame.draw.circle(canvas, medalha_cor, (painel.x + 26, y + 34), 16)
        numero = fonte_pontos.render(str(indice + 1), True, (38, 42, 52))
        canvas.blit(numero, numero.get_rect(center=(painel.x + 26, y + 34)))

        if indice < len(ranking.entradas):
            entrada = ranking.entradas[indice]
            nome = fonte_nome.render(entrada["nome"], True, (35, 40, 52))
            pontos = fonte_pontos.render(f'{entrada["pontos"]} PTS', True, (45, 50, 62))
            nivel = DIFICULDADES[entrada["dificuldade"]]
            modo = pygame.font.SysFont("Arial", 12, bold=True).render(
                nivel["nome"], True, nivel["cor"]
            )
            canvas.blit(nome, (painel.x + 56, y + 10))
            canvas.blit(pontos, (painel.right - pontos.get_width() - 12, y + 35))
            modo_bg = pygame.Rect(painel.x + 56, y + 39, modo.get_width() + 12, 20)
            pygame.draw.rect(canvas, (50, 55, 68), modo_bg, border_radius=9)
            canvas.blit(modo, (modo_bg.x + 6, modo_bg.y + 3))
        else:
            vazio = fonte_vazio.render("ESPAÇO LIVRE", True, (118, 124, 136))
            canvas.blit(vazio, (painel.x + 60, y + 24))


def desenhar_seletor_dificuldade(canvas, dificuldade_atual):
    fonte_titulo = pygame.font.SysFont("Arial", 17, bold=True)
    fonte_opcao = pygame.font.SysFont("Arial", 15, bold=True)
    titulo = fonte_titulo.render("DIFICULDADE  [1] [2] [3]", True, (230, 245, 255))
    canvas.blit(titulo, (72, 396))

    rects = []
    for indice, chave in enumerate(ORDEM_DIFICULDADES):
        rect = pygame.Rect(62 + indice * 153, 422, 143, 58)
        rects.append(rect)
        ativa = chave == dificuldade_atual
        bg = (29, 42, 61) if not ativa else (48, 62, 78)
        borda = DIFICULDADES[chave]["cor"] if ativa else (95, 112, 132)
        pygame.draw.rect(canvas, bg, rect, border_radius=9)
        pygame.draw.rect(canvas, borda, rect, 3 if ativa else 1, border_radius=9)
        desenhar_icone_dificuldade(canvas, chave, (rect.x + 26, rect.centery), 14)
        texto = fonte_opcao.render(DIFICULDADES[chave]["nome"], True, borda)
        canvas.blit(texto, (rect.x + 48, rect.y + 19))
    return rects


def desenhar_indicador_sensor(canvas, posicao, ativo):
    """Desenha uma pequena cinta/sensor com ondas de conexao."""
    x, y = posicao
    cor = (75, 255, 145) if ativo else (145, 155, 175)
    pygame.draw.rect(canvas, (28, 34, 48), (x, y + 7, 28, 14), border_radius=5)
    pygame.draw.rect(canvas, cor, (x + 8, y + 3, 12, 22), 2, border_radius=3)
    if ativo:
        pygame.draw.arc(canvas, cor, (x + 24, y + 3, 18, 20), -1.0, 1.0, 2)
        pygame.draw.arc(canvas, cor, (x + 27, y, 25, 26), -1.0, 1.0, 2)


# =========================================================
# CLASSE DA VACA (PLAYER COM SISTEMA DE PULO)
# =========================================================
class VacaPlayer:
    def __init__(self, frames_andar, frames_agachar):
        self.frames_andar = frames_andar
        self.frames_agachar = frames_agachar

        # Comeca na faixa central e desliza suavemente entre as tres faixas.
        self.current_lane = 1
        self.target_x = self._calcular_x_da_faixa(self.current_lane)
        self.x = self.target_x
        self.y_base = BASE_Y
        self.is_moving = False

        # Física de Salto (Pulo)
        self.is_jumping = False
        self.jump_y = 0.0          # Deslocamento vertical negativo no ar
        self.vel_y = 0.0           # Velocidade vertical
        self.gravidade = 0.95      # Gravidade do pulo
        self.forca_pulo = -18.0    # Força inicial do salto
        self.is_crouching = False

        self.frame_index = 0.0
        self.anim_speed = 0.22

    def _calcular_x_da_faixa(self, lane_idx):
        cx, _, _ = calcular_posicao_pista(1.0, LANE_RATIOS[lane_idx])
        return cx - (LARGURA_VACA_NORMAL / 2.0)

    def update(self, input_ctrl):
        # 1. Camera envia a faixa absoluta; teclado/ESP32 podem enviar um passo.
        target_lane, shift = input_ctrl.consume_lane_commands()
        if target_lane is not None:
            self.current_lane = target_lane
        elif shift:
            self.current_lane = max(0, min(NUM_LANES - 1, self.current_lane + shift))
        self.target_x = self._calcular_x_da_faixa(self.current_lane)

        diff_x = self.target_x - self.x
        if abs(diff_x) > 1.2:
            self.x += diff_x * 0.26
            self.is_moving = True
        else:
            self.x = self.target_x
            self.is_moving = False

        # 2. Trata comando de PULO
        if input_ctrl.consume_jump() and not self.is_jumping:
            self.is_jumping = True
            self.vel_y = self.forca_pulo

        # 3. Física do Pulo no ar
        if self.is_jumping:
            self.jump_y += self.vel_y
            self.vel_y += self.gravidade
            # Aterrissagem no chão
            if self.jump_y >= 0.0:
                self.jump_y = 0.0
                self.is_jumping = False
                self.vel_y = 0.0

        # Agachamento e pulo sao mutuamente exclusivos na representacao.
        self.is_crouching = input_ctrl.is_crouching and not self.is_jumping

        # 4. Controle de animação
        self.frame_index = (self.frame_index + self.anim_speed) % len(self.frames_andar)

    def get_hitbox(self):
        """Retorna a hitbox ajustada para o pulo."""
        if self.is_jumping:
            # Hitbox no ar (deslocada para cima pelo jump_y)
            hb_w = LARGURA_VACA_NORMAL * 0.60
            hb_h = ALTURA_VACA_NORMAL * 0.65
            hb_x = self.x + (LARGURA_VACA_NORMAL - hb_w) / 2
            hb_y = self.y_base - ALTURA_VACA_NORMAL + 20 + self.jump_y
            return pygame.Rect(hb_x, hb_y, hb_w, hb_h)
        elif self.is_crouching:
            hb_w = LARGURA_VACA_AGACHADA * 0.68
            hb_h = ALTURA_VACA_AGACHADA * 0.58
            hb_x = self.x + (LARGURA_VACA_AGACHADA - hb_w) / 2
            hb_y = self.y_base - hb_h
            return pygame.Rect(hb_x, hb_y, hb_w, hb_h)
        else:
            # Hitbox normal em pé
            hb_w = LARGURA_VACA_NORMAL * 0.60
            hb_h = ALTURA_VACA_NORMAL * 0.75
            hb_x = self.x + (LARGURA_VACA_NORMAL - hb_w) / 2
            hb_y = self.y_base - hb_h
            return pygame.Rect(hb_x, hb_y, hb_w, hb_h)

    def draw(self, surface):
        # 1. Sombra no chão (diminui de tamanho quando a vaca pula alto)
        shadow_w = int(LARGURA_VACA_NORMAL * 0.75 * max(0.35, 1.0 - abs(self.jump_y) / 200.0))
        shadow_h = 16
        shadow_x = int(self.x + LARGURA_VACA_NORMAL / 2 - shadow_w / 2)
        shadow_y = int(self.y_base - 8)
        shadow_surf = pygame.Surface((shadow_w, shadow_h), pygame.SRCALPHA)
        shadow_alpha = int(140 * max(0.2, 1.0 - abs(self.jump_y) / 220.0))
        pygame.draw.ellipse(shadow_surf, (15, 15, 25, shadow_alpha), (0, 0, shadow_w, shadow_h))
        surface.blit(shadow_surf, (shadow_x, shadow_y))

        # 2. Desenho do Sprite da Vaca
        idx = int(self.frame_index) % 3
        if self.is_jumping:
            # Pose de salto no ar
            img = self.frames_andar[1]
            surface.blit(img, (self.x, self.y_base - ALTURA_VACA_NORMAL + self.jump_y))
        elif self.is_crouching:
            img = self.frames_agachar[idx]
            surface.blit(img, (self.x, self.y_base - img.get_height()))
        else:
            # Pose normal correndo
            img = self.frames_andar[idx]
            surface.blit(img, (self.x, self.y_base - ALTURA_VACA_NORMAL))


# =========================================================
# TELA CHEIA E GERENCIAMENTO DE RESOLUÇÃO (LETTERBOXING)
# =========================================================
class DisplayManager:
    """Gerencia a janela com proporção 16:9 perfeita em qualquer monitor."""
    def __init__(self):
        self.is_fullscreen = False
        self.real_screen = pygame.display.set_mode((LARGURA_VIRTUAL, ALTURA_VIRTUAL), pygame.RESIZABLE)
        pygame.display.set_caption("Cow Abduct - Visao Computacional (IFFar)")
        self.virtual_screen = pygame.Surface((LARGURA_VIRTUAL, ALTURA_VIRTUAL))

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            self.real_screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.real_screen = pygame.display.set_mode((LARGURA_VIRTUAL, ALTURA_VIRTUAL), pygame.RESIZABLE)

    def render(self):
        janela_w, janela_h = self.real_screen.get_size()
        escala = min(janela_w / LARGURA_VIRTUAL, janela_h / ALTURA_VIRTUAL)
        novo_w = int(LARGURA_VIRTUAL * escala)
        novo_h = int(ALTURA_VIRTUAL * escala)
        offset_x = (janela_w - novo_w) // 2
        offset_y = (janela_h - novo_h) // 2

        self.real_screen.fill((0, 0, 0))
        scaled = pygame.transform.smoothscale(self.virtual_screen, (novo_w, novo_h))
        self.real_screen.blit(scaled, (offset_x, offset_y))
        pygame.display.flip()

    def map_mouse_pos(self, mouse_pos):
        janela_w, janela_h = self.real_screen.get_size()
        escala = min(janela_w / LARGURA_VIRTUAL, janela_h / ALTURA_VIRTUAL)
        novo_w = int(LARGURA_VIRTUAL * escala)
        novo_h = int(ALTURA_VIRTUAL * escala)
        offset_x = (janela_w - novo_w) // 2
        offset_y = (janela_h - novo_h) // 2

        vx = (mouse_pos[0] - offset_x) / escala
        vy = (mouse_pos[1] - offset_y) / escala
        return vx, vy


# =========================================================
# TABELA / PAINEL DE DEBUG EM TEMPO REAL
# =========================================================
def desenhar_tabela_debug(canvas, input_ctrl, vision_ctrl, vaca=None, fps=60.0):
    """Renderiza telemetria da camera, dos gestos, do ESP32 e do player."""
    if not input_ctrl.show_debug:
        return

    painel_w, painel_h = 455, 378
    painel_x = LARGURA_VIRTUAL - painel_w - 20
    painel_y = 20

    painel_bg = pygame.Surface((painel_w, painel_h), pygame.SRCALPHA)
    painel_bg.fill((12, 16, 28, 230))
    pygame.draw.rect(painel_bg, (0, 180, 255), (0, 0, painel_w, painel_h), 2, border_radius=8)
    canvas.blit(painel_bg, (painel_x, painel_y))

    fonte_tit = pygame.font.SysFont("Courier New", 14, bold=True)
    fonte_txt = pygame.font.SysFont("Courier New", 13, bold=True)
    txt_tit = fonte_tit.render("== VISAO COMPUTACIONAL / CONTROLE ==", True, (255, 220, 80))
    canvas.blit(txt_tit, (painel_x + 15, painel_y + 10))
    pygame.draw.line(canvas, (0, 180, 255), (painel_x + 10, painel_y + 30), (painel_x + painel_w - 10, painel_y + 30), 1)

    camera_cor = (80, 255, 120) if vision_ctrl.connected and vision_ctrl.pose_visible else (255, 190, 80)
    esp_cor = (80, 255, 120) if input_ctrl.esp32_connected else (150, 160, 180)
    esp_status = input_ctrl.active_port_name if input_ctrl.esp32_connected else "fallback opcional"

    if vaca:
        if vaca.is_jumping:
            acao_str, acao_cor = "PULANDO NO AR", (100, 230, 255)
        elif vaca.is_crouching:
            acao_str, acao_cor = "AGACHADO", (255, 220, 80)
        else:
            acao_str, acao_cor = "CORRENDO NA PISTA", (80, 255, 120)
        lane_nome = NOME_LANES[vaca.current_lane]
    else:
        acao_str, acao_cor = "MENU INICIAL", (180, 180, 180)
        lane_nome = "CENTRO"

    linhas = [
        ("Camera:", vision_ctrl.status[:34], camera_cor),
        ("Detector:", vision_ctrl.engine, (100, 230, 255)),
        ("Gesto lido:", vision_ctrl.action, acao_cor),
        ("Mov. lateral:", f"{vision_ctrl.lateral:+.2f} troncos", (100, 230, 255)),
        ("Mov. vertical:", f"{vision_ctrl.vertical:+.2f} troncos", (255, 200, 80)),
        ("Faixa da vaca:", lane_nome, (255, 255, 100)),
        ("Estado da vaca:", acao_str, acao_cor),
        ("Ultima entrada:", input_ctrl.last_control_source.upper(), (200, 220, 255)),
        ("ESP32:", esp_status[:30], esp_cor),
        ("Sensor lateral:", f"{input_ctrl.sensor_lateral:+.2f} G", (120, 235, 255)),
        ("Sensor postura:", "AGACHADO" if input_ctrl.sensor_crouching else "EM PE", esp_cor),
        ("FPS jogo/camera:", f"{fps:.0f} / {vision_ctrl.fps:.0f}", (180, 220, 255)),
    ]

    curr_y = painel_y + 38
    for label, val, cor in linhas:
        t_lbl = fonte_txt.render(label, True, (160, 180, 210))
        t_val = fonte_txt.render(val, True, cor)
        canvas.blit(t_lbl, (painel_x + 15, curr_y))
        canvas.blit(t_val, (painel_x + 160, curr_y))
        curr_y += 24

    t_dica = fonte_tit.render("[C] Recalibrar | [V] Camera | [TAB] Painel", True, (120, 145, 175))
    canvas.blit(t_dica, (painel_x + 15, painel_y + painel_h - 22))

    if time.time() < input_ctrl.feedback_timer and input_ctrl.feedback_msg:
        fonte_pop = pygame.font.SysFont("Arial", 22, bold=True)
        t_pop = fonte_pop.render(input_ctrl.feedback_msg, True, (255, 255, 100))
        pop_w = t_pop.get_width() + 30
        pop_h = 44
        pop_x = (LARGURA_VIRTUAL - pop_w) // 2
        pop_y = 35
        pop_bg = pygame.Surface((pop_w, pop_h), pygame.SRCALPHA)
        pop_bg.fill((20, 30, 50, 235))
        pygame.draw.rect(pop_bg, (0, 220, 255), (0, 0, pop_w, pop_h), 2, border_radius=8)
        canvas.blit(pop_bg, (pop_x, pop_y))
        canvas.blit(t_pop, (pop_x + 15, pop_y + 8))


def desenhar_preview_camera(canvas, input_ctrl, vision_ctrl, posicao=(20, 445), tamanho=None):
    """Mostra a camera dentro do jogo, sem abrir uma segunda janela."""
    if not input_ctrl.show_camera:
        return

    preview = vision_ctrl.get_preview()
    x, y = posicao
    width, height = tamanho or vision_ctrl.PREVIEW_SIZE
    pygame.draw.rect(canvas, (10, 16, 28), (x - 5, y - 31, width + 10, height + 36), border_radius=8)
    pygame.draw.rect(canvas, (0, 210, 255), (x - 5, y - 31, width + 10, height + 36), 2, border_radius=8)

    fonte = pygame.font.SysFont("Arial", 16, bold=True)
    titulo = fonte.render("CAMERA IA  |  [V] ocultar", True, (220, 245, 255))
    canvas.blit(titulo, (x + 5, y - 25))

    if preview:
        frame_bytes, size = preview
        surface = pygame.image.frombuffer(frame_bytes, size, "RGB")
        if surface.get_size() != (width, height):
            surface = pygame.transform.smoothscale(surface, (width, height))
        canvas.blit(surface, (x, y))
    else:
        pygame.draw.rect(canvas, (22, 28, 42), (x, y, width, height))
        mensagem = fonte.render(vision_ctrl.status[:35], True, (255, 210, 100))
        canvas.blit(mensagem, (x + 12, y + height // 2 - 8))


# =========================================================
# TELA INICIAL
# =========================================================
def tela_inicial(
    display_mgr,
    input_ctrl,
    vision_ctrl,
    ranking,
    nome_jogador="JOGADOR",
    dificuldade_atual="NORMAL",
):
    fundo = carregar_asset([
        "Imagens/fundo_inicio.png",
        "Imagens/fundo_inicio1.png",
        "Imagens/fundo_inicio1.jpg",
        "Imagens/fundo_jogo/caminho.png",
        "Imagens/caminho.png"
    ])
    fundo = pygame.transform.scale(fundo, (LARGURA_VIRTUAL, ALTURA_VIRTUAL))

    botao = carregar_asset(["Imagens/botao_inicio.png", "Imagens/botao_inicio1.png"], com_alpha=True)
    botao = pygame.transform.scale(botao, (250, 90))
    botao_rect = botao.get_rect(center=(int(LARGURA_VIRTUAL // 4.4), 593))

    fonte_dica = pygame.font.SysFont("Arial", 22, bold=True)
    fonte_ctrl = pygame.font.SysFont("Arial", 20)
    fonte_nome = pygame.font.SysFont("Arial", 20, bold=True)
    fonte_nome_dica = pygame.font.SysFont("Arial", 13)
    clock = pygame.time.Clock()
    nome_digitado = normalizar_nome_jogador(nome_jogador)
    editando_nome = False
    nome_rect = pygame.Rect(62, 493, 448, 45)
    dificuldade_rects = [pygame.Rect(62 + i * 153, 422, 143, 58) for i in range(3)]

    esperando = True
    while esperando:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            if event.type == pygame.KEYDOWN and editando_nome:
                if event.key == pygame.K_RETURN:
                    editando_nome = False
                elif event.key == pygame.K_ESCAPE:
                    editando_nome = False
                elif event.key == pygame.K_BACKSPACE:
                    nome_digitado = nome_digitado[:-1]
                elif event.unicode and event.unicode.isprintable() and len(nome_digitado) < 12:
                    candidato = normalizar_nome_jogador(nome_digitado + event.unicode)
                    nome_digitado = "" if candidato == "JOGADOR" and not nome_digitado and event.unicode.isspace() else candidato
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_f or event.key == pygame.K_F11:
                    display_mgr.toggle_fullscreen()
                elif event.key == pygame.K_TAB:
                    input_ctrl.show_debug = not input_ctrl.show_debug
                elif event.key == pygame.K_v:
                    input_ctrl.show_camera = not input_ctrl.show_camera
                elif event.key == pygame.K_c:
                    input_ctrl.calibrate_center()
                elif event.key in (pygame.K_1, pygame.K_KP1):
                    dificuldade_atual = "FACIL"
                elif event.key in (pygame.K_2, pygame.K_KP2):
                    dificuldade_atual = "NORMAL"
                elif event.key in (pygame.K_3, pygame.K_KP3):
                    dificuldade_atual = "DIFICIL"
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    esperando = False

            if event.type == pygame.MOUSEBUTTONDOWN:
                vx, vy = display_mgr.map_mouse_pos(event.pos)
                if botao_rect.collidepoint((vx, vy)):
                    esperando = False
                elif nome_rect.collidepoint((vx, vy)):
                    editando_nome = True
                    if nome_digitado == "JOGADOR":
                        nome_digitado = ""
                else:
                    editando_nome = False
                    for indice, rect in enumerate(dificuldade_rects):
                        if rect.collidepoint((vx, vy)):
                            dificuldade_atual = ORDEM_DIFICULDADES[indice]
                            break

        # Renderiza no canvas virtual
        display_mgr.virtual_screen.blit(fundo, (0, 0))
        display_mgr.virtual_screen.blit(botao, botao_rect)

        desenhar_ranking(display_mgr.virtual_screen, ranking)
        desenhar_seletor_dificuldade(display_mgr.virtual_screen, dificuldade_atual)

        nome_bg = pygame.Surface(nome_rect.size, pygame.SRCALPHA)
        nome_bg.fill((25, 35, 52, 225))
        display_mgr.virtual_screen.blit(nome_bg, nome_rect)
        pygame.draw.rect(
            display_mgr.virtual_screen,
            (80, 225, 255) if editando_nome else (115, 135, 158),
            nome_rect,
            2,
            border_radius=8,
        )
        cursor = "_" if editando_nome and int(time.time() * 2) % 2 == 0 else ""
        nome_exibido = nome_digitado or "DIGITE SEU NOME"
        txt_nome = fonte_nome.render(f"JOGADOR: {nome_exibido}{cursor}", True, (238, 246, 255))
        display_mgr.virtual_screen.blit(txt_nome, (nome_rect.x + 14, nome_rect.y + 8))
        txt_nome_dica = fonte_nome_dica.render("clique para editar", True, (170, 194, 215))
        display_mgr.virtual_screen.blit(txt_nome_dica, (nome_rect.right - txt_nome_dica.get_width() - 10, nome_rect.bottom - 17))

        txt_dica = fonte_dica.render("[ESPAÇO] Iniciar  |  [1–3] Dificuldade  |  [F] Tela Cheia", True, (240, 240, 240))
        display_mgr.virtual_screen.blit(txt_dica, (LARGURA_VIRTUAL // 2 - txt_dica.get_width() // 2, ALTURA_VIRTUAL - 55))

        txt_inst = fonte_ctrl.render("Corpo: lados = faixas | subir = pular | baixar = agachar | [C] recalibrar", True, (255, 230, 100))
        display_mgr.virtual_screen.blit(txt_inst, (LARGURA_VIRTUAL // 2 - txt_inst.get_width() // 2, ALTURA_VIRTUAL - 26))

        # A camera e o esqueleto sao o controle principal; teclado e ESP32 sao fallback.
        if vision_ctrl.connected and vision_ctrl.pose_visible:
            badge_txt = fonte_dica.render("● CAMERA IA ATIVA", True, (80, 255, 120))
        else:
            badge_txt = fonte_dica.render(f"○ {vision_ctrl.status}", True, (255, 210, 100))
        display_mgr.virtual_screen.blit(badge_txt, (30, 30))

        # A camera fica em miniatura para liberar o quadro original do ranking.
        desenhar_preview_camera(
            display_mgr.virtual_screen,
            input_ctrl,
            vision_ctrl,
            posicao=(20, 105),
            tamanho=(210, 158),
        )
        desenhar_tabela_debug(display_mgr.virtual_screen, input_ctrl, vision_ctrl, None, clock.get_fps())

        display_mgr.render()
        clock.tick(FPS)

    return normalizar_nome_jogador(nome_digitado), dificuldade_atual


# =========================================================
# LOOP PRINCIPAL DA GAMEPLAY (PULAR E ABAIXAR)
# =========================================================
def loop_gameplay(
    display_mgr,
    input_ctrl,
    vision_ctrl,
    frames_andar,
    frames_agachar,
    imagem_cenario,
    imagens_obstaculos,
    ranking,
    nome_jogador,
    dificuldade,
):
    fonte_hud = pygame.font.SysFont("Arial", 28, bold=True)
    fonte_hud_status = pygame.font.SysFont("Arial", 16, bold=True)
    fonte_go_grande = pygame.font.SysFont("Arial", 64, bold=True)
    fonte_go_sub = pygame.font.SysFont("Arial", 26)
    fonte_alerta = pygame.font.SysFont("Arial", 20, bold=True)
    clock = pygame.time.Clock()
    config_dificuldade = DIFICULDADES[dificuldade]

    while True:
        vaca = VacaPlayer(frames_andar, frames_agachar)
        # Nao carrega para uma nova partida um pulo feito ainda no menu/game over.
        input_ctrl.consume_jump()
        obstaculos = []

        spawn_timer = 0
        spawn_intervalo = config_dificuldade["spawn"]
        pontuacao = 0.0
        distancia = 0.0
        multiplicador_dificuldade = 1.0
        game_over = False
        posicao_ranking = None

        partida_ativa = True
        while partida_ativa:
            # 1. Trata Eventos
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return False

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_f or event.key == pygame.K_F11:
                        display_mgr.toggle_fullscreen()
                    elif event.key == pygame.K_TAB:
                        input_ctrl.show_debug = not input_ctrl.show_debug
                    elif event.key == pygame.K_v:
                        input_ctrl.show_camera = not input_ctrl.show_camera
                    elif event.key == pygame.K_ESCAPE:
                        return True
                    elif game_over:
                        if event.key in (pygame.K_r, pygame.K_SPACE, pygame.K_RETURN):
                            partida_ativa = False

            # 2. Atualiza Entradas
            keys = pygame.key.get_pressed()
            input_ctrl.update_from_keyboard(keys)

            # 3. Lógica do Jogo
            if not game_over:
                velocidade_modo = config_dificuldade["velocidade"]
                distancia += 0.35 * velocidade_modo * multiplicador_dificuldade
                pontuacao += velocidade_modo * multiplicador_dificuldade

                multiplicador_dificuldade = min(2.2, 1.0 + (distancia / 1400.0))
                spawn_intervalo_atual = max(26, int(spawn_intervalo / multiplicador_dificuldade))

                # Geração de Obstáculos (Baixo / Alto)
                spawn_timer += 1
                if spawn_timer >= spawn_intervalo_atual:
                    obstaculos.append(criar_obstaculo(
                        velocidade_base=velocidade_modo * multiplicador_dificuldade
                    ))
                    spawn_timer = 0

                # Atualiza Vaca (Pulo / Agacho)
                vaca.update(input_ctrl)
                hitbox_vaca = vaca.get_hitbox()

                # Atualiza Obstáculos ao longo da perspectiva dos anéis
                for obs in obstaculos:
                    obs['progresso_y'] += obs['velocidade']

                # Remove obstáculos fora da tela
                obstaculos = [o for o in obstaculos if o['progresso_y'] < 1.35]

                # Colide apenas quando a base do obstaculo cruza o plano da vaca.
                for obs in obstaculos:
                    _, cy, _ = calcular_posicao_pista(obs['progresso_y'], obs['lane'])
                    if BASE_Y - 45 <= cy <= BASE_Y + 35:
                        if hitbox_vaca.colliderect(calcular_hitbox_obstaculo(obs)):
                            game_over = True
                            posicao_ranking = ranking.registrar(
                                nome_jogador,
                                int(pontuacao),
                                dificuldade,
                            )
                            break

            # 4. Renderização no Canvas Virtual
            canvas = display_mgr.virtual_screen
            canvas.blit(imagem_cenario, (0, 0))
            desenhar_guias_faixas(canvas)

            # Do horizonte para a camera: os mais proximos cobrem os distantes.
            for obs in sorted(obstaculos, key=lambda item: item['progresso_y']):
                if obs['progresso_y'] > PROGRESSO_MINIMO_VISIVEL:
                    desenhar_obstaculo(canvas, obs, imagens_obstaculos)

            # Desenha a Vaca (com sombra dinâmica e animação de pulo/agacho)
            vaca.draw(canvas)

            # HUD Superior
            hud_bg = pygame.Surface((390, 135), pygame.SRCALPHA)
            hud_bg.fill((20, 20, 35, 190))
            canvas.blit(hud_bg, (20, 20))

            txt_score = fonte_hud.render(f"PONTOS: {int(pontuacao)}", True, (255, 230, 90))
            txt_dist = fonte_hud.render(f"DISTÂNCIA: {int(distancia)}m", True, (255, 255, 255))
            canvas.blit(txt_score, (35, 26))
            canvas.blit(txt_dist, (35, 56))

            if vision_ctrl.connected and vision_ctrl.pose_visible:
                txt_status = fonte_hud_status.render(f"● CAMERA IA: {vision_ctrl.action}", True, (80, 255, 120))
            elif input_ctrl.esp32_connected:
                txt_status = fonte_hud_status.render(f"● ESP32 [{input_ctrl.active_port_name}]", True, (80, 255, 120))
            else:
                txt_status = fonte_hud_status.render("○ FALLBACK: TECLADO (WASD / SETAS)", True, (255, 210, 100))
            canvas.blit(txt_status, (35, 86))

            velocidade_atual = config_dificuldade["velocidade"] * multiplicador_dificuldade
            desenhar_icone_dificuldade(canvas, dificuldade, (48, 126), 12)
            txt_dificuldade = fonte_hud_status.render(
                f'{config_dificuldade["nome"]}  •  VELOCIDADE x{velocidade_atual:.2f}',
                True,
                config_dificuldade["cor"],
            )
            canvas.blit(txt_dificuldade, (68, 117))
            desenhar_indicador_sensor(canvas, (342, 108), input_ctrl.esp32_connected)

            # Alerta de Ação no HUD
            if vaca.is_jumping:
                txt_act = fonte_alerta.render("🚀 SALTO!", True, (100, 230, 255))
                canvas.blit(txt_act, (380, 30))
            elif vaca.is_crouching:
                txt_act = fonte_alerta.render("🛡️ AGACHADO!", True, (255, 220, 80))
                canvas.blit(txt_act, (380, 30))

            desenhar_preview_camera(canvas, input_ctrl, vision_ctrl)
            desenhar_tabela_debug(canvas, input_ctrl, vision_ctrl, vaca, clock.get_fps())

            # Tela de Game Over
            if game_over:
                overlay = pygame.Surface((LARGURA_VIRTUAL, ALTURA_VIRTUAL), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 195))
                canvas.blit(overlay, (0, 0))

                txt_go = fonte_go_grande.render("GAME OVER", True, (255, 60, 60))
                txt_score_final = fonte_hud.render(f"Pontuação Final: {int(pontuacao)}", True, (255, 255, 255))
                txt_sub1 = fonte_go_sub.render("Pressione [R] ou [ESPAÇO] para Jogar Novamente", True, (240, 240, 240))
                txt_sub2 = fonte_go_sub.render("Pressione [ESC] para Voltar ao Menu Inicial", True, (180, 180, 180))

                if posicao_ranking is not None:
                    txt_ranking = fonte_go_sub.render(
                        f"NOVO #{posicao_ranking} DO RANKING!",
                        True,
                        (255, 220, 80),
                    )
                else:
                    txt_ranking = fonte_go_sub.render(
                        "Continue tentando para entrar no TOP 5!",
                        True,
                        (190, 205, 220),
                    )

                canvas.blit(txt_go, (LARGURA_VIRTUAL // 2 - txt_go.get_width() // 2, 220))
                canvas.blit(txt_score_final, (LARGURA_VIRTUAL // 2 - txt_score_final.get_width() // 2, 310))
                canvas.blit(txt_ranking, (LARGURA_VIRTUAL // 2 - txt_ranking.get_width() // 2, 355))
                canvas.blit(txt_sub1, (LARGURA_VIRTUAL // 2 - txt_sub1.get_width() // 2, 415))
                canvas.blit(txt_sub2, (LARGURA_VIRTUAL // 2 - txt_sub2.get_width() // 2, 460))

            display_mgr.render()
            clock.tick(FPS)


# =========================================================
# PONTO DE ENTRADA PRINCIPAL
# =========================================================
def main():
    pygame.init()
    pygame.font.init()

    display_mgr = DisplayManager()

    input_ctrl = InputController()
    vision_ctrl = VisionController(input_ctrl)
    input_ctrl.vision_recalibrate_callback = vision_ctrl.request_calibration
    vision_ctrl.start()
    input_ctrl.start_esp32_connection(port="auto", baudrate=115200)
    ranking = RankingPersistente()
    nome_jogador = "JOGADOR"
    dificuldade = "NORMAL"

    try:
        # Carrega cenário do jogo e caixa de obstáculos
        imagem_cenario = carregar_asset([
            "Imagens/fundo_jogo/caminho.png",
            "Imagens/fundo_jogo/caminho1.png",
            "Imagens/caminho.png",
            "Imagens/caminho1.png",
            "Imagens/fundo_jogo/listra.png"
        ])
        imagem_cenario = pygame.transform.scale(imagem_cenario, (LARGURA_VIRTUAL, ALTURA_VIRTUAL))

        imagens_obstaculos = carregar_assets_obstaculos()

        frames_andar, frames_agachar = carregar_sprites_vaca()

        while True:
            nome_jogador, dificuldade = tela_inicial(
                display_mgr,
                input_ctrl,
                vision_ctrl,
                ranking,
                nome_jogador,
                dificuldade,
            )
            continuar = loop_gameplay(
                display_mgr,
                input_ctrl,
                vision_ctrl,
                frames_andar,
                frames_agachar,
                imagem_cenario,
                imagens_obstaculos,
                ranking,
                nome_jogador,
                dificuldade,
            )
            if not continuar:
                break
    finally:
        vision_ctrl.stop()
        input_ctrl.esp32_running = False
        pygame.quit()


if __name__ == "__main__":
    main()
