"""Offline duplicate chat delivery checks."""
import unittest

from clientless_bot import ClientlessChatDeduplicator


class ClientlessChatDedupTests(unittest.TestCase):
    def test_six_accounts_one_public_message(self):
        cache=ClientlessChatDeduplicator()
        results=[cache.should_display(str(i),123,'Chat',77,'hello',10+i/10)
                 for i in range(6)]
        self.assertEqual(results,[True,False,False,False,False,False])

    def test_two_identical_messages_are_not_collapsed(self):
        cache=ClientlessChatDeduplicator()
        results=[cache.should_display(account,123,'Chat',77,'hello',now)
                 for account,now in [('a',10),('a',10.1),('b',10.2),
                                     ('b',10.3),('c',10.4),('c',10.5)]]
        self.assertEqual(results,[True,True,False,False,False,False])

    def test_private_and_unknown_room_messages_stay_separate(self):
        cache=ClientlessChatDeduplicator()
        for kind,room in [('Whisper',123),('Chat',None)]:
            for account in ('a','b'):
                self.assertTrue(cache.should_display(account,room,kind,77,'hello',10))

    def test_room_sender_kind_and_text_are_distinct(self):
        cache=ClientlessChatDeduplicator()
        for room,kind,index,message in [(123,'Chat',77,'hello'),
                (124,'Chat',77,'hello'),(123,'Shout',77,'hello'),
                (123,'Chat',78,'hello'),(123,'Chat',77,'other')]:
            self.assertTrue(cache.should_display('a',room,kind,index,message,10))
            self.assertFalse(cache.should_display('b',room,kind,index,message,10.1))

    def test_old_delivery_expires_and_cache_is_bounded(self):
        cache=ClientlessChatDeduplicator()
        self.assertTrue(cache.should_display('a',123,'Chat',77,'hello',10))
        self.assertTrue(cache.should_display('b',123,'Chat',77,'hello',12.1))
        for i in range(600):
            cache.should_display('a',123,'Chat',77,str(i),13)
        self.assertLessEqual(len(cache._recent),512)


class ClientlessChatNamesTests(unittest.TestCase):
    def setUp(self):
        import ast
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import Mock
        source=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
        names={'_bot_chat_sender_name','_bot_show_chat'}
        nodes=[n for n in ast.walk(ast.parse(source.read_text(encoding='utf-8')))
               if isinstance(n,ast.FunctionDef) and n.name in names]
        scope={'time':SimpleNamespace(monotonic=lambda:10,strftime=lambda fmt:'20:24:11')}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),scope)
        self.app=SimpleNamespace(_tcp_generation={'a':1,'b':2,'c':3},
            _bot_anti_afk_rooms={'a':99,'b':99,'c':100},
            _coffee_room_state={
                'a':dict(generation=1,room=99,players={1:(77,'Alice')}),
                'b':dict(generation=2,room=99,players={2:(78,'Bob')}),
                'c':dict(generation=3,room=100,players={3:(79,'Other')})},
            _bot_follow_room_bots={'a':dict(generation=1,room=99,
                units={80:('RoomBot',1,1,42)})},
            _coffee_session=lambda ident:object(),bot_chat_log=Mock(),
            _bot_chat_dedup=ClientlessChatDeduplicator())
        self.app.bot_chat_log.winfo_exists.return_value=True
        self.app.bot_chat_log.index.return_value='1.0'
        for name in names:setattr(self.app,name,scope[name].__get__(self.app))

    def test_chat_uses_player_and_bot_names_and_unknown_fallback(self):
        app=self.app
        app._bot_show_chat('a','Chat',77,'hello')
        app.bot_chat_log.insert.assert_called_with('end','20:24:11 [Room 99] Chat Alice: hello\n')
        app._bot_show_chat('a','Chat',80,'hi')
        app.bot_chat_log.insert.assert_called_with('end','20:24:11 [Room 99] Chat RoomBot: hi\n')
        app._bot_show_chat('a','Chat',79,'unknown')
        app.bot_chat_log.insert.assert_called_with('end','20:24:11 [Room 99] Chat room index 79: unknown\n')

    def test_same_room_fallback_and_stale_or_ambiguous_names(self):
        app=self.app
        self.assertEqual(app._bot_chat_sender_name('a',99,78),'Bob')
        self.assertIsNone(app._bot_chat_sender_name('a',99,79))
        app._tcp_generation['b']=3
        self.assertIsNone(app._bot_chat_sender_name('a',99,78))
        app._coffee_room_state['a']['players'][4]=(77,'Different')
        self.assertIsNone(app._bot_chat_sender_name('a',99,77))

    def test_public_chat_stays_deduplicated(self):
        app=self.app
        app._bot_show_chat('a','Chat',77,'hello')
        app._bot_show_chat('b','Chat',77,'hello')
        self.assertEqual(app.bot_chat_log.insert.call_count,1)
        app._bot_show_chat('a','Whisper',77,'private')
        app._bot_show_chat('b','Whisper',77,'private')
        self.assertEqual(app.bot_chat_log.insert.call_count,3)
