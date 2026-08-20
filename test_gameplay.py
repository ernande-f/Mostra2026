import os
import unittest

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


if __name__ == "__main__":
    unittest.main()
