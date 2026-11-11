"""Offline username resolution tests for the coffee pass feature."""
import ast
from pathlib import Path
import json
import re
from types import SimpleNamespace
import unittest

SOURCE=Path(__file__).resolve().parent.parent/'Habbo_Companion.pyw'
tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
names={'incoming_packet_is','room_user_ids_from_packet','removed_room_user_index',
       'build_coffee_pass_sequence'}
funcs=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
constants=[node for node in tree.body
           if isinstance(node,ast.Assign) and any(
               isinstance(target,ast.Name) and target.id in ('ROOM_USER_PAIR_RE','ROOM_USER_INDEX_RE')
               for target in node.targets)]
namespace={'re':re,'json':json}
exec(compile(ast.Module(body=constants+funcs,type_ignores=[]),str(SOURCE),'exec'),namespace)
parse=namespace['room_user_ids_from_packet']
builder=namespace['build_coffee_pass_sequence']
removed=namespace['removed_room_user_index']

class Var:
    def __init__(self,value):self.value=value
    def get(self):return self.value

class UsernameCoffeeTests(unittest.TestCase):
    def test_name_id_prefix_without_relying_on_entity_tail(self):
        packet=(' {in:Users}{i:2}'
                '{i:68808036}{s:"Atuu"}{s:"motto"}{s:"hd-180-1"}{i:7}'
                '{i:68446836}{s:"Micro"}{s:"hello"}{s:"hd-185-1"}{i:9}'
                '{s:"new changed tail fields"}')
        found=parse(packet)
        self.assertEqual(found['atuu'],('Atuu',68808036,7))
        self.assertEqual(found['micro'],('Micro',68446836,9))

    def test_room_names_are_only_taken_from_named_incoming_users_packet(self):
        for packet in ('{in:Chat}{i:68808036}{s:"Atuu"}',
                       '{out:Users}{i:68808036}{s:"Atuu"}',
                       '[Unknown] {i:68808036}{s:"Atuu"}',None):
            self.assertEqual(parse(packet),{})

    def test_does_not_guess_invalid_id(self):
        self.assertEqual(parse('{in:Users}{i:0}{s:"Atuu"}'),{})
        self.assertEqual(parse('{in:Users}{s:"Atuu"}'),{})
        self.assertEqual(parse('{in:Users}{i:68808036}{s:"Atuu"}')['atuu'][1],68808036)

    def test_json_escaped_username(self):
        found=parse(r'{in:Users}{i:15}{s:"A\"B"}')
        self.assertEqual(found['a"b'][1],15)

    def test_single_cup_uses_only_first_furniture(self):
        self.assertEqual(builder('476989081','', '68808036',single_cup=True),(
            '{out:UseFurniture}{i:476989081}{i:0}',
            '{out:PassCarryItem}{i:68808036}',
        ))
        with self.assertRaises(ValueError):
            builder('xyz','', '68808036',single_cup=True)

    def test_room_leave_index_parser(self):
        self.assertEqual(removed('{in:UserRemove}{s:"9"}'),9)
        self.assertIsNone(removed('{in:Users}{s:"9"}'))

    def test_username_resolution_is_case_insensitive(self):
        cls=next(node for node in tree.body
                 if isinstance(node,ast.ClassDef) and node.name=='ChatOverlayApp')
        fn=next(node for node in cls.body
                if isinstance(node,ast.FunctionDef) and node.name=='_resolve_coffee_recipient')
        ns={}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),str(SOURCE),'exec'),ns)
        resolve=ns['_resolve_coffee_recipient']
        obj=SimpleNamespace(coffee_username_var=Var(' aTuU '),
                            coffee_recipient_var=Var('999'),
                            _room_users={'atuu':('Atuu',68808036,7)})
        self.assertEqual(resolve(obj),('68808036','Atuu'))
        obj.coffee_username_var=Var('SomeoneElse')
        with self.assertRaisesRegex(ValueError,'not found'):
            resolve(obj)  # must NOT quietly send to the fallback ID
        obj.coffee_username_var=Var('')
        self.assertEqual(resolve(obj),('999',''))

if __name__=='__main__':
    unittest.main()
