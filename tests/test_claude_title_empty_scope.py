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


class ClaudeTitleFallbackTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.projects = Path(self.temp.name) / '.claude' / 'projects' / 'fixture'
        self.projects.mkdir(parents=True)
        self.env = patch.dict('os.environ', {'HOME': self.temp.name})
        self.env.start(); self.addCleanup(self.env.stop)
        self.mine = '11111111-1111-4111-8111-111111111111'
        self.other = '22222222-2222-4222-8222-222222222222'
    def write(self, sid, text):
        import json
        (self.projects / (sid + '.jsonl')).write_text(json.dumps({'message': {'role': 'user', 'content': text}}) + '\n')
    def test_only_authorized_first_message_and_empty_scope(self):
        self.write(self.mine, 'Minha primeira mensagem')
        self.write(self.other, 'Título de outra pessoa')
        self.assertEqual(server._fallback_claude_titles(set()), {})
        result = server._fallback_claude_titles({self.mine})
        self.assertEqual(set(result), {self.mine})
        self.assertEqual(result[self.mine]['name'], 'Minha primeira mensagem')
    def test_symlink_and_oversized_line_are_refused(self):
        self.write(self.other, 'Outra conversa')
        (self.projects / (self.mine + '.jsonl')).symlink_to(self.projects / (self.other + '.jsonl'))
        self.assertEqual(server._fallback_claude_titles({self.mine}), {})
        (self.projects / (self.mine + '.jsonl')).unlink()
        self.write(self.mine, 'x' * 20000)
        self.assertEqual(server._fallback_claude_titles({self.mine}), {})
    def test_manual_and_explicit_titles_win(self):
        manual = {self.mine: {'name':'Nome manual', 'auto':False}}
        fallback = {self.mine: {'name':'Primeira mensagem', 'kind':'first-message'}}
        with patch.object(server, '_index_claude_titles', return_value={}):
            self.assertEqual(server._try_import_claude_sessions(manual, {self.mine}, fallback=fallback), 0)
        self.assertEqual(manual[self.mine]['name'], 'Nome manual')
        with patch.object(server, '_index_claude_titles', return_value={self.mine:{'name':'Título explícito','kind':'custom'}}):
            names = {}
            server._try_import_claude_sessions(names, {self.mine}, fallback=fallback)
            self.assertEqual(names[self.mine]['name'], 'Título explícito')

    def test_traversal_stops_at_directory_and_entry_limits(self):
        from pathlib import Path
        for i in range(20):
            (self.projects / f'junk-{i}.txt').write_text('unused')
        real_scandir = server.os.scandir
        counts = {'dirs': 0, 'entries': 0}
        class Counted:
            def __init__(self, path): self.inner = real_scandir(path)
            def __enter__(self): counts['dirs'] += 1; return self
            def __exit__(self, *args): self.inner.close()
            def __iter__(self): return self
            def __next__(self):
                item = next(self.inner); counts['entries'] += 1; return item
        with patch.object(server.os, 'scandir', side_effect=lambda path: Counted(path)), \
             patch.object(server, '_CLAUDE_FALLBACK_DIRS', 2), \
             patch.object(server, '_CLAUDE_FALLBACK_ENTRIES', 3):
            server._fallback_claude_titles({self.mine})
        self.assertLessEqual(counts['dirs'], 2)
        self.assertLessEqual(counts['entries'], 3)

    def test_total_read_budget_bounds_title_extraction(self):
        self.write(self.mine, 'mensagem mais longa que o orçamento')
        with patch.object(server, '_CLAUDE_FALLBACK_BYTES', 8):
            self.assertEqual(server._fallback_claude_titles({self.mine}), {})
