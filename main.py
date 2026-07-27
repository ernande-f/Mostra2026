import pygame
import random

LARGURA_TELA = 1280
ALTURA_TELA = 720
TAMANHO_PERSONAGEM = 300
TAMANHO_CAIXA = 300

def nao_escapar(pos_x, pos_y):
    if (pos_x < 0):
        pos_x = 0
    if (pos_x > LARGURA_TELA - TAMANHO_PERSONAGEM):
        pos_x = LARGURA_TELA - TAMANHO_PERSONAGEM
    if (pos_y < 0):
        pos_y = 0
    if (pos_y > ALTURA_TELA - TAMANHO_PERSONAGEM):
        pos_y = ALTURA_TELA - TAMANHO_PERSONAGEM

    return pos_x, pos_y

def criar_caixa():
    return {
        'x': random.randint(0, LARGURA_TELA - TAMANHO_CAIXA),
        'y': -TAMANHO_CAIXA,
        'velocidade': random.randint(6, 11),
    }

def desenhar_caixa(screen, imagem_caixa, caixa):
    profundidade = max(0.35, min(1.0, caixa['y'] / ALTURA_TELA))
    tamanho = int(TAMANHO_CAIXA * profundidade)
    if tamanho < 20:
        tamanho = 20

    caixa_redimensionada = pygame.transform.scale(imagem_caixa, (tamanho, tamanho))
    x = caixa['x'] + (TAMANHO_CAIXA - tamanho) // 2
    y = caixa['y']
    screen.blit(caixa_redimensionada, (x, y))

def colidiu(personagem_x, personagem_y, caixa_x, caixa_y, caixa_tamanho):
    personagem_rect = pygame.Rect(personagem_x, personagem_y, TAMANHO_PERSONAGEM, TAMANHO_PERSONAGEM)
    caixa_rect = pygame.Rect(caixa_x, caixa_y, caixa_tamanho, caixa_tamanho)
    caixa_rect = caixa_rect.inflate(-caixa_tamanho * 0.45, -caixa_tamanho * 0.45)
    return personagem_rect.colliderect(caixa_rect)

def main():
    pygame.init()
    screen = pygame.display.set_mode((LARGURA_TELA, ALTURA_TELA))
    clock = pygame.time.Clock()
    running = True

    personagem = pygame.image.load('p_atras.png').convert_alpha()
    personagem = pygame.transform.scale(personagem, (300, 300))

    caminho = pygame.image.load('caminho.png').convert_alpha()
    caminho = pygame.transform.scale(caminho, (LARGURA_TELA, ALTURA_TELA))

    caixa = pygame.image.load('caixa.png').convert_alpha()
    caixa = pygame.transform.scale(caixa, (TAMANHO_CAIXA, TAMANHO_CAIXA))

    pos_x, pos_y = 500, 450
    caixas = []
    spawn_timer = 0
    caixa_tempo = 55
    fonte = pygame.font.SysFont(None, 48)
    game_over = False

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        screen.fill('green')
        screen.blit(caminho, (0, 0))
        
        if not game_over:
            spawn_timer += 1
            if spawn_timer >= caixa_tempo:
                caixas.append(criar_caixa())
                spawn_timer = 0

            for caixa_atual in caixas:
                caixa_atual['y'] += caixa_atual['velocidade']

            caixas = [caixa_atual for caixa_atual in caixas if caixa_atual['y'] < ALTURA_TELA]

        for caixa_atual in caixas:
            desenhar_caixa(screen, caixa, caixa_atual)
            tamanho_caixa = int(TAMANHO_CAIXA * max(0.35, min(1.0, caixa_atual['y'] / ALTURA_TELA)))
            if tamanho_caixa < 20:
                tamanho_caixa = 20
            if colidiu(pos_x, pos_y, caixa_atual['x'], caixa_atual['y'], tamanho_caixa):
                game_over = True

        screen.blit(personagem, (pos_x, pos_y))

        if game_over:
            texto = fonte.render('GAME OVER', True, 'white')
            texto_rect = texto.get_rect(center=(LARGURA_TELA // 2, ALTURA_TELA // 2))
            screen.blit(texto, texto_rect)

        if not game_over:
            keys = pygame.key.get_pressed()
            if keys[pygame.K_LEFT]:
                pos_x -= 50
                pos_x, pos_y = nao_escapar(pos_x, pos_y)
            if keys[pygame.K_RIGHT]:
                pos_x += 50
                pos_x, pos_y = nao_escapar(pos_x, pos_y)

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

if __name__ == '__main__':
    main()
