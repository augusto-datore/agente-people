"""Interpreta pedidos dos usuários e executa as ações do Google"""

import json #converter os dados da ferramenta do Google em JSON
import os #interage com o sistema operacional
import re #extrai dados do texto do usuário
import unicodedata #normaliza strings Unicode

from dotenv import load_dotenv #carrega variáveis de ambiente do arquivo .env
from openai import OpenAI #acessa a API do OpenAI

from google_tools import (
    cancelar_evento_calendar,
    criar_evento_entrevista_com_meet,
    registrar_candidato_planilha,
)

#carregar a groq_api_key
load_dotenv() #carrega variáveis de ambiente do arquivo .env
groq_api_key = os.getenv("GROQ_API_KEY")
#ERRO: groq_api_key não foi definida, crregue-a com os.getenv("GROQ_API_KEY") antes desse ponto
client = OpenAI(
    api_key=groq_api_key,
    base_url="https://api.groq.com/openai/v1",
) if groq_api_key else None


#definir o modelo e indicar o id da planilha
MODELO_GROQ = "openai/gpt-oss-20b"
PLANILHA_ID = os.environ.get("PLANILHA_ID")

#criando as ferramentas do agente

FERRAMENTAS = [
    {
        "type": "function",
        "function": {
            "name": "agendar_entrevista_com_meet",
            "description": "Agendar uma entrevista no Google Calendar com link do Google Meet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_candidato": {"type": "string"},
                    "email_candidato": {"type": "string"},
                    "data_hora_inicio": {
                        "type": "string",
                        "description": "Data e hora de início da entrevista no formato ISO 8601 (ex: 2023-10-01T14:00:00)",
                    },
                    "data_hora_fim": {
                        "type": "string",
                        "description": "Data e hora de término da entrevista no formato ISO 8601 (ex: 2023-10-01T15:00:00)",
                    },
                },
                "required": [
                    "nome_candidato",
                    "email_candidato",
                    "data_hora_inicio",
                    "data_hora_fim",
                ],
            },
        },
    },
    {
        #crie a função para registrar o candidato na planilha do Google Sheets
        "type": "function",
        "function": {
            "name": "registrar_candidato_planilha",
            "description": "Registrar informações do candidato em uma planilha do Google Sheets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome": {"type": "string"},
                    "email": {"type": "string"},
                    "vaga": {"type": "string"},
                    "status": {"type": "string"},
                    "data_hora_inicio": {"type": "string"},
                    "data_hora_fim": {"type": "string"},
                },
                "required": ["nome", "email"],
            },
        },
    },
]

#prompt para definir as regras do agente e os padrões para os dados informados

PROMPT = (
"Você é um agente de recrutamento e seleção. Sua função é interpretar os pedidos dos usuários e executar as ações do Google, como agendar entrevistas no Google Calendar com link do Google Meet e registrar informações de candidatos em uma planilha do Google Sheets."
"Siga as instruções abaixo:"
"1. Solicite o nome completo do candidato. \n"
"2. Solicite o e-mail do candidato. \n"
"3. Solicite a vaga para a qual o candidato está se candidatando. \n"
"4. Solicite o status do candidato (ex: aprovado, reprovado, em análise). \n"
"5. Solicite a data e hora de início da entrevista no formato ISO 8601 (ex: 2023-10-01T14:00:00). \n"
"6. Solicite a data e hora de término da entrevista no formato ISO 8601 (ex: 2023-10-01T15:00:00). \n"
"Após coletar todas as informações, utilize as funções disponíveis para agendar a entrevista e registrar o candidato na planilha. "
"Se a solicitação incluir agendamento de entrevista, a pessoa também deve ser registrada na planilha automaticamente. \n"
 )
#função para normalizar os dados d entrada
def normalizar(texto):
    """Função para normalizar,removendo acentos e caracteres especiais."""
    sem_acento = unicodedata.normalize('NFKD', texto)
    return "".join(letra for letra in sem_acento if not unicodedata.combining(letra)).lower()


def _limpar_status(status):
    if not status:
        return "Cadastrado"

    status = re.sub(
        r"\s*(?:e|,)?\s*(?:registre|registrar)\s+(?:na|o)\s+planilha.*$",
        "",
        status.strip(),
        flags=re.IGNORECASE,
    )
    return status.rstrip(" .,;:") or "Cadastrado"


def _extrair_dados_do_texto(texto):
    dados = {}
    email = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", texto)
    if email:
        dados["email"] = email.group(0)

    vaga = re.search(
        r"(?:vaga|cargo)\s*(?:de|para|:|\-)?\s*(.+?)(?=,|;|\.|\bstatus\b|\bsitua[cç][aã]o\b|$)",
        texto,
        flags=re.IGNORECASE,
    )
    if vaga:
        dados["vaga"] = vaga.group(1).strip()

    status = re.search(
        r"(?:status|situa[cç][aã]o)\s*(?:de|:|\-)?\s*(.+?)(?=,|;|\.|$)",
        texto,
        flags=re.IGNORECASE,
    )
    if status:
        dados["status"] = _limpar_status(status.group(1))

    return dados


#função para executar o agente
def executar_agente_rh(mensagem_usuario):
    if client is None:
        return [("erro", "Configure a chave API do Groq para usar o agente.")]

    if not PLANILHA_ID:
        return [("erro", "Configure a variável de ambiente PLANILHA_ID antes de usar o agente.")]

    # enviar a mensagem do usuário para o modelo do Groq
    resposta = client.chat.completions.create(
        model=MODELO_GROQ,
        messages=[
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": mensagem_usuario},
        ],
        tools=FERRAMENTAS,
        tool_choice="auto",
    )

    # extrair a mensagem retornada pela IA dentro da resposta da API
    mensagem = resposta.choices[0].message
    tool_calls = mensagem.tool_calls or []

    if not tool_calls:
        return [("texto", mensagem.content or "Não sei fazer isso.")]

    chamadas = []
    for chamada in tool_calls:
        chamadas.append((chamada.function.name, json.loads(chamada.function.arguments)))

    chamada_agendamento = next(
        (args for nome, args in chamadas if nome == "agendar_entrevista_com_meet"),
        None,
    )
    chamada_planilha = next(
        (args for nome, args in chamadas if nome == "registrar_candidato_planilha"),
        None,
    )

    if chamada_agendamento:
        evento = criar_evento_entrevista_com_meet(
            chamada_agendamento["nome_candidato"],
            chamada_agendamento["email_candidato"],
            chamada_agendamento["data_hora_inicio"],
            chamada_agendamento["data_hora_fim"],
        )
        if chamada_planilha:
            dados_planilha = chamada_planilha
            nome = dados_planilha.get("nome") or chamada_agendamento["nome_candidato"]
            email = dados_planilha.get("email") or chamada_agendamento["email_candidato"]
            vaga = dados_planilha.get("vaga", "Não informado")
            status = _limpar_status(dados_planilha.get("status"))
        else:
            dados_texto = _extrair_dados_do_texto(mensagem_usuario)
            nome = chamada_agendamento["nome_candidato"]
            email = chamada_agendamento["email_candidato"]
            vaga = dados_texto.get("vaga", "Não informado")
            status = _limpar_status(dados_texto.get("status"))

        try:
            registro = registrar_candidato_planilha(
                PLANILHA_ID,
                nome,
                email,
                vaga,
                status,
                chamada_agendamento["data_hora_inicio"],
                chamada_agendamento["data_hora_fim"],
            )
        except Exception as erro_planilha:
            try:
                cancelar_evento_calendar(evento["id"])
            except Exception as erro_cancelamento:
                return [("erro", (
                    "O registro na planilha falhou e não foi possível cancelar a reunião "
                    f"({evento.get('link')}). Erro da planilha: {erro_planilha}. "
                    f"Erro ao cancelar: {erro_cancelamento}"
                ))]
            return [("erro", (
                "O registro na planilha falhou; a reunião recém-criada foi cancelada. "
                f"Erro: {erro_planilha}"
            ))]

        return [("calendar", evento.get("link")), ("sheets", registro)]

    if chamada_planilha:
        try:
            registro = registrar_candidato_planilha(
                PLANILHA_ID,
                chamada_planilha["nome"],
                chamada_planilha["email"],
                chamada_planilha.get("vaga", "Não informado"),
                _limpar_status(chamada_planilha.get("status")),
                chamada_planilha.get("data_hora_inicio"),
                chamada_planilha.get("data_hora_fim"),
            )
            return [("sheets", registro)]
        except Exception as erro:
            return [("erro", f"Não foi possível registrar na planilha: {erro}")]

    return [("texto", "Nenhuma ação foi executada.")]
    