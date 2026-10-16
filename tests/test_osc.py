import time
import unittest
from core.osc_receiver import build_osc_message, parse_osc_message, OSCReceiver
from core.osc_broadcaster import OSCBroadcaster

class TestOSC(unittest.TestCase):
    def test_build_and_parse_message(self):
        # 1. Mensaje con float
        raw = build_osc_message("/seek", [12.5])
        addr, args = parse_osc_message(raw)
        self.assertEqual(addr, "/seek")
        self.assertAlmostEqual(args[0], 12.5, places=3)

        # 2. Mensaje con int y string
        raw2 = build_osc_message("/cue", [1, "intro"])
        addr2, args2 = parse_osc_message(raw2)
        self.assertEqual(addr2, "/cue")
        self.assertEqual(args2[0], 1)
        self.assertEqual(args2[1], "intro")

        # 3. Mensaje simple sin argumentos (/play)
        raw3 = build_osc_message("/play", [])
        addr3, args3 = parse_osc_message(raw3)
        self.assertEqual(addr3, "/play")
        self.assertEqual(len(args3), 0)

    def test_receiver_and_broadcaster_loopback(self):
        received = []

        receiver = OSCReceiver(port=9753, host="127.0.0.1")
        receiver.on("/cue", lambda addr, args: received.append((addr, args)))
        receiver.start()

        time.sleep(0.1)

        broadcaster = OSCBroadcaster(target_host="127.0.0.1", port=9753)
        broadcaster.send("/cue", [2, "sala_noche"])

        # Esperar recepción
        for _ in range(10):
            if received:
                break
            time.sleep(0.05)

        receiver.stop()
        broadcaster.close()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], "/cue")
        self.assertEqual(received[0][1][0], 2)
        self.assertEqual(received[0][1][1], "sala_noche")

if __name__ == "__main__":
    unittest.main()
