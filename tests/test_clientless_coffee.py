"""Offline hand-item schema and bounded settings tests."""
import unittest
import struct
import clientless_bot as bot

class CoffeeTests(unittest.TestCase):
    def test_pinned_single_actions(self):
        release=bot.BUNDLED_AIR_RELEASE
        self.assertEqual(bot.encode_clientless_action(None,release,"Collect hand item",furniture=476989081),
                         ((3753,struct.pack(">ii",476989081,0),"UseFurniture"),))
        self.assertEqual(bot.encode_clientless_action(None,release,"Pass hand item",recipient_id=123),
                         ((3129,struct.pack(">i",123),"PassCarryItem"),))
        with self.assertRaises(bot.ClientlessBotError):
            bot.encode_clientless_action(None,"WIN63-202611251140-12345","Pass hand item",recipient_id=123)
    def test_settings_are_bounded(self):
        self.assertEqual(bot.validate_clientless_coffee_settings("476989081","476989024","15","3"),
                         ((476989081,476989024),15.,3))
        self.assertEqual(bot.validate_clientless_coffee_settings("1","2","0","5"),((1,2),0.,5))
        for delay,count in [("-1","5"),("nan","5"),("10","0"),("10","6"),("inf","1"),("3601","1")]:
            with self.assertRaises(bot.ClientlessBotError):
                bot.validate_clientless_coffee_settings("1","2",delay,count)
    def test_observations_are_release_bound(self):
        release=bot.BUNDLED_AIR_RELEASE
        self.assertEqual(bot.decode_clientless_hand_observation(release,1548,struct.pack(">ii",9,2)),
                         ("carry",(9,2)))
        self.assertEqual(bot.decode_clientless_hand_observation(release,2675,struct.pack(">H",1)+b"9"),
                         ("remove",9))
        self.assertIsNone(bot.decode_clientless_hand_observation("unknown",1548,struct.pack(">ii",9,2)))
