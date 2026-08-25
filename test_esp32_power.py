import socket
import time
import unittest

from esp32_power import (
    Esp32PowerController,
    MotionPowerSystem,
    SensorSample,
    parse_sensor_packet,
)


class SensorPacketTests(unittest.TestCase):
    def test_parses_current_packet_with_accelerometer_and_gyroscope(self):
        sample = parse_sensor_packet(
            b"COW1,42,0.125,-0.250,0.980,12.5,-20.0,185.0"
        )
        self.assertIsNotNone(sample)
        self.assertEqual(sample.sequence, 42)
        self.assertAlmostEqual(sample.az, 0.98)
        self.assertAlmostEqual(sample.gz, 185.0)

    def test_keeps_compatibility_with_old_accelerometer_packet(self):
        sample = parse_sensor_packet("0.100,0.200,0.970")
        self.assertIsNotNone(sample)
        self.assertEqual((sample.gx, sample.gy, sample.gz), (0.0, 0.0, 0.0))

    def test_rejects_invalid_or_unbounded_packets(self):
        for payload in (
            "",
            "COW1,1,0,0,1,0,0",
            "COW1,1,nan,0,1,0,0,0",
            "COW1,1,20,0,1,0,0,0",
            "qualquer coisa",
        ):
            self.assertIsNone(parse_sensor_packet(payload))


class MotionPowerSystemTests(unittest.TestCase):
    @staticmethod
    def still(gyro=0.0):
        return SensorSample(0.0, 0.0, 1.0, 0.0, 0.0, gyro)

    @staticmethod
    def shake():
        return SensorSample(1.0, 0.0, 1.0)

    def charged_system(self):
        system = MotionPowerSystem(
            charge_per_shake=0.25,
            shake_threshold=0.5,
            shake_release_threshold=0.2,
            twist_threshold_dps=180.0,
            settle_seconds=0.2,
            shield_seconds=10.0,
        )
        now = 0.0
        system.update(self.still(), now)
        for _ in range(4):
            now += 0.10
            system.update(self.shake(), now)
            now += 0.05
            system.update(self.still(), now)
            now += 0.05
            system.update(self.still(), now)
        return system, now

    def test_shakes_charge_the_power_without_activating_it(self):
        system, _ = self.charged_system()
        self.assertEqual(system.charge_ratio, 1.0)
        self.assertTrue(system.armed)
        self.assertFalse(system.twist_ready)
        self.assertFalse(system.shield_active(1.0))

    def test_settle_then_twist_activates_one_collision_shield(self):
        system, now = self.charged_system()

        now += 0.05
        system.update(self.still(), now)
        now += 0.25
        system.update(self.still(), now)
        self.assertTrue(system.twist_ready)

        now += 0.05
        events = system.update(self.still(gyro=220.0), now)
        self.assertEqual(events, ("shield",))
        self.assertTrue(system.shield_active(now))
        self.assertTrue(system.absorb_collision(now + 0.1))
        self.assertFalse(system.absorb_collision(now + 0.2))

    def test_twist_before_settling_does_not_activate(self):
        system, now = self.charged_system()
        events = system.update(self.still(gyro=250.0), now + 0.01)
        self.assertEqual(events, ())
        self.assertFalse(system.shield_active(now + 0.01))


class Esp32PowerControllerTests(unittest.TestCase):
    def test_controller_reports_connection_without_needing_live_hardware(self):
        controller = Esp32PowerController(connected_timeout=1.0)
        controller.set_enabled(True, reset=True)
        accepted = controller.process_datagram(
            "COW1,7,0,0,1,0,0,0",
            source_ip="192.168.4.1",
            now=5.0,
        )
        snapshot = controller.snapshot(now=5.5)

        self.assertTrue(accepted)
        self.assertTrue(snapshot.connected)
        self.assertEqual(snapshot.status, "CONECTADO")
        self.assertEqual(snapshot.source_ip, "192.168.4.1")
        self.assertEqual(snapshot.packets_received, 1)
        self.assertFalse(controller.snapshot(now=6.2).connected)

    def test_udp_listener_receives_a_real_local_datagram(self):
        controller = Esp32PowerController(host="127.0.0.1", port=0)
        controller.start()
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            deadline = time.monotonic() + 1.0
            while controller.listening_port == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            if controller.listening_port == 0:
                status = controller.snapshot().status
                if "Operation not permitted" in status or "Permission denied" in status:
                    self.skipTest("ambiente isolado bloqueou a abertura do socket UDP")
                self.fail(f"receptor UDP nao iniciou: {status}")

            sender.sendto(
                b"COW1,9,0,0,1,0,0,0",
                ("127.0.0.1", controller.listening_port),
            )
            while (
                controller.snapshot().packets_received == 0
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            self.assertEqual(controller.snapshot().packets_received, 1)
        finally:
            sender.close()
            controller.stop()


if __name__ == "__main__":
    unittest.main()
