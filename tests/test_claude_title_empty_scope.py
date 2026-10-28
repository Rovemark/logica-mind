"""Background title capture must not import unrelated local sessions."""
import unittest
from unittest.mock import patch
from logica_mind.web import server

class InlineThread:
    def __init__(self, *, target, **_kwargs): self.target = target
    def start(self): self.target()

class ClaudeTitleScopeTests(unittest.TestCase):
    def setUp(self):
        self.old_state = dict(server._CAPTURE_STATE)
        server._CAPTURE_STATE.update(running=False, at=-1e9)
    def tearDown(self):
        server._CAPTURE_STATE.update(self.old_state)
    def test_empty_scope_neither_scans_nor_saves_or_consumes_throttle(self):
        with patch.object(server, '_index_claude_titles', return_value={'other': {'name':'Private', 'kind':'custom'}}) as scan, \
             patch.object(server, '_load_session_names', return_value={}), \
             patch.object(server, '_save_session_names') as save, \
             patch.object(server.threading, 'Thread', InlineThread):
            server._kick_claude_capture(object(), set())
            scan.assert_not_called(); save.assert_not_called()
            self.assertEqual(server._CAPTURE_STATE, {'running': False, 'at': -1e9})
    def test_nonempty_scope_only_saves_known_ids(self):
        titles = {'mine': {'name':'Own', 'kind':'custom'}, 'other': {'name':'Private', 'kind':'custom'}}
        with patch.object(server, '_index_claude_titles', return_value=titles), \
             patch.object(server, '_load_session_names', return_value={}), \
             patch.object(server, '_save_session_names') as save, \
             patch.object(server.threading, 'Thread', InlineThread):
            server._kick_claude_capture(object(), {'mine'})
            saved = save.call_args.args[1]
            self.assertEqual(set(saved), {'mine'})
            self.assertEqual(saved['mine']['name'], 'Own')
