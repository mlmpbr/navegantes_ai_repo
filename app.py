import dash
from dash import dcc, html, Input, Output, State, dash_table
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import requests
import time
import datetime
import numpy as np
import os
import urllib3
import re
from dash.dash_table.Format import Format, Symbol

# --- CONFIGURAÇÃO DE CACHE ---
PASTA_CACHE = "dados_cache"
if not os.path.exists(PASTA_CACHE):
    os.makedirs(PASTA_CACHE)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================================================================
# 1. UTILITÁRIOS (CACHE, DATAS E FORMATAÇÃO)
# ==============================================================================

def cache_eh_valido_mensal(caminho_arquivo):
    """
    Verifica se o arquivo existe, não está vazio e é do MÊS/ANO atuais.
    """
    if not os.path.exists(caminho_arquivo): return False
    try:
        if os.path.getsize(caminho_arquivo) < 100: return False # Proteção contra arquivo corrompido
        
        ts = os.path.getmtime(caminho_arquivo)
        dt_arq = datetime.datetime.fromtimestamp(ts)
        agora = datetime.datetime.now()
        # Válido apenas se for do mesmo ano e mesmo mês
        return (dt_arq.year == agora.year and dt_arq.month == agora.month)
    except:
        return False

def fazer_requisicao_robusta(url, params=None, verify=False, timeout=45, max_tentativas=5):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*'
    }
    for tentativa in range(1, max_tentativas + 1):
        try:
            response = requests.get(url, headers=headers, params=params, verify=False, timeout=timeout)
            if response.status_code in [200, 201]: return response
            elif response.status_code == 429: time.sleep(10); continue
        except: time.sleep(2); continue
    return None

def converter_para_float(valor):
    """Converte financeiro BR (1.000,00) para float (1000.00)"""
    if pd.isna(valor) or valor == '': return 0.0
    if isinstance(valor, (int, float)): return float(valor)
    try:
        valor_limpo = str(valor).replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.')
        return float(valor_limpo)
    except: return 0.0

def corrigir_texto_licitacao(texto):
    """Corrige encoding quebrado (Mojibake)"""
    if not isinstance(texto, str): return texto
    replaces = {
        'Ãª': 'ê', 'Ã¡': 'á', 'Ã£': 'ã', 'Ã§': 'ç', 'Ã©': 'é', 
        'Ã³': 'ó', 'Ãwq': 'í', 'Ãº': 'ú', 'Ã¢': 'â', 'Ãµ': 'õ',
        'EletrÃ´nica': 'Eletrônica', 'ConcorrÃªncia': 'Concorrência',
        'PregÃ£o': 'Pregão', 'Dispensa de LicitaÃ§Ã£o': 'Dispensa de Licitação'
    }
    try:
        # Tenta decode direto
        return texto.encode('latin1').decode('utf-8')
    except:
        # Fallback manual
        for errado, certo in replaces.items():
            texto = texto.replace(errado, certo)
        return texto

# ==============================================================================
# 2. MOTORES DE CARGA (COM SISTEMA ANTI-TRAVAMENTO)
# ==============================================================================

# --- MOTOR DE RH ---
def carregar_rh_completo():
    arquivo_cache = f"{PASTA_CACHE}/rh_funcionarios_ativos.csv"
    
    # 1. Tenta Cache Válido (Mês Atual)
    if cache_eh_valido_mensal(arquivo_cache):
        try:
            try: df = pd.read_csv(arquivo_cache, sep=None, engine='python')
            except: df = pd.read_csv(arquivo_cache)
            if not df.empty and 'salarioBase' in df.columns:
                df['salarioBase'] = df['salarioBase'].apply(converter_para_float)
                return df
        except: pass

    # 2. Tenta Atualizar via API (Se falhar, não quebra)
    print("    🌍 RH: Tentando atualização via API...")
    base_url = "https://navegantes.atende.net/api/transparencia-pessoal-funcionarios"
    todos = []
    pag = 1
    sucesso_api = False

    # Limite seguro de páginas para não estourar tempo no Cloud
    while pag < 150:
        resp = fazer_requisicao_robusta(base_url, params={"tipoBusca": 1, "pagina": pag})
        if not resp: break
        try:
            d = resp.json()
            recs = d if isinstance(d, list) else d.get('registros', d.get('entidade', []))
            if not recs: break
            todos.extend(recs)
            pag += 1
            sucesso_api = True
        except: break
    
    # Se atualizou com sucesso, salva novo cache
    if sucesso_api and todos:
        df = pd.DataFrame(todos)
        if 'salarioBase' in df.columns:
            df['salarioBase'] = df['salarioBase'].apply(converter_para_float)
        df.to_csv(arquivo_cache, index=False, sep=',') 
        return df

    # 3. PLANO B (FALLBACK): API Falhou? Carrega o cache antigo se existir
    print("    ⚠️ RH: API indisponível/bloqueada. Usando cache existente.")
    if os.path.exists(arquivo_cache):
        try:
            try: df = pd.read_csv(arquivo_cache, sep=None, engine='python')
            except: df = pd.read_csv(arquivo_cache)
            if 'salarioBase' in df.columns: 
                df['salarioBase'] = df['salarioBase'].apply(converter_para_float)
            return df
        except: pass

    return pd.DataFrame()

# --- MOTOR FINANCEIRO ---
def obter_dados_financeiros(endpoint, ano, tipo):
    arquivo = f"{PASTA_CACHE}/{tipo}_{ano}.csv"
    
    # 1. Cache Válido?
    if cache_eh_valido_mensal(arquivo):
        try: return pd.read_csv(arquivo).to_dict('records')
        except: pass
    
    # 2. Tenta API
    print(f"    🌍 {tipo} {ano}: Tentando API...")
    base_url = "https://navegantes.atende.net/api/WCPDadosAbertos/"
    url = f"{base_url}{endpoint}?dataInicial=01/01/{ano}&dataFinal=31/12/{ano}"
    if tipo == 'restos': url = f"{base_url}{endpoint}?dataFinal=31/12/{ano}"
    
    resp = fazer_requisicao_robusta(url)
    if resp:
        try:
            recs = resp.json().get('retorno', [])
            if recs:
                pd.DataFrame(recs).to_csv(arquivo, index=False)
                return recs
        except: pass
    
    # 3. PLANO B (FALLBACK): API Falhou? Usa cache antigo
    if os.path.exists(arquivo):
        print(f"    ⚠️ {tipo} {ano}: Usando cache local (API falhou).")
        try: return pd.read_csv(arquivo).to_dict('records')
        except: pass

    return []

def carregar_historico_financeiro(tipo):
    lista_dfs = []
    ano_atual = datetime.datetime.now().year
    endpoint = {'receitas': 'receitas', 'receitas_orcadas': 'receitasOrcadas', 'despesas': 'despesas', 'despesas_orcadas': 'despesasOrcadas', 'restos': 'despesaRestos'}.get(tipo)
    ano_ini = 2015 if tipo != 'restos' else ano_atual - 4
    
    for ano in range(ano_ini, ano_atual + 1):
        d = obter_dados_financeiros(endpoint, ano, tipo)
        if d:
            df = pd.DataFrame(d)
            df['ano'] = ano
            lista_dfs.append(df)
            
    if not lista_dfs: return pd.DataFrame()
    
    df_final = pd.concat(lista_dfs, ignore_index=True)
    cols = ['valorArrecadado', 'valorOrcado', 'valorEmpenhado', 'valorPago', 'valorProcessadoInscrito', 'valorNaoProcessadoInscrito']
    for c in cols:
        if c in df_final.columns: df_final[c] = df_final[c].apply(converter_para_float)
        else: df_final[c] = 0.0
    return df_final

# --- MOTOR LICITAÇÕES ---
def carregar_licitacoes(arquivo="arquivos_combinados.csv"):
    if not os.path.exists(arquivo):
        print(f"    ⚠️ Aviso: '{arquivo}' não encontrado.")
        return pd.DataFrame()
    
    try:
        try: df = pd.read_csv(arquivo, sep=';', encoding='latin1')
        except: df = pd.read_csv(arquivo, sep=',', encoding='utf-8')
        
        if df.empty: return pd.DataFrame()

        # Normaliza colunas
        df.columns = [re.sub(r'\s+', '_', re.sub(r'[^\w\s]', '', c.strip().upper())) for c in df.columns]
        
        # Mapeia
        mapa = {'ANO': ['ANO','EXERCICIO'], 'SITUACAO': ['SITUACAO','STATUS'], 'MODALIDADE': ['MODALIDADE']}
        for std, aliases in mapa.items():
            for alias in aliases:
                match = next((c for c in df.columns if alias in c), None)
                if match: 
                    df.rename(columns={match: std}, inplace=True)
                    break
        
        if 'ANO' in df.columns:
            df['ANO'] = pd.to_numeric(df['ANO'], errors='coerce').fillna(0).astype(int)
        
        # Corrige Encoding de Texto
        cols_texto = ['MODALIDADE', 'SITUACAO', 'OBJETO']
        for col in cols_texto:
            if col in df.columns:
                df[col] = df[col].astype(str).apply(corrigir_texto_licitacao)
        
        return df
    except Exception as e:
        print(f"Erro Licitações: {e}")
        return pd.DataFrame()

# --- CARGA INICIAL ---
print(f"\n=== NAVEGANTES 360º: STARTUP (Base: {datetime.datetime.now().year}) ===")
rh_df = carregar_rh_completo()
receitas_df = carregar_historico_financeiro('receitas')
rec_orc_df = carregar_historico_financeiro('receitas_orcadas')
despesas_df = carregar_historico_financeiro('despesas')
desp_orc_df = carregar_historico_financeiro('despesas_orcadas')
restos_df = carregar_historico_financeiro('restos')
licitacoes_df = carregar_licitacoes() 
print("=== SISTEMA PRONTO PARA USO ===")

# ==============================================================================
# 3. DASHBOARD
# ==============================================================================
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.FONT_AWESOME])
app.title = "Navegantes 360º"
server = app.server

# Listas
op_rec = [{'label': 'TOTAL GERAL', 'value': 'TOTAL'}] + ([{'label': n, 'value': n} for n in sorted(receitas_df['contaDescricao'].dropna().unique())] if not receitas_df.empty else [])
op_desp = [{'label': 'TOTAL GERAL', 'value': 'TOTAL'}] + ([{'label': n, 'value': n} for n in sorted(despesas_df['orgaoDescricao'].dropna().unique())] if not despesas_df.empty else [])
op_restos = [{'label': 'TOTAL GERAL', 'value': 'TOTAL'}] + ([{'label': n, 'value': n} for n in sorted(restos_df['orgaoDescricao'].dropna().unique())] if not restos_df.empty else [])

# Estilos
SIDEBAR_STYLE = {"position": "fixed", "top": 0, "left": 0, "bottom": 0, "width": "18rem", "padding": "2rem 1rem", "backgroundColor": "#f8f9fa", "overflowY": "auto"}
CONTENT_STYLE = {"marginLeft": "18rem", "padding": "2rem 1rem"}

sidebar = html.Div([
    html.Div([html.Img(src=app.get_asset_url('logo_nvt.jpg'), style={"width": "100%", "maxWidth": "150px"}) if os.path.exists("assets/logo_nvt.jpg") else html.H2("NVT", className="text-center")], className="text-center mb-4"),
    html.Div([html.Div("SEPAF - Departamento de", style={"fontSize": "0.75rem", "color": "#cbd5e1"}), html.Div("Planejamento e Gestão", style={"fontSize": "0.85rem", "fontWeight": "bold", "color": "#ffffff"})], style={"backgroundColor": "#1F2937", "padding": "12px", "borderRadius": "8px", "textAlign": "center", "marginBottom": "1.5rem"}),
    dbc.Nav([
        dbc.NavLink([html.I(className="fas fa-wallet me-3"), "Receitas"], href="/", active="exact"),
        dbc.NavLink([html.I(className="fas fa-file-invoice-dollar me-3"), "Despesas"], href="/despesas", active="exact"),
        dbc.NavLink([html.I(className="fas fa-history me-3"), "Restos a Pagar"], href="/restos", active="exact"),
        dbc.NavLink([html.I(className="fas fa-users me-3"), "Recursos Humanos"], href="/rh", active="exact"),
        html.Div([
            html.B("Licitações", className="ms-3 text-secondary"),
            dbc.NavLink([html.I(className="fas fa-chart-pie me-3"), "Visão Geral"], href="/licitacoes_graficos", active="exact", className="ms-4"),
            dbc.NavLink([html.I(className="fas fa-table me-3"), "Detalhamento"], href="/licitacoes_tabela", active="exact", className="ms-4"),
        ], className="my-2"),
        dbc.NavLink([html.I(className="fas fa-table me-3"), "Base de Dados"], href="/tabela", active="exact"),
    ], vertical=True, pills=True),
], style=SIDEBAR_STYLE)

content = html.Div(id="page-content", style=CONTENT_STYLE)
app.layout = html.Div([dcc.Location(id="url", refresh=False), sidebar, content])

# --- PÁGINAS ---

def layout_licitacoes_graficos():
    if licitacoes_df.empty: 
        return dbc.Alert([html.H4("Arquivo não encontrado"), html.P("Faça upload de 'arquivos_combinados.csv' na raiz.")], color="warning")

    df = licitacoes_df.copy()
    
    # 1. KPIs
    ano_atual = datetime.datetime.now().year
    ano_ant = ano_atual - 1
    total_geral = len(df)
    total_atual = len(df[df['ANO'] == ano_atual]) if 'ANO' in df.columns else 0
    total_ant = len(df[df['ANO'] == ano_ant]) if 'ANO' in df.columns else 0
    
    # Status
    hom = abt = fra = des = 0
    if 'SITUACAO' in df.columns:
        s = df['SITUACAO'].str.upper().value_counts()
        hom = s.get('HOMOLOGADA', 0)
        abt = s.get('ABERTA', 0) + s.get('EM ANDAMENTO', 0)
        fra = s.get('FRACASSADA', 0)
        des = s.get('DESERTA', 0)

    # 2. Layout Cards
    cards = html.Div([
        html.H5("Fluxo de Processos", className="text-muted"),
        dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody([html.H3(total_atual, className="text-primary"), html.P(f"Novos em {ano_atual}")]), className="shadow-sm"), width=4),
            dbc.Col(dbc.Card(dbc.CardBody([html.H3(total_ant, className="text-secondary"), html.P(f"Novos em {ano_ant}")]), className="shadow-sm"), width=4),
            dbc.Col(dbc.Card(dbc.CardBody([html.H3(total_geral, className="text-dark"), html.P("Total Base")]), className="shadow-sm"), width=4),
        ], className="mb-4"),
        html.H5("Status Atual", className="text-muted"),
        dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody([html.H4(hom, className="text-success"), html.P("Homologadas")]), className="shadow-sm border-start border-success border-4"), width=3),
            dbc.Col(dbc.Card(dbc.CardBody([html.H4(abt, className="text-info"), html.P("Abertas")]), className="shadow-sm border-start border-info border-4"), width=3),
            dbc.Col(dbc.Card(dbc.CardBody([html.H4(fra, className="text-warning"), html.P("Fracassadas")]), className="shadow-sm border-start border-warning border-4"), width=3),
            dbc.Col(dbc.Card(dbc.CardBody([html.H4(des, className="text-danger"), html.P("Desertas")]), className="shadow-sm border-start border-danger border-4"), width=3),
        ], className="mb-4")
    ])

    # 3. Gráfico (COM FILTRO PARA REMOVER BARRA HOMOLOGADA)
    fig = px.line(title="Sem dados")
    if 'ANO' in df.columns and 'MODALIDADE' in df.columns:
        df_mod = df[df['ANO'] >= 2020].copy()
        # Filtra 'HOMOLOGADA' da coluna Modalidade
        df_mod = df_mod[df_mod['MODALIDADE'].str.upper() != 'HOMOLOGADA']
        
        df_grp = df_mod.groupby(['ANO', 'MODALIDADE']).size().reset_index(name='Qtd')
        fig = px.bar(df_grp, x='ANO', y='Qtd', color='MODALIDADE', title="Evolução das Modalidades (2020+)", barmode='group', template='plotly_white')
        fig.update_layout(xaxis_title="Ano", yaxis_title="Processos")

    return html.Div([html.H2("📊 Painel de Licitações"), html.Hr(), cards, dcc.Graph(figure=fig)])

def layout_licitacoes_tabela():
    if licitacoes_df.empty: return dbc.Alert("Sem dados.", color="danger")
    cols = [{"name": c.title().replace('_', ' '), "id": c} for c in licitacoes_df.columns]
    return html.Div([html.H2("📋 Detalhamento"), dbc.Spinner(dash_table.DataTable(data=licitacoes_df.to_dict('records'), columns=cols, page_size=15, sort_action="native", filter_action="native", style_table={'overflowX': 'auto'}))])

def layout_rh():
    if rh_df.empty: return dbc.Alert("Dados de RH indisponíveis.", color="danger")
    
    kpis = dbc.Row([
        dbc.Col(dbc.Card(dbc.CardBody([html.H4(len(rh_df), className="text-primary"), html.P("Ativos")]), className="shadow-sm border-start border-primary border-4"), width=4),
        dbc.Col(dbc.Card(dbc.CardBody([html.H4(f"R$ {rh_df['salarioBase'].sum():,.2f}", className="text-success"), html.P("Folha Mensal")]), className="shadow-sm border-start border-success border-4"), width=4),
        dbc.Col(dbc.Card(dbc.CardBody([html.H4(f"R$ {rh_df['salarioBase'].mean():,.2f}", className="text-info"), html.P("Média")]), className="shadow-sm border-start border-info border-4"), width=4),
    ], className="mb-4")
    
    df_cargos = rh_df['cargo'].value_counts().nlargest(10).reset_index()
    df_cargos.columns = ['Cargo', 'Qtd']
    fig_bar = px.bar(df_cargos, x='Qtd', y='Cargo', orientation='h', title="Top 10 Cargos", template='plotly_white')
    fig_bar.update_layout(yaxis={'categoryorder':'total ascending'})
    
    col_regime = 'regime' if 'regime' in rh_df.columns else 'situacao'
    df_regime = rh_df[col_regime].value_counts().reset_index()
    df_regime.columns = ['Tipo', 'Qtd']
    fig_tree = px.treemap(df_regime, path=['Tipo'], values='Qtd', color='Tipo', title="Vínculos", template='plotly_white')
    fig_tree.update_traces(textinfo="label+value+percent root")

    return html.Div([html.H2("Gestão de Pessoas"), html.Hr(), kpis, dbc.Row([dbc.Col(dcc.Graph(figure=fig_bar), width=12)]), dbc.Row([dbc.Col(dcc.Graph(figure=fig_tree), width=12)])])

def layout_receitas():
    return html.Div([
        html.H2("Receitas Públicas"), html.Hr(),
        dbc.Row([dbc.Col(dcc.Dropdown(id='rec-dd', options=op_rec, value='TOTAL'), width=8), dbc.Col(dcc.Dropdown(id='rec-stat', options=[{'label':'Soma','value':'sum'},{'label':'Média','value':'mean'}], value='sum'), width=4)]),
        dcc.Graph(id='rec-graph')
    ])
def layout_despesas(): return html.Div([html.H2("Despesas"), html.Hr(), dcc.Dropdown(id='desp-dd', options=op_desp, value='TOTAL'), dcc.Graph(id='desp-graph')])
def layout_restos(): return html.Div([html.H2("Restos a Pagar"), html.Hr(), dcc.Dropdown(id='restos-dd', options=op_restos, value='TOTAL'), dcc.Graph(id='restos-graph')])
def layout_tabela(): return html.Div([html.H2("Base de Dados"), dcc.Dropdown(id='tab-dd', options=[{'label':'Receitas','value':'rec'},{'label':'RH','value':'rh'},{'label':'Licitações','value':'lic'}], value='rec'), html.Br(), dbc.Spinner(dash_table.DataTable(id='tabela-main', page_size=15, style_table={'overflowX': 'auto'}))])

# --- CALLBACKS ---
@app.callback(Output("page-content", "children"), Input("url", "pathname"))
def render_page(path):
    if path == "/despesas": return layout_despesas()
    if path == "/restos": return layout_restos()
    if path == "/rh": return layout_rh()
    if path == "/tabela": return layout_tabela()
    if path == "/licitacoes_graficos": return layout_licitacoes_graficos()
    if path == "/licitacoes_tabela": return layout_licitacoes_tabela()
    return layout_receitas()

@app.callback(Output('rec-graph', 'figure'), [Input('rec-dd', 'value'), Input('rec-stat', 'value')])
def update_rec(conta, stat):
    if receitas_df.empty: return px.line(title="Sem dados")
    df = receitas_df if conta == 'TOTAL' else receitas_df[receitas_df['contaDescricao'] == conta]
    df_orc = rec_orc_df if conta == 'TOTAL' else pd.DataFrame()
    g_real = df.groupby('ano')['valorArrecadado'].agg(stat).reset_index()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=g_real['ano'], y=g_real['valorArrecadado'], name='Realizado', marker_color='#2E86C1'))
    if not df_orc.empty and conta == 'TOTAL':
        g_orc = df_orc.groupby('ano')['valorOrcado'].agg(stat).reset_index()
        fig.add_trace(go.Scatter(x=g_orc['ano'], y=g_orc['valorOrcado'], name='Meta', line=dict(color='red', dash='dot')))
    if len(g_real) > 1:
        x, y = g_real['ano'], g_real['valorArrecadado']
        z = np.polyfit(x, y, 1); p = np.poly1d(z)
        fig.add_trace(go.Scatter(x=x, y=p(x), name='Tendência', line=dict(color='orange', width=2)))
    fig.update_layout(template="plotly_white", title=f"Evolução: {conta}")
    return fig

@app.callback(Output('desp-graph', 'figure'), Input('desp-dd', 'value'))
def update_desp(orgao):
    if despesas_df.empty: return px.line(title="Sem dados")
    df = despesas_df if orgao == 'TOTAL' else despesas_df[despesas_df['orgaoDescricao'] == orgao]
    g_real = df.groupby('ano')['valorEmpenhado'].sum().reset_index()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=g_real['ano'], y=g_real['valorEmpenhado'], name='Empenhado', marker_color='#D4AC0D'))
    if len(g_real) > 1:
        x, y = g_real['ano'], g_real['valorEmpenhado']
        z = np.polyfit(x, y, 1); p = np.poly1d(z)
        fig.add_trace(go.Scatter(x=x, y=p(x), name='Tendência', line=dict(color='black', dash='dash')))
    fig.update_layout(template="plotly_white", title=f"Despesa: {orgao}")
    return fig

@app.callback(Output('restos-graph', 'figure'), Input('restos-dd', 'value'))
def update_rest(orgao):
    df = restos_df if orgao == 'TOTAL' else restos_df[restos_df['orgaoDescricao'] == orgao]
    return px.bar(df.groupby('ano')['valorPago'].sum().reset_index(), x='ano', y='valorPago', title="Restos Pagos", template="plotly_white")

@app.callback([Output('tabela-main', 'data'), Output('tabela-main', 'columns')], Input('tab-dd', 'value'))
def update_tab(tipo):
    df_map = {'rh': rh_df, 'rec': receitas_df.head(200), 'lic': licitacoes_df.head(200)}
    df = df_map.get(tipo, pd.DataFrame())
    cols = [{"name": c, "id": c} for c in df.columns]
    return df.to_dict('records'), cols

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=7860)