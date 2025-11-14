import dash
from dash import dcc, html
import plotly.express as px
import pandas as pd
from dash.dependencies import Input, Output
from datetime import datetime, timedelta
import re 
import requests # ¡NUEVO! Necesario para la API
import json     # ¡NUEVO!
import os       # ¡NUEVO! Para leer las variables de entorno

# --- Constantes de Estilo (¡ACTUALIZADAS!) ---
COLOR_FONDO = "#222222" # Fondo oscuro
COLOR_TEXTO = "#f0f0f0" # Texto claro
COLOR_KPI = "#333333"   # Fondo de tarjetas oscuro
COLOR_BARRA_AZUL = "#0d1bd4" # Tu color azul
KPI_BOX_SHADOW = "0 4px 6px rgba(0, 0, 0, 0.4)" # Sombra más oscura
KPI_BORDER_RADIUS = "8px"
# ARCHIVO_DATOS = "yesterday_sample.json" # <-- ELIMINADO. Ya no leemos de un archivo.

# -------------------------------------------------------------------
# ¡NUEVO! LECTURA DE VARIABLES DE ENTORNO (SECRETOS)
# -------------------------------------------------------------------
# Render pondrá los valores aquí desde su panel de control
HIBOT_BASE_URL = os.environ.get("HIBOT_BASE_URL", "https://pdn.api.hibot.us/api_external")
HIBOT_APP_ID = os.environ.get("HIBOT_APP_ID")
HIBOT_APP_SECRET = os.environ.get("HIBOT_APP_SECRET")

# -------------------------------------------------------------------
# ¡NUEVO! LÓGICA DE EXTRACCIÓN DE DATOS (API)
# -------------------------------------------------------------------

def get_auth_token():
    """
    Obtiene el token de autenticación JWT desde la API de HiBot.
    """
    login_url = f"{HIBOT_BASE_URL}/login"
    payload = {
        "appId": HIBOT_APP_ID,
        "appSecret": HIBOT_APP_SECRET
    }
    print(f"Solicitando token de {login_url}...")
    try:
        response = requests.post(login_url, json=payload)
        response.raise_for_status() 
        data = response.json()
        token = data.get("token")
        if token:
            print("¡Token obtenido exitosamente!")
            return token
        print("Error: No se encontró 'token' en la respuesta.")
        return None
    except Exception as e:
        print(f"Error al obtener token: {e}")
        return None

def fetch_live_data(token):
    """
    Obtiene las conversaciones del MES EN CURSO.
    """
    if not token:
        print("No hay token, no se pueden obtener datos.")
        return []

    conversations_url = f"{HIBOT_BASE_URL}/conversations"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Lógica de Fecha: Mes en curso
    hoy = datetime.now()
    inicio_mes = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Convertimos a formato "timestamp" en milisegundos
    timestamp_from = int(inicio_mes.timestamp() * 1000)
    timestamp_to = int(hoy.timestamp() * 1000) # Hasta el momento actual

    filter_payload = {
        "from": timestamp_from,
        "to": timestamp_to,
    }
    
    print(f"Consultando conversaciones del mes (desde {inicio_mes.date()})...")
    
    try:
        response = requests.post(conversations_url, headers=headers, json=filter_payload)
        response.raise_for_status()
        conversations_data = response.json()
        print(f"¡Éxito! Se encontraron {len(conversations_data)} conversaciones.")
        return conversations_data
    except Exception as e:
        print(f"Error al obtener conversaciones: {e}")
        return [] # Devolver lista vacía en caso de error

# --- Carga y Limpieza de Datos ---
def cargar_datos(raw_data):
    """
    Procesa los datos JSON (desde la API) y los prepara para el dashboard.
    """
    if not raw_data:
        print("No hay datos crudos para procesar.")
        return pd.DataFrame()

    try:
        df = pd.DataFrame(raw_data)
    except Exception as e:
        print(f"Error al crear DataFrame: {e}")
        return pd.DataFrame()

    if df.empty:
        print("El DataFrame está vacío. No hay datos para mostrar.")
        return df

    # --- VALIDACIÓN DE SEGURIDAD ---
    # (Verificamos columnas clave)
    columnas_requeridas = ['created', 'channel', 'typing', 'status', 'agent']
    
    columnas_faltantes = [col for col in columnas_requeridas if col not in df.columns]
    if columnas_faltantes:
        print("¡ADVERTENCIA DE DATOS!")
        print(f"Faltan columnas esperadas: {columnas_faltantes}")
        print(f"Columnas encontradas: {df.columns.to_list()}")
        
    # --- PREPARACIÓN DE DATOS ---
    
    # Extraer 'channelType'
    if 'channel' in df.columns and df['channel'].apply(isinstance, args=(dict,)).any():
        df['channelType'] = df['channel'].apply(lambda x: x.get('type') if isinstance(x, dict) else 'N/A')
    
    # --- ¡NUEVO! Parseo de 'agent' para 'PuntoDeVenta' y 'NombreAgenteLimpio' ---
    if 'agent' in df.columns:
        # 1. Obtenemos el nombre crudo (Ej: "R18 V - MAURICIO PUCHETA")
        df['agentNameRaw'] = df['agent'].apply(lambda x: x.get('name') if isinstance(x, dict) else 'Sin Agente')
        df['agentNameRaw'] = df['agentNameRaw'].fillna('Sin Agente')

        # 2. Definimos la función de parseo
        def parse_agent_name(name_raw):
            if ' - ' not in name_raw:
                return 'Sin Asignar', 'Sin Agente' # Caso "Sin Agente" o BOTS
            
            # Dividimos en header ("R18 V") y nombre ("MAURICIO PUCHETA")
            parts = name_raw.split(' - ', 1)
            header = parts[0]
            agent_name = parts[1] if len(parts) > 1 else 'Nombre Desconocido'
            
            # Caso Especial "VD" (CANAL DIGITAL)
            if " VD" in header:
                pos = "CANAL DIGITAL"
            else:
                # Extraemos el código "Rxx" (Ej: "R18")
                match = re.match(r'^(R\d+)', header)
                if match:
                    pos_code = match.group(1)
                    pos = f"Reino {pos_code[1:]}" # Convierte "R18" a "Reino 18"
                else:
                    pos = 'Otro' # Fallback si no coincide el patrón
            
            return pos, agent_name

        # 3. Aplicamos la función para crear las dos nuevas columnas
        parsed_data = df['agentNameRaw'].apply(parse_agent_name)
        df['PuntoDeVenta'] = parsed_data.apply(lambda x: x[0])
        df['NombreAgenteLimpio'] = parsed_data.apply(lambda x: x[1])

    else:
        df['PuntoDeVenta'] = 'N/A'
        df['NombreAgenteLimpio'] = 'N/A'

    # Convertir fechas (usamos 'created' para casi todo)
    if 'created' in df.columns:
        df['created'] = pd.to_datetime(df['created'], errors='coerce', unit='ms')
        df['hora_inicio'] = df['created'].dt.hour
        df['dia_semana'] = df['created'].dt.day_name()
        df['dia_mes'] = df['created'].dt.date
    
    # Convertir 'assigned' si existe
    if 'assigned' in df.columns:
        df['assigned_dt'] = pd.to_datetime(df['assigned'], errors='coerce', unit='ms')
        df['hora_asignacion'] = df['assigned_dt'].dt.hour
    
    # --- FILTRO 2: DATOS DEL MES EN CURSO ---
    # La API ya filtró por mes, pero volvemos a filtrar por si acaso
    if 'created' in df.columns:
        hoy = datetime.now()
        inicio_mes = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        df['created'] = df['created'].dt.tz_localize(None) # Hacemos naive para comparar
        df_filtrado = df[df['created'] >= inicio_mes].copy()
        
        print(f"Datos del mes en curso procesados: {len(df_filtrado)}")
        
        # Llenamos valores NaN en 'typing' para conteo
        if 'typing' in df_filtrado.columns:
            df_filtrado['typing'] = df_filtrado['typing'].fillna('N/A')
        
        return df_filtrado
    
    return pd.DataFrame() # Devolver vacío si no hay 'created'

# --- ¡¡¡CAMBIO IMPORTANTE!!! ---
# 1. OBTENER TOKEN
# 2. OBTENER DATOS
# 3. PROCESAR DATOS
# Esto se ejecuta UNA SOLA VEZ cuando el servidor de Render se inicia.
print("--- INICIANDO SERVIDOR DEL DASHBOARD ---")
if not HIBOT_APP_ID or not HIBOT_APP_SECRET:
    print("¡ERROR GRAVE! Faltan HIBOT_APP_ID o HIBOT_APP_SECRET en las variables de entorno.")
    print("El dashboard se iniciará, pero no mostrará datos.")
    df_mes_en_curso = pd.DataFrame()
else:
    api_token = get_auth_token()
    raw_data_api = fetch_live_data(api_token)
    df_mes_en_curso = cargar_datos(raw_data_api)
print("----------------------------------------")


# --- Calcular KPIs Principales (Requisito 3) ---
total_conversaciones_mes = 0
total_conversaciones_hoy = 0
total_venta = 0
total_venta_a_confirmar = 0
total_venta_perdida = 0
total_otro_motivo = 0
total_reclamo = 0
conversion_whatsapp = 0.0

if not df_mes_en_curso.empty:
    # KPI: TOTAL DE CONVERSACIONES ACUMULADAS MES
    total_conversaciones_mes = len(df_mes_en_curso)
    
    # KPI: TOTAL DE CONVERSACIONES HOY
    hoy_normal = datetime.now().date()
    total_conversaciones_hoy = len(df_mes_en_curso[df_mes_en_curso['created'].dt.date == hoy_normal])
    
    # KPIs por 'typing'
    total_venta = len(df_mes_en_curso[df_mes_en_curso['typing'] == 'VENTA'])
    total_venta_a_confirmar = len(df_mes_en_curso[df_mes_en_curso['typing'] == 'VENTA A CONFIRMAR'])
    total_venta_perdida = len(df_mes_en_curso[df_mes_en_curso['typing'] == 'VENTA PERDIDA'])
    total_otro_motivo = len(df_mes_en_curso[df_mes_en_curso['typing'] == 'OTRO MOTIVO'])
    total_reclamo = len(df_mes_en_curso[df_mes_en_curso['typing'] == 'RECLAMO'])

    # KPI: % DE CONVERSION COMPAÑIA (Solo WhatsApp)
    df_whatsapp = df_mes_en_curso[df_mes_en_curso['channelType'] == 'WHATSAPP']
    total_whatsapp = len(df_whatsapp)
    ventas_whatsapp = len(df_whatsapp[df_whatsapp['typing'] == 'VENTA'])
    
    if total_whatsapp > 0:
        conversion_whatsapp = (ventas_whatsapp / total_whatsapp) * 100

# --- Crear Gráficos (Requisito 4) ---
# (Creamos figuras vacías por si acaso)
fig_diaria_mes = px.bar(title="Conversaciones Diarias (Mes en Curso)")
fig_canal_torta = px.pie(title="Participación por Canal")
fig_hora_creacion = px.bar(title="Conversaciones por Hora de Creación (0-23hs)")
fig_hora_asignacion = px.bar(title="Conversaciones por Hora de Asignación (9-18hs)")
fig_dia_semana = px.bar(title="Conversaciones por Día de la Semana")
fig_pos_bar = px.bar(title="Conversaciones por Punto de Venta (Mes)") # ¡NUEVO!
fig_agente_bar = px.bar(title="Conversaciones por Agente (Mes)") # Actualizado

if not df_mes_en_curso.empty:
    
    # GRAFICO MENSUAL DE CONVERSACIONES DIARIAS
    if 'dia_mes' in df_mes_en_curso.columns:
        data_diaria = df_mes_en_curso.groupby('dia_mes').size().reset_index(name='conteo')
        fig_diaria_mes = px.bar(data_diaria, x='dia_mes', y='conteo', 
                                title="Conversaciones Diarias (Mes en Curso)",
                                color_discrete_sequence=[COLOR_BARRA_AZUL],
                                text_auto=True) # <-- ETIQUETA DE DATOS

    # GRAFICO DE PARTICIPACION POR CANAL (TORTA)
    if 'channelType' in df_mes_en_curso.columns:
        data_canal = df_mes_en_curso.groupby('channelType').size().reset_index(name='conteo')
        fig_canal_torta = px.pie(data_canal, names='channelType', values='conteo', 
                                 title="Participación por Canal")

    # GRAFICO ACUMULADO MENSUAL DE CONVERSACIONES POR HORA (CREACION)
    if 'hora_inicio' in df_mes_en_curso.columns:
        data_hora_creacion = df_mes_en_curso.groupby('hora_inicio').size().reset_index(name='conteo')
        fig_hora_creacion = px.bar(data_hora_creacion, x='hora_inicio', y='conteo', 
                                   title="Conversaciones por Hora de Creación (0-23hs)",
                                   color_discrete_sequence=[COLOR_BARRA_AZUL],
                                   text_auto=True)
        fig_hora_creacion.update_xaxes(type='category') 

    # GRAFICO MENSUAL DE CONVERSACIONES POR HORA (ASIGNACION 9-18HS)
    if 'hora_asignacion' in df_mes_en_curso.columns:
        df_asig_filtrado = df_mes_en_curso[
            (df_mes_en_curso['hora_asignacion'] >= 9) & 
            (df_mes_en_curso['hora_asignacion'] <= 18)
        ]
        data_hora_asig = df_asig_filtrado.groupby('hora_asignacion').size().reset_index(name='conteo')
        fig_hora_asignacion = px.bar(data_hora_asig, x='hora_asignacion', y='conteo', 
                                     title="Conversaciones por Hora de Asignación (9-18hs)",
                                     color_discrete_sequence=[COLOR_BARRA_AZUL],
                                     text_auto=True)
        fig_hora_asignacion.update_xaxes(type='category')
        
    # CANTIDAD DE CONVERSACIONES ACUMULADAS POR DIA DE LA SEMANA (ORDENADO)
    if 'dia_semana' in df_mes_en_curso.columns:
        data_dia_sem = df_mes_en_curso.groupby('dia_semana').size().reset_index(name='conteo')
        data_dia_sem = data_dia_sem.sort_values(by='conteo', ascending=False)
        fig_dia_semana = px.bar(data_dia_sem, x='dia_semana', y='conteo', 
                                title="ConversACIONES por Día de la Semana (Más a Menos)",
                                color_discrete_sequence=[COLOR_BARRA_AZUL],
                                text_auto=True)

    # --- ¡NUEVO! GRAFICO POR PUNTO DE VENTA (ORDENADO) ---
    if 'PuntoDeVenta' in df_mes_en_curso.columns:
        data_pos = df_mes_en_curso.groupby('PuntoDeVenta').size().reset_index(name='conteo')
        data_pos = data_pos.sort_values(by='conteo', ascending=False)
        fig_pos_bar = px.bar(data_pos, x='PuntoDeVenta', y='conteo', 
                             title="Conversaciones por Punto de Venta (Mes)",
                             color_discrete_sequence=[COLOR_BARRA_AZUL],
                             text_auto=True)

    # --- ¡ACTUALIZADO! GRAFICO POR AGENTE (ORDENADO) ---
    if 'NombreAgenteLimpio' in df_mes_en_curso.columns:
        data_agente = df_mes_en_curso.groupby('NombreAgenteLimpio').size().reset_index(name='conteo')
        # Filtramos agentes con pocas conversaciones para que el gráfico sea legible
        data_agente = data_agente[data_agente['conteo'] > 1] # Opcional: ajustar este filtro
        data_agente = data_agente.sort_values(by='conteo', ascending=False)
        fig_agente_bar = px.bar(data_agente, x='NombreAgenteLimpio', y='conteo', 
                                title="Conversaciones por Agente (Mes)",
                                color_discrete_sequence=[COLOR_BARRA_AZUL],
                                text_auto=True)

# --- ¡NUEVO! APLICAR ESTILOS DE MODO OSCURO A TODOS LOS GRÁFICOS ---
list_of_figures = [
    fig_diaria_mes, fig_canal_torta, fig_hora_creacion, 
    fig_hora_asignacion, fig_dia_semana, fig_pos_bar, fig_agente_bar
]

for fig in list_of_figures:
    fig.update_layout(
        plot_bgcolor=COLOR_KPI,     # Fondo del área del gráfico
        paper_bgcolor=COLOR_KPI,    # Fondo de la tarjeta del gráfico
        font_color=COLOR_TEXTO,     # Color del texto (ejes, etiquetas)
        font_family="Arial",        # Tipografía de datos (ejes)
        title_font_family="Open Sans", # Tipografía de títulos
        title_font_weight="bold"        # Negrita para títulos
    )
    # Asegurar que las etiquetas de datos (texto en barras) sean claras
    fig.update_traces(textfont_color=COLOR_TEXTO, textposition='outside')


# --- ¡NUEVO! Cargar Tipografías Externas ---
external_stylesheets = [
    'https://fonts.googleapis.com/css2?family=Open+Sans:wght@700&family=Arial&display=swap'
]

# --- Inicializar la App Dash ---
app = dash.Dash(__name__, external_stylesheets=external_stylesheets)
# Necesario para Render:
server = app.server

# --- Layout de la Aplicación ---
app.layout = html.Div(style={'backgroundColor': COLOR_FONDO, 'fontFamily': 'Arial', 'padding': '20px'}, children=[
    
    # --- Requisito 1: Aquí puedes editar el título ---
    html.H1(
        children='Tablero de control Digital - Reino Cerámicos',
        style={'textAlign': 'center', 'color': COLOR_TEXTO, 'fontFamily': 'Open Sans', 'fontWeight': 'bold'}
    ),
    
    html.P(
        children=f"Mostrando datos del Mes en Curso (desde {datetime.now().strftime('%Y-%m-01')})",
        style={'textAlign': 'center', 'color': '#aaaaaa'} # Texto de subtítulo más suave
    ),

    # --- Fila de KPIs (Requisito 3) ---
    html.Div(style={'display': 'flex', 'justifyContent': 'space-around', 'margin': '20px 0', 'flexWrap': 'wrap'}, children=[
        
        # TOTAL DE CONVERSACIONES ACUMULADAS MES
        html.Div(style={'backgroundColor': COLOR_KPI, 'padding': '15px', 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'width': '23%', 'textAlign': 'center', 'margin': '1%'}, children=[
            html.H3('Total Conversaciones (Mes)', style={'color': COLOR_TEXTO, 'margin': '0', 'fontSize': '16px', 'fontFamily': 'Open Sans', 'fontWeight': 'bold'}),
            html.H2(f"{total_conversaciones_mes}", style={'color': '#007bff', 'fontSize': '32px', 'margin': '10px 0 0 0', 'fontFamily': 'Arial'})
        ]),
        
        # TOTAL DE CONVERSACIONES HOY
        html.Div(style={'backgroundColor': COLOR_KPI, 'padding': '15px', 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'width': '23%', 'textAlign': 'center', 'margin': '1%'}, children=[
            html.H3('Total Conversaciones (Hoy)', style={'color': COLOR_TEXTO, 'margin': '0', 'fontSize': '16px', 'fontFamily': 'Open Sans', 'fontWeight': 'bold'}),
            html.H2(f"{total_conversaciones_hoy}", style={'color': '#17a2b8', 'fontSize': '32px', 'margin': '10px 0 0 0', 'fontFamily': 'Arial'})
        ]),

        # % DE CONVERSION COMPAÑIA
        html.Div(style={'backgroundColor': COLOR_KPI, 'padding': '15px', 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'width': '23%', 'textAlign': 'center', 'margin': '1%'}, children=[
            html.H3('% Conversión (WhatsApp)', style={'color': COLOR_TEXTO, 'margin': '0', 'fontSize': '16px', 'fontFamily': 'Open Sans', 'fontWeight': 'bold'}),
            html.H2(f"{conversion_whatsapp:.2f}%", style={'color': '#28a745', 'fontSize': '32px', 'margin': '10px 0 0 0', 'fontFamily': 'Arial'})
        ]),
        
        # TOTAL DE CONVERSACIONES typing "VENTA"
        html.Div(style={'backgroundColor': COLOR_KPI, 'padding': '15px', 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'width': '23%', 'textAlign': 'center', 'margin': '1%'}, children=[
            html.H3('Total "Venta"', style={'color': COLOR_TEXTO, 'margin': '0', 'fontSize': '16px', 'fontFamily': 'Open Sans', 'fontWeight': 'bold'}),
            html.H2(f"{total_venta}", style={'color': '#28a745', 'fontSize': '32px', 'margin': '10px 0 0 0', 'fontFamily': 'Arial'})
        ]),

        # TOTAL DE CONVERSACIONES typing "VENTA A CONFIRMAR"
        html.Div(style={'backgroundColor': COLOR_KPI, 'padding': '15px', 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'width': '23%', 'textAlign': 'center', 'margin': '1%'}, children=[
            html.H3('Total "Venta a Confirmar"', style={'color': COLOR_TEXTO, 'margin': '0', 'fontSize': '16px', 'fontFamily': 'Open Sans', 'fontWeight': 'bold'}),
            html.H2(f"{total_venta_a_confirmar}", style={'color': '#ffc107', 'fontSize': '32px', 'margin': '10px 0 0 0', 'fontFamily': 'Arial'})
        ]),

        # TOTAL DE CONVERSACIONES typing "VENTA PERDIDA"
        html.Div(style={'backgroundColor': COLOR_KPI, 'padding': '15px', 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'width': '23%', 'textAlign': 'center', 'margin': '1%'}, children=[
            html.H3('Total "Venta Perdida"', style={'color': COLOR_TEXTO, 'margin': '0', 'fontSize': '16px', 'fontFamily': 'Open Sans', 'fontWeight': 'bold'}),
            html.H2(f"{total_venta_perdida}", style={'color': '#dc3545', 'fontSize': '32px', 'margin': '10px 0 0 0', 'fontFamily': 'Arial'})
        ]),

        # TOTAL DE CONVERSACIONES typing "OTRO MOTIVO"
        html.Div(style={'backgroundColor': COLOR_KPI, 'padding': '15px', 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'width': '23%', 'textAlign': 'center', 'margin': '1%'}, children=[
            html.H3('Total "Otro Motivo"', style={'color': COLOR_TEXTO, 'margin': '0', 'fontSize': '16px', 'fontFamily': 'Open Sans', 'fontWeight': 'bold'}),
            html.H2(f"{total_otro_motivo}", style={'color': '#6c757d', 'fontSize': '32px', 'margin': '10px 0 0 0', 'fontFamily': 'Arial'})
        ]),

        # TOTAL DE CONVERSACIONES typing "RECLAMO"
        html.Div(style={'backgroundColor': COLOR_KPI, 'padding': '15px', 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'width': '23%', 'textAlign': 'center', 'margin': '1%'}, children=[
            html.H3('Total "Reclamo"', style={'color': COLOR_TEXTO, 'margin': '0', 'fontSize': '16px', 'fontFamily': 'Open Sans', 'fontWeight': 'bold'}),
            html.H2(f"{total_reclamo}", style={'color': '#fd7e14', 'fontSize': '32px', 'margin': '10px 0 0 0', 'fontFamily': 'Arial'})
        ]),
    ]),

    # --- Fila de Gráficos (Requisito 4) ---
    html.Div(style={'display': 'flex', 'justifyContent': 'space-around', 'margin': '20px 0', 'flexWrap': 'wrap'}, children=[
        dcc.Graph(
            id='graph-diaria-mes',
            figure=fig_diaria_mes,
            style={'width': '100%', 'backgroundColor': COLOR_KPI, 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'padding': '10px', 'margin': '10px'}
        ),
        dcc.Graph(
            id='graph-canal-torta',
            figure=fig_canal_torta,
            style={'width': '48%', 'backgroundColor': COLOR_KPI, 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'padding': '10px', 'margin': '10px'}
        ),
        dcc.Graph(
            id='graph-dia-semana',
            figure=fig_dia_semana,
            style={'width': '48%', 'backgroundColor': COLOR_KPI, 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'padding': '10px', 'margin': '10px'}
        ),
        dcc.Graph(
            id='graph-hora-creacion',
            figure=fig_hora_creacion,
            style={'width': '48%', 'backgroundColor': COLOR_KPI, 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'padding': '10px', 'margin': '10px'}
        ),
        dcc.Graph(
            id='graph-hora-asignacion',
            figure=fig_hora_asignacion,
            style={'width': '48%', 'backgroundColor': COLOR_KPI, 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'padding': '10px', 'margin': '10px'}
        ),
        
        # --- ¡NUEVOS GRÁFICOS REQUERIDOS! ---
        dcc.Graph(
            id='graph-pos-bar',
            figure=fig_pos_bar,
            style={'width': '48%', 'backgroundColor': COLOR_KPI, 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'padding': '10px', 'margin': '10px'}
        ),
         dcc.Graph(
            id='graph-agente-bar',
            figure=fig_agente_bar,
            style={'width': '48%', 'backgroundColor': COLOR_KPI, 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'padding': '10px', 'margin': '10px'}
        ),
    ]),
])

# --- Ejecutar la App ---
if __name__ == '__main__':
    print("Iniciando servidor Dash en http://127.0.0.1:8050/")
    # Corregimos el comando de ejecución
    app.run(debug=True, port=8050)
