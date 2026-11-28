"""Offline tests for source-derived clientless bot action integration.

No real sockets, cookies, game servers, accounts or G-Earth launched.
"""
import struct
import threading
import unittest
from unittest import mock

import clientless_bot as bot
import habbo_tcp as tcp

RELEASE=tcp.TCP_FALLBACK_RELEASE
OUT={
    "GetGuestRoom":225,"Quit":226,"MoveAvatar":227,"LookTo":228,
    "Chat":229,"Shout":230,"Whisper":231,"Dance":232,
    "Sign":233,"ChangePosture":234,
}
IN={"Chat":311,"Shout":312,"Whisper":313,"RoomReady":314}
MAPPING={"release":RELEASE,"outgoing":OUT,"incoming":IN}


class ActionCompositionTests(unittest.TestCase):
    def test_random_basic_figures_and_release_bound_outfit_packet(self):
        import random
        for mode,expected in (("Male","M"),("Female","F"),("Mixed",None)):
            rng=random.Random(15)
            looks=[bot.random_clientless_figure(mode,rng) for _ in range(10)]
            self.assertGreater(len(set(looks)),1)
            for gender,figure in looks:
                if expected:self.assertEqual(gender,expected)
                self.assertEqual({p[:2] for p in figure.split(".")},{"hd","hr","ch","lg","sh"})
                pkt=bot.encode_clientless_action(None,bot.BUNDLED_AIR_RELEASE,
                    "Change outfit",gender=gender,figure=figure)
                self.assertEqual(pkt,((1038,bot._packet_string(gender)+bot._packet_string(figure),
                                      "UpdateFigureData"),))
        for gender,figure in (("X","hd-180-1.ch-210-66"),("M","invalid"),
                              ("F","hd-600-1.hd-620-2")):
            with self.assertRaises(bot.ClientlessBotError):
                bot.build_clientless_action("Change outfit",gender=gender,figure=figure)
        self.assertEqual(bot.encode_clientless_action(MAPPING,RELEASE,"Change outfit",
            gender="M",figure="hd-180-1.ch-210-66")[0][0],1038)

    def test_room_join_matches_source_two_step_flags(self):
        frames=bot.encode_clientless_action(MAPPING,RELEASE,"Join room",room=123456)
        self.assertEqual(frames,(
            (225,struct.pack(">iii",123456,0,1),"GetGuestRoom"),
            (225,struct.pack(">iii",123456,1,0),"GetGuestRoom")))
        self.assertEqual(bot.encode_clientless_action(
            MAPPING,RELEASE,"Leave room"),((226,b"","Quit"),))

    def test_movement_and_facing_are_distinct(self):
        self.assertEqual(bot.encode_clientless_action(
            MAPPING,RELEASE,"Walk",x=4,y=9),
            ((227,struct.pack(">ii",4,9),"MoveAvatar"),))
        self.assertEqual(bot.encode_clientless_action(
            MAPPING,RELEASE,"Face tile",x=4,y=9),
            ((228,struct.pack(">ii",4,9),"LookTo"),))

    def test_chat_and_whisper_use_habbo_string_prefix(self):
        # Observed AIR ChatMessageComposer.getMessageArray():
        # [text, styleId, chatTrackingId] where default trackingId = -1.
        say=bot.encode_clientless_action(MAPPING,RELEASE,"Say",text="Hello ✓")
        self.assertEqual(say[0][2],"Chat")
        self.assertEqual(say[0][1],
                         bot._packet_string("Hello ✓")+struct.pack(">ii",0,-1))
        # Shout and Whisper each contain exactly two fields in the AIR source.
        shout=bot.encode_clientless_action(MAPPING,RELEASE,"Shout",text="Hello ✓")
        self.assertEqual(shout[0][2],"Shout")
        self.assertEqual(shout[0][1],
                         bot._packet_string("Hello ✓")+struct.pack(">i",0))
        pkt=bot.encode_clientless_action(
            MAPPING,RELEASE,"Whisper",recipient="Alice",text="hey")
        self.assertEqual(pkt[0][1],bot._packet_string("Alice hey")+struct.pack(">i",0))
        self.assertEqual(pkt[0][2],"Whisper")

    def test_chat_payload_matches_air_three_field_contract(self):
        # Real AIR defaults: style=0; tracking=-1. Verify full wire frame
        # (without guessing a production header for the current release).
        packet_id,body,name=bot.encode_clientless_action(
            MAPPING,RELEASE,"Say",text="test123")[0]
        self.assertEqual(name,"Chat")
        self.assertEqual(packet_id,OUT["Chat"])
        self.assertEqual(body,struct.pack(">H",7)+b"test123"
                         +struct.pack(">ii",0,-1))
        self.assertEqual(len(body),17)

    def test_dance_sign_posture_values_are_constrained(self):
        for action,kw,name in (
            ("Dance",{"dance":4},"Dance"),("Dance",{"dance":0},"Dance"),
            ("Sign",{"sign":14},"Sign"),("Posture",{"posture":1},"ChangePosture"),
        ):
            result=bot.encode_clientless_action(MAPPING,RELEASE,action,**kw)
            self.assertEqual(result[0][2],name)
            self.assertEqual(result[0][1],struct.pack(">i",list(kw.values())[0]))
        for action,kw in (
            ("Dance",{"dance":5}),("Sign",{"sign":-1}),
            ("Posture",{"posture":7}),("Join room",{"room":-4}),
            ("Walk",{"x":1024,"y":1}),("Face tile",{"x":True,"y":1}),
            ("Say",{"text":""}),("Shout",{"text":"x\nf"}),
            ("Whisper",{"recipient":"Alice\nBob","text":"hello"}),
            ("Whisper",{"recipient":"Alice","text":"x"*180}),
        ):
            with self.subTest(action=action,kwargs=kw):
                with self.assertRaises(bot.ClientlessBotError):
                    bot.build_clientless_action(action,**kw)
        with self.assertRaises(bot.ClientlessBotError):
            bot.build_clientless_action("Raw packet",packet_id=999,payload=b"hi")

    def test_mapping_metadata_is_whitelisted_and_ambiguous_dropped(self):
        outgoing={55:[{"Name":"Dance"}],77:[{"Name":"Chat"}],
                  85:[{"Name":"RoomReady"}],95:[{"Name":"Unrelated"}],
                  10:[{"Name":"MoveAvatar"}],11:[{"Name":"MoveAvatar"}]}
        incoming={70:[{"Name":"Chat"}],71:[{"Name":"Shout"}]}
        result=bot.capture_clientless_headers(outgoing,incoming,RELEASE)
        self.assertEqual(result["outgoing"],{"Dance":55,"Chat":77})
        self.assertEqual(result["incoming"],{"Chat":70,"Shout":71})
        with self.assertRaises(bot.ClientlessBotError):
            bot.capture_clientless_headers({},incoming,RELEASE)

    def test_packet_mapping_rejects_stale_and_unsafe_inputs(self):
        with self.assertRaisesRegex(bot.ClientlessBotError,"different AIR release"):
            bot.encode_clientless_action(MAPPING,"WIN63-202601121721-391685409",
                                         "Dance",dance=1)
        with self.assertRaisesRegex(bot.ClientlessBotError,"missing"):
            bot.encode_clientless_action({
                "release":RELEASE,"outgoing":{"Dance":232},"incoming":{}},
                RELEASE,"Walk",x=3,y=6)
        for broken in (
            {"release":RELEASE,"outgoing":{"Dance":True},"incoming":{}},
            {"release":RELEASE,"outgoing":{"Dance":232,"Chat":232},"incoming":{}},
            {"release":RELEASE,"outgoing":{"Unknown":232},"incoming":{}},
            {"release":RELEASE,"outgoing":{"Dance":232},"incoming":{"Bad":30}},
        ):
            with self.subTest(mapping=broken):
                with self.assertRaises(bot.ClientlessBotError):
                    bot.validate_clientless_headers(broken,RELEASE)

    def test_chat_parser_only_handles_matching_bounded_events(self):
        payload=struct.pack(">i",17)+bot._packet_string("Hi there")+"trailer".encode()
        self.assertEqual(bot.decode_clientless_chat(MAPPING,RELEASE,311,payload),
                         ("Chat",17,"Hi there"))
        self.assertIsNone(bot.decode_clientless_chat(MAPPING,RELEASE,4000,payload))
        self.assertIsNone(bot.decode_clientless_chat(
            MAPPING,RELEASE,311,struct.pack(">iH",15,80)+b"x"))
        self.assertIsNone(bot.decode_clientless_chat(
            MAPPING,RELEASE,311,struct.pack(">iH",15,1)+b"\xff"))
        with self.assertRaises(bot.ClientlessBotError):
            bot.decode_clientless_chat(MAPPING,"WIN63-202601121721-391685409",
                                       311,payload)


class ConnectedSessionActionTests(unittest.TestCase):
    def test_actions_require_authenticated_socket(self):
        session=tcp.HabboTcpSession("abcdef123456")
        with self.assertRaisesRegex(tcp.HabboTcpError,"not authenticated"):
            session.send_game_action(232,b"")
        session.sock=mock.Mock()
        session.stop.clear()
        session.authenticated=True
        with mock.patch.object(session,"_send") as sender:
            session.send_game_action(232,struct.pack(">i",1))
            sender.assert_called_once_with(232,struct.pack(">i",1))
        for packet_id,body in ((-1,b""),(0,b""),(65536,b""),
                               (True,b""),(232,b"x"*9000),(232,"not bytes")):
            with self.subTest(packet_id=packet_id):
                with self.assertRaises(tcp.HabboTcpError):
                    session.send_game_action(packet_id,body)
        session.close()
        self.assertIsNone(session.release)
        with self.assertRaises(tcp.HabboTcpError):
            session.send_game_action(232,b"")

    def test_content_callback_is_optional_and_does_not_require_raw_logs(self):
        session=tcp.HabboTcpSession("abcdef123456")
        self.assertIsNone(session.on_content)
        incoming=[]
        other=tcp.HabboTcpSession(
            "abcdef123456",content=lambda packet_id,body:incoming.append((packet_id,body)))
        self.assertTrue(callable(other.on_content))


if __name__=="__main__":
    unittest.main()
