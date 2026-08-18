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
# CONSTANTES DA PISTA (ANÉIS DE SATURNO - LADO DIREITO)
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

# Dimensões da Vaca nos Anéis
LARGURA_VACA_NORMAL = 105
ALTURA_VACA_NORMAL = 135
LARGURA_VACA_AGACHADA = 105
ALTURA_VACA_AGACHADA = 90
VELOCIDADE_VACA = 8.5

# Dimensões dos Obstáculos
TAMANHO_OBSTACULO_MIN = 18
TAMANHO_OBSTACULO_MAX = 68


# =========================================================
# CONTROLADOR DE ENTRADA (PRONTO PARA TECLADO E ESP32)
# =========================================================
class InputController:
    """
    Abstrai as entradas do jogo.
    Suporta Teclado nativamente e possui estrutura em thread
    para conexão futura com ESP32 via Bluetooth / Porta Serial.
    """
    def __init__(self):
        self.move_x = 0.0          # -1.0 (esquerda) a +1.0 (direita)
        self.is_crouching = False  # True quando agachado
        
        # Variáveis para integração com ESP32 / Acelerômetro
        self.esp32_connected = False
        self.esp32_thread = None
        self.esp32_running = False
        self.esp32_port = None
        
        # Limiares de calibração do acelerômetro
        self.tilt_deadzone = 12.0    # graus de inclinação neutra
        self.tilt_max = 45.0         # graus para velocidade máxima
        self.crouch_accel_thresh = -1.2  # limiar de agachamento corporal

    def update_from_keyboard(self, keys):
        """Lê os comandos do teclado."""
        # Movimento horizontal
        target_x = 0.0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            target_x -= 1.0
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            target_x += 1.0
        self.move_x = target_x

        # Agachamento
        self.is_crouching = (
            keys[pygame.K_DOWN] or 
            keys[pygame.K_s] or 
            keys[pygame.K_SPACE] or 
            keys[pygame.K_LSHIFT]
        )

    def start_esp32_connection(self, port="/dev/tty.ESP32_COW", baudrate=115200):
        """
        Inicia a leitura em segundo plano dos dados do ESP32 via Serial/Bluetooth.
        Não bloqueia o loop principal de 60 FPS do Pygame.
        """
        self.esp32_port = port
        self.esp32_running = True
        self.esp32_thread = threading.Thread(target=self._esp32_worker, daemon=True)
        self.esp32_thread.start()

    def _esp32_worker(self):
        """Thread que recebe e interpreta os pacotes do ESP32."""
        try:
            import serial  # pyserial
            ser = serial.Serial(self.esp32_port, 115200, timeout=0.1)
            self.esp32_connected = True
            print(f"[ESP32] Conectado com sucesso na porta {self.esp32_port}")
            
            while self.esp32_running:
                linha = ser.readline().decode('utf-8', errors='ignore').strip()
                if linha:
                    # Formato esperado do ESP32: "ROLL,PITCH,CROUCH_FLAG" ou JSON
                    partes = linha.split(',')
                    if len(partes) >= 2:
                        try:
                            roll = float(partes[0])   # Inclinação lateral (esquerda/direita)
                            crouch = int(partes[1]) if len(partes) > 2 else 0
                            
                            # Mapeia inclinação lateral para -1.0 a +1.0
                            if abs(roll) < self.tilt_deadzone:
                                self.move_x = 0.0
                            else:
                                raw_val = (roll - math.copysign(self.tilt_deadzone, roll)) / (self.tilt_max - self.tilt_deadzone)
                                self.move_x = max(-1.0, min(1.0, raw_val))
                            
                            self.is_crouching = bool(crouch)
                        except ValueError:
                            pass
        except Exception as e:
            self.esp32_connected = False
            # Falha silenciosa de conexão para não interromper testes no teclado


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
    """Gera um obstáculo no horizonte associado a uma faixa da pista."""
    return {
        'lane': random.uniform(0.05, 0.95),  # Posição relativa na pista
        'progresso_y': -0.15,               # Começa um pouco antes do horizonte
        'velocidade': random.uniform(0.009, 0.015) * velocidade_base,
    }


# =========================================================
# CLASSE DA VACA (PLAYER)
# =========================================================
class VacaPlayer:
    def __init__(self, frames_andar, frames_agachar):
        self.frames_andar = frames_andar
        self.frames_agachar = frames_agachar
        
        # Posição horizontal contínua (centro da pista)
        self.x = (BASE_X_MIN + BASE_X_MAX - LARGURA_VACA_NORMAL) / 2.0
        self.y_base = BASE_Y  # Linha dos pés da vaca
        
        self.is_crouching = False
        self.is_moving = False
        
        self.frame_index = 0.0
        self.anim_speed = 0.18

    def update(self, input_ctrl):
        # Atualiza estado de agachamento
        self.is_crouching = input_ctrl.is_crouching
        
        # Atualiza movimentação horizontal suave
        move_val = input_ctrl.move_x
        if abs(move_val) > 0.05:
            self.x += move_val * VELOCIDADE_VACA
            self.is_moving = True
        else:
            self.is_moving = False

        # Limita a vaca estritamente aos anéis de Saturno
        limite_min = BASE_X_MIN + 10
        limite_max = BASE_X_MAX - LARGURA_VACA_NORMAL - 10
        if self.x < limite_min:
            self.x = limite_min
        elif self.x > limite_max:
            self.x = limite_max

        # Controle de animação:
        # Quando parada (idle), permanece no frame estável (0) sem tremer!
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
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    esperando = False
                    
            if event.type == pygame.MOUSEBUTTONDOWN:
                vx, vy = display_mgr.map_mouse_pos(event.pos)
                if botao_rect.collidepoint((vx, vy)):
                    esperando = False

        # Renderiza no canvas virtual
        display_mgr.virtual_screen.blit(fundo, (0, 0))
        display_mgr.virtual_screen.blit(botao, botao_rect)
        
        # Dica de tela cheia
        txt_dica = fonte_dica.render("Pressione [F] para Tela Cheia | [Espaço] para Iniciar", True, (240, 240, 240))
        display_mgr.virtual_screen.blit(txt_dica, (LARGURA_VIRTUAL // 2 - txt_dica.get_width() // 2, ALTURA_VIRTUAL - 40))
        
        display_mgr.render()
        clock.tick(FPS)


# =========================================================
# LOOP PRINCIPAL DA GAMEPLAY
# =========================================================
def loop_gameplay(display_mgr, input_ctrl, frames_andar, frames_agachar, imagem_cenario, imagem_caixa):
    vaca = VacaPlayer(frames_andar, frames_agachar)
    caixas = []
    
    spawn_timer = 0
    spawn_intervalo = 48
    pontuacao = 0.0
    distancia = 0.0
    multiplicador_dificuldade = 1.0
    game_over = False
    
    fonte_hud = pygame.font.SysFont("Arial", 28, bold=True)
    fonte_go_grande = pygame.font.SysFont("Arial", 64, bold=True)
    fonte_go_sub = pygame.font.SysFont("Arial", 26)
    
    clock = pygame.time.Clock()
    running = True

    while running:
        # 1. Trata Eventos
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False  # Sair do jogo
                
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_f or event.key == pygame.K_F11:
                    display_mgr.toggle_fullscreen()
                elif event.key == pygame.K_ESCAPE:
                    return True  # Volta para o menu
                elif game_over:
                    if event.key in (pygame.K_r, pygame.K_SPACE, pygame.K_RETURN):
                        # Reinicia a partida imediatamente
                        return loop_gameplay(display_mgr, input_ctrl, frames_andar, frames_agachar, imagem_cenario, imagem_caixa)

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

        # HUD (Pontuação e Distância)
        hud_bg = pygame.Surface((310, 85), pygame.SRCALPHA)
        hud_bg.fill((20, 20, 35, 180))
        canvas.blit(hud_bg, (20, 20))
        
        txt_score = fonte_hud.render(f"PONTOS: {int(pontuacao)}", True, (255, 230, 90))
        txt_dist = fonte_hud.render(f"DISTÂNCIA: {int(distancia)}m", True, (255, 255, 255))
        canvas.blit(txt_score, (35, 28))
        canvas.blit(txt_dist, (35, 62))

        # Feedback de Agachamento no HUD
        if vaca.is_crouching:
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

        # 5. Apresenta o Frame
        display_mgr.render()
        clock.tick(FPS)

    return False


# =========================================================
# FUNÇÃO PRINCIPAL (ENTRY POINT)
# =========================================================
def main():
    pygame.init()
    pygame.font.init()

    display_mgr = DisplayManager()
    input_ctrl = InputController()

    # Inicia conexão opcional com ESP32 (não bloqueante)
    # input_ctrl.start_esp32_connection(port="/dev/cu.ESP32_COW")

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

