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


class GameplayVisualAndCollisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((320, 180))
        cls.walk_frames, cls.crouch_frames = main.carregar_sprites_vaca()
        cls.assets = main.carregar_assets_obstaculos()
        cls.base_progress = (
            (main.BASE_Y - main.HORIZON_Y)
            / (main.BASE_Y - main.HORIZON_Y + 120)
        )

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

    def test_other_lane_does_not_collide(self):
        cow = self.cow(lane=0)
        for kind in ("chao", "alto"):
            self.assertFalse(cow.get_hitbox().colliderect(
                main.calcular_hitbox_obstaculo(self.obstacle(kind, lane=2))
            ))

    def test_obstacle_is_born_above_the_track_horizon(self):
        obstacle = main.criar_obstaculo()
        self.assertEqual(obstacle["progresso_y"], main.PROGRESSO_SPAWN)
        _, y, _ = main.calcular_posicao_pista(obstacle["progresso_y"], obstacle["lane"])
        self.assertLess(y, main.HORIZON_Y)
        self.assertLessEqual(main.PROGRESSO_MINIMO_VISIVEL, -0.20)

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

    def test_difficulty_changes_approach_speed(self):
        with patch("main.random.uniform", return_value=0.012):
            easy = main.criar_obstaculo(main.DIFICULDADES["FACIL"]["velocidade"])
            hard = main.criar_obstaculo(main.DIFICULDADES["DIFICIL"]["velocidade"])
        self.assertGreater(hard["velocidade"], easy["velocidade"] * 1.5)

    def test_sensor_tilt_changes_lane_once_until_returning_to_center(self):
        controller = main.InputController()
        controller._process_sensor_line("0.45,0.00,1.00", "TESTE")
        _, shift = controller.consume_lane_commands()
        self.assertEqual(shift, 1)

        controller._process_sensor_line("0.50,0.00,1.00", "TESTE")
        _, repeated_shift = controller.consume_lane_commands()
        self.assertEqual(repeated_shift, 0)

        controller._process_sensor_line("0.00,0.00,1.00", "TESTE")
        controller._process_sensor_line("-0.45,0.00,1.00", "TESTE")
        _, shift = controller.consume_lane_commands()
        self.assertEqual(shift, -1)

    def test_sensor_forward_tilt_controls_crouch(self):
        controller = main.InputController()
        controller._process_sensor_line("0.00,0.50,0.65", "TESTE")
        self.assertTrue(controller.is_crouching)
        self.assertTrue(controller.sensor_crouching)

        controller.sensor_crouch_until = 0.0
        controller._process_sensor_line("0.00,0.00,1.00", "TESTE")
        self.assertFalse(controller.is_crouching)

    def test_persistent_ranking_keeps_only_top_five(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ranking.json"
            ranking = main.RankingPersistente(path)
            for name, score in (("Ana", 20), ("Bia", 50), ("Caio", 10), ("Duda", 90), ("Eva", 40), ("Fê", 70)):
                ranking.registrar(name, score, "DIFICIL")

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
