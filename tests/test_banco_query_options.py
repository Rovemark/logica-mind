"""Life query/option regressions on a private PG cluster; never the live DSN.

Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. <python-with-psycopg>
     -m unittest discover -s tests -p test_banco_query_options.py -v
"""
import base64
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import patch

import test_banco_life_integrity as Fixture
from logica_mind.banco import consulta as Q, nucleo as N, servico as S
from logica_mind.banco.calculados import ErroDeCalculo


class BancoQueryOptionsTests(Fixture.BancoLifeIntegrityTests):
    def seed_sorted(self):
        self.rows = {}
        with self.connection() as con:
            con.execute("DELETE FROM banco.linha WHERE no_id=%s", (self.ids["source_base"],))
            for key, kind in (("prazo", "data"), ("score", "numero"), ("tags", "multi_selecao"), ("nome", "texto")):
                con.execute("INSERT INTO banco.propriedade(id,no_id,user_id,chave,nome,tipo) VALUES (%s,%s,'alice',%s,%s,%s)",
                            (str(uuid.uuid4()), self.ids["source_base"], key, key, kind))
            for i, (name, position, day, score) in enumerate((
                    ("A", 30, "2026-10-01", "9"), ("B", 20, {"inicio": "2026-10-02", "fim": "2026-10-05"}, "10"),
                    ("C", 10, "2026-10-03", "10"), ("D", 10, None, None), ("E", 9, "", "-3.25"),
                    ("F", 8, "2026-10-02", "10"), ("G", 7, {"inicio": "2026-10-01"}, "2"))):
                ident = str(uuid.uuid4())
                self.rows[name] = ident
                props = {"prazo": day, "score": score, "tags": ["one", "two"] if i % 2 else ["two"], "nome": name}
                con.execute("INSERT INTO banco.linha(id,no_id,user_id,titulo,posicao,props,criado_em,atualizado_em) "
                            "VALUES (%s,%s,'alice',%s,%s,%s::jsonb,%s::timestamptz,%s::timestamptz)",
                            (ident, self.ids["source_base"], name, position, json.dumps(props), f"2026-10-0{i+1}T12:00:00Z", f"2026-10-0{i+1}T12:00:00Z"))

    def query(self, *, cursor=None, order=None, filter=None, limit=2, no=None):
        qs = {"no": no or self.ids["source_base"], "limite": str(limit)}
        if cursor is not None:
            qs["cursor"] = cursor
        if order is not None:
            qs["ordenacao"] = json.dumps(order)
        if filter is not None:
            qs["filtro"] = json.dumps(filter)
        return self.request("linhas", method="GET", qs=qs)

    def collect(self, **args):
        result, cursor, seen = [], None, set()
        for _ in range(100):
            response = self.query(cursor=cursor, **args)
            self.assertEqual(response.codigo, 200, response.corpo)
            data = response.corpo["dados"]
            result.extend(data["linhas"])
            if not data["tem_mais"]:
                self.assertIsNone(data["cursor"])
                return result
            self.assertTrue(data["cursor"].startswith("lc2."))
            self.assertLess(len(data["cursor"]), 1024)
            self.assertNotIn(data["cursor"], seen)
            seen.add(data["cursor"])
            cursor = data["cursor"]
        self.fail("cursor failed to terminate")

    def test_every_supported_order_mixed_directions_and_nulls_pages_exactly_once(self):
        self.seed_sorted()
        cases = [None]
        for key in ("titulo", "nome", "prazo", "score", "posicao", "criado_em", "atualizado_em"):
            cases.extend([[{"prop": key, "dir": direction}] for direction in ("asc", "desc")])
        cases.extend([[{"prop": "score", "dir": "desc"}, {"prop": "prazo", "dir": "asc"}],
                      [{"prop": "prazo", "dir": "asc"}, {"prop": "posicao", "dir": "desc"}]])
        for order in cases:
            with self.subTest(order=order):
                reference = self.query(order=order, limit=200).corpo["dados"]["linhas"]
                paged = self.collect(order=order, limit=1)
                self.assertEqual([r["id"] for r in paged], [r["id"] for r in reference])
                self.assertEqual(len({r["id"] for r in paged}), 7)
        dates = self.collect(order=[{"prop": "prazo", "dir": "asc"}])
        self.assertEqual([r["titulo"] for r in dates], ["G", "A", "F", "B", "C", "E", "D"])
        scores = self.collect(order=[{"prop": "score", "dir": "asc"}])
        self.assertEqual([r["titulo"] for r in scores], ["E", "G", "A", "F", "C", "B", "D"])

    def test_filter_and_order_bind_correct_values_on_each_page(self):
        self.seed_sorted()
        filtered = self.collect(order=[{"prop": "prazo", "dir": "asc"}],
                                filter={"prop": "prazo", "op": "depois", "valor": "2026-10-01"}, limit=1)
        self.assertEqual([r["titulo"] for r in filtered], ["F", "B", "C"])
        filtered = self.collect(order=[{"prop": "score", "dir": "desc"}],
                                filter={"e": [{"prop": "score", "op": "maior", "valor": 8}, {"prop": "tags", "op": "tem", "valor": "one"}]}, limit=1)
        self.assertEqual([r["titulo"] for r in filtered], ["F", "B"])

    def test_multi_membership_accepts_scalar_and_all_requested_list_items(self):
        self.seed_sorted()
        for value in ("one", ["one"], ["one", "two"]):
            rows = self.collect(filter={"prop": "tags", "op": "tem", "valor": value})
            self.assertEqual({r["titulo"] for r in rows}, {"B", "D", "F"})
        self.assertEqual(self.collect(filter={"prop": "tags", "op": "tem", "valor": "absent"}), [])

    def test_cursor_rejects_changed_filter_order_base_owner_or_property_type(self):
        self.seed_sorted()
        order = [{"prop": "score", "dir": "asc"}]
        cursor = self.query(order=order).corpo["dados"]["cursor"]
        for args in ({}, {"order": [{"prop": "score", "dir": "desc"}]}, {"order": order, "filter": {"prop": "score", "op": "maior", "valor": 0}}, {"order": order, "no": self.ids["target_base"]}):
            with self.subTest(args=args):
                self.assertEqual(self.query(cursor=cursor, **args).codigo, 400)
        bob = S.trata("GET", "/api/banco/linhas", {"no": self.ids["source_base"], "cursor": cursor, "ordenacao": json.dumps(order)}, {}, "bob")
        self.assertEqual(bob.codigo, 400)
        with self.connection() as con:
            con.execute("UPDATE banco.propriedade SET tipo='texto' WHERE no_id=%s AND chave='score'", (self.ids["source_base"],))
        self.assertEqual(self.query(order=order, cursor=cursor).codigo, 400)

    def test_cursor_strict_typed_malformed_and_legacy_compatibility(self):
        self.seed_sorted()
        first = self.query().corpo["dados"]
        cursor = first["cursor"]
        payload = json.loads(base64.urlsafe_b64decode(cursor[4:] + "=" * (-len(cursor[4:]) % 4)))
        invalid = ["garbage", "lc1.%%%", "lc1." + "a" * 33000]
        for change in ({"v": True}, {"v": 1}, {"a": True}, {"a": "bad-uuid"}, {"a": None}, {"f": "invalid"}, {"extra": True}):
            mutated = {**payload, **change}
            invalid.append("lc2." + base64.urlsafe_b64encode(json.dumps(mutated).encode()).decode().rstrip("="))
        legacy_payload = {"v": 1, "q": payload["q"], "k": [str(first["linhas"][-1]["posicao"]), first["linhas"][-1]["id"]]}
        for k in ([True, self.rows["A"]], ["NaN", self.rows["A"]], ["1e200000", self.rows["A"]], ["3", "bad-uuid"], [None, self.rows["A"]], ["3"]):
            mutated = {**legacy_payload, "k": k}
            invalid.append("lc1." + base64.urlsafe_b64encode(json.dumps(mutated).encode()).decode().rstrip("="))
        for bad in invalid:
            self.assertEqual(self.query(cursor=bad).codigo, 400)
        last = first["linhas"][-1]
        legacy = f"{last['posicao']}|{last['id']}"
        self.assertEqual(self.query(cursor=legacy).codigo, 200)
        valid_lc1 = "lc1." + base64.urlsafe_b64encode(json.dumps(legacy_payload).encode()).decode().rstrip("=")
        self.assertEqual(self.query(cursor=valid_lc1).codigo, 200)
        self.assertEqual(self.query(cursor=legacy, order=[{"prop": "titulo", "dir": "asc"}]).codigo, 400)
        self.assertEqual(self.query(cursor=legacy, filter={"prop": "titulo", "op": "contem", "valor": "A"}).codigo, 400)

    def test_manual_cursor_preserves_decimal_precision_not_response_float(self):
        self.seed_sorted()
        with self.connection() as con:
            for i, name in enumerate("ABCDEFG"):
                con.execute("UPDATE banco.linha SET posicao=%s WHERE id=%s", (Decimal("9007199254740992") + Decimal(i) / 1000, self.rows[name]))
        self.assertEqual([r["titulo"] for r in self.collect(limit=1)], list("ABCDEFG"))
        sql, _ = Q.montar(self.ids["source_base"], "alice", {"score": "numero"}, ordenacao=[{"prop": "score", "dir": "desc"}])
        self.assertNotIn("OFFSET", sql)

    def test_invalid_filter_and_order_are_400_not_uncaught_errors(self):
        self.seed_sorted()
        for filter in (["bad"], {"e": "bad"}, {"ou": {}}, {"prop": "nome\n", "op": "igual", "valor": "A"}):
            self.assertEqual(self.query(filter=filter).codigo, 400)
        for order in ({"prop": "titulo"}, [None], [{"prop": "titulo", "dir": "sideways"}]):
            self.assertEqual(self.query(order=order).codigo, 400)

    def seed_option(self, kind="selecao", count=205):
        prop = str(uuid.uuid4())
        self.option_id = prop
        self.option_rows = []
        with self.connection() as con:
            con.execute("INSERT INTO banco.propriedade(id,no_id,user_id,chave,nome,tipo,config) VALUES (%s,%s,'alice','state','State',%s,%s::jsonb)",
                        (prop, self.ids["source_base"], kind, json.dumps({"opcoes": [{"nome": "Old", "cor": "blue", "meta": 7}, {"nome": "Other", "cor": "red"}], "extra": "keep"})))
            for i in range(count):
                ident = str(uuid.uuid4())
                self.option_rows.append(ident)
                value = ["Old", "Other", "Unknown"] if kind == "multi_selecao" else "Old"
                con.execute("INSERT INTO banco.linha(id,no_id,user_id,titulo,props) VALUES (%s,%s,'alice',%s,%s::jsonb)",
                            (ident, self.ids["source_base"], f"option-{i}", json.dumps({"state": value, "untouched": i})))
            con.execute("UPDATE banco.linha SET arquivado_em=now() WHERE id=%s", (self.option_rows[-2],))
            con.execute("UPDATE banco.linha SET deletado_em=now() WHERE id=%s", (self.option_rows[-1],))
        return prop

    def option(self, new, **changes):
        return self.request("propriedade.opcao.alterar", **{"id": self.option_id, "nome": "Old", "novo_nome": new, "versao": self.property().get("opcoes_version", 0), **changes})

    def property(self):
        with self.connection() as con:
            return con.execute("SELECT config FROM banco.propriedade WHERE id=%s", (self.option_id,)).fetchone()[0]

    def values(self):
        with self.connection() as con:
            return {str(i): p for i, p in con.execute("SELECT id,props FROM banco.linha WHERE no_id=%s", (self.ids["source_base"],))}

    def test_single_option_rename_updates_every_page_archives_but_never_deleted_rows(self):
        self.seed_option()
        result = self.option("New")
        self.assertEqual(result.codigo, 200, result.corpo)
        self.assertEqual(result.corpo["dados"]["linhas_alteradas"], 204)
        prop = result.corpo["dados"]["propriedade"]
        self.assertEqual(prop["config"], {"opcoes": [{"nome": "New", "cor": "blue", "meta": 7}, {"nome": "Other", "cor": "red"}], "extra": "keep", "opcoes_version": 1, "opcoes_retiradas": ["Old"]})
        values = self.values()
        self.assertEqual([values[r]["state"] for r in self.option_rows[:-1]], ["New"] * 204)
        self.assertEqual(values[self.option_rows[-1]]["state"], "Old")
        self.assertEqual([values[r]["untouched"] for r in self.option_rows], list(range(205)))

    def test_single_option_remove_clears_key_without_destroying_unknown_values(self):
        self.seed_option(count=5)
        with self.connection() as con:
            con.execute("UPDATE banco.linha SET props=jsonb_set(props,'{state}','\"Unknown\"') WHERE id=%s", (self.option_rows[0],))
        self.assertEqual(self.option(None).corpo["dados"]["linhas_alteradas"], 3)
        values = self.values()
        self.assertEqual(values[self.option_rows[0]]["state"], "Unknown")
        for row in self.option_rows[1:-1]:
            self.assertNotIn("state", values[row])
        self.assertEqual(self.property()["opcoes"], [{"nome": "Other", "cor": "red"}])

    def test_multi_option_rename_remove_preserves_arrays_and_legacy_scalar(self):
        self.seed_option("multi_selecao", count=8)
        with self.connection() as con:
            con.execute("UPDATE banco.linha SET props=jsonb_set(props,'{state}','\"Old\"') WHERE id=%s", (self.option_rows[0],))
            con.execute("UPDATE banco.linha SET props=jsonb_set(props,'{state}','[\"Old\",\"Old\",\"Unknown\"]') WHERE id=%s", (self.option_rows[1],))
        self.assertEqual(self.option("New").corpo["dados"]["linhas_alteradas"], 7)
        values = self.values()
        self.assertEqual(values[self.option_rows[0]]["state"], ["New"])
        self.assertEqual(values[self.option_rows[1]]["state"], ["New", "Unknown"])
        self.assertEqual(values[self.option_rows[2]]["state"], ["New", "Other", "Unknown"])
        self.assertEqual(self.option(None, nome="New").codigo, 200)
        values = self.values()
        self.assertEqual(values[self.option_rows[0]]["state"], [])
        self.assertEqual(values[self.option_rows[2]]["state"], ["Other", "Unknown"])

    def test_option_scope_validation_collisions_stale_requests_and_noop(self):
        self.seed_option(count=5)
        before = self.values()
        for change in ({"id": self.ids["foreign_prop"]}, {"id": "invalid"}, {"nome": "Unknown"}, {"novo_nome": "Other"}, {"novo_nome": " "}, {"novo_nome": ["bad"]}, {"extra": True}):
            self.assertEqual(self.option("New", **change).codigo, 400)
            self.assertEqual(self.values(), before)
        self.assertEqual(self.option("Old").corpo["dados"]["linhas_alteradas"], 0)
        self.assertEqual(self.option("New").codigo, 200)
        self.assertEqual(self.option("Again").codigo, 400)

    def test_option_hook_failure_rolls_back_metadata_all_rows_and_hook_writes(self):
        self.seed_option(count=8)
        before, config = self.values(), self.property()
        calls = 0
        def fail_hook(cur, user_id, row_id):
            nonlocal calls
            calls += 1
            cur.execute("UPDATE banco.linha SET titulo='hook mutation' WHERE id=%s", (self.ids["source"],))
            if calls == 3:
                raise ErroDeCalculo("synthetic calculation failure after two confirmed rows")
        with patch.object(S.C, "recalcular_cascata", side_effect=fail_hook):
            result = self.option("New")
        self.assertEqual(result.codigo, 400)
        self.assertEqual(calls, 3)
        self.assertEqual(self.property(), config)
        self.assertEqual(self.values(), before)
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT titulo FROM banco.linha WHERE id=%s", (self.ids["source"],)).fetchone()[0], "source")

    def test_concurrent_option_renames_confirm_one_complete_operation_only(self):
        self.seed_option(count=8)
        barrier = threading.Barrier(2)
        def rename(new):
            barrier.wait(timeout=3)
            return self.option(new, versao=0)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(rename, n) for n in ("NewOne", "NewTwo")]
            results = [f.result(timeout=10) for f in futures]
        self.assertEqual(sorted(r.codigo for r in results), [200, 409])
        winner = self.property()["opcoes"][0]["nome"]
        self.assertEqual({self.values()[r]["state"] for r in self.option_rows[:-1]}, {winner})

    def test_concurrent_partial_row_merges_preserve_both_fields(self):
        barrier = threading.Barrier(2)
        def update(key):
            with self.connection() as con:
                barrier.wait(timeout=3)
                N.atualizar_linha(con.cursor(), "alice", self.ids["source"], {key: key})
                time.sleep(.03)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(update, key) for key in ("one", "two")]
            for future in futures:
                future.result(timeout=10)
        self.assertEqual(self.values()[self.ids["source"]], {"one": "one", "two": "two"})

    def test_option_rename_preserves_nested_saved_filter_semantics_only_for_its_property(self):
        self.seed_option(count=8)
        view, foreign_view = str(uuid.uuid4()), str(uuid.uuid4())
        filtro = {"e": [{"prop": "state", "op": "igual", "valor": "Old"},
                        {"ou": [{"prop": "state", "op": "algum_de", "valor": ["Old", "Other"]},
                                {"nao": {"prop": "state", "op": "diferente", "valor": "Old"}}]},
                        {"prop": "description", "op": "igual", "valor": "Old"},
                        {"prop": "state", "op": "contem", "valor": "Old"}]}
        with self.connection() as con:
            con.execute("INSERT INTO banco.vista(id,no_id,user_id,nome,tipo,config) VALUES (%s,%s,'alice','Filtered','tabela',%s::jsonb)",
                        (view, self.ids["source_base"], json.dumps({"filtro": filtro, "expressao": "state == 'Old'", "extra": "Old"})))
            con.execute("INSERT INTO banco.vista(id,no_id,user_id,nome,tipo,config) VALUES (%s,%s,'bob','Foreign','tabela',%s::jsonb)",
                        (foreign_view, self.ids["foreign_base"], json.dumps({"filtro": filtro})))
        before = self.query(filter={"prop": "state", "op": "igual", "valor": "Old"}, limit=200).corpo["dados"]["linhas"]
        result = self.option("New")
        self.assertEqual(result.corpo["dados"]["filtros_atualizados"], 1)
        self.assertEqual(result.corpo["dados"]["referencias_revisar"], 0)
        with self.connection() as con:
            config = con.execute("SELECT config FROM banco.vista WHERE id=%s", (view,)).fetchone()[0]
            foreign = con.execute("SELECT config FROM banco.vista WHERE id=%s", (foreign_view,)).fetchone()[0]
        self.assertEqual(config["filtro"]["e"][0]["valor"], "New")
        self.assertEqual(config["filtro"]["e"][1]["ou"][0]["valor"], ["New", "Other"])
        self.assertEqual(config["filtro"]["e"][1]["ou"][1]["nao"]["valor"], "New")
        self.assertEqual(config["filtro"]["e"][2]["valor"], "Old")
        self.assertEqual(config["filtro"]["e"][3]["valor"], "Old")
        self.assertEqual(config["expressao"], "state == 'Old'")
        self.assertEqual(config["extra"], "Old")
        self.assertEqual(foreign["filtro"], filtro)
        after = self.query(filter=config["filtro"]["e"][0], limit=200).corpo["dados"]["linhas"]
        self.assertEqual({r["id"] for r in before}, {r["id"] for r in after})

    def test_option_remove_keeps_retired_filter_reference_and_reports_review(self):
        self.seed_option(count=5)
        filtro = {"nao": {"prop": "state", "op": "tem", "valor": ["Old", "Other"]}}
        with self.connection() as con:
            view = N.criar_vista(con.cursor(), "alice", self.ids["source_base"], "Keep filter", "tabela", {"filtro": filtro})
        result = self.option(None)
        self.assertEqual(result.codigo, 200)
        self.assertEqual(result.corpo["dados"]["filtros_atualizados"], 0)
        self.assertEqual(result.corpo["dados"]["referencias_revisar"], 1)
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT config FROM banco.vista WHERE id=%s", (view["id"],)).fetchone()[0]["filtro"], filtro)

    def test_option_hook_failure_rolls_back_saved_filter_remap(self):
        self.seed_option(count=5)
        filtro = {"prop": "state", "op": "igual", "valor": "Old"}
        with self.connection() as con:
            view = N.criar_vista(con.cursor(), "alice", self.ids["source_base"], "Keep filter", "tabela", {"filtro": filtro})
        with patch.object(S.C, "recalcular_cascata", side_effect=ErroDeCalculo("fail after view remap")):
            self.assertEqual(self.option("New").codigo, 400)
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT config FROM banco.vista WHERE id=%s", (view["id"],)).fetchone()[0]["filtro"], filtro)

    def test_multi_empty_and_nonempty_match_arrays_missing_null_and_legacy_scalars(self):
        self.seed_sorted()
        values = {"A": [], "B": ["Urgente"], "C": "", "D": None, "E": "missing", "F": "Legacy", "G": [""]}
        with self.connection() as con:
            for name, value in values.items():
                if value == "missing":
                    con.execute("UPDATE banco.linha SET props=props-'tags' WHERE id=%s", (self.rows[name],))
                else:
                    con.execute("UPDATE banco.linha SET props=jsonb_set(props,'{tags}',%s::jsonb) WHERE id=%s", (json.dumps(value), self.rows[name]))
        self.assertEqual({r["titulo"] for r in self.collect(filter={"prop": "tags", "op": "vazio"})}, {"A", "C", "D", "E"})
        self.assertEqual({r["titulo"] for r in self.collect(filter={"prop": "tags", "op": "nao_vazio"})}, {"B", "F", "G"})

    def test_compact_anchor_cursor_handles_large_legal_text_and_expires_on_sort_drift(self):
        self.seed_sorted()
        with self.connection() as con:
            con.execute("UPDATE banco.linha SET props=jsonb_set(props,'{nome}',%s::jsonb) WHERE id=%s", (json.dumps("0" * 70000), self.rows["A"]))
        order = [{"prop": "nome", "dir": "asc"}]
        first = self.query(order=order, limit=1).corpo["dados"]
        self.assertEqual(first["linhas"][0]["id"], self.rows["A"])
        self.assertLess(len(first["cursor"]), 1024)
        self.assertEqual(len(self.collect(order=order, limit=1)), 7)
        self.assertEqual(self.query(order=order, cursor=first["cursor"]).codigo, 200)
        with self.connection() as con:
            con.execute("UPDATE banco.linha SET props=jsonb_set(props,'{nome}','\"Changed\"') WHERE id=%s", (self.rows["A"],))
        self.assertEqual(self.query(order=order, cursor=first["cursor"]).codigo, 409)

    def test_anchor_deleted_archived_or_no_longer_matching_filter_returns_409(self):
        self.seed_sorted()
        for mutation in ("deletado_em=now()", "arquivado_em=now()", "props=jsonb_set(props,'{score}','0')"):
            with self.subTest(mutation=mutation):
                with self.connection() as con:
                    con.execute("UPDATE banco.linha SET deletado_em=NULL,arquivado_em=NULL,props=jsonb_set(props,'{score}','9') WHERE id=%s", (self.rows["A"],))
                order = [{"prop": "titulo", "dir": "asc"}]
                filter = {"prop": "score", "op": "maior", "valor": 1}
                cursor = self.query(order=order, filter=filter, limit=1).corpo["dados"]["cursor"]
                with self.connection() as con:
                    con.execute("UPDATE banco.linha SET " + mutation + " WHERE id=%s", (self.rows["A"],))
                self.assertEqual(self.query(order=order, filter=filter, cursor=cursor).codigo, 409)

    def test_concurrent_stale_assignment_waits_option_scan_then_rejects_retired_name(self):
        self.seed_option(count=8)
        target = self.option_rows[0]
        with self.connection() as con:
            con.execute("UPDATE banco.linha SET props=jsonb_set(props,'{state}','\"Other\"') WHERE id=%s", (target,))
        scanned, release, attempting = threading.Event(), threading.Event(), threading.Event()
        original = N.alterar_opcao
        def paused(*args, **kwargs):
            result = original(*args, **kwargs)
            scanned.set()
            self.assertTrue(release.wait(5))
            return result
        def stale_writer():
            self.assertTrue(scanned.wait(5))
            attempting.set()
            return self.request("linha.atualizar", id=target, mudancas={"state": "Old"})
        with patch.object(N, "alterar_opcao", side_effect=paused), ThreadPoolExecutor(max_workers=2) as executor:
            rename = executor.submit(self.option, "New")
            writer = executor.submit(stale_writer)
            try:
                self.assertTrue(attempting.wait(5))
                time.sleep(.1)
                self.assertFalse(writer.done(), "writer passed parent lock while option mutation was uncommitted")
            finally:
                release.set()
            self.assertEqual(rename.result(timeout=6).codigo, 200)
            self.assertEqual(writer.result(timeout=6).codigo, 409)
        self.assertEqual(self.values()[target]["state"], "Other")
        self.assertNotIn("Old", {self.values()[r]["state"] for r in self.option_rows[:-1]})

    def test_stale_property_config_cannot_undo_rename_and_fresh_color_ack_has_version(self):
        self.seed_option(count=5)
        stale = self.property()
        self.assertEqual(self.option("New").codigo, 200)
        for action in ("propriedade.salvar", "propriedade.renomear"):
            result = self.request(action, id=self.option_id, nome="State", config=stale)
            self.assertEqual(result.codigo, 409)
            self.assertEqual(self.property()["opcoes"][0]["nome"], "New")
        fresh = self.property()
        fresh["opcoes"][0]["cor"] = "purple"
        fresh.pop("opcoes_retiradas", None)  # client cannot erase tombstones
        result = self.request("propriedade.salvar", id=self.option_id, config=fresh)
        self.assertEqual(result.codigo, 200)
        ack = result.corpo["dados"]["propriedade"]["config"]
        self.assertEqual(ack["opcoes_version"], 2)
        self.assertEqual(ack["opcoes_retiradas"], ["Old"])
        self.assertEqual(ack["opcoes"][0]["cor"], "purple")

    def test_removed_choice_rejects_new_assignments_until_explicit_fresh_add(self):
        self.seed_option("multi_selecao", count=5)
        self.assertEqual(self.option(None).codigo, 200)
        self.assertEqual(self.request("linha.atualizar", id=self.option_rows[0], mudancas={"state": ["Old", "Unknown"]}).codigo, 409)
        self.assertEqual(self.request("linha.criar", no_id=self.ids["source_base"], props={"state": ["Old"]}).codigo, 409)
        config = self.property()
        config["opcoes"].append({"nome": "Old", "cor": "blue"})
        self.assertEqual(self.request("propriedade.salvar", id=self.option_id, config=config).codigo, 200)
        self.assertEqual(self.property()["opcoes_retiradas"], [])
        self.assertEqual(self.request("linha.atualizar", id=self.option_rows[0], mudancas={"state": ["Old", "Unknown"]}).codigo, 200)

    def test_preexisting_legacy_unknown_and_restored_trash_choices_are_not_normalized(self):
        self.seed_option("multi_selecao", count=5)
        self.assertEqual(self.option(None).codigo, 200)
        with self.connection() as con:
            con.execute("UPDATE banco.linha SET deletado_em=NULL WHERE id=%s", (self.option_rows[-1],))
        preserved = self.request("linha.atualizar", id=self.option_rows[-1], mudancas={"state": ["Old", "Other", "Unknown"], "extra": "changed"})
        self.assertEqual(preserved.codigo, 200)
        self.assertEqual(self.values()[self.option_rows[-1]]["state"], ["Old", "Other", "Unknown"])
        unknown = self.request("linha.atualizar", id=self.option_rows[0], mudancas={"state": ["Unknown", "Brand new legacy label"]})
        self.assertEqual(unknown.codigo, 200)

    def test_option_cas_rejects_old_remove_intent_after_same_name_is_reintroduced(self):
        self.seed_option(count=5)
        for version in (True, "0", -1):
            self.assertEqual(self.option(None, versao=version).codigo, 400)
        # Missing version is version0 for the first legacy operation only.
        first = self.request("propriedade.opcao.alterar", id=self.option_id, nome="Old", novo_nome=None)
        self.assertEqual(first.codigo, 200)
        config = self.property()
        config["opcoes"].append({"nome": "Old", "cor": "green"})
        self.assertEqual(self.request("propriedade.salvar", id=self.option_id, config=config).codigo, 200)
        self.assertEqual(self.property()["opcoes_version"], 2)
        self.assertEqual(self.option(None, versao=0).codigo, 409)
        self.assertEqual(self.request("propriedade.opcao.alterar", id=self.option_id, nome="Old", novo_nome=None).codigo, 409)
        self.assertIn("Old", [p["nome"] for p in self.property()["opcoes"]])

    def test_choice_config_hook_failure_rolls_back_version_metadata_and_color(self):
        self.seed_option(count=5)
        before = self.property()
        config = {**before, "opcoes": [{**p, "cor": "purple"} for p in before["opcoes"]]}
        with patch.object(S.P, "enfileirar_no", side_effect=N.ErroDeBanco("synthetic bridge failure")):
            self.assertEqual(self.request("propriedade.salvar", id=self.option_id, config=config).codigo, 400)
        self.assertEqual(self.property(), before)
