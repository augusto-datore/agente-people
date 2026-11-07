# ETAPA 1

# importa bibliotecas necessárias para o funcionamento do código
import os  # acessa os arquivos do sistema operacional
import unicodedata  # normaliza os caracteres unicode
import uuid  # gera identificadores únicos
from datetime import datetime, timedelta, timezone  # manipula datas e horas

from google.auth.exceptions import RefreshError  # trata erros de autenticação do Google
from google.auth.transport.requests import Request  # faz requisições HTTP para autenticação
from google.oauth2.credentials import Credentials  # trabalha com credenciais do Google
from google_auth_oauthlib.flow import InstalledAppFlow  # gerencia o fluxo de autenticação OAuth 2.0
from googleapiclient.discovery import build  # constrói serviços da API do Google

# ETAPA 2 Criar os escopos de autenticação
SCOPES = [
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/spreadsheets',
]  # credenciais de acesso para o Google Calendar e Google Sheets

# dicionario com os nomes das colunas na planilha e seus respectivos ids
CAMPOS_DA_PLANILHA = {
    "nome": {"nome", "nomecandidato"},
    "vaga": {"vaga", "cargo"},
    "data": {"data", "datacandidato"},
    "hora": {"hora", "horario", "horarioentrevista"},
    "email": {"email", "emailcandidato"},
    "status": {"status", "situacao"},
}
FUSO_HORARIO_BR = timezone(timedelta(hours=-3))


def _normalizar_campo(valor):
    texto = unicodedata.normalize("NFKD", str(valor).lower())
    return texto.encode("ascii", "ignore").decode("ascii").strip()


def _parse_data_hora(valor):
    if isinstance(valor, datetime):
        data_hora = valor
    else:
        texto = str(valor).strip()
        try:
            data_hora = datetime.fromisoformat(texto)
        except ValueError:
            try:
                data_hora = datetime.strptime(texto, "%d/%m/%Y %H:%M")
            except ValueError:
                try:
                    data_hora = datetime.strptime(texto, "%d/%m/%Y")
                except ValueError as erro:
                    raise ValueError(
                        "Data inválida. Use ISO 8601 ou dd/mm/yyyy HH:MM."
                    ) from erro

    if data_hora.tzinfo is None:
        return data_hora.replace(tzinfo=FUSO_HORARIO_BR)
    return data_hora.astimezone(FUSO_HORARIO_BR)


def _validar_intervalo_entrevista(inicio, fim):
    agora = datetime.now(FUSO_HORARIO_BR)
    if inicio <= agora:
        raise ValueError("A entrevista precisa começar em uma data e horário futuros.")
    if fim <= inicio:
        raise ValueError("O horário de término precisa ser posterior ao início.")


def _verificar_conflito_calendar(servico, inicio, fim, ignorar_evento_id=None):
    resposta = servico.events().list(
        calendarId='primary',
        timeMin=inicio.isoformat(),
        timeMax=fim.isoformat(),
        singleEvents=True,
        showDeleted=False,
        orderBy='startTime',
        fields='items(id,summary,status,start,end)',
    ).execute()

    for evento in resposta.get('items', []):
        if evento.get('id') == ignorar_evento_id or evento.get('status') == 'cancelled':
            continue
        inicio_evento = _parse_data_hora(
            evento.get('start', {}).get('dateTime') or evento.get('start', {}).get('date')
        )
        fim_evento = _parse_data_hora(
            evento.get('end', {}).get('dateTime') or evento.get('end', {}).get('date')
        )
        if inicio_evento < fim and fim_evento > inicio:
            descricao = evento.get('summary') or 'Outro compromisso'
            raise ValueError(
                f"Horário indisponível: existe um compromisso que se sobrepõe ({descricao})."
            )


# ETAPA 3: Função para autenticar google e retornar o serviço de planilhas e calendario
def autenticar_google():
    credenciais = None  # variavel para alocar as credenciais do google
    if os.path.exists('token.json'):  # verifica se o arquivo token existe
        credenciais = Credentials.from_authorized_user_file('token.json', SCOPES)  # carrega as credenciais do arquivo token.json

    if credenciais and credenciais.expired and credenciais.refresh_token:  # verifica se as credenciais estão expiradas e se existe um token de atualização
        try:
            credenciais.refresh(Request())  # atualiza as credenciais
        except RefreshError as erro:  # caso ocorra um erro de atualização
            if "invalid_grant" in str(erro):  # verifica se o erro é de concessão inválida
                raise
            credenciais = None  # se ocorrer um erro, define as credenciais como None

    if not credenciais or not credenciais.valid:  # não existem credenciais ou não são válidas
        fluxo = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)  # cria um fluxo de autenticação a partir do arquivo client_secret.json
        credenciais = fluxo.run_local_server(port=0)  # executa o fluxo de autenticação em um servidor local

    with open('token.json', 'w') as token:  # abre o arquivo token.json para escrita
        token.write(credenciais.to_json())  # escreve as credenciais no arquivo token.json
    return credenciais  # retorna as credenciais autenticadas


def criar_evento_entrevista_com_meet(
    nome_candidato,
    email_candidato,
    data_hora_inicio,
    data_hora_fim,
):
    """Cria uma entrevista futura e retorna os dados para eventual rollback."""
    inicio = _parse_data_hora(data_hora_inicio)
    fim = _parse_data_hora(data_hora_fim)
    _validar_intervalo_entrevista(inicio, fim)

    servico = build('calendar', 'v3', credentials=autenticar_google())  # cria um serviço do Google Calendar usando as credenciais autenticadas
    _verificar_conflito_calendar(servico, inicio, fim)

    evento = {
        'summary': f'Entrevista com {nome_candidato}',  # título do evento
        'description': 'Entrevista de alinhamento com o time do people',  # descrição do evento
        'start': {
            "dateTime": inicio.isoformat(),  # data e hora de início do evento
            "timeZone": 'America/Sao_Paulo',  # fuso horário do evento
        },
        'end': {
            "dateTime": fim.isoformat(),  # data e hora de término do evento
            "timeZone": 'America/Sao_Paulo',  # fuso horário do evento
        },
        "attendees": [
            {"email": email_candidato},  # adiciona o e-mail do candidato como participante do evento
        ],
        "conferenceData": {
            "createRequest": {
                "requestId": str(uuid.uuid4()),  # gera um identificador único para a solicitação de criação da conferência
                "conferenceSolutionKey": {"type": "hangoutsMeet"},  # define o tipo de conferência como Google Meet
            }
        },
    }

    evento_criado = servico.events().insert(
        calendarId='primary',  # define o calendário principal do usuário
        body=evento,  # passa o dicionário do evento como corpo da solicitação
        conferenceDataVersion=1,
        sendUpdates='all',
    ).execute()  # executa a solicitação de criação do evento

    return {"id": evento_criado["id"], "link": evento_criado.get("hangoutLink")}


def agendar_entrevista_com_meet(
    nome_candidato,
    email_candidato,
    data_hora_inicio,
    data_hora_fim,
):
    """Mantém a interface que retorna somente o link do Meet."""
    return criar_evento_entrevista_com_meet(
        nome_candidato, email_candidato, data_hora_inicio, data_hora_fim
    )["link"]


def cancelar_evento_calendar(id_evento):
    servico = build('calendar', 'v3', credentials=autenticar_google())
    servico.events().delete(calendarId='primary', eventId=id_evento, sendUpdates='all').execute()


def atualizar_agendamento_calendar(email_candidato, inicio_atual, novo_inicio, novo_fim):
    """Atualiza somente o horário do evento que corresponde ao registro selecionado."""
    fuso = FUSO_HORARIO_BR
    inicio_atual = _parse_data_hora(inicio_atual)
    novo_inicio = _parse_data_hora(novo_inicio)
    novo_fim = _parse_data_hora(novo_fim)
    _validar_intervalo_entrevista(novo_inicio, novo_fim)

    servico = build('calendar', 'v3', credentials=autenticar_google())
    inicio_dia = datetime.combine(inicio_atual.date(), datetime.min.time(), tzinfo=fuso)
    fim_dia = inicio_dia + timedelta(days=1)
    resposta = servico.events().list(
        calendarId='primary',
        timeMin=inicio_dia.isoformat(),
        timeMax=fim_dia.isoformat(),
        singleEvents=True,
        orderBy='startTime',
        fields='items(id,attendees(email),start)',
    ).execute()

    eventos_correspondentes = []
    for evento in resposta.get('items', []):
        participantes = evento.get('attendees', [])
        emails = {participante.get('email', '').casefold() for participante in participantes}
        inicio_evento = evento.get('start', {}).get('dateTime')
        if email_candidato.casefold() not in emails or not inicio_evento:
            continue
        inicio_evento = datetime.fromisoformat(inicio_evento).astimezone(fuso)
        if inicio_evento.replace(second=0, microsecond=0) == inicio_atual.replace(second=0, microsecond=0):
            eventos_correspondentes.append(evento)

    if len(eventos_correspondentes) != 1:
        if not eventos_correspondentes:
            raise ValueError("Não encontrei um evento único correspondente ao e-mail e horário atuais.")
        raise ValueError("Há mais de um evento correspondente. Nenhum agendamento foi alterado.")

    _verificar_conflito_calendar(
        servico,
        novo_inicio,
        novo_fim,
        ignorar_evento_id=eventos_correspondentes[0]['id'],
    )

    return servico.events().patch(
        calendarId='primary',
        eventId=eventos_correspondentes[0]['id'],
        sendUpdates='all',
        body={
            'start': {'dateTime': novo_inicio.isoformat(), 'timeZone': 'America/Sao_Paulo'},
            'end': {'dateTime': novo_fim.isoformat(), 'timeZone': 'America/Sao_Paulo'},
        },
    ).execute()


def registrar_candidato_planilha(
    id_planilha,
    nome,
    email,
    vaga,
    status,
    data_hora_inicio=None,
    data_hora_fim=None,
):
    """Função para registrar informações do candidato em uma planilha do Google Sheets."""
    servico = build('sheets', 'v4', credentials=autenticar_google())  # cria um serviço do Google Sheets usando as credenciais autenticadas

    planilha = servico.spreadsheets().get(
        spreadsheetId=id_planilha,
        fields='sheets(properties(sheetId,title))',
    ).execute()

    if not planilha.get("sheets"):
        raise ValueError("Aba não encontrada na planilha.")

    resposta = servico.spreadsheets().values().get(
        spreadsheetId=id_planilha,
        range='1:1',
        majorDimension='ROWS',
    ).execute()

    cabecalho = resposta.get("values", [[]])[0] if resposta.get("values") else []

    if not cabecalho:
        cabecalho = ["nome", "email", "vaga", "status", "data", "hora"]
        servico.spreadsheets().values().update(
            spreadsheetId=id_planilha,
            range='A1:F1',
            valueInputOption='RAW',
            body={'values': [cabecalho]},
        ).execute()

    colunas = {}
    for indice, titulo in enumerate(cabecalho):
        campo_normalizado = _normalizar_campo(titulo)
        for campo, aliases in CAMPOS_DA_PLANILHA.items():
            if campo_normalizado in aliases or campo_normalizado == campo:
                colunas[campo] = indice
                break

    dados = {
        "nome": nome,
        "email": email,
        "vaga": vaga,
        "status": status,
    }

    if data_hora_inicio:
        inicio = _parse_data_hora(data_hora_inicio)
        dados["data"] = inicio.strftime("%d/%m/%Y")  # formata a data de início para o formato dd/mm/aaaa
        hora = inicio.strftime("%H:%M")  # formata a hora de início para o formato hh:mm

        if data_hora_fim:
            fim = _parse_data_hora(data_hora_fim)
            hora = f"{hora} - {fim.strftime('%H:%M')}"  # adiciona a hora de fim ao campo de hora, separada por um hífen

        dados["hora"] = hora

    max_coluna = max(colunas.values(), default=0) + 1
    quantidade_colunas = max(len(cabecalho), max_coluna)
    valores = [""] * quantidade_colunas

    for campo, indice in colunas.items():
        if campo in dados:
            valores[indice] = dados[campo]

    resultado = servico.spreadsheets().values().append(
        spreadsheetId=id_planilha,
        range='A1',
        valueInputOption='USER_ENTERED',
        body={'values': [valores]},
    ).execute()

    return resultado


def listar_candidatos_planilha(id_planilha):
    """Retorna os cabeçalhos e registros da primeira aba da planilha."""
    servico = build('sheets', 'v4', credentials=autenticar_google())
    planilha = servico.spreadsheets().get(
        spreadsheetId=id_planilha,
        fields='sheets(properties(title))',
    ).execute()
    abas = planilha.get("sheets", [])
    if not abas:
        raise ValueError("Aba não encontrada na planilha.")

    titulo_aba = abas[0]["properties"]["title"]
    titulo_escapado = titulo_aba.replace("'", "''")
    resposta = servico.spreadsheets().values().get(
        spreadsheetId=id_planilha,
        range=f"'{titulo_escapado}'!A:ZZ",
        majorDimension='ROWS',
    ).execute()
    linhas = resposta.get("values", [])
    if not linhas:
        return {"aba": titulo_aba, "cabecalho": [], "linhas": []}

    cabecalho = linhas[0]
    registros = []
    for numero_linha, valores in enumerate(linhas[1:], start=2):
        valores_completos = list(valores) + [""] * (len(cabecalho) - len(valores))
        registros.append({"numero": numero_linha, "valores": valores_completos})

    return {"aba": titulo_aba, "cabecalho": cabecalho, "linhas": registros}


def atualizar_campos_linha_planilha(id_planilha, titulo_aba, numero_linha, cabecalho, campos):
    """Atualiza apenas as células declaradas, preservando fórmulas e demais dados."""
    if numero_linha < 2:
        raise ValueError("A linha do cabeçalho não pode ser editada.")
    if not campos:
        raise ValueError("Não há dados para atualizar.")

    def numero_para_coluna(numero):
        coluna = ""
        while numero:
            numero, resto = divmod(numero - 1, 26)
            coluna = chr(65 + resto) + coluna
        return coluna

    titulo_escapado = titulo_aba.replace("'", "''")
    atualizacoes = []
    for campo, valor in campos.items():
        aliases = CAMPOS_DA_PLANILHA[campo]
        indice = next(
            (i for i, titulo in enumerate(cabecalho) if _normalizar_campo(titulo) in aliases),
            None,
        )
        if indice is None:
            raise ValueError(f"A coluna de {campo} não existe na planilha.")
        atualizacoes.append({
            "range": f"'{titulo_escapado}'!{numero_para_coluna(indice + 1)}{numero_linha}",
            "values": [[valor]],
        })

    servico = build('sheets', 'v4', credentials=autenticar_google())
    return servico.spreadsheets().values().batchUpdate(
        spreadsheetId=id_planilha,
        body={'valueInputOption': 'RAW', 'data': atualizacoes},
    ).execute()