import dash
from dash import dcc, html, Input, Output, dash_table
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import os
import re

# --- CONFIGURAÇÕES DE PASTA ---
PASTA_CACHE = "dados_cache"
if not os.path.exists(PASTA_CACHE): os.makedirs(PASTA_CACHE)

# ==============================================================================
# 1. MOTORES DE CARGA E LIMPEZA
# ==============================================================================

def converter_para_float(valor):
    if pd.isna(valor) or valor == '': return 0.0
    if isinstance(valor, (int, float)): return float(valor)
    try:
        v = str(valor).replace('R$', '').strip()
        # Se for formato brasileiro (ex: 1.000,50), removemos o ponto e trocamos vírgula por ponto
        if ',' in v and '.' in v and v.rfind(',') > v.rfind('.'):
            v = v.replace('.', '').replace(',', '.')
        elif ',' in v and '.' not in v: # Apenas vírgula (ex: 1000,50)
            v = v.replace(',', '.')
        return float(v)
    except: return 0.0

def limpar_colunas(df):
    if df.empty: return df
    # A mágica aqui: removemos espaços vazios e sublinhados dos cabeçalhos
    df.columns = [str(c).strip().lower().replace(' ', '').replace('_', '') for c in df.columns]
    mapa = {'exercicio': 'ano', 'ano_licitacao': 'ano', 'exercicio_contrato': 'ano'}
    df.rename(columns=mapa, inplace=True)
    return df

def carregar_csv_seguro(nome_arquivo, separador=';'):
    caminho = os.path.join(PASTA_CACHE, nome_arquivo)
    if not os.path.exists(caminho): return pd.DataFrame()
    
    # Tenta ler com o separador inicial (ponto e vírgula)
    try:
        df = pd.read_csv(caminho, sep=separador, encoding='utf-8', on_bad_lines='skip', low_memory=False)
        if len(df.columns) == 1: # Se não dividiu direito, tenta vírgula
            df = pd.read_csv(caminho, sep=',', encoding='utf-8', on_bad_lines='skip', low_memory=False)
    except:
        df = pd.read_csv(caminho, sep=separador, encoding='latin1', on_bad_lines='skip', low_memory=False)
        if len(df.columns) == 1:
            df = pd.read_csv(caminho, sep=',', encoding='latin1', on_bad_lines='skip', low_memory=False)
            
    return limpar_colunas(df)

def carregar_todos_os_anos(prefixo):
    arquivos = [f for f in os.listdir(PASTA_CACHE) if f.startswith(prefixo) and f.endswith('.csv')]
    dfs = []
    for f in arquivos:
        # TENTA PONTO E VÍRGULA PRIMEIRO (Evita quebrar os centavos)
        try:
            temp_df = pd.read_csv(os.path.join(PASTA_CACHE, f), sep=';', encoding='utf-8', on_bad_lines='skip')
            if len(temp_df.columns) == 1:
                temp_df = pd.read_csv(os.path.join(PASTA_CACHE, f), sep=',', encoding='utf-8', on_bad_lines='skip')
        except:
            temp_df = pd.read_csv(os.path.join(PASTA_CACHE, f), sep=';', encoding='latin1', on_bad_lines='skip')
            if len(temp_df.columns) == 1:
                temp_df = pd.read_csv(os.path.join(PASTA_CACHE, f), sep=',', encoding='latin1', on_bad_lines='skip')
        
        if not temp_df.empty:
            match = re.search(r'(\d{4})', f)
            if match: temp_df['ano'] = int(match.group(1))
            dfs.append(limpar_colunas(temp_df))
            
    if not dfs: return pd.DataFrame()
    
    df_final = pd.concat(dfs, ignore_index=True)
    cols_financeiras = ['valorarrecadado', 'valorempenhado', 'valorpago']
    for col in cols_financeiras:
        if col in df_final.columns:
            df_final[col] = df_final[col].apply(converter_para_float)
    return df_final

# --- CARGA GLOBAL ---
receitas_df = carregar_todos_os_anos("receitas_")
despesas_df = carregar_todos_os_anos("despesas_")
restos_df = carregar_todos_os_anos("restos_")
licitacoes_df = carregar_csv_seguro("licitacoes.csv")
contratos_df = carregar_csv_seguro("contratos.csv")

if not contratos_df.empty and 'valortotal' in contratos_df.columns:
    contratos_df['valortotal'] = contratos_df['valortotal'].apply(converter_para_float)

col_est = next((c for c in licitacoes_df.columns if 'estimado' in c), None)
col_hom = next((c for c in licitacoes_df.columns if 'homologado' in c), None)
col_sit = next((c for c in licitacoes_df.columns if 'situa' in c or 'status' in c), None)
col_mod = next((c for c in licitacoes_df.columns if 'modalidade' in c), None)

if col_est: licitacoes_df[col_est] = licitacoes_df[col_est].apply(converter_para_float)
if col_hom: licitacoes_df[col_hom] = licitacoes_df[col_hom].apply(converter_para_float)

# ==============================================================================
# 2. OPÇÕES DOS DROPDOWNS E PRÉ-CÁLCULOS
# ==============================================================================

op_rec = [{'label': 'VISÃO GERAL', 'value': 'TOTAL'}]
if not receitas_df.empty and 'contadescricao' in receitas_df.columns:
    op_rec += [{'label': str(n), 'value': str(n)} for n in sorted(receitas_df['contadescricao'].dropna().unique())]

op_desp = [{'label': 'VISÃO GERAL', 'value': 'TOTAL'}]
if not despesas_df.empty and 'orgaodescricao' in despesas_df.columns:
    op_desp += [{'label': str(n), 'value': str(n)} for n in sorted(despesas_df['orgaodescricao'].dropna().unique())]

op_forn = [{'label': 'VISÃO GERAL (Top 10 Fornecedores)', 'value': 'TOTAL'}]
if not contratos_df.empty and 'fornecedor' in contratos_df.columns:
    op_forn += [{'label': str(n), 'value': str(n)} for n in sorted(contratos_df['fornecedor'].dropna().unique())]

op_mod = [{'label': 'VISÃO GERAL (Todas as Modalidades)', 'value': 'TOTAL'}]
if not licitacoes_df.empty and col_mod:
    op_mod += [{'label': str(n).upper(), 'value': str(n)} for n in sorted(licitacoes_df[col_mod].dropna().astype(str).unique())]

def format_currency(val):
    return f"R$ {val:,.2f}".replace(',','X').replace('.',',').replace('X','.')

def extrair_periodo(df):
    if not df.empty and 'ano' in df.columns:
        anos = pd.to_numeric(df['ano'], errors='coerce').dropna()
        if not anos.empty: return f"({int(anos.min())} a {int(anos.max())})"
    return "(Base Total)"

rec_anual = receitas_df.groupby('ano')['valorarrecadado'].sum().reset_index() if not receitas_df.empty else pd.DataFrame()
des_anual = despesas_df.groupby('ano')['valorempenhado'].sum().reset_index() if not despesas_df.empty else pd.DataFrame()

# ==============================================================================
# 3. ESTRUTURA BASE (SIDEBAR)
# ==============================================================================

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.FONT_AWESOME])
app.title = "Navegantes 360º"
server = app.server

SIDEBAR_STYLE = {
    "position": "fixed", "top": 0, "left": 0, "bottom": 0, "width": "18rem", 
    "padding": "2rem 1rem", "backgroundColor": "#1F2937", "color": "white", "overflowY": "auto"
}
CONTENT_STYLE = {"marginLeft": "18rem", "padding": "2rem 1rem", "backgroundColor": "#F3F4F6", "minHeight": "100vh"}

sidebar = html.Div([
    html.Div([
        html.H3("⚓ Navegantes 360", className="text-white mb-0"),
        html.Div(id="periodo-dinamico", style={"fontSize": "0.8rem", "color": "#9CA3AF", "marginTop": "5px"})
    ], className="text-center mb-4"),
    
    html.Div([
        html.Div("SEPAF - Departamento de", style={"fontSize": "0.7rem", "color": "#9CA3AF"}),
        html.Div("Planejamento e Gestão", style={"fontSize": "0.85rem", "fontWeight": "bold"})
    ], style={"backgroundColor": "#111827", "padding": "12px", "borderRadius": "8px", "textAlign": "center", "marginBottom": "2rem"}),

    dbc.Nav([
        dbc.NavLink([html.I(className="fas fa-chart-line me-3"), "Visão Geral"], href="/", active="exact", className="text-white-50"),
        dbc.NavLink([html.I(className="fas fa-wallet me-3"), "Receitas"], href="/receitas", active="exact", className="text-white-50"),
        dbc.NavLink([html.I(className="fas fa-file-invoice-dollar me-3"), "Despesas"], href="/despesas", active="exact", className="text-white-50"),
        html.Hr(style={"color": "#4B5563"}),
        dbc.NavLink([html.I(className="fas fa-gavel me-3"), "Licitações"], href="/licitacoes", active="exact", className="text-white-50"),
        dbc.NavLink([html.I(className="fas fa-file-contract me-3"), "Contratos"], href="/contratos", active="exact", className="text-white-50"),
    ], vertical=True, pills=True),
], style=SIDEBAR_STYLE)

app.layout = html.Div([dcc.Location(id="url"), sidebar, html.Div(id="page-content", style=CONTENT_STYLE)])

# ==============================================================================
# 4. CALLBACKS E ROTEAMENTO
# ==============================================================================

@app.callback(Output("periodo-dinamico", "children"), Input("url", "pathname"))
def atualizar_periodo(path):
    df_map = {"/": pd.concat([rec_anual, des_anual]) if not rec_anual.empty else pd.DataFrame(), "/receitas": rec_anual, "/despesas": des_anual, "/licitacoes": licitacoes_df, "/contratos": contratos_df}
    return f"Período: {extrair_periodo(df_map.get(path, pd.DataFrame()))}"

@app.callback(Output("page-content", "children"), Input("url", "pathname"))
def render_page(path):
    if path == "/receitas":
        return html.Div([
            html.H2("💰 Receitas"),
            dcc.Dropdown(id='rec-dd', options=op_rec, value='TOTAL', className="mb-4", clearable=False),
            html.Div(id='rec-content')
        ])
    if path == "/despesas":
        return html.Div([
            html.H2("💸 Despesas"),
            dcc.Dropdown(id='desp-dd', options=op_desp, value='TOTAL', className="mb-4", clearable=False),
            html.Div(id='desp-content')
        ])
    if path == "/contratos":
        return html.Div([
            html.H2("📄 Gestão de Contratos"),
            dcc.Dropdown(id='contrato-dd', options=op_forn, value='TOTAL', className="mb-4", clearable=False),
            html.Div(id='contrato-content')
        ])
    if path == "/licitacoes":
        return html.Div([
            html.H2("⚖️ Processos Licitatórios"),
            dcc.Dropdown(id='licitacao-dd', options=op_mod, value='TOTAL', className="mb-4", clearable=False),
            html.Div(id='licitacao-content')
        ])
    
    # HOME MANTIDA INTACTA CONFORME PEDIDO
    if rec_anual.empty or des_anual.empty: return dbc.Alert("Aguardando dados...", color="warning")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=rec_anual['ano'], y=rec_anual['valorarrecadado'], name="Receita", marker_color='#10B981'))
    fig.add_trace(go.Bar(x=des_anual['ano'], y=des_anual['valorempenhado'], name="Despesa", marker_color='#EF4444'))
    if len(rec_anual) > 1:
        fig.add_trace(go.Scatter(x=rec_anual['ano'], y=np.poly1d(np.polyfit(rec_anual['ano'], rec_anual['valorarrecadado'], 1))(rec_anual['ano']), name='Tendência Rec.', line=dict(color='#065F46', dash='dot')))
    if len(des_anual) > 1:
        fig.add_trace(go.Scatter(x=des_anual['ano'], y=np.poly1d(np.polyfit(des_anual['ano'], des_anual['valorempenhado'], 1))(des_anual['ano']), name='Tendência Desp.', line=dict(color='#991B1B', dash='dot')))
    fig.update_layout(title="Equilíbrio Orçamentário Anual com Tendência", barmode='group', template="plotly_white")

    total_con = contratos_df['valortotal'].sum() if not contratos_df.empty and 'valortotal' in contratos_df.columns else 0
    ultima_rec = rec_anual['valorarrecadado'].iloc[-1] if not rec_anual.empty else 0
    ano_rec = int(rec_anual['ano'].iloc[-1]) if not rec_anual.empty else ""

    return html.Div([
        html.H2("🏁 Visão Geral Executiva", className="mb-4"),
        dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody([html.H4(format_currency(ultima_rec), className="text-success"), html.P(f"Última Receita Anual ({ano_rec})")]), className="border-0 shadow-sm"), width=4),
            dbc.Col(dbc.Card(dbc.CardBody([html.H4(format_currency(total_con), className="text-primary"), html.P(f"Total em Contratos {extrair_periodo(contratos_df)}")]), className="border-0 shadow-sm"), width=4),
            dbc.Col(dbc.Card(dbc.CardBody([html.H4(len(licitacoes_df), className="text-info"), html.P(f"Processos Licitatórios {extrair_periodo(licitacoes_df)}")]), className="border-0 shadow-sm"), width=4),
        ], className="mb-4"),
        dbc.Card(dbc.CardBody(dcc.Graph(figure=fig)), className="border-0 shadow-sm")
    ])

# --- LÓGICA DINÂMICA DOS DROPDOWNS ---

@app.callback(Output('rec-content', 'children'), Input('rec-dd', 'value'))
def update_rec(conta):
    df = receitas_df if conta == 'TOTAL' else receitas_df[receitas_df['contadescricao'] == conta]
    fig = px.line(df.groupby('ano')['valorarrecadado'].sum().reset_index(), x='ano', y='valorarrecadado', title=f"Evolução: {conta}", markers=True, template="plotly_white")
    return dbc.Card(dbc.CardBody(dcc.Graph(figure=fig)), className="border-0 shadow-sm")

@app.callback(Output('desp-content', 'children'), Input('desp-dd', 'value'))
def update_desp(orgao):
    df = despesas_df if orgao == 'TOTAL' else despesas_df[despesas_df['orgaodescricao'] == orgao]
    fig = px.bar(df.groupby('ano')['valorempenhado'].sum().reset_index(), x='ano', y='valorempenhado', title=f"Despesa: {orgao}", template="plotly_white", color_discrete_sequence=['#EF4444'])
    return dbc.Card(dbc.CardBody(dcc.Graph(figure=fig)), className="border-0 shadow-sm")

@app.callback(Output('contrato-content', 'children'), Input('contrato-dd', 'value'))
def update_contrato(forn):
    if contratos_df.empty: return dbc.Alert("Sem dados", color="danger")
    if forn == 'TOTAL':
        df_top = contratos_df.groupby('fornecedor')['valortotal'].sum().nlargest(10).reset_index()
        fig = px.bar(df_top, x='valortotal', y='fornecedor', orientation='h', title="Top 10 Fornecedores", template="plotly_white", color_discrete_sequence=['#3B82F6'])
        fig.update_layout(yaxis={'categoryorder':'total ascending'})
        return html.Div([
            dbc.Row([dbc.Col(dbc.Card(dbc.CardBody([html.H4(format_currency(contratos_df['valortotal'].sum()), className="text-primary"), html.P("Volume Financeiro Total")]), className="border-0 shadow-sm mb-4"), width=6)]),
            dbc.Card(dbc.CardBody(dcc.Graph(figure=fig)), className="border-0 shadow-sm")
        ])
    else:
        df_f = contratos_df[contratos_df['fornecedor'] == forn]
        cols = [{"name": i.upper(), "id": i} for i in df_f.columns if i not in ['ano', 'fornecedor']]
        return html.Div([
            dbc.Row([dbc.Col(dbc.Card(dbc.CardBody([html.H4(format_currency(df_f['valortotal'].sum()), className="text-primary"), html.P(f"Total Contratado: {forn}")]), className="border-0 shadow-sm mb-4"), width=12)]),
            dbc.Card(dbc.CardBody(dash_table.DataTable(data=df_f.to_dict('records'), columns=cols, page_size=10, style_table={'overflowX': 'auto'}, style_header={'backgroundColor': '#F3F4F6', 'fontWeight': 'bold'})), className="border-0 shadow-sm")
        ])

@app.callback(Output('licitacao-content', 'children'), Input('licitacao-dd', 'value'))
def update_licitacao(mod):
    if licitacoes_df.empty: return dbc.Alert("Sem dados", color="danger")
    df_l = licitacoes_df if mod == 'TOTAL' else licitacoes_df[licitacoes_df[col_mod] == mod]
    
    fig_status = go.Figure().update_layout(title="Status não disponível")
    if col_sit: fig_status = px.bar(df_l[col_sit].value_counts().reset_index(), x=col_sit, y='count', title=f"Status: {mod}", template="plotly_white", color_discrete_sequence=['#8B5CF6'])
    
    est = df_l[col_est].sum() if col_est else 0
    hom = df_l[col_hom].sum() if col_hom else 0
    return html.Div([
        dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody([html.H4(format_currency(est), className="text-warning"), html.P("Estimado Global")]), className="border-0 shadow-sm"), width=6),
            dbc.Col(dbc.Card(dbc.CardBody([html.H4(format_currency(hom), className="text-success"), html.P("Homologado Global")]), className="border-0 shadow-sm"), width=6),
        ], className="mb-4"),
        dbc.Card(dbc.CardBody(dcc.Graph(figure=fig_status)), className="border-0 shadow-sm")
    ])

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=7860)