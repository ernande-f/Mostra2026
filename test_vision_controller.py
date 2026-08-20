import unittest

from vision_controller import PoseGestureInterpreter


class PoseGestureInterpreterTests(unittest.TestCase):
    def make_calibrated(self):
        detector = PoseGestureInterpreter(calibration_frames=4)
        result = None
        for frame in range(4):
            result = detector.update(0.50, 0.50, 0.20, now=frame * 0.03)
        self.assertTrue(result.calibrated)
        self.assertEqual(result.target_lane, 1)
        return detector

    def test_maps_body_position_to_three_lanes_with_hysteresis(self):
        detector = self.make_calibrated()

        events = [detector.update(0.58, 0.50, 0.20, now=1 + i * 0.03) for i in range(4)]
        self.assertIn(2, [event.target_lane for event in events])
        self.assertEqual(detector.current_lane, 2)

        # Pequeno tremor perto da direita nao deve alternar a faixa.
        for i in range(4):
            result = detector.update(0.55, 0.50, 0.20, now=2 + i * 0.03)
            self.assertIsNone(result.target_lane)

        events = [detector.update(0.50, 0.50, 0.20, now=3 + i * 0.03) for i in range(5)]
        self.assertIn(1, [event.target_lane for event in events])

    def test_jump_fires_once_until_body_returns_to_center(self):
        detector = self.make_calibrated()

        first_jump = detector.update(0.50, 0.43, 0.20, now=1.0)
        self.assertTrue(first_jump.jump)
        self.assertFalse(detector.update(0.50, 0.42, 0.20, now=1.1).jump)

        for i in range(8):
            detector.update(0.50, 0.50, 0.20, now=2.0 + i * 0.05)
        second_jump = detector.update(0.50, 0.43, 0.20, now=3.0)
        self.assertTrue(second_jump.jump)

    def test_crouch_is_held_until_player_stands_again(self):
        detector = self.make_calibrated()
        results = [detector.update(0.50, 0.56, 0.20, now=1 + i * 0.05) for i in range(3)]
        self.assertTrue(results[-1].crouching)

        # A histerese mantem a pose mesmo com uma pequena oscilacao.
        self.assertTrue(detector.update(0.50, 0.52, 0.20, now=1.3).crouching)
        results = [detector.update(0.50, 0.50, 0.20, now=2 + i * 0.05) for i in range(5)]
        self.assertFalse(results[-1].crouching)

    def test_recalibration_forgets_previous_center(self):
        detector = self.make_calibrated()
        detector.reset_calibration()
        self.assertFalse(detector.calibrated)
        for frame in range(4):
            result = detector.update(0.62, 0.54, 0.18, now=frame * 0.03)
        self.assertTrue(result.calibrated)
        self.assertAlmostEqual(detector.base_x, 0.62)
        self.assertAlmostEqual(detector.base_y, 0.54)


if __name__ == "__main__":
    unittest.main()
