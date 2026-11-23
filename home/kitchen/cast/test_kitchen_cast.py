import sys, types, unittest, os
# The decision needs no network: stub pychromecast so the test runs anywhere.
pc = types.ModuleType("pychromecast"); ctl = types.ModuleType("pychromecast.controllers"); dc = types.ModuleType("pychromecast.controllers.dashcast")
dc.DashCastController = object
sys.modules.update({"pychromecast": pc, "pychromecast.controllers": ctl, "pychromecast.controllers.dashcast": dc})
sys.path.insert(0, os.path.dirname(__file__))
from kitchen_cast import decide, DASHCAST_APP


class Decide(unittest.TestCase):
    def test_idle_daytime_casts(self):
        self.assertEqual(decide(None, 9), "cast")
        self.assertEqual(decide("E8C28D3C", 17), "cast")

    def test_never_over_someone_else(self):
        self.assertEqual(decide("CC32E753", 12), "in use")   # e.g. Spotify

    def test_already_up(self):
        self.assertEqual(decide(DASHCAST_APP, 12), "already showing")

    def test_overnight_left_alone(self):
        self.assertEqual(decide(None, 23), "overnight")
        self.assertEqual(decide(None, 3), "overnight")
        self.assertEqual(decide(None, 6), "cast")

    def test_force(self):
        self.assertEqual(decide(None, 2, force=True), "cast")


if __name__ == "__main__":
    unittest.main()
