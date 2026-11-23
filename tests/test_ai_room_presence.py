"""Regression tests for real room membership versus stale AI checkbox names."""
import runpy
from pathlib import Path
import time
import unittest

from persona_responder import (
    current_room_player_names, ROOM_FALLBACK_PRESENCE_SECONDS,
)

ROOT=Path(__file__).resolve().parents[1]


class RoomPresenceTests(unittest.TestCase):
    def test_a_spoken_name_does_not_live_forever(self):
        now=2000.0
        speakers={
            'recent':('Recent',now-10),
            'gone':('Gone',now-ROOM_FALLBACK_PRESENCE_SECONDS-1),
        }
        names=current_room_player_names({}, {}, speakers, now=now)
        self.assertEqual(names,['Recent'])
        self.assertEqual(current_room_player_names(
            {},{},speakers,now=now+ROOM_FALLBACK_PRESENCE_SECONDS+20),[])

    def test_room_indexed_users_stay_until_habbo_removes_them(self):
        scope=runpy.run_path(str(ROOT/'Habbo_Companion.pyw'),
                             run_name='test_room_roster')
        merge=scope['merge_room_user_records']
        remove=scope['remove_room_user_by_index']
        original={
            'alice':('Alice',101,3),
            'bob':('Bob',102,5),
        }
        later={'alice':('Alice',101,None)}
        combined=merge(original,later)
        self.assertEqual(combined['alice'],('Alice',101,3),
                         'Later partially decoded Users must not erase room index')
        displayed=current_room_player_names(
            combined,{}, {},now=5000.0)
        self.assertEqual(displayed,['Alice','Bob'])
        after,removed=remove(combined,3)
        self.assertEqual(removed,('alice',))
        self.assertEqual(
            current_room_player_names(after,{}, {},now=5000.0),['Bob'])

    def test_mismatched_account_id_never_retains_previous_room_index(self):
        scope=runpy.run_path(str(ROOT/'Habbo_Companion.pyw'),
                             run_name='test_room_roster')
        merge=scope['merge_room_user_records']
        got=merge({'alice':('Alice',101,3)},
                  {'alice':('Alice',999,None)})
        self.assertEqual(got['alice'],('Alice',999,None))

    def test_unindexed_room_roster_entries_age_out_unless_chat_is_recent(self):
        now=10000.0
        unindexed={
            'present':('Present',700,None),
            'old':('Old',701,None),
        }
        seen={'present':now-20,'old':now-ROOM_FALLBACK_PRESENCE_SECONDS-1}
        self.assertEqual(current_room_player_names(
            unindexed,seen,{},now=now),['Present'])
        speakers={'old':('Old',now-5)}
        self.assertEqual(current_room_player_names(
            unindexed,seen,speakers,now=now),['Old','Present'])

    def test_do_not_list_self_or_historical_log_names(self):
        now=time.time()
        names=current_room_player_names(
            {'me':('MyAvatar',123,2),'bob':('Bob',456,9)},
            {'me':now,'bob':now},
            {'old':('OldSpeaker',now-1000)},
            own_name='myavatar',now=now)
        self.assertEqual(names,['Bob'])
        self.assertNotIn('OldSpeaker',names)


if __name__=='__main__':
    unittest.main()
