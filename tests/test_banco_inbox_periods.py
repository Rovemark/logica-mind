"""Canonical Inbox routes on the existing private, disposable PG harness only."""
import importlib.util
from pathlib import Path
import unittest
from uuid import uuid4

_spec = importlib.util.spec_from_file_location("_life_private_fixture", Path(__file__).with_name("test_banco_life_integrity.py"))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


class InboxPeriodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _fixture.BancoLifeIntegrityTests.setUpClass()
        cls.addClassCleanup(_fixture.BancoLifeIntegrityTests.doClassCleanups)

    def setUp(self):
        self.case = _fixture.BancoLifeIntegrityTests(methodName="test_invalid_limit_is_a_clear_400")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        with self.case.connection() as con:
            self.assertTrue(self.case.directory.name.startswith("life-banco-integrity-"))
            self.assertIn(f"host={self.case.directory}", self.case.dsn)
            con.execute("TRUNCATE banco.notificacao")
            for title, offset, read in (("Past", "-2 days", False), ("Next", "1 hour", False), ("Far", "2 days", False), ("Read past", "-1 day", True), ("Read future", "3 days", True)):
                con.execute("INSERT INTO banco.notificacao(id,user_id,chave,tipo,titulo,disponivel_em,lida_em) VALUES (%s,'alice',%s,'lembrete',%s,now()+%s::interval,CASE WHEN %s THEN now() ELSE NULL END)",
                            (str(uuid4()), title, title, offset, read))
            con.execute("INSERT INTO banco.notificacao(id,user_id,chave,tipo,titulo,disponivel_em) VALUES (%s,'bob','foreign','lembrete','Foreign',now())",(str(uuid4()),))

    def listing(self, **qs):
        response = self.case.request("notificacoes", method="GET", qs=qs)
        self.assertEqual(response.codigo,200)
        return [item["titulo"] for item in response.corpo["dados"]]

    def test_named_periods_are_exclusive_and_owner_scoped(self):
        self.assertEqual(self.listing(periodo="agora"),["Past"])
        self.assertEqual(self.listing(periodo="proximas"),["Next","Far"])
        self.assertEqual(set(self.listing(periodo="arquivo")),{"Read past","Read future"})

    def test_legacy_include_flags_remain_compatible(self):
        self.assertEqual(self.listing(),["Past"])
        self.assertEqual(set(self.listing(futuras="1")),{"Past","Next","Far"})
        self.assertEqual(set(self.listing(lidas="1",futuras="1")),{"Past","Next","Far","Read past","Read future"})

    def test_upcoming_limit_selects_nearest_not_farthest(self):
        self.assertEqual(self.listing(periodo="proximas",limite="1"),["Next"])

    def test_mark_all_reads_due_only_and_never_marks_another_owner(self):
        response = self.case.request("notificacoes.ler_todas")
        self.assertEqual(response.codigo,200)
        self.assertEqual(self.listing(periodo="agora"),[])
        self.assertEqual(self.listing(periodo="proximas"),["Next","Far"])
        with self.case.connection() as con:
            self.assertIsNone(con.execute("SELECT lida_em FROM banco.notificacao WHERE user_id='bob'").fetchone()[0])

    def test_invalid_period_and_limit_are_explicit_400(self):
        for qs in ({"periodo":"wrong"},{"periodo":"proximas","limite":"NaN"}):
            self.assertEqual(self.case.request("notificacoes",method="GET",qs=qs).codigo,400)


if __name__ == "__main__":
    unittest.main()
