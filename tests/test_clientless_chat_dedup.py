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
