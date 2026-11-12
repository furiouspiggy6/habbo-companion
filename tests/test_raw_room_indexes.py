"""Recover actual room avatar indexes from the typed binary Users prefixes.

Later fields in G-Python's HEntity parser vary by client generation, so
a valid roster can fail an old full-entity parser even when the prefix is
still valid. Account ID != room index.
"""
import ast
import re
from pathlib import Path
import unittest
from types import SimpleNamespace

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
CODE=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(CODE)
FN=next(n for n in TREE.body if isinstance(n,ast.FunctionDef)
        and n.name=='room_users_from_binary_prefixes')
ns={'re':re}
exec(compile(ast.Module(body=[FN],type_ignores=[]),str(SOURCE),'exec'),ns)
parse=ns['room_users_from_binary_prefixes']

def i32(v):
    return int(v).to_bytes(4,'big',signed=True)

def s(value):
    b=value.encode('iso-8859-1')
    return len(b).to_bytes(2,'big')+b

def user(ident,name,index):
    return (i32(ident)+s(name)+s('motto:testing')+s('hr-100-42.hd-180-1')
            +i32(index)+i32(5)+i32(11)+s('1.25')+i32(2)+i32(1))

def packet(data,count):
    return SimpleNamespace(bytearray=bytearray(i32(0)+b'\x00\x7f'
                                             +i32(count)+data))

class UsersPrefixTests(unittest.TestCase):
    def test_self_account_id_matches_actual_room_index_without_full_tail(self):
        # The second entity is the user and the first entity has an
        # intentionally unknown tail. Do not depend on parsing that tail.
        p=packet(user(16212392,'Atuu',8)+b'\xfd\xfe\xff'
                 +user(69016008,'dan.alt100',27)+b'\x99\x88\x77',2)
        known={'atuu':('Atuu',16212392,None),
               'dan.alt100':('dan.alt100',69016008,None)}
        found=parse(p,known)
        self.assertEqual(found['dan.alt100'],('dan.alt100',69016008,27))
        self.assertEqual(found['atuu'],('Atuu',16212392,8))
        self.assertNotEqual(found['dan.alt100'][1],found['dan.alt100'][2])

    def test_first_user_index_extracted_even_if_tail_cannot_be_decoded(self):
        p=packet(user(69016008,'dan.alt100',43)+b'\x00\xfe\xaa\xdd',1)
        self.assertEqual(parse(p,{'dan.alt100':('dan.alt100',69016008,None)})
                         ['dan.alt100'][2],43)

    def test_fifty_player_roster_handles_own_avatar_in_the_middle(self):
        people=[user(100000+i,'user'+str(i),i+1)+b'\xff'
                for i in range(24)]
        people.append(user(69016008,'dan.alt100',104))
        people.extend(user(200000+i,'other'+str(i),i+200)+b'\xee'
                      for i in range(25))
        known={'user'+str(i):('user'+str(i),100000+i,None)
               for i in range(24)}
        known.update({'other'+str(i):('other'+str(i),200000+i,None)
                      for i in range(25)})
        known['dan.alt100']=('dan.alt100',69016008,None)
        found=parse(packet(b''.join(people),50),known)
        self.assertEqual(len(found),50)
        self.assertEqual(found['dan.alt100'],('dan.alt100',69016008,104))

    def test_does_not_treat_arbitrary_four_byte_integer_as_an_avatar(self):
        p=packet(i32(69016008)+s('dan.alt100')+s('motto')+
                 s('figure')+i32(12)+i32(999999)+i32(200000)+
                 b'broken tail',1)
        self.assertEqual(parse(p,{'dan.alt100':('dan.alt100',69016008,None)}),{})

    def test_invalid_or_ambiguous_room_rosters_are_rejected(self):
        known={'dan.alt100':('dan.alt100',69016008,None)}
        self.assertEqual(parse(packet(b'',0),known),{})
        self.assertEqual(parse(packet(b'',501),known),{})
        p=packet(user(69016008,'dan.alt100',5)
                 +user(69016008,'dan.alt100',8),2)
        self.assertEqual(parse(p,known),{})
        self.assertEqual(parse(p,{'dan.alt100':('dan.alt100',99999,None)}),{})
        self.assertEqual(parse(p),{})

    def test_still_only_invoked_for_real_incoming_users_packet(self):
        hook=CODE[CODE.index("elif kind=='Users':"):
                  CODE.index("if self.config.get('whispers_right',True):",
                             CODE.index("elif kind=='Users':"))]
        self.assertIn('users.update(room_users_from_binary_prefixes(',hook)
        self.assertIn('msg.packet,trusted)',hook)
        self.assertIn("('room_users_binary',bytes(raw))",hook)
        self.assertIn("self._recover_own_room_index_from_snapshot()",CODE)
        self.assertIn('users.update(full_room_users_from_packet(msg.packet))',hook)

if __name__=='__main__':
    unittest.main()
