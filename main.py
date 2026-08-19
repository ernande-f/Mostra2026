import pygame
import random
import math
import sys
import threading
import time

# ==========================================
# CONFIGURAÇÕES GERAIS E RESOLUÇÃO VIRTUAL
# ==========================================
LARGURA_VIRTUAL = 1280
ALTURA_VIRTUAL = 720
FPS = 60

# ==========================================
# CONSTANTES DA PISTA (ANÉIS DE SATURNO - 3 TRILHAS)
# ==========================================
# Os anéis de Saturno ficam na metade direita da imagem
# No topo da pista (horizonte dos anéis)
HORIZON_Y = 120
HORIZON_X_MIN = 750
HORIZON_X_MAX = 1110
HORIZON_CENTER_X = (HORIZON_X_MIN + HORIZON_X_MAX) / 2
HORIZON_LARGURA = HORIZON_X_MAX - HORIZON_X_MIN

# Na base (onde a vaca corre nos anéis)
BASE_Y = 580
BASE_X_MIN = 740
BASE_X_MAX = 1130
BASE_CENTER_X = (BASE_X_MIN + BASE_X_MAX) / 2
BASE_LARGURA = BASE_X_MAX - BASE_X_MIN

# Configuração das 3 Trilhas (Faixas / Lanes)
# 0 = Trilha Esquerda | 1 = Trilha Central | 2 = Trilha Direita
LANE_RATIOS = [0.18, 0.50, 0.82]
NUM_LANES = len(LANE_RATIOS)
NOME_TRILHAS = ["0 (Esquerda)", "1 (Centro)", "2 (Direita)"]

# Dimensões da Vaca nos Anéis
LARGURA_VACA_NORMAL = 105
ALTURA_VACA_NORMAL = 135
LARGURA_VACA_AGACHADA = 105
ALTURA_VACA_AGACHADA = 90

# FLAG DE CONTROLE DE AGACHAMENTO (Temporariamente desativado conforme solicitado)
ENABLE_CROUCH = False

# Dimensões dos Obstáculos
TAMANHO_OBSTACULO_MIN = 18
TAMANHO_OBSTACULO_MAX = 68


# =========================================================
# CONTROLADOR DE ENTRADA (SISTEMA DE TRILHAS E ACELERÔMETRO)
# =========================================================
class InputController:
    """
    Abstrai as entradas do jogo com sistema de Trilhas (Lanes).
    Detecta passos/deslocamentos laterais e dispara troca de trilha discreta.
    """
    def __init__(self):
        self.lane_shift_event = 0  # -1 = Mudar para Esquerda | +1 = Mudar para Direita | 0 = Nenhum
        self.is_crouching = False  # True quando agachado
        
        # Telemetria para Debug
        self.raw_ax = 0.0          # Aceleração X em Gs
        self.raw_ay = 0.0          # Aceleração Lateral Y em Gs (Translação / Passos)
        self.raw_az = 1.0          # Aceleração Vertical Z em Gs
        self.raw_crouch = 0
        
        self.active_port_name = "Nenhuma"
        self.show_debug = True     # Exibe a tabela de debug na tela
        
        # Variáveis para integração com ESP32
        self.esp32_connected = False
        self.esp32_thread = None
        self.esp32_running = False
        self.esp32_port = "auto"
        self.esp32_baudrate = 115200
        
        # Calibração e Filtro Dinâmico de Aceleração (Alta Precisão Bluetooth e USB)
        self.accel_trigger_thresh = 0.28  # Gs dinâmicos para disparar (Ágil e Firme)
        self.shift_cooldown = 0.25        # Cooldown estrito de 250ms
        self.last_shift_time = 0.0
        self.gravity_lateral = 0.0        # Linha de base da gravidade estática
        self.dynamic_ay = 0.0             # Aceleração puramente dinâmica do movimento
        self.peak_ay = 0.0                # Rastreia o pico dinâmico recente
        
        self.last_packet_time = 0.0
        self.wifi_thread = None
        
        # Debounce do teclado
        self.prev_k_left = False
        self.prev_k_right = False

    def update_from_keyboard(self, keys):
        """Lê os comandos do teclado detectando cliques únicos para troca de trilha."""
        k_left = keys[pygame.K_LEFT] or keys[pygame.K_a]
        k_right = keys[pygame.K_RIGHT] or keys[pygame.K_d]

        # Dispara mudança de trilha apenas no momento em que a tecla é pressionada
        if k_left and not self.prev_k_left:
            self.lane_shift_event = -1
        elif k_right and not self.prev_k_right:
            self.lane_shift_event = +1

        self.prev_k_left = k_left
        self.prev_k_right = k_right

        # Agachamento via teclado (controlado pela flag ENABLE_CROUCH)
        if ENABLE_CROUCH:
            tecla_agachar = (
                keys[pygame.K_DOWN] or 
                keys[pygame.K_s] or 
                keys[pygame.K_SPACE] or 
                keys[pygame.K_LSHIFT]
            )
            if tecla_agachar or not self.esp32_connected:
                self.is_crouching = tecla_agachar
        else:
            self.is_crouching = False

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
        """Decodifica o pacote e executa o filtro dinâmico de troca de trilha."""
        partes = [p.strip() for p in linha.split(',') if p.strip()]
        if len(partes) >= 1:
            try:
                if len(partes) == 1:
                    ay = float(partes[0])
                    ax = 0.0
                    az = 1.0
                    crouch = 0
                elif len(partes) == 3:
                    ax = float(partes[0])
                    ay = float(partes[1])
                    az = float(partes[2])
                    crouch = 0
                elif len(partes) == 4:
                    ax = float(partes[0])
                    ay = float(partes[1])
                    az = float(partes[2])
                    crouch = int(partes[3])
                elif len(partes) >= 6:
                    crouch = int(partes[2])
                    ax = float(partes[3])
                    ay = float(partes[4])
                    az = float(partes[5])
                else:
                    ay = float(partes[0])
                    ax = 0.0
                    az = 1.0
                    crouch = 0
                
                self.raw_ax = ax
                self.raw_ay = ay
                self.raw_az = az
                self.raw_crouch = crouch

                # Registra sucesso da conexão
                self.esp32_connected = True
                self.active_port_name = source_name
                self.last_packet_time = time.time()

                # Eixo lateral dominante
                val_raw = ay if abs(ay) >= abs(ax) else ax

                # Filtro Passa-Alta calibrado
                self.gravity_lateral = 0.95 * self.gravity_lateral + 0.05 * val_raw
                self.dynamic_ay = val_raw - self.gravity_lateral

                # Medidor de pico dinâmico
                self.peak_ay = max(self.peak_ay * 0.95, abs(self.dynamic_ay))

                # Disparo por Cooldown Estrito (250ms)
                agora = time.time()
                tempo_passado = agora - self.last_shift_time

                if tempo_passado >= self.shift_cooldown:
                    if self.dynamic_ay > self.accel_trigger_thresh:
                        self.lane_shift_event = +1
                        self.last_shift_time = agora
                    elif self.dynamic_ay < -self.accel_trigger_thresh:
                        self.lane_shift_event = -1
                        self.last_shift_time = agora

                self.is_crouching = bool(crouch) if ENABLE_CROUCH else False
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
            print("[WI-FI] Receptor UDP iniciado na porta 4210 (Aguardando ESP32_COW_GAME)...")
        except Exception as e:
            print(f"[WI-FI] Aviso: Não foi possível abrir porta UDP 4210: {e}")
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
            except Exception:
                time.sleep(0.05)

    def _get_candidate_ports(self):
        """Retorna uma lista ordenada de portas seriais USB válidas."""
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
            # Se já está recebendo dados ativos via Wi-Fi, aguarda
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
def carregar_sprites_vaca():
    """
    Carrega a sprite sheet 'Imagens/sprite1.png' com recorte exato
    das 6 poses, centralizando o centro de massa e alinhando os pés.
    Retorna (frames_andar, frames_agachar).
    """
    sprite_sheet = pygame.image.load("Imagens/sprite1.png").convert_alpha()
    
    # Coordenadas exatas das 6 caixas de recorte no sprite sheet original
    # Linha 0: 3 poses de corrida / em pé
    # Linha 1: 3 poses agachadas
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

    # Processa os frames em pé
    for x, y, w, h in boxes_andar:
        sub = sprite_sheet.subsurface(pygame.Rect(x, y, w, h))
        # Cria uma superfície padronizada para centralizar
        canvas = pygame.Surface((360, 750), pygame.SRCALPHA)
        # Alinha centro horizontal e base inferior (pés)
        dest_x = (360 - w) // 2
        dest_y = 750 - h
        canvas.blit(sub, (dest_x, dest_y))
        scaled = pygame.transform.smoothscale(canvas, (LARGURA_VACA_NORMAL, ALTURA_VACA_NORMAL))
        frames_andar.append(scaled)

    # Processa os frames agachados
    for x, y, w, h in boxes_agachar:
        sub = sprite_sheet.subsurface(pygame.Rect(x, y, w, h))
        canvas = pygame.Surface((360, 750), pygame.SRCALPHA)
        dest_x = (360 - w) // 2
        dest_y = 750 - h
        canvas.blit(sub, (dest_x, dest_y))
        scaled = pygame.transform.smoothscale(canvas, (LARGURA_VACA_AGACHADA, ALTURA_VACA_NORMAL))
        frames_agachar.append(scaled)

    return frames_andar, frames_agachar


# =========================================================
# FUNÇÕES DE PERSPECTIVA E CURVATURA DOS ANÉIS DE SATURNO
# =========================================================
def calcular_posicao_pista(progresso_y, lane_ratio):
    """
    Calcula a posição (x, y) e o tamanho do obstáculo seguindo
    a curvatura e perspectiva dos anéis de Saturno no lado direito.
    
    progresso_y: 0.0 (no horizonte) a 1.0 (na base da tela)
    lane_ratio: 0.0 (extrema esquerda da pista) a 1.0 (extrema direita)
    """
    # y no espaço virtual
    y = HORIZON_Y + progresso_y * (BASE_Y - HORIZON_Y + 120)
    
    # Fator de escala / profundidade (acelera conforme se aproxima)
    t = max(0.0, min(1.2, progresso_y))
    t_profundidade = t ** 1.3
    
    # Largura da pista nesta altura y
    largura_atual = HORIZON_LARGURA + (BASE_LARGURA - HORIZON_LARGURA) * t_profundidade
    
    # Curvatura dos anéis de Saturno: arco suave para a direita na parte média da tela
    curvatura_offset = math.sin(t * math.pi) * 35.0
    centro_x = HORIZON_CENTER_X + (BASE_CENTER_X - HORIZON_CENTER_X) * t + curvatura_offset
    
    # Posição x final baseada na faixa (lane) da pista nos anéis
    x = (centro_x - largura_atual / 2.0) + lane_ratio * largura_atual
    
    # Tamanho do obstáculo nesta profundidade
    tamanho = int(TAMANHO_OBSTACULO_MIN + (TAMANHO_OBSTACULO_MAX - TAMANHO_OBSTACULO_MIN) * t_profundidade)
    if tamanho < TAMANHO_OBSTACULO_MIN:
        tamanho = TAMANHO_OBSTACULO_MIN
        
    return x, y, tamanho


def criar_obstaculo(velocidade_base=1.0):
    """Gera um obstáculo no horizonte alinhado em uma das 3 trilhas."""
    lane_idx = random.randint(0, NUM_LANES - 1)
    return {
        'lane_idx': lane_idx,
        'lane': LANE_RATIOS[lane_idx],     # Posição exata da trilha
        'progresso_y': -0.15,               # Começa um pouco antes do horizonte
        'velocidade': random.uniform(0.009, 0.015) * velocidade_base,
    }


# =========================================================
# CLASSE DA VACA (PLAYER COM SISTEMA DE TRILHAS)
# =========================================================
class VacaPlayer:
    def __init__(self, frames_andar, frames_agachar):
        self.frames_andar = frames_andar
        self.frames_agachar = frames_agachar
        
        # Inicia na Trilha Central (1 = Centro)
        self.current_lane = 1
        self.target_x = self._calcular_x_da_trilha(self.current_lane)
        self.x = self.target_x
        self.y_base = BASE_Y
        
        self.is_crouching = False
        self.is_moving = False
        
        self.frame_index = 0.0
        self.anim_speed = 0.22

    def _calcular_x_da_trilha(self, lane_idx):
        """Calcula a posição X centralizada da vaca na trilha especificada."""
        lane_ratio = LANE_RATIOS[lane_idx]
        cx, _, _ = calcular_posicao_pista(1.0, lane_ratio)
        return cx - (LARGURA_VACA_NORMAL / 2.0)

    def update(self, input_ctrl):
        # 1. Trata evento de mudança de trilha
        shift = input_ctrl.lane_shift_event
        if shift != 0:
            if shift == -1 and self.current_lane > 0:
                self.current_lane -= 1
            elif shift == +1 and self.current_lane < NUM_LANES - 1:
                self.current_lane += 1
            # Se já estiver no limite esquerdo (0) ou direito (2), não faz nada!
            
            self.target_x = self._calcular_x_da_trilha(self.current_lane)
            input_ctrl.lane_shift_event = 0  # Consome o evento

        # 2. Deslocamento suave e ágil em direção à trilha alvo (Slide / Lerp)
        diff_x = self.target_x - self.x
        if abs(diff_x) > 1.5:
            self.x += diff_x * 0.26  # Transição rápida e fluida
            self.is_moving = True
        else:
            self.x = self.target_x
            self.is_moving = False

        # 3. Estado de agachamento
        self.is_crouching = input_ctrl.is_crouching

        # 4. Controle de animação:
        if self.is_moving:
            self.frame_index = (self.frame_index + self.anim_speed) % len(self.frames_andar)
        else:
            self.frame_index = 0.0

    def get_hitbox(self):
        """Retorna a hitbox ajustada para colisão justa."""
        if self.is_crouching:
            # Hitbox reduzida ao agachar (permite desviar de obstáculos suspensos)
            hb_w = LARGURA_VACA_AGACHADA * 0.7
            hb_h = ALTURA_VACA_AGACHADA * 0.6
            hb_x = self.x + (LARGURA_VACA_AGACHADA - hb_w) / 2
            hb_y = self.y_base - hb_h
            return pygame.Rect(hb_x, hb_y, hb_w, hb_h)
        else:
            hb_w = LARGURA_VACA_NORMAL * 0.6
            hb_h = ALTURA_VACA_NORMAL * 0.75
            hb_x = self.x + (LARGURA_VACA_NORMAL - hb_w) / 2
            hb_y = self.y_base - hb_h
            return pygame.Rect(hb_x, hb_y, hb_w, hb_h)

    def draw(self, surface):
        idx = int(self.frame_index) % 3
        if self.is_crouching:
            img = self.frames_agachar[idx]
            # Desenha alinhando a base dos pés
            surface.blit(img, (self.x, self.y_base - ALTURA_VACA_NORMAL + 20))
        else:
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
        pygame.display.set_caption("Cow Abduct - IFFar")
        self.virtual_screen = pygame.Surface((LARGURA_VIRTUAL, ALTURA_VIRTUAL))

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            self.real_screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.real_screen = pygame.display.set_mode((LARGURA_VIRTUAL, ALTURA_VIRTUAL), pygame.RESIZABLE)

    def render(self):
        """Escala a superfície virtual para a tela física mantendo o aspect ratio."""
        janela_w, janela_h = self.real_screen.get_size()
        
        # Calcula a melhor escala 16:9 com letterbox se necessário
        escala = min(janela_w / LARGURA_VIRTUAL, janela_h / ALTURA_VIRTUAL)
        novo_w = int(LARGURA_VIRTUAL * escala)
        novo_h = int(ALTURA_VIRTUAL * escala)
        
        offset_x = (janela_w - novo_w) // 2
        offset_y = (janela_h - novo_h) // 2
        
        scaled_surface = pygame.transform.scale(self.virtual_screen, (novo_w, novo_h))
        self.real_screen.fill((0, 0, 0))
        self.real_screen.blit(scaled_surface, (offset_x, offset_y))
        pygame.display.flip()

    def map_mouse_pos(self, mouse_pos):
        """Converte coordenadas físicas do mouse para o espaço virtual 1280x720."""
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
def desenhar_tabela_debug(canvas, input_ctrl, vaca=None, fps=60.0):
    """Renderiza um painel com tabela de telemetria do ESP32 e do Player."""
    if not input_ctrl.show_debug:
        return

    painel_w, painel_h = 380, 295
    painel_x = LARGURA_VIRTUAL - painel_w - 20
    painel_y = 20

    painel_bg = pygame.Surface((painel_w, painel_h), pygame.SRCALPHA)
    painel_bg.fill((12, 16, 28, 225))
    pygame.draw.rect(painel_bg, (0, 180, 255), (0, 0, painel_w, painel_h), 2, border_radius=8)
    canvas.blit(painel_bg, (painel_x, painel_y))

    fonte_tit = pygame.font.SysFont("Courier New", 14, bold=True)
    fonte_txt = pygame.font.SysFont("Courier New", 13, bold=True)

    # Cabeçalho
    txt_tit = fonte_tit.render("== DEBUG ESP32 / 3 TRILHAS ==", True, (255, 220, 80))
    canvas.blit(txt_tit, (painel_x + 15, painel_y + 10))
    pygame.draw.line(canvas, (0, 180, 255), (painel_x + 10, painel_y + 30), (painel_x + painel_w - 10, painel_y + 30), 1)

    # Dados da Tabela
    status_cor = (80, 255, 120) if input_ctrl.esp32_connected else (255, 90, 90)
    status_str = f"CONECTADO [{input_ctrl.active_port_name}]" if input_ctrl.esp32_connected else f"BUSCANDO ({input_ctrl.active_port_name})"
    crouch_str = "DESATIVADO (Flag)" if not ENABLE_CROUCH else ("SIM (Agachado)" if input_ctrl.is_crouching else "NAO (Em Pe)")
    crouch_cor = (160, 160, 170) if not ENABLE_CROUCH else ((80, 255, 120) if input_ctrl.is_crouching else (180, 180, 190))
    tempo_passado = time.time() - input_ctrl.last_shift_time
    pronto = tempo_passado >= input_ctrl.shift_cooldown
    gatilho_str = "ARMADO (Pronto)" if pronto else f"COOLDOWN ({(input_ctrl.shift_cooldown - tempo_passado):.2f}s)"
    gatilho_cor = (80, 255, 120) if pronto else (255, 200, 80)

    trilha_nome = NOME_TRILHAS[vaca.current_lane] if vaca else "N/A"

    linhas = [
        ("Status:", status_str, status_cor),
        ("Trilha da Vaca:", trilha_nome, (255, 255, 100)),
        ("Accel Dinamica:", f"{input_ctrl.dynamic_ay:+.3f} G", (100, 230, 255)),
        ("Pico Dinamico:", f"{input_ctrl.peak_ay:.3f} G", (255, 180, 220)),
        ("Limiar Disparo:", f"±{input_ctrl.accel_trigger_thresh:.2f} G", (255, 200, 80)),
        ("Status Gatilho:", gatilho_str, gatilho_cor),
        ("Agachamento:", crouch_str, crouch_cor),
        ("FPS:", f"{fps:.1f}", (180, 220, 255)),
    ]

    curr_y = painel_y + 38
    for label, val, cor in linhas:
        t_lbl = fonte_txt.render(label, True, (160, 180, 210))
        t_val = fonte_txt.render(val, True, cor)
        canvas.blit(t_lbl, (painel_x + 15, curr_y))
        canvas.blit(t_val, (painel_x + 160, curr_y))
        curr_y += 22

    # Rodapé com dica de alternância
    t_dica = fonte_tit.render("[TAB] Ocultar/Exibir Tabela", True, (120, 145, 175))
    canvas.blit(t_dica, (painel_x + 15, painel_y + painel_h - 22))


# =========================================================
# TELA INICIAL
# =========================================================
def tela_inicial(display_mgr, input_ctrl):
    fundo = pygame.image.load("Imagens/fundo_inicio.jpg").convert()
    fundo = pygame.transform.scale(fundo, (LARGURA_VIRTUAL, ALTURA_VIRTUAL))
    
    botao = pygame.image.load("Imagens/botao_inicio.png").convert_alpha()
    botao = pygame.transform.scale(botao, (250, 90))
    botao_rect = botao.get_rect(center=(int(LARGURA_VIRTUAL // 4.4), 593))
    
    fonte_dica = pygame.font.SysFont("Arial", 22, bold=True)
    clock = pygame.time.Clock()
    
    esperando = True
    while esperando:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
                
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_f or event.key == pygame.K_F11:
                    display_mgr.toggle_fullscreen()
                elif event.key == pygame.K_TAB:
                    input_ctrl.show_debug = not input_ctrl.show_debug
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    esperando = False
                    
            if event.type == pygame.MOUSEBUTTONDOWN:
                vx, vy = display_mgr.map_mouse_pos(event.pos)
                if botao_rect.collidepoint((vx, vy)):
                    esperando = False

        # Renderiza no canvas virtual
        display_mgr.virtual_screen.blit(fundo, (0, 0))
        display_mgr.virtual_screen.blit(botao, botao_rect)
        
        # Dica de tela cheia e status do controle
        txt_dica = fonte_dica.render("Pressione [F] para Tela Cheia | [Espaço] para Iniciar", True, (240, 240, 240))
        display_mgr.virtual_screen.blit(txt_dica, (LARGURA_VIRTUAL // 2 - txt_dica.get_width() // 2, ALTURA_VIRTUAL - 40))

        # Status do ESP32 na tela inicial
        if input_ctrl.esp32_connected:
            tipo_con = "BLUETOOTH" if any(k in input_ctrl.active_port_name.lower() for k in ["esp32", "cow", "bluetooth"]) else "USB"
            badge_txt = fonte_dica.render(f"● ESP32 {tipo_con} ATIVO", True, (80, 255, 120))
        else:
            badge_txt = fonte_dica.render("○ MODO TECLADO (Conecte via Bluetooth ou USB)", True, (200, 200, 220))
        display_mgr.virtual_screen.blit(badge_txt, (30, 30))

        # Tabela de Debug
        desenhar_tabela_debug(display_mgr.virtual_screen, input_ctrl, None, clock.get_fps())
        
        display_mgr.render()
        clock.tick(FPS)


# =========================================================
# LOOP PRINCIPAL DA GAMEPLAY
# =========================================================
def loop_gameplay(display_mgr, input_ctrl, frames_andar, frames_agachar, imagem_cenario, imagem_caixa):
    fonte_hud = pygame.font.SysFont("Arial", 28, bold=True)
    fonte_hud_status = pygame.font.SysFont("Arial", 16, bold=True)
    fonte_go_grande = pygame.font.SysFont("Arial", 64, bold=True)
    fonte_go_sub = pygame.font.SysFont("Arial", 26)
    clock = pygame.time.Clock()

    # Loop de Partidas (Permite jogar e reiniciar infinitamente sem recursão de memória)
    while True:
        vaca = VacaPlayer(frames_andar, frames_agachar)
        caixas = []
        
        spawn_timer = 0
        spawn_intervalo = 48
        pontuacao = 0.0
        distancia = 0.0
        multiplicador_dificuldade = 1.0
        game_over = False
        
        partida_ativa = True
        while partida_ativa:
            # 1. Trata Eventos
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return False  # Fecha o jogo
                    
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_f or event.key == pygame.K_F11:
                        display_mgr.toggle_fullscreen()
                    elif event.key == pygame.K_TAB:
                        input_ctrl.show_debug = not input_ctrl.show_debug
                    elif event.key == pygame.K_ESCAPE:
                        return True  # Volta para o menu inicial
                    elif game_over:
                        if event.key in (pygame.K_r, pygame.K_SPACE, pygame.K_RETURN):
                            # Reinicia uma nova partida limpamente
                            partida_ativa = False

            # 2. Atualiza Entradas
            keys = pygame.key.get_pressed()
            input_ctrl.update_from_keyboard(keys)

            # 3. Lógica do Jogo
            if not game_over:
                distancia += 0.35 * multiplicador_dificuldade
                pontuacao += 1.0 * multiplicador_dificuldade
                
                # Aceleração sutil e progressiva de dificuldade
                multiplicador_dificuldade = min(2.0, 1.0 + (distancia / 1500.0))
                spawn_intervalo_atual = max(24, int(spawn_intervalo / multiplicador_dificuldade))
                
                # Geração de caixas
                spawn_timer += 1
                if spawn_timer >= spawn_intervalo_atual:
                    caixas.append(criar_obstaculo(velocidade_base=multiplicador_dificuldade))
                    spawn_timer = 0

                # Atualiza Vaca
                vaca.update(input_ctrl)
                hitbox_vaca = vaca.get_hitbox()

                # Atualiza Caixas ao longo da curvatura dos anéis
                for caixa in caixas:
                    caixa['progresso_y'] += caixa['velocidade']

                # Remove caixas que saíram da tela
                caixas = [c for c in caixas if c['progresso_y'] < 1.35]

                # Checagem de Colisão
                for caixa in caixas:
                    if caixa['progresso_y'] > 0.0:
                        cx, cy, c_tam = calcular_posicao_pista(caixa['progresso_y'], caixa['lane'])
                        caixa_rect = pygame.Rect(cx - c_tam // 2, cy - c_tam // 2, c_tam, c_tam)
                        # Hitbox ajustada do obstáculo
                        caixa_hitbox = caixa_rect.inflate(-c_tam * 0.35, -c_tam * 0.35)
                        
                        if hitbox_vaca.colliderect(caixa_hitbox):
                            game_over = True
                            break

            # 4. Renderização no Canvas Virtual
            canvas = display_mgr.virtual_screen
            
            # Cenário de fundo
            canvas.blit(imagem_cenario, (0, 0))

            # Desenha os obstáculos em perspectiva curva
            for caixa in caixas:
                if caixa['progresso_y'] > -0.05:
                    cx, cy, c_tam = calcular_posicao_pista(caixa['progresso_y'], caixa['lane'])
                    caixa_scaled = pygame.transform.smoothscale(imagem_caixa, (c_tam, c_tam))
                    canvas.blit(caixa_scaled, (int(cx - c_tam / 2), int(cy - c_tam / 2)))

            # Desenha a Vaca
            vaca.draw(canvas)

            # HUD (Pontuação, Distância e Status do Sensor)
            hud_bg = pygame.Surface((310, 105), pygame.SRCALPHA)
            hud_bg.fill((20, 20, 35, 190))
            canvas.blit(hud_bg, (20, 20))
            
            txt_score = fonte_hud.render(f"PONTOS: {int(pontuacao)}", True, (255, 230, 90))
            txt_dist = fonte_hud.render(f"DISTÂNCIA: {int(distancia)}m", True, (255, 255, 255))
            canvas.blit(txt_score, (35, 26))
            canvas.blit(txt_dist, (35, 56))

            if input_ctrl.esp32_connected:
                tipo_con = "BLUETOOTH" if any(k in input_ctrl.active_port_name.lower() for k in ["esp32", "cow", "bluetooth"]) else "USB"
                txt_status = fonte_hud_status.render(f"● ESP32 {tipo_con} CONECTADO", True, (80, 255, 120))
            else:
                txt_status = fonte_hud_status.render("○ CONTROLE: TECLADO", True, (190, 190, 210))
            canvas.blit(txt_status, (35, 86))

            # Feedback de Agachamento no HUD
            if ENABLE_CROUCH and vaca.is_crouching:
                txt_crouch = fonte_go_sub.render("AGACHADO", True, (100, 255, 120))
                canvas.blit(txt_crouch, (350, 30))

            # Tela de Game Over
            if game_over:
                overlay = pygame.Surface((LARGURA_VIRTUAL, ALTURA_VIRTUAL), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 190))
                canvas.blit(overlay, (0, 0))

                txt_go = fonte_go_grande.render("GAME OVER", True, (255, 60, 60))
                txt_score_final = fonte_hud.render(f"Pontuação Final: {int(pontuacao)}", True, (255, 255, 255))
                txt_sub1 = fonte_go_sub.render("Pressione [R] ou [ESPAÇO] para Jogar Novamente", True, (240, 240, 240))
                txt_sub2 = fonte_go_sub.render("Pressione [ESC] para Voltar ao Menu Inicial", True, (180, 180, 180))

                canvas.blit(txt_go, (LARGURA_VIRTUAL // 2 - txt_go.get_width() // 2, 220))
                canvas.blit(txt_score_final, (LARGURA_VIRTUAL // 2 - txt_score_final.get_width() // 2, 310))
                canvas.blit(txt_sub1, (LARGURA_VIRTUAL // 2 - txt_sub1.get_width() // 2, 400))
                canvas.blit(txt_sub2, (LARGURA_VIRTUAL // 2 - txt_sub2.get_width() // 2, 445))

            # Tabela de Debug (Telemetria ao vivo do ESP32)
            desenhar_tabela_debug(canvas, input_ctrl, vaca, clock.get_fps())

            # 5. Apresenta o Frame
            display_mgr.render()
            clock.tick(FPS)


# =========================================================
# FUNÇÃO PRINCIPAL (ENTRY POINT)
# =========================================================
def main():
    pygame.init()
    pygame.font.init()

    display_mgr = DisplayManager()
    input_ctrl = InputController()

    # Inicia conexão em segundo plano com ESP32 (auto-detecta porta USB/Serial sem travar o jogo)
    input_ctrl.start_esp32_connection(port="auto")

    # Carrega os assets otimizados
    frames_andar, frames_agachar = carregar_sprites_vaca()
    
    imagem_cenario = pygame.image.load("Imagens/fundo_jogo/caminho.png").convert()
    imagem_cenario = pygame.transform.scale(imagem_cenario, (LARGURA_VIRTUAL, ALTURA_VIRTUAL))

    imagem_caixa = pygame.image.load("caixa.png").convert_alpha()

    # Loop da Aplicação (Menu -> Jogo -> Menu)
    app_running = True
    while app_running:
        tela_inicial(display_mgr, input_ctrl)
        app_running = loop_gameplay(
            display_mgr, 
            input_ctrl, 
            frames_andar, 
            frames_agachar, 
            imagem_cenario, 
            imagem_caixa
        )

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()

