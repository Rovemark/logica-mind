"""Os módulos prontos da Logica Life são DADOS, não código.

Esta é a tese do produto, e ela tem um teste que a protege: nenhum nome de módulo
("hábito", "tarefa", "finança") pode aparecer dentro do motor de vistas. Se aparecer,
aquele módulo deixou de ser template e virou código privilegiado, e a promessa de que
o usuário pode criar os próprios bancos morre junto.

Ligar um módulo cria um banco com estas propriedades e estas vistas. Depois disso ele
é INDISTINGUÍVEL de um banco criado à mão: o usuário pode apagar a propriedade,
renomear, trocar a vista padrão. Nada quebra, porque não há código que dependa desses
nomes.

Nem tudo nasce ligado. Quinze bancos vazios na primeira tela é a definição literal de
produto que ninguém usa. `PADRAO` liga cinco; o resto fica no catálogo.
"""

import json

# (chave, nome, tipo, config)
def _p(nome, tipo, **cfg):
    return {"nome": nome, "tipo": tipo, "config": cfg}


def _sel(*opcoes):
    return {"opcoes": [{"nome": o, "cor": c} for o, c in opcoes]}


MODELOS = {
    # ── a espinha ─────────────────────────────────────────────────────────────
    # Sem Áreas, o produto é dez silos e o painel "Hoje" nunca consegue dizer
    # "faz doze dias que você não toca em Saúde".
    "areas": {
        "nome": "Áreas da vida", "icone": "◈", "grupo": "base", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Cor", "selecao", **_sel(("sovereign","sovereign"),("ambar","mod"),("steel","steel"))),
            _p("Atributo", "selecao", **_sel(("VIGOR",""),("FOCO",""),("MENTE",""),("CORPO",""),("ORDEM",""))),
            _p("Estado", "selecao", **_sel(("saudável",""),("atenção",""),("negligenciada",""))),
            _p("Último toque", "data"),
        ],
        "vistas": [{"nome": "Áreas", "tipo": "galeria", "padrao": True, "config": {}}],
    },
    "projetos": {
        "nome": "Projetos", "icone": "▣", "grupo": "trabalho", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Status", "selecao", **_sel(("Ideia",""),("Ativo",""),("Pausado",""),("Concluído",""),("Arquivado",""))),
            _p("Área", "relacao", alvo_modelo="areas"),
            _p("Prazo", "data"),
            _p("Progresso", "numero", formato="porcento"),
            _p("Responsáveis", "pessoa", multiplo=True),
            _p("Projeto pai", "relacao", alvo_modelo="projetos", bidirecional=True, nome_inverso="Subprojetos"),
            _p("Dependências", "relacao", alvo_modelo="projetos", multiplo=True, bidirecional=True, nome_inverso="Bloqueia", semantica="dependencia"),
            _p("Modo de execução", "selecao", **_sel(("Manual",""),("Assistido",""),("Autônomo",""))),
            _p("Execução", "selecao", **_sel(("Não iniciada",""),("Na fila",""),("Executando",""),("Concluída",""),("Falhou",""))),
        ],
        "vistas": [
            {"nome": "Quadro", "tipo": "quadro", "padrao": True, "config": {"agrupar_por": "status"}},
            {"nome": "Tabela", "tipo": "tabela", "config": {}},
            {"nome": "Calendário", "tipo": "calendario", "config": {"data_por": "prazo"}},
        ],
    },
    "tarefas": {
        "nome": "Tarefas", "icone": "☑", "grupo": "trabalho", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Estado", "selecao", **_sel(("A fazer",""),("Fazendo",""),("Feito",""))),
            _p("Projeto", "relacao", alvo_modelo="projetos"),
            _p("Prazo", "data"),
            _p("Prioridade", "selecao", **_sel(("Alta",""),("Média",""),("Baixa",""))),
            _p("Esforço", "numero", unidade="min"),
            _p("Área", "relacao", alvo_modelo="areas"),
            # O "Foco de Hoje" é uma VISTA FILTRADA disto, não um banco próprio. Como
            # banco, seria um módulo que não é template de nada e a tese morre no
            # primeiro dia.
            _p("Foco", "checkbox"),
            _p("Data do foco", "data"),
            _p("Concluída em", "data"),
            _p("Responsáveis", "pessoa", multiplo=True),
            _p("Tarefa pai", "relacao", alvo_modelo="tarefas", bidirecional=True, nome_inverso="Subtarefas"),
            _p("Dependências", "relacao", alvo_modelo="tarefas", multiplo=True, bidirecional=True, nome_inverso="Bloqueia", semantica="dependencia"),
            _p("Recorrência", "selecao", **_sel(("Não repetir",""),("Diária",""),("Dias úteis",""),("Semanal",""),("Mensal",""),("Anual",""))),
            _p("Modo de execução", "selecao", **_sel(("Manual",""),("Assistido",""),("Autônomo",""))),
            _p("Execução", "selecao", **_sel(("Não iniciada",""),("Na fila",""),("Executando",""),("Concluída",""),("Falhou",""))),
        ],
        "vistas": [
            {"nome": "Hoje", "tipo": "lista", "padrao": True, "config": {
                "filtro": {"e": [{"prop": "estado", "op": "diferente", "valor": "Feito"}]},
                "ordenacao": [{"prop": "prazo", "dir": "asc"}]}},
            {"nome": "Foco de hoje", "tipo": "lista", "config": {
                "filtro": {"e": [{"prop": "foco", "op": "marcado"}]}, "limite": 3}},
            {"nome": "Quadro", "tipo": "quadro", "config": {"agrupar_por": "estado"}},
            {"nome": "Calendário", "tipo": "calendario", "config": {"data_por": "prazo"}},
        ],
    },
    "habitos": {
        "nome": "Hábitos", "icone": "◐", "grupo": "vida", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Cadência", "selecao", **_sel(("diário",""),("dias da semana",""),("N por semana",""))),
            _p("Vezes por semana", "numero"),
            _p("Atributo", "selecao", **_sel(("VIGOR",""),("FOCO",""),("MENTE",""),("CORPO",""),("ORDEM",""))),
            _p("Ativo", "checkbox"),
            _p("Área", "relacao", alvo_modelo="areas"),
            # rollup_janela: relação + data + checkbox vira N booleanos. É genérico —
            # serve hábito, remédio, planta regada. Sem ele, a grade de sete dias
            # viraria uma sexta vista e quebraria a promessa das cinco.
            _p("Últimos 7 dias", "rollup_janela", janela=7),
        ],
        "vistas": [{"nome": "Hoje", "tipo": "lista", "padrao": True, "config": {
            "filtro": {"e": [{"prop": "ativo", "op": "marcado"}]}}}],
    },
    "registros_habito": {
        "nome": "Registros de hábito", "icone": "·", "grupo": "vida", "titulo": "nome",
        "oculto": True,
        "propriedades": [
            _p("Nome", "texto"), _p("Hábito", "relacao", alvo_modelo="habitos"), _p("Data", "data"),
            _p("Feito", "checkbox"), _p("Observação", "texto_longo"),
        ],
        "vistas": [{"nome": "Calendário", "tipo": "calendario", "padrao": True,
                    "config": {"data_por": "data"}}],
    },
    "diario": {
        "nome": "Diário", "icone": "✎", "grupo": "vida", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"), _p("Data", "data"),
            _p("Humor", "selecao", **_sel(("ótimo",""),("bom",""),("neutro",""),("ruim",""),("péssimo",""))),
            _p("Energia", "numero", min=1, max=5),
            _p("Gratidão", "texto_longo"),
        ],
        "vistas": [{"nome": "Calendário", "tipo": "calendario", "padrao": True,
                    "config": {"data_por": "data"}}],
    },
    "notas": {
        "nome": "Notas", "icone": "▤", "grupo": "vida", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Tipo", "selecao", **_sel(("nota",""),("ideia",""),("referência",""),("receita",""),("reunião",""))),
            _p("Etiquetas", "multi_selecao"), _p("Fonte", "url"), _p("Revisar em", "data"),
        ],
        "vistas": [{"nome": "Galeria", "tipo": "galeria", "padrao": True, "config": {}}],
    },
    "saude": {
        "nome": "Saúde", "icone": "♡", "grupo": "vida", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"), _p("Data", "data"),
            _p("Tipo", "selecao", **_sel(("peso",""),("pressão",""),("sono",""),("passos",""),
                                          ("humor",""),("glicemia",""),("dor",""),("treino",""))),
            _p("Valor", "numero"), _p("Unidade", "texto"), _p("Contexto", "texto_longo"),
        ],
        "vistas": [{"nome": "Tabela", "tipo": "tabela", "padrao": True,
                    "config": {"ordenacao": [{"prop": "data", "dir": "desc"}]}}],
    },
    "compras": {
        "nome": "Lista de compras", "icone": "▦", "grupo": "casa", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"), _p("Quantidade", "numero"),
            _p("Unidade", "selecao", **_sel(("un",""),("kg",""),("g",""),("L",""),("ml",""),("pct",""))),
            _p("Corredor", "selecao", **_sel(("hortifruti",""),("mercearia",""),("limpeza",""),
                                              ("higiene",""),("frios",""),("outros",""))),
            _p("Comprado", "checkbox"),
            # DINHEIRO EM CENTAVOS INTEIROS. Se nascer em ponto flutuante, os totais
            # divergem por centavos e não tem conserto depois de mil lançamentos.
            _p("Preço", "moeda", moeda="BRL", em_centavos=True),
            _p("Loja", "texto"),
        ],
        "vistas": [{"nome": "Comprar", "tipo": "lista", "padrao": True, "config": {
            "filtro": {"e": [{"prop": "comprado", "op": "desmarcado"}]},
            "agrupar_por": "corredor"}}],
    },
    "financas": {
        "nome": "Lançamentos", "icone": "₪", "grupo": "dinheiro", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Valor", "moeda", moeda="BRL", em_centavos=True),
            _p("Tipo", "selecao", **_sel(("entrada",""),("saída",""),("transferência",""))),
            _p("Categoria", "selecao"), _p("Conta", "relacao"), _p("Data", "data"),
            _p("Método", "selecao", **_sel(("pix",""),("crédito",""),("débito",""),("dinheiro",""),("boleto",""))),
            _p("Recorrente", "checkbox"), _p("Observação", "texto_longo"),
        ],
        "vistas": [{"nome": "Por mês", "tipo": "tabela", "padrao": True,
                    "config": {"ordenacao": [{"prop": "data", "dir": "desc"}]}}],
    },
    "metas": {
        "nome": "Metas", "icone": "◎", "grupo": "trabalho", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Horizonte", "selecao", **_sel(("ano",""),("trimestre",""),("mês",""))),
            _p("Área", "relacao", alvo_modelo="areas"), _p("Métrica", "texto"),
            _p("Alvo", "numero"), _p("Atual", "numero"), _p("Prazo", "data"),
            _p("Estado", "selecao", **_sel(("ativa",""),("atingida",""),("abandonada",""))),
        ],
        "vistas": [{"nome": "Metas", "tipo": "tabela", "padrao": True,
                    "config": {"agrupar_por": "horizonte"}}],
    },
    "leituras": {
        "nome": "Leituras e mídia", "icone": "▭", "grupo": "vida", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Tipo", "selecao", **_sel(("livro",""),("artigo",""),("filme",""),("série",""),
                                          ("podcast",""),("curso",""))),
            _p("Autor", "texto"),
            _p("Estado", "selecao", **_sel(("quero",""),("lendo",""),("pausado",""),
                                            ("concluído",""),("abandonado",""))),
            _p("Nota", "numero", min=1, max=5), _p("Progresso", "numero", formato="porcento"),
            _p("Início", "data"), _p("Fim", "data"), _p("Link", "url"),
        ],
        "vistas": [{"nome": "Estante", "tipo": "galeria", "padrao": True,
                    "config": {"agrupar_por": "estado"}}],
    },
    # ── os que eu proponho ────────────────────────────────────────────────────
    "pessoas": {
        "nome": "Pessoas", "icone": "◑", "grupo": "vida", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Relação", "selecao", **_sel(("família",""),("amigo",""),("trabalho",""),("serviço",""))),
            _p("Aniversário", "data"), _p("Último contato", "data"),
            _p("Frequência desejada", "numero", unidade="dias"),
            _p("Telefone", "telefone"), _p("O que importa", "texto_longo"),
        ],
        "vistas": [{"nome": "Há mais tempo sem falar", "tipo": "tabela", "padrao": True,
                    "config": {"ordenacao": [{"prop": "ultimo_contato", "dir": "asc"}]}}],
    },
    "rotinas": {
        "nome": "Rotinas e manutenções", "icone": "↻", "grupo": "casa", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Categoria", "selecao", **_sel(("casa",""),("carro",""),("documentos",""),
                                               ("saúde",""),("dinheiro",""))),
            _p("A cada", "numero", unidade="dias"),
            _p("Última vez", "data"), _p("Próxima", "data"),
            _p("Custo estimado", "moeda", moeda="BRL", em_centavos=True),
        ],
        "vistas": [{"nome": "O que vence", "tipo": "lista", "padrao": True,
                    "config": {"ordenacao": [{"prop": "proxima", "dir": "asc"}]}}],
    },
    "coisas": {
        "nome": "Coisas", "icone": "▧", "grupo": "casa", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"), _p("Categoria", "selecao"), _p("Comprado em", "data"),
            _p("Valor", "moeda", moeda="BRL", em_centavos=True),
            _p("Garantia até", "data"), _p("Onde está", "texto"), _p("Nota fiscal", "arquivo"),
        ],
        "vistas": [{"nome": "Inventário", "tipo": "galeria", "padrao": True, "config": {}}],
    },
    "decisoes": {
        "nome": "Cofre de decisões", "icone": "◭", "grupo": "trabalho", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"), _p("Data", "data"),
            _p("Por quê", "texto_longo"), _p("O que eu esperava", "texto_longo"),
            _p("O que aconteceu", "texto_longo"), _p("Revisar em", "data"),
            _p("Acertou", "selecao", **_sel(("sim",""),("em parte",""),("não",""),("cedo demais",""))),
        ],
        "vistas": [{"nome": "Linha do tempo", "tipo": "lista", "padrao": True,
                    "config": {"ordenacao": [{"prop": "data", "dir": "desc"}]}}],
    },
    # ── PJ: a empresa ─────────────────────────────────────────────────────────
    # A Life serve pessoa física E jurídica, e não são o mesmo produto com outro nome:
    # quem toca uma empresa não quer "Hábitos" na lateral, e quem organiza a própria
    # vida não quer "Pipeline". Por isso ARRANJOS (ver ARRANJOS, no fim do arquivo) —
    # cada perfil instala o seu conjunto, no seu espaço.
    "clientes": {
        "nome": "Clientes", "icone": "◉", "grupo": "empresa", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Estágio", "selecao", **_sel(("Lead",""),("Conversando",""),("Proposta",""),("Fechado",""),("Perdido",""))),
            _p("Responsável", "texto"),
            _p("Valor", "numero", formato="dinheiro"),
            _p("Próximo passo", "texto"),
            _p("Último contato", "data"),
        ],
        "vistas": [
            {"nome": "Pipeline", "tipo": "quadro", "padrao": True, "config": {"agrupar_por": "estagio"}},
            {"nome": "Tabela", "tipo": "tabela", "config": {}},
        ],
    },
    "projetos_empresa": {
        "nome": "Projetos", "icone": "▣", "grupo": "empresa", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Status", "selecao", **_sel(("Ideia",""),("Planejamento",""),("Em andamento",""),("Em risco",""),("Concluído",""),("Arquivado",""))),
            _p("Cliente", "relacao", alvo_modelo="clientes"),
            _p("Responsáveis", "pessoa", multiplo=True),
            _p("Prazo", "data"),
            _p("Progresso", "numero", formato="porcento"),
            _p("Objetivo", "texto_longo"),
            _p("Projeto pai", "relacao", alvo_modelo="projetos_empresa", bidirecional=True, nome_inverso="Subprojetos"),
            _p("Dependências", "relacao", alvo_modelo="projetos_empresa", multiplo=True, bidirecional=True, nome_inverso="Bloqueia", semantica="dependencia"),
            _p("Modo de execução", "selecao", **_sel(("Manual",""),("Assistido",""),("Autônomo",""))),
            _p("Execução", "selecao", **_sel(("Não iniciada",""),("Na fila",""),("Executando",""),("Concluída",""),("Falhou",""))),
        ],
        "vistas": [
            {"nome": "Quadro", "tipo": "quadro", "padrao": True, "config": {"agrupar_por": "status"}},
            {"nome": "Tabela", "tipo": "tabela", "config": {}},
            {"nome": "Calendário", "tipo": "calendario", "config": {"data_por": "prazo"}},
        ],
    },
    "tarefas_empresa": {
        "nome": "Tarefas", "icone": "☑", "grupo": "empresa", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Estado", "selecao", **_sel(("A fazer",""),("Fazendo",""),("Revisão",""),("Feito",""),("Bloqueado",""))),
            _p("Projeto", "relacao", alvo_modelo="projetos_empresa"),
            _p("Cliente", "relacao", alvo_modelo="clientes"),
            _p("Prioridade", "selecao", **_sel(("Urgente",""),("Alta",""),("Média",""),("Baixa",""))),
            _p("Prazo", "data"),
            _p("Responsáveis", "pessoa", multiplo=True),
            _p("Origem", "selecao", **_sel(("Pessoa",""),("Cortex",""),("Rotina",""),("Integração",""))),
            _p("Tipo de executor", "selecao", **_sel(("Pessoa",""),("Cortex",""),("Agente",""),("Squad",""))),
            _p("Agentes", "texto"),
            _p("Tarefa pai", "relacao", alvo_modelo="tarefas_empresa", bidirecional=True, nome_inverso="Subtarefas"),
            _p("Dependências", "relacao", alvo_modelo="tarefas_empresa", multiplo=True, bidirecional=True, nome_inverso="Bloqueia", semantica="dependencia"),
            _p("Recorrência", "selecao", **_sel(("Não repetir",""),("Diária",""),("Dias úteis",""),("Semanal",""),("Mensal",""),("Anual",""))),
            _p("Modo de execução", "selecao", **_sel(("Manual",""),("Assistido",""),("Autônomo",""))),
            _p("Execução", "selecao", **_sel(("Não iniciada",""),("Na fila",""),("Executando",""),("Concluída",""),("Falhou",""))),
            _p("Concluída em", "data"),
        ],
        "vistas": [
            {"nome": "Quadro", "tipo": "quadro", "padrao": True, "config": {"agrupar_por": "estado"}},
            {"nome": "Tabela", "tipo": "tabela", "config": {}},
            {"nome": "Calendário", "tipo": "calendario", "config": {"data_por": "prazo"}},
        ],
    },
    "rotinas_empresa": {
        "nome": "Rotinas", "icone": "↻", "grupo": "empresa", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Estado", "selecao", **_sel(("Ativa",""),("Pausada",""),("Em revisão",""),("Com falha",""))),
            _p("Projeto", "relacao", alvo_modelo="projetos_empresa"),
            _p("Frequência", "selecao", **_sel(("A cada hora",""),("Diária",""),("Dias úteis",""),("Semanal",""),("Mensal",""),("Personalizada",""))),
            _p("Próxima execução", "data"),
            _p("Responsáveis", "pessoa", multiplo=True),
            _p("Tipo de executor", "selecao", **_sel(("Pessoa",""),("Cortex",""),("Agente",""),("Squad",""))),
            _p("Agentes", "texto"),
            _p("Modo de execução", "selecao", **_sel(("Manual",""),("Assistido",""),("Autônomo",""))),
            _p("Execução", "selecao", **_sel(("Não iniciada",""),("Na fila",""),("Executando",""),("Concluída",""),("Falhou",""))),
            _p("Última execução", "data"),
            _p("Resultado", "texto_longo"),
        ],
        "vistas": [
            {"nome": "Por estado", "tipo": "quadro", "padrao": True, "config": {"agrupar_por": "estado"}},
            {"nome": "Agenda", "tipo": "calendario", "config": {"data_por": "proxima_execucao"}},
            {"nome": "Tabela", "tipo": "tabela", "config": {}},
        ],
    },
    "propostas": {
        "nome": "Propostas", "icone": "▤", "grupo": "empresa", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Cliente", "relacao", alvo_modelo="clientes"),
            _p("Status", "selecao", **_sel(("Rascunho",""),("Enviada",""),("Em análise",""),("Aceita",""),("Recusada",""))),
            _p("Valor", "numero", formato="dinheiro"),
            _p("Enviada em", "data"),
            _p("Validade", "data"),
        ],
        "vistas": [
            {"nome": "Quadro", "tipo": "quadro", "padrao": True, "config": {"agrupar_por": "status"}},
            {"nome": "Tabela", "tipo": "tabela", "config": {}},
        ],
    },
    "reunioes": {
        "nome": "Reuniões", "icone": "◎", "grupo": "empresa", "titulo": "nome",
        "propriedades": [
            _p("Assunto", "texto"),
            _p("Quando", "data"),
            _p("Com quem", "texto"),
            _p("Decisões", "texto"),
            _p("Cliente", "relacao", alvo_modelo="clientes"),
        ],
        "vistas": [
            {"nome": "Calendário", "tipo": "calendario", "padrao": True, "config": {"data_por": "quando"}},
            {"nome": "Tabela", "tipo": "tabela", "config": {"ordenacao": [{"prop": "quando", "dir": "desc"}]}},
        ],
    },
    "entregas": {
        "nome": "Entregas", "icone": "◈", "grupo": "empresa", "titulo": "nome",
        "propriedades": [
            _p("Nome", "texto"),
            _p("Cliente", "relacao", alvo_modelo="clientes"),
            _p("Estado", "selecao", **_sel(("A fazer",""),("Fazendo",""),("Revisão",""),("Entregue",""))),
            _p("Prazo", "data"),
            _p("Responsável", "texto"),
        ],
        "vistas": [
            {"nome": "Quadro", "tipo": "quadro", "padrao": True, "config": {"agrupar_por": "estado"}},
            {"nome": "Calendário", "tipo": "calendario", "config": {"data_por": "prazo"}},
        ],
    },
    "caixa": {
        "nome": "Caixa da empresa", "icone": "$", "grupo": "empresa", "titulo": "descricao",
        "propriedades": [
            _p("Descrição", "texto"),
            _p("Tipo", "selecao", **_sel(("Entrada",""),("Saída",""))),
            _p("Valor", "numero", formato="dinheiro"),
            _p("Categoria", "selecao", **_sel(("Serviço",""),("Imposto",""),("Ferramenta",""),("Pessoal",""),("Outro",""))),
            _p("Quando", "data"),
            _p("Cliente", "relacao", alvo_modelo="clientes"),
        ],
        "vistas": [
            {"nome": "Movimento", "tipo": "tabela", "padrao": True,
             "config": {"ordenacao": [{"prop": "quando", "dir": "desc"}]}},
            {"nome": "Calendário", "tipo": "calendario", "config": {"data_por": "quando"}},
        ],
    },
}

# Cinco na primeira abertura. O resto no catálogo, com pré-visualização.
PADRAO = ("areas", "tarefas", "habitos", "registros_habito", "diario", "notas")

# ── ARRANJOS ──────────────────────────────────────────────────────────────────
#
# A Life serve pessoa FÍSICA e JURÍDICA, e não são o mesmo produto com outro rótulo.
# Quem toca uma empresa não quer "Hábitos" na lateral; quem organiza a própria vida não
# quer "Pipeline". Instalar tudo para todo mundo é a definição literal de produto que
# ninguém usa — o mesmo motivo pelo qual PADRAO liga seis bancos e não dezesseis.
#
# Cada arranjo diz: o nome do espaço, o ícone, e os bancos que nascem dentro dele. O
# perfil "ambos" cria os DOIS espaços, que é o caso de quem tem CNPJ e vida — a maioria
# de quem usa isto.
ARRANJOS = {
    "pessoal": {
        "nome": "Pessoal",
        "espaco": {"nome": "Minha vida", "icone": "◈"},
        "modelos": ("areas", "projetos", "tarefas", "habitos", "registros_habito", "diario", "notas"),
    },
    "empresa": {
        "nome": "Empresa",
        "espaco": {"nome": "Minha empresa", "icone": "▣"},
        "modelos": ("projetos_empresa", "tarefas_empresa", "rotinas_empresa", "clientes", "propostas", "entregas", "reunioes", "caixa", "notas"),
    },
    "ambos": {
        "nome": "Pessoal e empresa",
        "espacos": ("pessoal", "empresa"),
    },
}


def arranjos() -> list:
    """O catálogo de arranjos, para a tela de primeira abertura."""
    saida = []
    for chave, a in ARRANJOS.items():
        if "espacos" in a:
            modelos = tuple(m for e in a["espacos"] for m in ARRANJOS[e]["modelos"])
            saida.append({"chave": chave, "nome": a["nome"], "espacos": list(a["espacos"]),
                          "modelos": sorted(set(modelos))})
        else:
            saida.append({"chave": chave, "nome": a["nome"], "espaco": a["espaco"],
                          "modelos": list(a["modelos"])})
    return saida


def instalar(cur, user_id: str, chave: str, nucleo, espaco_id: str = None) -> dict:
    """Cria o banco, as propriedades e as vistas de um modelo. Depois disto ele é um
    banco comum: nada no motor sabe que ele veio de um template."""
    if chave not in MODELOS:
        raise ValueError(f"modelo desconhecido: {chave}")
    m = MODELOS[chave]
    no = nucleo.criar_no(cur, user_id, espaco_id=espaco_id, tipo="banco",
                         nome=m["nome"], icone=m.get("icone"), modelo=chave,
                         chave_titulo=m.get("titulo", "nome"))
    criadas = []
    for p in m["propriedades"]:
        criadas.append(nucleo.criar_propriedade(cur, user_id, no["id"], p["nome"],
                                                p["tipo"], p.get("config")))
    for v in m["vistas"]:
        nucleo.criar_vista(cur, user_id, no["id"], v["nome"], v["tipo"],
                           v.get("config"), bool(v.get("padrao")))
    no["propriedades"] = criadas
    return no


def ligar_relacoes(cur, user_id: str) -> int:
    """Resolve relações declaradas por modelo depois que um arranjo foi instalado.

    O ID concreto do banco não existe no template e pode mudar por pessoa. Guardar só
    ``alvo_modelo`` deixava a UI pedindo configuração manual; aqui ele vira
    ``alvo_no_id`` sem sobrescrever uma relação que a pessoa já personalizou.
    """
    cur.execute("SELECT id,modelo FROM banco.no WHERE user_id=%s AND modelo IS NOT NULL "
                "AND arquivado_em IS NULL", (user_id,))
    por_modelo = {modelo: str(ident) for ident, modelo in cur.fetchall()}
    feitos = 0
    for modelo, no_id in por_modelo.items():
        definicao = MODELOS.get(modelo) or {}
        for prop in definicao.get("propriedades", []):
            alvo_modelo = (prop.get("config") or {}).get("alvo_modelo")
            alvo_id = por_modelo.get(alvo_modelo)
            if prop.get("tipo") != "relacao" or not alvo_id:
                continue
            cur.execute("UPDATE banco.propriedade SET config=config || %s::jsonb "
                        "WHERE user_id=%s AND no_id=%s AND nome=%s AND tipo='relacao' "
                        "AND NOT (config ? 'alvo_no_id')",
                        (json.dumps({"alvo_modelo": alvo_modelo, "alvo_no_id": alvo_id}),
                         user_id, no_id, prop["nome"]))
            feitos += cur.rowcount
    return feitos


def atualizar_instalados(cur, user_id: str, nucleo) -> dict:
    """Acrescenta capacidades novas aos modelos já instalados sem reescrever nada.

    Campos renomeados, tipos alterados, opções e vistas que a pessoa personalizou
    permanecem intocados. Só uma ausência inequívoca é preenchida. A chamada é
    versionada no cliente para não transformar uma exclusão intencional em um campo
    que reaparece a cada abertura.
    """
    cur.execute("SELECT id,modelo FROM banco.no WHERE user_id=%s AND modelo IS NOT NULL "
                "AND arquivado_em IS NULL", (user_id,))
    instalados = [(str(ident), modelo) for ident, modelo in cur.fetchall()]
    props_criadas = 0
    vistas_criadas = 0
    for no_id, modelo in instalados:
        definicao = MODELOS.get(modelo)
        if not definicao:
            continue
        cur.execute("SELECT id,nome,tipo,config FROM banco.propriedade WHERE user_id=%s AND no_id=%s",
                    (user_id, no_id))
        existentes = {r[1]: {"id": str(r[0]), "tipo": r[2], "config": r[3] or {}} for r in cur.fetchall()}
        nomes_props = set(existentes)
        for prop in definicao.get("propriedades", []):
            if prop["nome"] in nomes_props:
                atual = existentes[prop["nome"]]
                if prop["tipo"] == "relacao" and atual["tipo"] == "relacao":
                    faltantes = {k: v for k, v in (prop.get("config") or {}).items()
                                 if k not in atual["config"] and k != "alvo_no_id"}
                    if faltantes:
                        cur.execute("UPDATE banco.propriedade SET config=config || %s::jsonb "
                                    "WHERE id=%s AND user_id=%s", (json.dumps(faltantes), atual["id"], user_id))
                        props_criadas += 1
                continue
            nucleo.criar_propriedade(cur, user_id, no_id, prop["nome"], prop["tipo"],
                                     prop.get("config"))
            nomes_props.add(prop["nome"])
            props_criadas += 1
        cur.execute("SELECT nome FROM banco.vista WHERE user_id=%s AND no_id=%s",
                    (user_id, no_id))
        nomes_vistas = {r[0] for r in cur.fetchall()}
        for vista in definicao.get("vistas", []):
            if vista["nome"] in nomes_vistas:
                continue
            nucleo.criar_vista(cur, user_id, no_id, vista["nome"], vista["tipo"],
                               vista.get("config"), False)
            nomes_vistas.add(vista["nome"])
            vistas_criadas += 1
    relacoes = ligar_relacoes(cur, user_id)
    return {"propriedades": props_criadas, "vistas": vistas_criadas,
            "relacoes_configuradas": relacoes}


def catalogo() -> list:
    return [{"chave": k, "nome": v["nome"], "icone": v.get("icone"),
             "grupo": v.get("grupo"), "oculto": bool(v.get("oculto")),
             "padrao": k in PADRAO,
             "propriedades": [p["nome"] for p in v["propriedades"]],
             "vistas": [{"nome": x["nome"], "tipo": x["tipo"]} for x in v["vistas"]]}
            for k, v in MODELOS.items()]
