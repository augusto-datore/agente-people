"""Monta a interface Streamlit da Central de Recrutamento."""

import os  # Verifica se os arquivos de configuração estão disponíveis.
import sys  # Permite importar módulos que ficam na pasta do projeto.
from datetime import datetime, timedelta, timezone
from pathlib import Path  # Encontra o CSS ao lado deste arquivo.

import streamlit as st  # Componentes visuais e estado da página.

# Garante que a pasta do projeto esteja no sys.path antes de importar o agente.
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Importamos o modelo, o ID da planilha e a função que processa pedidos.
from agente import MODELO_GROQ, PLANILHA_ID, executar_agente_rh  # type: ignore[reportMissingImports]
from google_tools import (
    CAMPOS_DA_PLANILHA,
    atualizar_agendamento_calendar,
    atualizar_campos_linha_planilha,
    listar_candidatos_planilha,
    _normalizar_campo,
)

# Configuramos o título, ícone e largura da aplicação.
st.set_page_config(
    page_title="Central de Recrutamento",
    page_icon="\U0001F4BC",
    layout="wide"
)

# O CSS separado define cores, espaçamentos, cartões e botões.
css_path = Path(__file__).with_name("styles.css")
css = css_path.read_text(encoding="utf-8")
st.markdown(f"<style>\n{css}\n</style>", unsafe_allow_html=True)

# Estes indicadores mostram se as configurações principais estão presentes.
groq_configurado = bool(os.environ.get("GROQ_API_KEY"))
google_configurado = os.path.exists("credentials.json")
planilha_configurada = bool(PLANILHA_ID)

# A barra lateral resume o nome do sistema, integrações e modelo utilizado.
with st.sidebar:
    st.markdown('<div class="brand-mark">TALENT WORKSPACE</div>', unsafe_allow_html=True)
    st.markdown("## Central de RH")
    st.caption("Assistente de recrutamento")
    st.divider()

    st.markdown("#### Integrações")
    # Cada par associa o nome de uma integração à sua configuração.
    for label, configurado in (
        ("Assistente de IA", groq_configurado),
        ("Google Workspace", google_configurado),
        ("Planilha de candidatos", planilha_configurada),
    ):
        # A classe CSS muda a cor do indicador conforme o estado.
        estado = "Configurado" if configurado else "Verificar configuração"
        classe = "ok" if configurado else "off"
        st.markdown(
            f'<div class="status-line"><span class="status-dot {classe}"></span>'
            f'<span>{label}</span></div>',
            unsafe_allow_html=True
        )
        if not configurado:
            st.caption(estado)

    st.divider()
    st.caption("Modelo de IA")
    st.code(MODELO_GROQ, language=None)
    st.caption("Conectado via Groq Cloud")

# Localiza os campos mesmo quando os títulos da planilha usam acentos ou aliases.
def valor_do_campo(cabecalho, valores, campo):
    aliases = CAMPOS_DA_PLANILHA[campo]
    for indice, titulo in enumerate(cabecalho):
        if _normalizar_campo(titulo) in aliases:
            return valores[indice] if indice < len(valores) else ""
    return ""


def atualizar_valor_do_campo(cabecalho, valores, campo, valor):
    aliases = CAMPOS_DA_PLANILHA[campo]
    for indice, titulo in enumerate(cabecalho):
        if _normalizar_campo(titulo) in aliases:
            valores[indice] = valor
            return


def horarios_futuros(data, agora, depois_de=None, ultimo_minuto=1435):
    passo_minutos = 5
    primeiro_minuto = 0
    if data == agora.date():
        minuto_atual = agora.hour * 60 + agora.minute
        primeiro_minuto = (minuto_atual // passo_minutos + 1) * passo_minutos
    if depois_de is not None:
        primeiro_minuto = max(primeiro_minuto, depois_de.hour * 60 + depois_de.minute + passo_minutos)
    primeiro_minuto = ((primeiro_minuto + passo_minutos - 1) // passo_minutos) * passo_minutos
    return [
        f"{minuto // 60:02d}:{minuto % 60:02d}"
        for minuto in range(primeiro_minuto, ultimo_minuto + 1, passo_minutos)
    ]


st.markdown('<div class="eyebrow">OPERAÇÕES DE TALENT ACQUISITION</div>', unsafe_allow_html=True)
st.title("Gestão de recrutamento")
st.markdown(
    '<div class="page-subtitle">Histórico, candidatos e agendamentos em um só lugar.</div>',
    unsafe_allow_html=True
)

solicitacao_tab, painel_tab = st.tabs(["Nova solicitação", "Painel e histórico"])

with painel_tab:
    st.subheader("Histórico de agendamentos")
    if not PLANILHA_ID:
        st.warning("Configure PLANILHA_ID para consultar e editar os registros.")
    else:
        if st.button("Atualizar histórico") or "dados_planilha" not in st.session_state:
            with st.spinner("Carregando registros da planilha..."):
                try:
                    st.session_state.dados_planilha = listar_candidatos_planilha(PLANILHA_ID)
                    st.session_state.erro_planilha = None
                except Exception as erro:
                    st.session_state.erro_planilha = str(erro)

        erro_planilha = st.session_state.get("erro_planilha")
        dados_planilha = st.session_state.get("dados_planilha")
        if erro_planilha:
            st.error(f"Não foi possível carregar a planilha: {erro_planilha}")
        elif dados_planilha:
            cabecalho = dados_planilha["cabecalho"]
            registros = dados_planilha["linhas"]
            total_agendados = sum(
                bool(valor_do_campo(cabecalho, registro["valores"], "data"))
                for registro in registros
            )
            total_analise = sum(
                "analise" in _normalizar_campo(valor_do_campo(cabecalho, registro["valores"], "status"))
                for registro in registros
            )

            metricas = st.columns(3)
            metricas[0].metric("Candidatos", len(registros))
            metricas[1].metric("Entrevistas com data", total_agendados)
            metricas[2].metric("Em análise", total_analise)

            busca_col, status_col = st.columns([2, 1])
            busca = busca_col.text_input("Buscar por nome, e-mail ou vaga", key="busca_historico")
            status_disponiveis = sorted({
                str(valor_do_campo(cabecalho, registro["valores"], "status"))
                for registro in registros
                if valor_do_campo(cabecalho, registro["valores"], "status")
            })
            status_filtro = status_col.selectbox("Filtrar status", ["Todos", *status_disponiveis])

            registros_filtrados = []
            for registro in registros:
                nome = valor_do_campo(cabecalho, registro["valores"], "nome")
                email = valor_do_campo(cabecalho, registro["valores"], "email")
                vaga = valor_do_campo(cabecalho, registro["valores"], "vaga")
                status = valor_do_campo(cabecalho, registro["valores"], "status")
                if status_filtro != "Todos" and status != status_filtro:
                    continue
                if busca and busca.casefold() not in f"{nome} {email} {vaga}".casefold():
                    continue
                registros_filtrados.append({
                    "Nome": nome,
                    "E-mail": email,
                    "Vaga": vaga,
                    "Status": status,
                    "Data": valor_do_campo(cabecalho, registro["valores"], "data"),
                    "Horário": valor_do_campo(cabecalho, registro["valores"], "hora"),
                })

            st.dataframe(registros_filtrados, use_container_width=True, hide_index=True)

            if registros:
                st.divider()
                st.subheader("Editar agendamento")
                fuso = timezone(timedelta(hours=-3))
                agora = datetime.now(fuso)
                opcoes_agendamento = {}
                for registro in registros:
                    data_atual = valor_do_campo(cabecalho, registro["valores"], "data")
                    horario_atual = valor_do_campo(cabecalho, registro["valores"], "hora")
                    email_atual = valor_do_campo(cabecalho, registro["valores"], "email")
                    try:
                        try:
                            dia_atual = datetime.strptime(data_atual, "%d/%m/%Y").date()
                        except ValueError:
                            dia_atual = datetime.fromisoformat(data_atual).date()
                        hora_inicio_atual = datetime.strptime(
                            horario_atual.split("-")[0].strip(), "%H:%M"
                        ).time()
                    except ValueError:
                        continue
                    if not email_atual:
                        continue
                    inicio_registro = datetime.combine(dia_atual, hora_inicio_atual, tzinfo=fuso)
                    nome_atual = valor_do_campo(cabecalho, registro["valores"], "nome") or "Sem nome"
                    vaga_atual = valor_do_campo(cabecalho, registro["valores"], "vaga") or "Sem vaga"
                    status_atual = valor_do_campo(cabecalho, registro["valores"], "status") or "Sem status"
                    rotulo = (
                        f"{nome_atual} · {email_atual} · {vaga_atual} · {status_atual} · "
                        f"{dia_atual.strftime('%d/%m/%Y')} · {horario_atual} · "
                        f"linha {registro['numero']}"
                    )
                    opcoes_agendamento[rotulo] = {
                        "registro": registro,
                        "inicio_atual": inicio_registro,
                    }

                if not opcoes_agendamento:
                    st.info("Não há entrevistas futuras com data, horário e e-mail para editar.")
                else:
                    escolha_agendamento = st.selectbox(
                        "Entrevista", list(opcoes_agendamento), key="selecao_agendamento"
                    )
                    agendamento_selecionado = opcoes_agendamento[escolha_agendamento]
                    registro_agendamento = agendamento_selecionado["registro"]
                    valores_agendamento = registro_agendamento["valores"]
                    horario_atual = valor_do_campo(cabecalho, valores_agendamento, "hora")
                    partes_horario = [parte.strip() for parte in horario_atual.split("-")]
                    try:
                        hora_inicio_padrao = datetime.strptime(partes_horario[0], "%H:%M").time()
                        hora_fim_padrao = datetime.strptime(
                            partes_horario[1] if len(partes_horario) > 1 else partes_horario[0],
                            "%H:%M",
                        ).time()
                    except ValueError:
                        hora_inicio_padrao = datetime.strptime("09:00", "%H:%M").time()
                        hora_fim_padrao = datetime.strptime("10:00", "%H:%M").time()

                    data_col, inicio_col, fim_col = st.columns(3)
                    data_padrao = max(agendamento_selecionado["inicio_atual"].date(), agora.date())
                    data_nova = data_col.date_input(
                        "Data",
                        value=data_padrao,
                        min_value=agora.date(),
                        key=f"data_agendamento_{registro_agendamento['numero']}",
                    )
                    minutos_inicio_padrao = hora_inicio_padrao.hour * 60 + hora_inicio_padrao.minute
                    opcoes_inicio = horarios_futuros(data_nova, agora, ultimo_minuto=1430)
                    if not opcoes_inicio:
                        st.info("Não há mais horários disponíveis hoje. Escolha outra data.")
                        salvar_agendamento = False
                    else:
                        inicio_padrao_texto = hora_inicio_padrao.strftime("%H:%M")
                        if inicio_padrao_texto not in opcoes_inicio:
                            inicio_padrao_texto = opcoes_inicio[0]
                        hora_inicio_nova = inicio_col.selectbox(
                            "Hora início",
                            opcoes_inicio,
                            index=opcoes_inicio.index(inicio_padrao_texto),
                            key=f"inicio_agendamento_{registro_agendamento['numero']}_{data_nova.isoformat()}",
                        )
                        hora_inicio_valor = datetime.strptime(hora_inicio_nova, "%H:%M").time()
                        opcoes_fim = horarios_futuros(
                            data_nova,
                            agora,
                            depois_de=hora_inicio_valor,
                        )
                        fim_padrao_texto = hora_fim_padrao.strftime("%H:%M")
                        if fim_padrao_texto not in opcoes_fim:
                            fim_padrao_texto = opcoes_fim[0]
                        hora_fim_nova = fim_col.selectbox(
                            "Hora fim",
                            opcoes_fim,
                            index=opcoes_fim.index(fim_padrao_texto),
                            key=f"fim_agendamento_{registro_agendamento['numero']}_{data_nova.isoformat()}_{hora_inicio_nova}",
                        )
                        salvar_agendamento = st.button(
                            "Salvar agendamento",
                            type="primary",
                            key=f"salvar_agendamento_{registro_agendamento['numero']}",
                        )

                    if salvar_agendamento:
                        novo_inicio = datetime.combine(
                            data_nova, datetime.strptime(hora_inicio_nova, "%H:%M").time(), tzinfo=fuso
                        )
                        novo_fim = datetime.combine(
                            data_nova, datetime.strptime(hora_fim_nova, "%H:%M").time(), tzinfo=fuso
                        )
                        if novo_inicio <= datetime.now(fuso):
                            st.error("A entrevista precisa começar em uma data e horário futuros.")
                        elif novo_fim <= novo_inicio:
                            st.error("O horário de término precisa ser posterior ao início.")
                        else:
                            campos_novos = {
                                "data": data_nova.strftime("%d/%m/%Y"),
                                "hora": f"{hora_inicio_nova} - {hora_fim_nova}",
                            }
                            campos_antigos = {
                                "data": valor_do_campo(cabecalho, valores_agendamento, "data"),
                                "hora": valor_do_campo(cabecalho, valores_agendamento, "hora"),
                            }
                            try:
                                atualizar_campos_linha_planilha(
                                    PLANILHA_ID,
                                    dados_planilha["aba"],
                                    registro_agendamento["numero"],
                                    cabecalho,
                                    campos_novos,
                                )
                                try:
                                    atualizar_agendamento_calendar(
                                        valor_do_campo(cabecalho, valores_agendamento, "email"),
                                        agendamento_selecionado["inicio_atual"],
                                        novo_inicio,
                                        novo_fim,
                                    )
                                except Exception:
                                    atualizar_campos_linha_planilha(
                                        PLANILHA_ID,
                                        dados_planilha["aba"],
                                        registro_agendamento["numero"],
                                        cabecalho,
                                        campos_antigos,
                                    )
                                    raise
                                st.session_state.dados_planilha = listar_candidatos_planilha(PLANILHA_ID)
                                st.success("Agendamento atualizado no Calendar e no histórico.")
                                st.rerun()
                            except Exception as erro:
                                st.error(f"Não foi possível atualizar o agendamento: {erro}")

                st.divider()
                st.subheader("Editar informações do candidato")
                opcoes = {
                    f"{valor_do_campo(cabecalho, registro['valores'], 'nome') or 'Sem nome'} · "
                    f"{valor_do_campo(cabecalho, registro['valores'], 'email') or 'Sem e-mail'} · linha {registro['numero']}": registro
                    for registro in registros
                }
                escolha = st.selectbox("Candidato", list(opcoes))
                selecionado = opcoes[escolha]
                valores_originais = selecionado["valores"]

                with st.form("editar_registro"):
                    edit_col_1, edit_col_2 = st.columns(2)
                    nome_editado = edit_col_1.text_input(
                        "Nome", valor_do_campo(cabecalho, valores_originais, "nome"),
                        key=f"nome_{selecionado['numero']}"
                    )
                    email_editado = edit_col_2.text_input(
                        "E-mail", valor_do_campo(cabecalho, valores_originais, "email"),
                        key=f"email_{selecionado['numero']}"
                    )
                    vaga_editada = edit_col_1.text_input(
                        "Vaga", valor_do_campo(cabecalho, valores_originais, "vaga"),
                        key=f"vaga_{selecionado['numero']}"
                    )
                    status_editado = edit_col_2.text_input(
                        "Status", valor_do_campo(cabecalho, valores_originais, "status"),
                        key=f"status_{selecionado['numero']}"
                    )
                    salvar_edicao = st.form_submit_button("Salvar alterações", type="primary")

                if salvar_edicao:
                    campos_editados = {
                        "nome": nome_editado,
                        "email": email_editado,
                        "vaga": vaga_editada,
                        "status": status_editado,
                    }
                    try:
                        atualizar_campos_linha_planilha(
                            PLANILHA_ID,
                            dados_planilha["aba"],
                            selecionado["numero"],
                            cabecalho,
                            campos_editados,
                        )
                        st.success("Registro atualizado na planilha.")
                        st.session_state.dados_planilha = listar_candidatos_planilha(PLANILHA_ID)
                        st.rerun()
                    except Exception as erro:
                        st.error(f"Não foi possível salvar as alterações: {erro}")

with solicitacao_tab:
    st.subheader("Nova solicitação")
    st.markdown(
        "Descreva as ações desejadas e inclua os dados do candidato, a vaga e os horários "
        "quando aplicável."
    )
    with st.form("solicitacao_recrutamento"):
        prompt_usuario = st.text_area(
            "Instruções",
            key="prompt_input",
            height=150,
            placeholder=(
                "Ex.: Agende uma entrevista com nome@empresa.com em 30/10/2026, "
                "das 14h às 15h, para a vaga de Analista Financeiro."
            )
        )
        submitted = st.form_submit_button(
            "Processar solicitação",
            type="primary",
            use_container_width=True
        )

    if submitted:
        if not prompt_usuario.strip():
            st.session_state.pop("resultado_processamento", None)
            st.warning("Escreva uma instrução antes de continuar.")
        else:
            with st.spinner("Processando a solicitação..."):
                st.session_state.resultado_processamento = executar_agente_rh(prompt_usuario)
            st.session_state.pop("dados_planilha", None)

    if "resultado_processamento" in st.session_state:
        st.markdown("### Resultado da solicitação")
        for tipo, conteudo in st.session_state.resultado_processamento:
            if tipo == "calendar":
                st.success(f"**Google Calendar e Meet**  \n{conteudo}")
            elif tipo == "sheets":
                st.success(f"**Google Sheets**  \n{conteudo}")
            elif tipo == "texto":
                st.info(conteudo)
            elif tipo == "erro":
                st.error(conteudo)