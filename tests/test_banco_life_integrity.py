"""Canonical Banco code against a private disposable PostgreSQL cluster.

Run with the Python that has psycopg, PYTHONPATH pointing at this checkout and
PYTHONDONTWRITEBYTECODE=1. Never reads LM_PG_DSN or connects to an installed DB.
"""
import json
import os
import random
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import psycopg

from logica_mind.banco import esquema, nucleo as N, servico as S
from logica_mind.banco.calculados import ErroDeCalculo


class BancoLifeIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("initdb") or not shutil.which("pg_ctl"):
            raise unittest.SkipTest("PostgreSQL binaries unavailable; no real DB was contacted")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise unittest.SkipTest("initdb must run unprivileged; no real DB was contacted")
        cls.directory = Path(tempfile.mkdtemp(prefix="life-banco-integrity-"))
        cls.data = cls.directory / "data"
        cls.port = random.randint(56000, 59000)
        cls.started = False
        cls.addClassCleanup(cls.cleanup)
        subprocess.run(["initdb", "-D", str(cls.data), "--auth=trust", "--no-locale", "-E", "UTF8"],
                       check=True, capture_output=True, timeout=180)
        subprocess.run(["pg_ctl", "-D", str(cls.data), "-l", str(cls.directory / "postgres.log"), "-o",
                        f"-F -p {cls.port} -c listen_addresses= -c unix_socket_directories={cls.directory}", "-w", "start"],
                       check=True, capture_output=True, timeout=60)
        cls.started = True
        cls.dsn = f"host={cls.directory} port={cls.port} dbname=postgres connect_timeout=3"
        with psycopg.connect(cls.dsn) as con:
            con.execute("CREATE FUNCTION public.lm_unaccent_imm(text) RETURNS text LANGUAGE sql IMMUTABLE AS 'SELECT $1'")
            esquema.aplicar(con.cursor())

    @classmethod
    def cleanup(cls):
        if cls.started:
            subprocess.run(["pg_ctl", "-D", str(cls.data), "-m", "fast", "-w", "stop"], capture_output=True, timeout=30)
        if cls.directory.is_dir() and cls.directory.name.startswith("life-banco-integrity-"):
            shutil.rmtree(cls.directory)

    def setUp(self):
        self.stack = [patch.dict(os.environ, {"LM_VIDA_PONTE": "0"}), patch.object(S, "somente_leitura", return_value=False),
                      patch.object(S, "pool", return_value=self)]
        for item in self.stack:
            item.__enter__()
            self.addCleanup(item.__exit__, None, None, None)
        self.ids = {name: str(uuid.uuid4()) for name in ("space", "source_base", "target_base", "wrong_base", "source", "old", "new", "wrong", "single", "multiple", "foreign_space", "foreign_base", "foreign_row", "foreign_prop")}
        with self.connection() as con:
            con.execute("TRUNCATE banco.espaco CASCADE")
            con.execute("INSERT INTO banco.espaco(id,user_id,nome) VALUES (%s,'alice','Fixture'),(%s,'bob','Foreign')", (self.ids["space"], self.ids["foreign_space"]))
            for name in ("source_base", "target_base", "wrong_base"):
                con.execute("INSERT INTO banco.no(id,espaco_id,user_id,tipo,nome,chave_titulo) VALUES (%s,%s,'alice','banco',%s,'nome')", (self.ids[name], self.ids["space"], name))
            con.execute("INSERT INTO banco.no(id,espaco_id,user_id,tipo,nome) VALUES (%s,%s,'bob','banco','Foreign')", (self.ids["foreign_base"], self.ids["foreign_space"]))
            for name, base in (("source", "source_base"), ("old", "target_base"), ("new", "target_base"), ("wrong", "wrong_base")):
                con.execute("INSERT INTO banco.linha(id,no_id,user_id,titulo) VALUES (%s,%s,'alice',%s)", (self.ids[name], self.ids[base], name))
            con.execute("INSERT INTO banco.linha(id,no_id,user_id,titulo) VALUES (%s,%s,'bob','Foreign')", (self.ids["foreign_row"], self.ids["foreign_base"]))
            for name, multiple in (("single", False), ("multiple", True)):
                con.execute("INSERT INTO banco.propriedade(id,no_id,user_id,chave,nome,tipo,config) VALUES (%s,%s,'alice',%s,%s,'relacao',%s::jsonb)",
                            (self.ids[name], self.ids["source_base"], name, name, json.dumps({"alvo_no_id": self.ids["target_base"], "multiplo": multiple})))
            con.execute("INSERT INTO banco.propriedade(id,no_id,user_id,chave,nome,tipo,config) VALUES (%s,%s,'bob','foreign','Foreign','relacao',%s::jsonb)",
                        (self.ids["foreign_prop"], self.ids["foreign_base"], json.dumps({"alvo_no_id": self.ids["foreign_base"], "multiplo": True})))

    def connection(self):
        return psycopg.connect(self.dsn)

    def request(self, action, *, method="POST", qs=None, **body):
        return S.trata(method, "/api/banco/" + action, qs or {}, body, "alice")

    def body(self, property="single", dest="new"):
        return {"propriedade_id": self.ids[property], "origem_id": self.ids["source"], "destino_id": self.ids[dest] if dest else None}

    def linked(self, property="single"):
        with self.connection() as con:
            return {str(row[0]) for row in con.execute("SELECT destino_id FROM banco.elo WHERE propriedade_id=%s AND origem_id=%s", (self.ids[property], self.ids["source"]))}

    def seed(self, property="single", dest="old"):
        with self.connection() as con:
            N.ligar(con.cursor(), "alice", **self.body(property, dest))

    def test_limit_1000_is_clamped_once_and_still_returns_next_cursor(self):
        with self.connection() as con:
            for i in range(202):
                con.execute("INSERT INTO banco.linha(id,no_id,user_id,titulo,posicao) VALUES (%s,%s,'alice',%s,%s)",
                            (str(uuid.uuid4()), self.ids["source_base"], f"row-{i}", i + 2000))
        first = self.request("linhas", method="GET", qs={"no": self.ids["source_base"], "limite": "1000"})
        self.assertEqual(first.codigo, 200)
        page = first.corpo["dados"]
        self.assertEqual(len(page["linhas"]), 200)
        self.assertTrue(page["tem_mais"])
        self.assertTrue(page["cursor"])
        second = self.request("linhas", method="GET", qs={"no": self.ids["source_base"], "limite": "1000", "cursor": page["cursor"]}).corpo["dados"]
        self.assertEqual(len(second["linhas"]), 3)
        self.assertFalse(second["tem_mais"])
        self.assertEqual(len({row["id"] for row in page["linhas"] + second["linhas"]}), 203)

    def test_invalid_limit_is_a_clear_400(self):
        self.assertEqual(self.request("linhas", method="GET", qs={"no": self.ids["source_base"], "limite": "not-int"}).codigo, 400)

    def test_property_key_is_forwarded_and_preserved(self):
        result = self.request("propriedade.criar", no_id=self.ids["source_base"], nome="Renamed display label", tipo="texto", chave="stable_key")
        self.assertEqual(result.codigo, 200)
        self.assertEqual(result.corpo["dados"]["chave"], "stable_key")

    def test_property_keys_reject_reserved_empty_or_malformed_keys(self):
        for key in ("", "__proto__", "constructor", "prototype", "Upper", "has space", "valid\n", ["not-string"]):
            with self.subTest(key=key):
                self.assertEqual(self.request("propriedade.criar", no_id=self.ids["source_base"], nome="Title", tipo="texto", chave=key).codigo, 400)

    def test_property_creation_needs_the_same_owner_base(self):
        result = self.request("propriedade.criar", no_id=self.ids["foreign_base"], nome="Foreign", tipo="texto", chave="foreign_attempt")
        self.assertEqual(result.codigo, 400)
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM banco.propriedade WHERE chave='foreign_attempt'").fetchone()[0], 0)

    def test_single_relation_replace_and_clear_are_atomic(self):
        self.seed()
        changed = self.request("elo.substituir", **self.body())
        self.assertEqual(changed.codigo, 200)
        self.assertTrue(changed.corpo["dados"]["substituiu"])
        self.assertEqual(self.linked(), {self.ids["new"]})
        self.assertFalse(self.request("elo.substituir", **self.body()).corpo["dados"]["substituiu"])
        self.assertEqual(self.request("elo.substituir", **self.body(dest=None)).codigo, 200)
        self.assertEqual(self.linked(), set())

    def test_invalid_target_never_removes_the_previous_relation(self):
        self.seed()
        for target in (self.ids["wrong"], self.ids["foreign_row"], str(uuid.uuid4()), "broken-id"):
            with self.subTest(target=target):
                self.assertEqual(self.request("elo.substituir", **{**self.body(), "destino_id": target}).codigo, 400)
                self.assertEqual(self.linked(), {self.ids["old"]})

    def test_replace_rejects_multiple_relations_unknown_or_missing_fields(self):
        self.assertEqual(self.request("elo.substituir", **self.body("multiple")).codigo, 400)
        self.assertEqual(self.request("elo.substituir", **self.body(), user_id="bob").codigo, 400)
        self.assertEqual(self.request("elo.substituir", propriedade_id=self.ids["single"], origem_id=self.ids["source"]).codigo, 400)

    def test_all_relation_writers_enforce_owner_source_and_target_base(self):
        self.seed("multiple")
        for action in ("elo.ligar", "elo.desligar", "elo.substituir"):
            for change in ({"propriedade_id": self.ids["foreign_prop"]}, {"origem_id": self.ids["wrong"]}, {"origem_id": self.ids["foreign_row"]}, {"destino_id": self.ids["wrong"]}, {"destino_id": self.ids["foreign_row"]}):
                with self.subTest(action=action, change=change):
                    self.assertEqual(self.request(action, **{**self.body(), **change}).codigo, 400)
        self.assertEqual(self.linked("multiple"), {self.ids["old"]})

    def test_multiple_relation_can_add_and_remove_without_replacing_other_targets(self):
        self.seed("multiple")
        self.assertEqual(self.request("elo.ligar", **self.body("multiple")).codigo, 200)
        self.assertEqual(self.linked("multiple"), {self.ids["old"], self.ids["new"]})
        self.assertEqual(self.request("elo.desligar", **self.body("multiple")).codigo, 200)
        self.assertEqual(self.linked("multiple"), {self.ids["old"]})

    def test_legacy_link_cannot_accumulate_second_target_in_single_relation(self):
        self.seed()
        self.assertEqual(self.request("elo.ligar", **self.body()).codigo, 400)
        self.assertEqual(self.linked(), {self.ids["old"]})

    def test_derived_hook_failure_rolls_back_each_writer_even_when_http_returns_400(self):
        for action in ("elo.ligar", "elo.desligar", "elo.substituir"):
            with self.subTest(action=action):
                if not self.linked():
                    self.seed()
                body = self.body(dest="old") if action != "elo.substituir" else self.body()
                with patch.object(S.C, "recalcular_cascata", side_effect=ErroDeCalculo("synthetic derived failure")):
                    self.assertEqual(self.request(action, **body).codigo, 400)
                self.assertEqual(self.linked(), {self.ids["old"]})

    def test_concurrent_single_replacements_share_lock_and_never_accumulate_targets(self):
        self.seed()
        barrier = threading.Barrier(2)
        def replace(target):
            with self.connection() as con:
                barrier.wait(timeout=3)
                N.substituir_elo(con.cursor(), "alice", **self.body(dest=target))
                time.sleep(0.04)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(replace, name) for name in ("old", "new")]
            for future in futures:
                future.result(timeout=6)
        self.assertEqual(len(self.linked()), 1)

    def test_row_concurrency_capability_is_read_only_and_explicit(self):
        response = self.request("capacidades", method="GET")
        self.assertEqual(response.codigo, 200)
        self.assertEqual(response.corpo["dados"]["linha_valores_base"], 1)
        self.assertEqual(self.request("capacidades").codigo, 405)

    def test_stale_title_is_rejected_without_overwriting_or_running_hooks(self):
        row = self.ids["source"]
        first = self.request("linha.atualizar", id=row, mudancas={"nome": "Linux"}, valores_base={"nome": "source"})
        self.assertEqual(first.codigo, 200)
        self.assertTrue(first.corpo["dados"]["precondicoes_verificadas"])
        with patch.object(S.NF, "sincronizar_lembretes") as notify:
            stale = self.request("linha.atualizar", id=row, mudancas={"nome": "Mac"}, valores_base={"nome": "source"})
        self.assertEqual(stale.codigo, 409)
        notify.assert_not_called()
        with self.connection() as con:
            saved = con.execute("SELECT titulo, props FROM banco.linha WHERE id=%s", (row,)).fetchone()
        self.assertEqual(saved[0], "Linux")
        self.assertEqual(saved[1]["nome"], "Linux")

    def test_non_overlapping_fields_can_merge_without_rebasing_the_changed_field(self):
        row = self.ids["source"]
        self.assertEqual(self.request("linha.atualizar", id=row, mudancas={"nome": "Linux"}, valores_base={"nome": "source"}).codigo, 200)
        self.assertEqual(self.request("linha.atualizar", id=row, mudancas={"priority": "high"}, valores_base={"priority": None}).codigo, 200)
        with self.connection() as con:
            title, props = con.execute("SELECT titulo, props FROM banco.linha WHERE id=%s", (row,)).fetchone()
        self.assertEqual(title, "Linux")
        self.assertEqual(props["priority"], "high")

    def test_preconditions_must_cover_exactly_the_changes_and_preserve_json_types(self):
        row = self.ids["source"]
        self.assertEqual(self.request("linha.atualizar", id=row, mudancas={"flag": True}, valores_base={"flag": None}).codigo, 200)
        for base in ({}, {"flag": True, "extra": None}, [], "true"):
            with self.subTest(base=base):
                self.assertEqual(self.request("linha.atualizar", id=row, mudancas={"flag": False}, valores_base=base).codigo, 400)
        self.assertEqual(self.request("linha.atualizar", id=row, mudancas={"flag": False}, valores_base={"flag": 1}).codigo, 409)
        # Other owners never get the current value through the conflict response.
        denied = self.request("linha.atualizar", id=self.ids["foreign_row"], mudancas={"titulo": "Intrusion"}, valores_base={"titulo": "Foreign"})
        self.assertEqual(denied.codigo, 400)

    def test_two_autocommit_writers_on_same_base_have_one_winner(self):
        barrier = threading.Barrier(2)
        row = self.ids["source"]
        def write(title):
            barrier.wait(timeout=4)
            return self.request("linha.atualizar", id=row, mudancas={"nome": title}, valores_base={"nome": "source"}).codigo
        with patch.object(self, "connection", side_effect=lambda: psycopg.connect(self.dsn, autocommit=True)):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(write, title) for title in ("Linux", "Mac")]
                statuses = [future.result(timeout=10) for future in futures]
        self.assertEqual(sorted(statuses), [200, 409])

    def test_batch_conflict_rolls_back_previous_rows_in_autocommit_pool(self):
        first, second = sorted([self.ids["source"], self.ids["old"]])
        first_title = "source" if first == self.ids["source"] else "old"
        changes = [
            {"id": first, "mudancas": {"nome": "Must roll back"}, "valores_base": {"nome": first_title}},
            {"id": second, "mudancas": {"nome": "Stale"}, "valores_base": {"nome": "not-current"}},
        ]
        with patch.object(self, "connection", side_effect=lambda: psycopg.connect(self.dsn, autocommit=True)):
            response = self.request("linha.lote", mudancas=changes)
        self.assertEqual(response.codigo, 409)
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT titulo FROM banco.linha WHERE id=%s", (first,)).fetchone()[0], first_title)

    def test_json_numbers_merge_but_nested_booleans_do_not_equal_numbers(self):
        row = self.ids["source"]
        self.assertEqual(self.request("linha.atualizar", id=row, mudancas={"value": {"n": 1.0, "flag": True}}, valores_base={"value": None}).codigo, 200)
        self.assertEqual(self.request("linha.atualizar", id=row, mudancas={"value": {"n": 2}}, valores_base={"value": {"n": 1, "flag": 1}}).codigo, 409)
        self.assertEqual(self.request("linha.atualizar", id=row, mudancas={"value": {"n": 2}}, valores_base={"value": {"flag": True, "n": 1}}).codigo, 200)

    def test_batch_ack_preserves_request_order_and_legacy_writes_are_not_marked_guarded(self):
        rows = sorted([self.ids["source"], self.ids["old"]], reverse=True)
        response = self.request("linha.lote", mudancas=[{"id": row, "mudancas": {"extra": "value"}, "valores_base": {"extra": None}} for row in rows])
        self.assertEqual(response.codigo, 200)
        self.assertEqual([item["id"] for item in response.corpo["dados"]], rows)
        self.assertTrue(all(item["precondicoes_verificadas"] for item in response.corpo["dados"]))
        legacy = self.request("linha.atualizar", id=rows[0], mudancas={"extra": "Legacy"})
        self.assertEqual(legacy.codigo, 200)
        self.assertFalse(legacy.corpo["dados"]["precondicoes_verificadas"])

    def test_hook_failure_rolls_back_guarded_row_in_autocommit_pool(self):
        with patch.object(self, "connection", side_effect=lambda: psycopg.connect(self.dsn, autocommit=True)), \
             patch.object(S.C, "recalcular_cascata", side_effect=ErroDeCalculo("synthetic derived failure")):
            response = self.request("linha.atualizar", id=self.ids["source"], mudancas={"nome": "Must roll back"}, valores_base={"nome": "source"})
        self.assertEqual(response.codigo, 400)
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT titulo FROM banco.linha WHERE id=%s", (self.ids["source"],)).fetchone()[0], "source")


if __name__ == "__main__":
    unittest.main()
