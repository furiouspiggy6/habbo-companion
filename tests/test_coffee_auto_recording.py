"""Automatic full-session local CSV recording of normal fast coffee loops."""
import ast
import csv
from datetime import datetime
from pathlib import Path
import tempfile
import threading
import time
import uuid
import unittest

SRC=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
CODE=SRC.read_text(encoding='utf-8')
TREE=ast.parse(CODE)
recorder_class=next(node for node in TREE.body
                    if isinstance(node,ast.ClassDef) and
                    node.name=='CoffeeSessionRecorder')
ns={'Path':Path,'csv':csv,'datetime':datetime,'threading':threading,
    'time':time,'uuid':uuid}
exec(compile(ast.Module(body=[recorder_class],type_ignores=[]),
             str(SRC),'exec'),ns)
Recorder=ns['CoffeeSessionRecorder']

class RecordingTests(unittest.TestCase):
    def test_csv_is_saved_automatically_and_has_all_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder=Recorder(Path(directory)/'coffee_sessions',0.1,
                              ('476989081','476989024','476989072'),
                              (('Atuu','16212392'),))
            self.assertTrue(recorder.path.exists())
            self.assertTrue(recorder.record('pickup_request',
                                            furniture='476989081',action_number=1))
            self.assertTrue(recorder.record('own_held_update',
                                            room_index=40928,hand_item=42))
            self.assertTrue(recorder.record('pass_request',
                                            name='Atuu',account_id='16212392',
                                            action_number=2))
            self.assertTrue(recorder.record('own_empty_update',
                                            room_index=40928,hand_item=0))
            self.assertTrue(recorder.record('target_held_update',
                                            name='Atuu',room_index=13,hand_item=42))
            result=recorder.finish('STOP pressed')
            self.assertTrue(recorder.summary_path.exists())
            self.assertFalse(recorder.record('anything'))
            self.assertEqual(result['pickups_sent'],1)
            self.assertEqual(result['passes_sent'],1)
            self.assertEqual(result['own_held'],1)
            self.assertEqual(result['own_empty'],1)
            self.assertEqual(result['target_held'],1)
            self.assertEqual(result['source_requests'],{'476989081':1})
            with open(recorder.path,newline='',encoding='utf-8') as fh:
                rows=list(csv.DictReader(fh))
            self.assertEqual(len(rows),7)
            self.assertEqual([row['event'] for row in rows],
                             ['session_start','pickup_request','own_held_update',
                              'pass_request','own_empty_update',
                              'target_held_update','session_stop'])
            self.assertEqual(rows[2]['avatar_room_index'],'40928')
            self.assertEqual(rows[4]['hand_item_type'],'0')
            summary=recorder.summary_path.read_text(encoding='utf-8')
            self.assertIn('Pickup requests by furniture: 476989081: 1',summary)
            self.assertIn('NOTE: Sent packets only confirm a local send',summary)
            self.assertIn('recipient',summary.lower())

    def test_normal_loop_timing_does_not_depend_on_server_acks(self):
        cls=next(n for n in TREE.body if isinstance(n,ast.ClassDef)
                 and n.name=='ChatOverlayApp')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef)
                    and n.name=='_coffee_loop_tick')
        txt=ast.get_source_segment(CODE,method)
        self.assertIn("recorder.record(",txt)
        self.assertIn("'pickup_request' if pickup else 'pass_request'",txt)
        self.assertIn('if self._coffee_wait_for_hand:',txt)
        self.assertIn('self.root.after(coffee_delay_ms(self._coffee_interval)',txt)
        self.assertIn('self._coffee_after_id=self.root.after',txt)

    def test_capture_is_relevant_only_and_does_not_operate_tk_from_worker(self):
        method=CODE[CODE.index('    def _record_coffee_carry('):
                    CODE.index('    def _run_coffee_speed_test(',CODE.index('    def _record_coffee_carry('))]
        self.assertIn('room_index==own_index',method)
        self.assertIn('room_index==target_index',method)
        self.assertNotIn('self.coffee_status_var.set',method)
        self.assertNotIn('self.root.after',method)
        self.assertIn('self._record_coffee_carry(carry[0],carry[1])',CODE)

    def test_spreadsheet_formula_injection_is_neutralized(self):
        with tempfile.TemporaryDirectory() as directory:
            r=Recorder(directory,0.1,('123','124'),(('=CMD','123'),))
            r.record('pass_request',name='=HYPERLINK("bad")',note='@fmla')
            r.finish('done')
            with open(r.path,newline='',encoding='utf-8') as fh:
                rows=list(csv.DictReader(fh))
            self.assertTrue(rows[1]['recipient_name'].startswith("'="))
            self.assertTrue(rows[1]['note'].startswith("'@"))

    def test_events_are_thread_safe_for_interception_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            r=Recorder(directory,0.1,('1','2'),(('A','12'),))
            def work():
                for i in range(100):
                    self.assertTrue(r.record('own_held_update',
                                             room_index=8,hand_item=i+1))
            workers=[threading.Thread(target=work) for _ in range(3)]
            for t in workers:t.start()
            for t in workers:t.join()
            stats=r.finish('done')
            self.assertEqual(stats['own_held'],300)
            with open(r.path,newline='',encoding='utf-8') as fh:
                rows=list(csv.DictReader(fh))
            self.assertEqual(len(rows),302)

    def test_size_limit_reports_error_instead_of_silently_dropping(self):
        with tempfile.TemporaryDirectory() as directory:
            r=Recorder(directory,0.1,('1','2'),(('A','12'),))
            r.MAX_BYTES=10
            self.assertFalse(r.record('pickup_request',furniture='123'))
            self.assertIn('64 MB',r.error)
            result=r.finish('recording limit')
            self.assertTrue(result['error'])
            self.assertTrue(r.summary_path.exists())

if __name__=='__main__':
    unittest.main()
