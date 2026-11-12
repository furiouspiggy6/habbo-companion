"""Local authenticated Habbo.com session -> Direct Classic ticket retrieval.

All test responses are fake; no actual Habbo requests or session cookies.
"""
import ast
import re
from pathlib import Path
import unittest

from local_classic_launch import parse_classic_ticket

APP=Path(__file__).resolve().parents[1]/"Habbo_Companion.pyw"
SOURCE=APP.read_text(encoding="utf-8")
TREE=ast.parse(SOURCE)
NAMES={"account_parse_official_ticket_response",
       "account_fetch_ticket_from_signed_in_profile"}
NODES=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in NAMES]
JS=next(ast.literal_eval(n.value) for n in TREE.body
        if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=="HABBO_SESSION_TICKET_JS"
                for t in n.targets))


def make_scope(page=None,response=None):
    scope={"re":re,"parse_classic_ticket":parse_classic_ticket,
           "HABBO_SESSION_TICKET_JS":JS}
    exec(compile(ast.Module(body=NODES,type_ignores=[]),
                 str(APP),"exec"),scope)
    calls=[]
    scope["account_habbo_page"]=lambda port:page
    def cdp(ws,method,params,timeout=0):
        calls.append((ws,method,params,timeout))
        return response
    scope["account_cdp_call"]=cdp
    return scope,calls


TICKET="b6fa0b5a-268a-46a6-988d-3a684b45067c"


class OfficialTicketFormatTests(unittest.TestCase):
    def test_existing_authenticated_session_response_shapes(self):
        scope,_=make_scope()
        parse=scope["account_parse_official_ticket_response"]
        for raw in (
            "hhus."+TICKET+".V4.dan.alt100",
            TICKET+".V4.dan.alt100",
            "habbo://hab?server=hhus&token="+TICKET+".V4.dan.alt100",
        ):
            ticket=parse(raw)
            self.assertEqual(ticket.server_id,"hhus")
            self.assertEqual(ticket.secret,TICKET+".V4")
            self.assertEqual(ticket.username,"dan.alt100")

    def test_no_unsupported_ticket_formats_are_guessed(self):
        scope,_=make_scope()
        parse=scope["account_parse_official_ticket_response"]
        for raw in (
            None, "", "not-a-ticket", "hhes."+TICKET+".V4",
            "http://external.example/ticket", "hhus."+TICKET+".V4;foo",
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    parse(raw)


class NoBrowserUiTicketRetrievalTests(unittest.TestCase):
    def test_authenticated_profile_fetches_only_official_api(self):
        page={"url":"https://www.habbo.com/",
              "webSocketDebuggerUrl":"ws://127.0.0.1:43210/devtools/page/aaa",
              "_preflight_step":{"kind":"play"}}
        response={"result":{"value":{"kind":"ticket",
                                     "value":"hhus."+TICKET+".V4.d277"}}}
        scope,calls=make_scope(page,response)
        ticket=scope["account_fetch_ticket_from_signed_in_profile"](43210)
        self.assertEqual(ticket.username,"d277")
        self.assertEqual(ticket.secret,TICKET+".V4")
        self.assertEqual(len(calls),1)
        ws,method,params,timeout=calls[0]
        self.assertEqual(method,"Runtime.evaluate")
        self.assertIn("127.0.0.1:43210",ws)
        self.assertTrue(params["awaitPromise"])
        self.assertTrue(params["returnByValue"])
        self.assertIn("/api/client/clientnative/url",params["expression"])
        self.assertIn("credentials: 'same-origin'",params["expression"])
        self.assertEqual(timeout,13)

    def test_disconnected_and_logged_out_profiles_do_not_send_api_request(self):
        for page in (None,
                     {"url":"https://www.habbo.com/","_preflight_step":{"kind":"login"}},
                     {"url":"https://www.habbo.com/","_preflight_step":{"kind":"waiting"}},
                     {"_inspect_error":"DevTools failure"}):
            scope,calls=make_scope(page,None)
            with self.assertRaises(ValueError):
                scope["account_fetch_ticket_from_signed_in_profile"](43210)
            self.assertEqual(calls,[])

    def test_rejected_session_does_not_queue_a_token(self):
        page={"webSocketDebuggerUrl":"ws://127.0.0.1:43210/devtools/page/aaa",
              "_preflight_step":{"kind":"signed_in"}}
        response={"result":{"value":{"kind":"error","reason":"http_error","status":401}}}
        scope,calls=make_scope(page,response)
        with self.assertRaisesRegex(ValueError,"rejected the existing session"):
            scope["account_fetch_ticket_from_signed_in_profile"](43210)
        self.assertEqual(len(calls),1)

    def test_unknown_response_and_script_failure_produce_safe_message(self):
        page={"webSocketDebuggerUrl":"ws://127.0.0.1:43210/devtools/page/aaa",
              "_preflight_step":{"kind":"play"}}
        for response in (
            {"result":{"value":{"kind":"error","reason":"no_ticket_in_response"}}},
            {"result":{"value":{"kind":"ticket","value":"unexpected-secret-format"}}},
            {"exceptionDetails":{"exception":{"value":"internal"}}},
        ):
            scope,calls=make_scope(page,response)
            with self.assertRaises(ValueError) as err:
                scope["account_fetch_ticket_from_signed_in_profile"](43210)
            self.assertNotIn("unexpected-secret-format",str(err.exception))
            self.assertNotIn("internal",str(err.exception))
            self.assertEqual(len(calls),1)

    def test_javascript_never_reads_password_or_cookies(self):
        self.assertIn("location.hostname",JS)
        self.assertIn("response.json()",JS)
        self.assertIn("redirect: 'error'",JS)
        self.assertNotIn("document.cookie",JS)
        self.assertNotIn("localStorage",JS)
        self.assertNotIn("browser_token",JS)
        self.assertNotIn("password",JS)
        self.assertNotIn("https://bobba",JS)

    def test_ui_has_explicit_optional_button_and_only_memory_queue(self):
        self.assertIn("Fetch from signed-in local session",SOURCE)
        self.assertIn("account_fetch_ticket_from_signed_in_profile(",SOURCE)
        self.assertIn("('direct_ticket_fetched',account_id,ticket)",SOURCE)
        self.assertIn("self._direct_ticket_queue[ident]=ticket",SOURCE)
        self.assertNotIn("self.config['direct_ticket_queue']",SOURCE)


if __name__=="__main__":
    unittest.main()
