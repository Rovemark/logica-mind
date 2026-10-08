"""Space metadata regressions on the private PostgreSQL fixture, never live data.

Run with psycopg installed:
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. <python> -m unittest discover -s tests
      -p test_banco_space_options.py -v
"""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_banco_life_integrity as Fixture
from logica_mind.banco import servico as S


class BancoSpaceOptionsTests(Fixture.BancoLifeIntegrityTests):
    def space(self, ident=None):
        with self.connection() as con:
            return con.execute("SELECT nome,icone,ordem,arquivado_em FROM banco.espaco WHERE id=%s",
                               (ident or self.ids["space"],)).fetchone()

    def update(self, **body):
        return self.request("espaco.atualizar", id=self.ids["space"], **body)

    def test_node_icon_only_patch_preserves_a_concurrent_rename_and_cover(self):
        node = self.ids["source_base"]
        with self.connection() as con:
            # Another editor renamed it after the UI read its old title. An icon
            # change must not require sending that stale title back to the server.
            con.execute("UPDATE banco.no SET nome='Concurrent title',capa='url:/cover.png' WHERE id=%s", (node,))
        self.assertEqual(self.request("no.renomear", id=node, icone="icone:user").codigo, 200)
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT nome,icone,capa FROM banco.no WHERE id=%s", (node,)).fetchone(),
                             ("Concurrent title", "icone:user", "url:/cover.png"))
        self.assertEqual(self.request("no.renomear", id=node, icone=None).codigo, 200)
        self.assertEqual(self.request("no.renomear", id=node, capa=None).codigo, 200)
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT nome,icone,capa FROM banco.no WHERE id=%s", (node,)).fetchone(),
                             ("Concurrent title", None, None))

    def test_node_full_rename_remains_compatible_and_foreign_owner_is_not_changed(self):
        node = self.ids["source_base"]
        response = self.request("no.renomear", id=node, nome="Legacy title", icone="icone:building", capa="url:/new-cover.png")
        self.assertEqual(response.codigo, 200)
        self.assertEqual(response.corpo, {"ok": True, "dados": {"id": node}})
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT nome,icone,capa FROM banco.no WHERE id=%s", (node,)).fetchone(),
                             ("Legacy title", "icone:building", "url:/new-cover.png"))
            foreign_before = con.execute("SELECT nome,icone,capa FROM banco.no WHERE id=%s", (self.ids["foreign_base"],)).fetchone()
        self.assertEqual(self.request("no.renomear", id=self.ids["foreign_base"], icone="icone:user").codigo, 404)
        self.assertEqual(self.request("no.renomear", id=self.ids["foreign_base"], nome="Taken", user_id="bob").codigo, 404)
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT nome,icone,capa FROM banco.no WHERE id=%s", (self.ids["foreign_base"],)).fetchone(), foreign_before)

    def test_space_name_patch_preserves_icon_order_identity_and_children(self):
        self.assertEqual(self.update(icone="icone:user").codigo, 200)
        before = self.space()
        with self.connection() as con:
            children = con.execute("SELECT id,espaco_id,nome FROM banco.no WHERE user_id='alice' ORDER BY id").fetchall()
        response = self.update(nome="  Vida de André  ")
        self.assertEqual(response.codigo, 200)
        self.assertEqual(response.corpo, {"ok": True, "dados": {
            "id": self.ids["space"], "nome": "Vida de André", "icone": "icone:user", "ordem": float(before[2])}})
        self.assertEqual(self.space()[1:3], before[1:3])
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT id,espaco_id,nome FROM banco.no WHERE user_id='alice' ORDER BY id").fetchall(), children)

    def test_space_icon_patch_and_clear_preserve_the_name(self):
        for icon, saved in (("icone:building", "icone:building"), ("👩🏽‍💻", "👩🏽‍💻"),
                            ("url:/api/uploads/icone/fixture.png", "url:/api/uploads/icone/fixture.png"),
                            (None, None), ("", None)):
            with self.subTest(icon=icon):
                response = self.update(icone=icon)
                self.assertEqual(response.codigo, 200)
                self.assertEqual(response.corpo["dados"]["nome"], "Fixture")
                self.assertEqual(response.corpo["dados"]["icone"], saved)

    def test_space_bad_names_do_not_apply_a_valid_icon_in_the_same_patch(self):
        before = self.space()
        for name in (None, False, 1, [], {}, "", "  ", "n" * 121, "a\x00b", "a\nb", "a\x85b"):
            with self.subTest(name=name):
                response = self.update(nome=name, icone="icone:user")
                self.assertEqual(response.codigo, 400)
                self.assertFalse(response.corpo["ok"])
                self.assertEqual(self.space(), before)
        self.assertEqual(self.update(nome="n" * 120).codigo, 200)

    def test_space_bad_icons_do_not_apply_a_valid_name_in_the_same_patch(self):
        before = self.space()
        for icon in (False, 1, [], {}, "x" * 2049, "a\x00b", "a\nb", "a\x85b"):
            with self.subTest(icon=icon):
                self.assertEqual(self.update(nome="New name", icone=icon).codigo, 400)
                self.assertEqual(self.space(), before)
        self.assertEqual(self.update(icone="x" * 2048).codigo, 200)

    def test_space_uuid_required_patch_required_and_unknown_fields_rejected(self):
        before = self.space()
        for ident in (None, False, 1, [], {}, "", "bad-id"):
            with self.subTest(ident=ident):
                self.assertEqual(self.request("espaco.atualizar", id=ident, nome="New").codigo, 400)
                self.assertEqual(self.space(), before)
        self.assertEqual(self.request("espaco.atualizar", nome="New").codigo, 400)
        self.assertEqual(self.update().codigo, 400)
        for unknown in ({"user_id": "bob"}, {"ordem": 0}, {"arquivado_em": None}, {"extra": True}):
            self.assertEqual(self.update(nome="New", **unknown).codigo, 400)
            self.assertEqual(self.space(), before)
        self.assertEqual(self.request("espaco.atualizar", id=str(uuid.uuid4()), nome="New").codigo, 404)

    def test_space_foreign_owner_and_archived_target_return_404_without_changes(self):
        foreign_before = self.space(self.ids["foreign_space"])
        self.assertEqual(self.request("espaco.atualizar", id=self.ids["foreign_space"], nome="Taken", icone="icone:user").codigo, 404)
        self.assertEqual(self.space(self.ids["foreign_space"]), foreign_before)
        with self.connection() as con:
            con.execute("UPDATE banco.espaco SET arquivado_em=now() WHERE id=%s", (self.ids["space"],))
        own_before = self.space()
        self.assertEqual(self.update(nome="Reopened", icone=None).codigo, 404)
        self.assertEqual(self.space(), own_before)

    def test_space_update_is_a_write_and_honors_read_only_gate(self):
        before = self.space()
        self.assertEqual(self.request("espaco.atualizar", method="GET", id=self.ids["space"], nome="New").codigo, 404)
        with patch.object(S, "somente_leitura", return_value=True):
            self.assertEqual(self.update(nome="New").codigo, 503)
        self.assertEqual(self.space(), before)

    def test_space_invalid_credentials_are_rejected_before_opening_the_pool(self):
        with patch.object(S, "ligado", return_value=True), patch.object(S, "pool", side_effect=AssertionError("unexpected database access")):
            for auth, loopback in (("", False), ("", True), ("Bearer invalid-fixture-token", False), ("Bearer invalid-fixture-token", True)):
                response = S.despacha("POST", "/api/banco/espaco.atualizar", {},
                    {"id": self.ids["space"], "nome": "New"}, auth, "fixture-global-token", False, de_loopback=loopback)
                self.assertEqual(response.codigo, 401)
                self.assertFalse(response.corpo["ok"])

    def test_space_patch_body_requires_an_object(self):
        before = self.space()
        for body in ([], "name", 1, None):
            response = S.trata("POST", "/api/banco/espaco.atualizar", {}, body, "alice")
            self.assertEqual(response.codigo, 400)
            self.assertEqual(self.space(), before)

    def test_space_independent_concurrent_patches_do_not_erase_each_other(self):
        barrier = threading.Barrier(2)

        def edit(body):
            barrier.wait(timeout=5)
            return self.update(**body).codigo

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(edit, ({"nome": "Concurrent name"}, {"icone": "icone:building"})))
        self.assertEqual(results, [200, 200])
        self.assertEqual(self.space()[:2], ("Concurrent name", "icone:building"))

    def test_arrangement_install_reuses_renamed_space_and_keeps_metadata(self):
        with self.connection() as con:
            con.execute("UPDATE banco.no SET modelo='areas' WHERE id=%s", (self.ids["source_base"],))
            before_spaces = con.execute("SELECT count(*) FROM banco.espaco WHERE user_id='alice'").fetchone()[0]
        self.assertEqual(self.update(nome="Meu universo", icone="icone:user").codigo, 200)
        response = self.request("arranjo.instalar", chave="pessoal")
        self.assertEqual(response.codigo, 200)
        self.assertGreater(response.corpo["dados"]["criados"], 0)
        self.assertTrue(all(n["espaco_id"] == self.ids["space"] for n in response.corpo["dados"]["bancos"]))
        self.assertEqual(self.space()[:2], ("Meu universo", "icone:user"))
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM banco.espaco WHERE user_id='alice'").fetchone()[0], before_spaces)
        second = self.request("arranjo.instalar", chave="pessoal")
        self.assertEqual(second.codigo, 200)
        self.assertEqual(second.corpo["dados"]["criados"], 0)
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM banco.espaco WHERE user_id='alice'").fetchone()[0], before_spaces)

    def test_arrangement_personal_and_company_signatures_never_merge_via_notes(self):
        with self.connection() as con:
            company = str(uuid.uuid4())
            con.execute("INSERT INTO banco.espaco(id,user_id,nome,icone,ordem) VALUES (%s,'alice','Negócios','icone:building',2000)", (company,))
            con.execute("UPDATE banco.espaco SET nome='Pessoal',icone='icone:user' WHERE id=%s", (self.ids["space"],))
            con.execute("UPDATE banco.no SET modelo='areas' WHERE id=%s", (self.ids["source_base"],))
            con.execute("UPDATE banco.no SET espaco_id=%s,modelo='clientes' WHERE id=%s", (company, self.ids["target_base"]))
            con.execute("UPDATE banco.no SET espaco_id=%s,modelo='notas' WHERE id=%s", (company, self.ids["wrong_base"]))
        response = self.request("arranjo.instalar", chave="ambos")
        self.assertEqual(response.codigo, 200)
        personal = set(S.M.ARRANJOS["pessoal"]["modelos"]) - {"notas"}
        business = set(S.M.ARRANJOS["empresa"]["modelos"]) - {"notas"}
        with self.connection() as con:
            models = {str(ident): model for ident, model in con.execute("SELECT id,modelo FROM banco.no WHERE user_id='alice'").fetchall()}
        for node in response.corpo["dados"]["bancos"]:
            if models[node["id"]] in personal:
                self.assertEqual(node["espaco_id"], self.ids["space"])
            if models[node["id"]] in business:
                self.assertEqual(node["espaco_id"], company)
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM banco.espaco WHERE user_id='alice'").fetchone()[0], 2)
        self.assertEqual(self.space()[:2], ("Pessoal", "icone:user"))
        self.assertEqual(self.space(company)[:2], ("Negócios", "icone:building"))

    def test_arrangement_signatures_ignore_archived_spaces_and_foreign_owner(self):
        with self.connection() as con:
            con.execute("UPDATE banco.no SET modelo='areas' WHERE id IN (%s,%s)", (self.ids["source_base"], self.ids["foreign_base"]))
            con.execute("UPDATE banco.espaco SET arquivado_em=now() WHERE id=%s", (self.ids["space"],))
        own_before, foreign_before = self.space(), self.space(self.ids["foreign_space"])
        response = self.request("arranjo.instalar", chave="pessoal")
        self.assertEqual(response.codigo, 200)
        destinations = {n["espaco_id"] for n in response.corpo["dados"]["bancos"]}
        self.assertEqual(len(destinations), 1)
        self.assertNotIn(self.ids["space"], destinations)
        self.assertNotIn(self.ids["foreign_space"], destinations)
        with self.connection() as con:
            installed_models = {model for (model,) in con.execute("SELECT modelo FROM banco.no WHERE espaco_id=%s AND user_id='alice'", (next(iter(destinations)),)).fetchall()}
        self.assertIn("areas", installed_models)
        self.assertEqual(self.space(), own_before)
        self.assertEqual(self.space(self.ids["foreign_space"]), foreign_before)

    def test_arrangement_prefers_model_signature_over_another_default_name(self):
        with self.connection() as con:
            misleading = str(uuid.uuid4())
            con.execute("INSERT INTO banco.espaco(id,user_id,nome,ordem) VALUES (%s,'alice','Minha vida',0)", (misleading,))
            con.execute("UPDATE banco.no SET modelo='areas' WHERE id=%s", (self.ids["source_base"],))
        self.assertEqual(self.update(nome="Minha organização", icone="icone:home").codigo, 200)
        response = self.request("arranjo.instalar", chave="pessoal")
        self.assertEqual(response.codigo, 200)
        self.assertTrue(all(n["espaco_id"] == self.ids["space"] for n in response.corpo["dados"]["bancos"]))
        self.assertEqual(self.space()[:2], ("Minha organização", "icone:home"))
