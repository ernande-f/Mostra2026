import os
import json
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import main
from esp32_power import PowerSnapshot


class GameplayVisualAndCollisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((320, 180))
        cls.walk_frames, cls.crouch_frames = main.carregar_sprites_vaca()
        cls.assets = main.carregar_assets_obstaculos()
        cls.base_progress = main.PROGRESSO_PLANO_VACA

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def obstacle(self, kind, lane=1):
        return {
            "tipo": kind,
            "lane_idx": lane,
            "lane": main.LANE_RATIOS[lane],
            "progresso_y": self.base_progress,
            "velocidade": 0.0,
        }

    def cow(self, lane=1):
        cow = main.VacaPlayer(self.walk_frames, self.crouch_frames)
        cow.current_lane = lane
        cow.target_x = cow._calcular_x_da_faixa(lane)
        cow.x = cow.target_x
        return cow

    def test_generated_obstacle_assets_have_real_alpha_and_content(self):
        for image in self.assets.values():
            self.assertTrue(image.get_flags() & pygame.SRCALPHA)
            self.assertGreater(image.get_bounding_rect(min_alpha=10).width, 100)
            self.assertGreater(image.get_bounding_rect(min_alpha=10).height, 100)

    def test_crouched_sprite_is_visibly_lower_than_standing_sprite(self):
        self.assertLess(
            self.crouch_frames[0].get_height(),
            self.walk_frames[0].get_height() * 0.70,
        )

    def test_active_esp32_shield_draws_a_large_effect_around_the_cow(self):
        canvas = pygame.Surface(
            (main.LARGURA_VIRTUAL, main.ALTURA_VIRTUAL),
            pygame.SRCALPHA,
        )
        snapshot = PowerSnapshot(
            connected=True,
            status="CONECTADO",
            source_ip="192.168.4.1",
            packets_received=10,
            charge_ratio=0.0,
            armed=False,
            twist_ready=False,
            shield_active=True,
            motion_intensity=0.0,
            gyro_speed=0.0,
            activation_flash=1.0,
            hit_flash=0.0,
        )
        cow = self.cow()
        main.desenhar_poder_esp32(canvas, cow, snapshot, agora=1.0)
        effect_rect = canvas.get_bounding_rect(min_alpha=10)
        self.assertGreater(effect_rect.width, 150)
        self.assertGreater(effect_rect.height, 150)

    def test_ground_crate_hits_standing_or_crouched_cow_in_same_lane(self):
        cow = self.cow()
        crate = self.obstacle("chao")
        self.assertTrue(cow.get_hitbox().colliderect(main.calcular_hitbox_obstaculo(crate)))

        cow.is_crouching = True
        self.assertTrue(cow.get_hitbox().colliderect(main.calcular_hitbox_obstaculo(crate)))

    def test_jump_clears_ground_crate(self):
        cow = self.cow()
        controller = main.InputController()
        controller.trigger_jump("teste")
        for _ in range(8):
            cow.update(controller)
        self.assertFalse(cow.get_hitbox().colliderect(
            main.calcular_hitbox_obstaculo(self.obstacle("chao"))
        ))

    def test_crouch_clears_high_gate_but_standing_cow_hits_beam(self):
        cow = self.cow()
        gate_hitbox = main.calcular_hitbox_obstaculo(self.obstacle("alto"))
        self.assertTrue(cow.get_hitbox().colliderect(gate_hitbox))

        cow.is_crouching = True
        self.assertFalse(cow.get_hitbox().colliderect(gate_hitbox))

    def test_full_obstacle_requires_changing_lane(self):
        obstacle_hitbox = main.calcular_hitbox_obstaculo(self.obstacle("bloqueio"))

        standing_cow = self.cow()
        self.assertTrue(standing_cow.get_hitbox().colliderect(obstacle_hitbox))

        crouched_cow = self.cow()
        crouched_cow.is_crouching = True
        self.assertTrue(crouched_cow.get_hitbox().colliderect(obstacle_hitbox))

        jumping_cow = self.cow()
        jumping_cow.is_jumping = True
        jumping_cow.jump_y = -180.0
        self.assertTrue(jumping_cow.get_hitbox().colliderect(obstacle_hitbox))

    def test_other_lane_does_not_collide(self):
        cow = self.cow(lane=0)
        for kind in ("chao", "alto", "bloqueio"):
            self.assertFalse(cow.get_hitbox().colliderect(
                main.calcular_hitbox_obstaculo(self.obstacle(kind, lane=2))
            ))

    def test_obstacle_is_born_at_the_beginning_of_the_rings(self):
        obstacle = main.criar_obstaculo()
        self.assertEqual(obstacle["progresso_y"], main.PROGRESSO_SPAWN)
        _, y, _ = main.calcular_posicao_pista(obstacle["progresso_y"], obstacle["lane"])
        self.assertLess(y, main.HORIZON_Y)
        self.assertEqual(main.PROGRESSO_MINIMO_VISIVEL, main.PROGRESSO_SPAWN)

    def test_saturn_video_is_available_as_animated_game_background(self):
        fallback = pygame.Surface((main.LARGURA_VIRTUAL, main.ALTURA_VIRTUAL))
        background = main.FundoJogoAnimado(
            main.VIDEO_FUNDO_JOGO,
            fallback,
            (main.LARGURA_VIRTUAL, main.ALTURA_VIRTUAL),
        )
        try:
            self.assertTrue(background.video_ativo)
            self.assertEqual(
                background.frame_atual.get_size(),
                (main.LARGURA_VIRTUAL, main.ALTURA_VIRTUAL),
            )
        finally:
            background.close()

    def test_initial_background_uses_every_native_gif_frame(self):
        background = main.FundoGifAnimado(
            main.PASTA_PROJETO / "Imagens" / "fundo_inicio.gif",
            (main.LARGURA_VIRTUAL, main.ALTURA_VIRTUAL),
        )
        self.assertEqual(background.frame_count, 5)
        self.assertEqual(
            {frame.get_size() for frame in background.frames},
            {(main.LARGURA_VIRTUAL, main.ALTURA_VIRTUAL)},
        )

    def test_name_input_keeps_partial_text_and_accepts_accents(self):
        self.assertEqual(main.limpar_nome_digitado(""), "")
        self.assertEqual(main.limpar_nome_digitado("Fê da-Silva!"), "FÊ DA-SILVA")
        self.assertEqual(main.normalizar_nome_jogador("  "), "JOGADOR")

    def test_play_opens_name_editor_and_enter_confirms_the_name(self):
        class FakeDisplay:
            def __init__(self):
                self.virtual_screen = pygame.Surface(
                    (main.LARGURA_VIRTUAL, main.ALTURA_VIRTUAL)
                )

            @staticmethod
            def map_mouse_pos(pos):
                return pos

            @staticmethod
            def toggle_fullscreen():
                return None

            @staticmethod
            def render():
                return None

        class FakeVision:
            pass

        pygame.event.clear()
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
        pygame.event.post(pygame.event.Event(pygame.TEXTINPUT, text="Fê"))
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))

        nome = main.tela_inicial(
            FakeDisplay(),
            main.InputController(),
            FakeVision(),
            main.RankingPersistente(Path("/arquivo/que/nao/existe.json")),
        )
        self.assertEqual(nome, "FÊ")

    def test_only_easy_mode_is_available(self):
        self.assertEqual(tuple(main.DIFICULDADES), (main.MODO_JOGO,))
        with patch("main.random.uniform", return_value=0.012):
            easy = main.criar_obstaculo(main.DIFICULDADES["FACIL"]["velocidade"])
        self.assertAlmostEqual(easy["velocidade"], 0.012 * 0.78)

    def test_lane_routes_follow_the_three_bands_in_the_background(self):
        samples = (
            (240, (637, 715, 803)),
            (380, (749, 848, 958)),
            (580, (765, 924, 1067)),
            (700, (725, 924, 1082)),
        )
        alcance_vertical = main.BASE_Y - main.HORIZON_Y + 120
        for y, expected_xs in samples:
            progress = (y - main.HORIZON_Y) / alcance_vertical
            actual_xs = [
                main.calcular_posicao_pista(progress, lane)[0]
                for lane in main.LANE_RATIOS
            ]
            for actual, expected in zip(actual_xs, expected_xs):
                self.assertAlmostEqual(actual, expected, delta=2.0)

    def test_cow_uses_the_same_lane_centers_as_obstacles(self):
        for lane_index, lane_ratio in enumerate(main.LANE_RATIOS):
            cow = self.cow(lane=lane_index)
            cow_center = cow.x + main.LARGURA_VACA_NORMAL / 2
            route_center = main.calcular_posicao_pista(
                main.PROGRESSO_PLANO_VACA,
                lane_ratio,
            )[0]
            self.assertAlmostEqual(cow_center, route_center)

    def test_obstacle_scale_stops_growing_near_the_end_of_lane(self):
        size_at_cap = main.calcular_posicao_pista(0.92)[2]
        self.assertEqual(main.calcular_posicao_pista(1.00)[2], size_at_cap)
        self.assertEqual(main.calcular_posicao_pista(1.20)[2], size_at_cap)

    def test_obstacle_moves_in_front_of_cow_at_the_crossing_plane(self):
        for kind in ("chao", "alto", "bloqueio"):
            obstacle = self.obstacle(kind)
            self.assertTrue(main.obstaculo_em_primeiro_plano(obstacle))

            obstacle["progresso_y"] = main.PROGRESSO_SPAWN
            self.assertFalse(main.obstaculo_em_primeiro_plano(obstacle))

    def test_runtime_input_has_no_esp32_or_accelerometer_hooks(self):
        controller = main.InputController()
        self.assertFalse(hasattr(controller, "start_esp32_connection"))
        self.assertFalse(hasattr(controller, "esp32_connected"))
        self.assertFalse(hasattr(controller, "impact_interpreter"))
        self.assertFalse(hasattr(controller, "consume_impacts"))
        self.assertFalse(controller.show_camera)

    def test_persistent_ranking_keeps_only_top_five(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ranking.json"
            ranking = main.RankingPersistente(path)
            for name, score in (("Ana", 20), ("Bia", 50), ("Caio", 10), ("Duda", 90), ("Eva", 40), ("Fê", 70)):
                ranking.registrar(name, score, main.MODO_JOGO)

            reloaded = main.RankingPersistente(path)
            self.assertEqual([item["pontos"] for item in reloaded.entradas], [90, 70, 50, 40, 20])
            self.assertEqual(reloaded.entradas[1]["nome"], "FÊ")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))[0]["nome"], "DUDA")

    def test_corrupt_ranking_file_does_not_break_game(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ranking.json"
            path.write_text("nao e json", encoding="utf-8")
            self.assertEqual(main.RankingPersistente(path).entradas, [])


if __name__ == "__main__":
    unittest.main()
