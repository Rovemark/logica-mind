"""Contratos de migração do Banco de dados (ponte Life ↔ Mind).

O ensaio de appliance pega a integração real com Postgres. Estes testes curtos
protegem a ordem do DDL também em ambientes de desenvolvimento sem servidor SQL.
"""

from logica_mind.banco.esquema import DDL


def test_no_expoe_chave_composta_antes_da_fk_autorreferente():
    tabela_no = DDL.index("CREATE TABLE IF NOT EXISTS no")
    unica = DDL.index("CONSTRAINT ux_no_id_user_id UNIQUE (id, user_id)", tabela_no)
    fk_pai = DDL.index("FOREIGN KEY (pai_id, user_id)", tabela_no)
    assert tabela_no < unica < fk_pai


def test_upgrade_repara_indice_e_fk_antes_das_tabelas_filhas():
    tabela_no = DDL.index("CREATE TABLE IF NOT EXISTS no")
    indice_upgrade = DDL.index(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_no_id_user_id ON no (id, user_id)",
        tabela_no,
    )
    fk_upgrade = DDL.index("ADD CONSTRAINT fk_no_pai_user", indice_upgrade)
    primeira_filha = DDL.index("CREATE TABLE IF NOT EXISTS propriedade", tabela_no)
    assert tabela_no < indice_upgrade < fk_upgrade < primeira_filha

