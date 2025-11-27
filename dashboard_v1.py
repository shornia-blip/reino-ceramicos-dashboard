import dash
from dash import dcc, html, dash_table
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from dash.dependencies import Input, Output, State
from datetime import datetime, timedelta
import re 
import requests 
import json      
import os        
import numpy as np 
import io 

# --- Constantes de Estilo y Colores ---
COLOR_FONDO = "#222222" 
COLOR_TEXTO = "#f0f0f0" 
COLOR_KPI = "#333333"   
COLOR_BARRA_AZUL = "#0d1bd4" # Azul de Reino Cerámicos
KPI_BOX_SHADOW = "0 4px 6px rgba(0, 0, 0, 0.4)" 
KPI_BORDER_RADIUS = "8px"
ARCHIVO_LOCAL = "yesterday_sample.json" # Archivo de respaldo para desarrollo local

# Colores específicos para canales (Requisito 10)
CANAL_COLORS = {
    'WhatsApp': "#1fff39",
    'Facebook': "#1f23ff", 
    'Instagram': "#8B2EEF",
    'Mercado Libre': "#fff700", 
    'N/A': 'gray'
}

# Orden fijo de días de la semana (Requisito 11)
ORDEN_DIAS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
NOMBRES_DIAS_ES = {
    'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles',
    'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
}

# --- OBJETIVOS (LÍNEAS GUÍA) ---
# Objetivo diario POR PUNTO DE VENTA (Base)
OBJETIVO_DIARIO_POR_PV = {
    'Monday': 50, 'Tuesday': 50, 'Wednesday': 50, 'Thursday': 50, 'Friday': 50, # Lunes a Viernes: 50
    'Saturday': 25, # Sábados: 25
    'Sunday': 10  # Domingos: 10
}
META_CONVERSION_WHATSAPP = 50 # Objetivo para la barra horizontal

# Requisito 2: Conversaciones por Día de la Semana (Valores variables)
OBJETIVO_SEMANAL = {
    'Monday': 500, 'Tuesday': 500, 'Wednesday': 500, 'Thursday': 500, 'Friday': 500,
    'Saturday': 275, 'Sunday': 115
}
# -------------------------------------------------------------------
# LÓGICA DE EXTRACCIÓN Y PROCESAMIENTO
# -------------------------------------------------------------------

HIBOT_BASE_URL = os.environ.get("HIBOT_BASE_URL", "https://pdn.api.hibot.us/api_external")
HIBOT_APP_ID = os.environ.get("HIBOT_APP_ID")
HIBOT_APP_SECRET = os.environ.get("HIBOT_APP_SECRET")

def get_auth_token():
    """ Obtiene el token de autenticación JWT desde la API. """
    if not HIBOT_APP_ID or not HIBOT_APP_SECRET:
        print("Error: No se configuraron HIBOT_APP_ID/SECRET.")
        return None
    try:
        login_url = f"{HIBOT_BASE_URL}/login"
        payload = {"appId": HIBOT_APP_ID, "appSecret": HIBOT_APP_SECRET}
        print(f"Solicitando token a API...")
        response = requests.post(login_url, json=payload, timeout=10)
        response.raise_for_status() 
        return response.json().get("token")
    except Exception as e:
        print(f"Error al obtener token API: {e}")
        return None

def fetch_live_data(token):
    """ Obtiene las conversaciones del MES EN CURSO desde la API. """
    if not token: return []
    try:
        conversations_url = f"{HIBOT_BASE_URL}/conversations"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        
        hoy = datetime.now()
        inicio_mes = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        timestamp_from = int(inicio_mes.timestamp() * 1000)
        timestamp_to = int(hoy.timestamp() * 1000)

        filter_payload = {"from": timestamp_from, "to": timestamp_to}
        
        print(f"Consultando API (desde {inicio_mes.date()})...")
        response = requests.post(conversations_url, headers=headers, json=filter_payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        print(f"¡Éxito API! {len(data)} conversaciones descargadas.")
        return data
    except Exception as e:
        print(f"Error al obtener datos de API: {e}")
        return []

def cargar_datos_locales():
    """ Carga datos desde el archivo JSON local (Modo Desarrollo). """
    print(f"Intentando cargar datos locales de '{ARCHIVO_LOCAL}'...")
    try:
        with open(ARCHIVO_LOCAL, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f"¡Éxito Local! {len(data)} conversaciones cargadas del archivo.")
        return data
    except FileNotFoundError:
        print(f"Error: No se encontró '{ARCHIVO_LOCAL}'. Ejecuta get_yesterday_sample.py primero.")
        return []
    except Exception as e:
        print(f"Error leyendo archivo local: {e}")
        return []

def procesar_dataframe(raw_data):
    """ Convierte la lista de diccionarios en un DataFrame limpio y procesado. """
    if not raw_data: return pd.DataFrame()

    df = pd.DataFrame(raw_data)
    if df.empty: return df

    # 1. Validación de columnas mínimas
    if 'created' not in df.columns: return pd.DataFrame()

    # 2. Parseo de Fechas
    df['created'] = pd.to_datetime(df['created'], errors='coerce', unit='ms')
    df['created'] = df['created'].dt.tz_localize(None)
    
    df['hora_inicio'] = df['created'].dt.hour
    df['dia_semana'] = df['created'].dt.day_name()
    df['dia_mes'] = df['created'].dt.date
    df['dia_mes_str'] = df['dia_mes'].apply(lambda x: x.strftime('%d-%m')) 

    if 'assigned' in df.columns:
        df['assigned_dt'] = pd.to_datetime(df['assigned'], errors='coerce', unit='ms')
        df['assigned_dt'] = df['assigned_dt'].dt.tz_localize(None)
        # Columna clave para el gráfico de asignación por hora
        df['hora_asignacion'] = df['assigned_dt'].dt.hour 
    else:
        df['hora_asignacion'] = np.nan 

    # 3. Extracción channelType
    if 'channel' in df.columns:
        def get_channel_type(x):
            if isinstance(x, dict): return x.get('type', 'N/A')
            return 'N/A'
        df['channelType'] = df['channel'].apply(get_channel_type)
        # Limpieza de nombres
        df['channelType'] = df['channelType'].replace({'WHATSAPP': 'WhatsApp', 'FACEBOOK': 'Facebook', 'INSTAGRAM': 'Instagram', 'MERCADOLIBRE': 'Mercado Libre'})

    # 4. Parseo de Agente y Punto de Venta (Lógica compleja)
    if 'agent' in df.columns:
        def get_agent_name(x):
            if isinstance(x, dict): 
                # Nuevo campo: nombre completo del agente (para la tabla detalle)
                return x.get('name', 'Sin Agente')
            return 'N/A'
        
        df['agent.name'] = df['agent'].apply(get_agent_name).fillna('N/A')
        
        # Lógica de Parseo Rxx / VD
        def parse_agent(name_raw):
            if not isinstance(name_raw, str) or ' - ' not in name_raw: return 'Sin Asignar', 'Sin Agente'
            
            parts = name_raw.split(' - ', 1)
            header = parts[0].strip()
            name_clean = parts[1].strip()

            if "VD" in header: pos = "CANAL DIGITAL"
            else:
                match = re.match(r'^(R\d+)', header)
                pos = f"Reino {match.group(1)[1:]}" if match else 'Otro'
            return pos, name_clean

        # Aplicar y asignar
        parsed = df['agent.name'].apply(parse_agent)
        df['PuntoDeVenta'] = parsed.apply(lambda x: x[0])
    else:
        df['PuntoDeVenta'] = 'N/A'
        df['agent.name'] = 'N/A' # Asegura que la columna exista

    # 5. Extracción de ID y nombre de usuario/cliente (Corregido y Fortalecido)
    if 'user' in df.columns:
        def get_user_data(x, key):
            if isinstance(x, dict): return x.get(key, None)
            return None
        # Corregido: Extracción robusta de user id
        df['userId'] = df['user'].apply(lambda x: get_user_data(x, 'id'))
        df['client.name'] = df['user'].apply(lambda x: get_user_data(x, 'name'))
    else:
        df['userId'] = None
        df['client.name'] = None
    
    # 6. Extracción de otros campos para la tabla detalle (Punto 4)
    df['id'] = df.get('id', pd.Series(dtype='object'))
    df['attentionHour'] = df.get('attentionHour', pd.Series(dtype='object')) # Asumo que attentionHour está en el JSON si existe
    df['status'] = df.get('status', 'N/A') # Estado de la conversación
    df['direction'] = df.get('direction', 'N/A')
    df['answerTime'] = df.get('answerTime', pd.Series(dtype='object'))
    df['note'] = df.get('note', pd.Series(dtype='object'))
    df['assigned'] = df.get('assigned', pd.Series(dtype='object')) # Raw timestamp para la tabla

    # 7. Filtro por Mes en Curso
    hoy = datetime.now()
    inicio_mes = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    df_filtrado = df[df['created'] >= inicio_mes].copy()
    
    if 'typing' in df_filtrado.columns:
        df_filtrado['typing'] = df_filtrado['typing'].fillna('N/A')
    
    return df_filtrado

# --- BLOQUE PRINCIPAL DE CARGA DE DATOS ---
def calcular_objetivo_pos_venta_acumulado(hoy):
    """ Calcula el objetivo acumulado para un Punto de Venta hasta la fecha actual. """
    inicio_mes = hoy.replace(day=1).date()
    objetivo_acumulado = 0
    
    current_date = inicio_mes
    while current_date <= hoy.date():
        day_name = current_date.strftime('%A')
        objetivo_acumulado += OBJETIVO_DIARIO_POR_PV.get(day_name, 0)
        current_date += timedelta(days=1)
        
    return objetivo_acumulado

def cargar_datos_y_calcular_kpis():
    """ Función que encapsula la carga de datos y el cálculo de KPIs, para ser llamada por el intervalo. """
    print("--- INICIANDO CARGA DE DATOS ---")
    if HIBOT_APP_ID and HIBOT_APP_SECRET:
        print("Modo detectado: PRODUCCIÓN (API)")
        token = get_auth_token()
        raw_data = fetch_live_data(token)
    else:
        print("Modo detectado: DESARROLLO LOCAL (Archivo JSON)")
        raw_data = cargar_datos_locales()

    df_mes_en_curso = procesar_dataframe(raw_data)
    print(f"Conversaciones procesadas para el mes: {len(df_mes_en_curso)}")
    print("--------------------------------")

    OBJETIVO_POS_VENTA_ACUMULADO = calcular_objetivo_pos_venta_acumulado(datetime.now())

    # --- CÁLCULO DE KPIS ---
    total_conversaciones_mes = 0
    total_conversaciones_hoy = 0
    total_contactos_unicos_hoy = 0 
    total_contactos_unicos_mes = 0 
    total_venta = 0
    total_venta_a_confirmar = 0
    total_venta_perdida = 0
    total_otro_motivo = 0
    total_reclamo = 0
    conversion_whatsapp = 0.0

    if not df_mes_en_curso.empty:
        hoy_fecha = datetime.now().date()
        
        # Conversaciones (Total rows)
        total_conversaciones_mes = len(df_mes_en_curso)
        df_hoy = df_mes_en_curso[df_mes_en_curso['created'].dt.date == hoy_fecha]
        total_conversaciones_hoy = len(df_hoy)
        
        # Contactos Únicos (Unique user IDs)
        # Corregido: La lógica ahora funciona ya que el userId se extrae robustamente en procesar_dataframe
        if 'userId' in df_mes_en_curso.columns and df_mes_en_curso['userId'].notna().any():
            total_contactos_unicos_mes = df_mes_en_curso['userId'].nunique()
            total_contactos_unicos_hoy = df_hoy['userId'].nunique()
        
        # Typing metrics
        if 'typing' in df_mes_en_curso.columns:
            total_venta = len(df_mes_en_curso[df_mes_en_curso['typing'] == 'VENTA'])
            total_venta_a_confirmar = len(df_mes_en_curso[df_mes_en_curso['typing'] == 'VENTA A CONFIRMAR'])
            total_venta_perdida = len(df_mes_en_curso[df_mes_en_curso['typing'] == 'VENTA PERDIDA'])
            total_otro_motivo = len(df_mes_en_curso[df_mes_en_curso['typing'] == 'OTRO MOTIVO'])
            total_reclamo = len(df_mes_en_curso[df_mes_en_curso['typing'] == 'RECLAMO'])

        # WhatsApp Conversion (CÁLCULO AJUSTADO a Contactos Únicos)
        if 'channelType' in df_mes_en_curso.columns:
            df_wp = df_mes_en_curso[df_mes_en_curso['channelType'] == 'WhatsApp']
            
            ventas_wp = len(df_wp[df_wp['typing'] == 'VENTA'])
            # Usar contactos únicos no nulos de WhatsApp
            contactos_unicos_wp = df_wp['userId'].dropna().nunique() if 'userId' in df_wp.columns else len(df_wp)
            
            if contactos_unicos_wp > 0:
                conversion_whatsapp = (ventas_wp / contactos_unicos_wp) * 100
            else:
                conversion_whatsapp = 0.0
    
    return {
        'df': df_mes_en_curso,
        'conv_mes': total_conversaciones_mes,
        'conv_hoy': total_conversaciones_hoy,
        'contactos_mes': total_contactos_unicos_mes,
        'contactos_hoy': total_contactos_unicos_hoy,
        'venta': total_venta,
        'venta_conf': total_venta_a_confirmar,
        'venta_perdida': total_venta_perdida,
        'otro_motivo': total_otro_motivo,
        'reclamo': total_reclamo,
        'conv_wp': conversion_whatsapp,
        'meta_pv_acumulada': OBJETIVO_POS_VENTA_ACUMULADO
    }

# Variables globales iniciales vacías para el layout (se llenarán con el primer callback)
df_mes_en_curso = pd.DataFrame()
OBJETIVO_POS_VENTA_ACUMULADO = 0
total_conversaciones_mes = 0
total_conversaciones_hoy = 0
total_contactos_unicos_mes = 0
total_contactos_unicos_hoy = 0
total_venta = 0
total_venta_a_confirmar = 0
total_venta_perdida = 0
total_otro_motivo = 0
total_reclamo = 0
conversion_whatsapp = 0.0


# --- CREACIÓN DE BARRA DE CUMPLIMIENTO HORIZONTAL (Requisito 8) ---
def create_horizontal_bar(value):
    """ Crea un gráfico de barra horizontal para la conversión de WhatsApp con meta. """
    # Definición de rangos y colores (manteniendo la lógica del velocímetro)
    if value < 15.01: color = '#dc3545' # Rojo
    elif value < 25.01: color = '#ffc107' # Amarillo
    elif value < 49.01: color = '#28a745' # Verde
    else: color = COLOR_BARRA_AZUL # Azul
    
    # Asegurar que el valor no exceda el 100% para el gráfico
    display_value = min(value, 100.0)
    
    fig = go.Figure(go.Bar(
        y=['CONVERSIÓN WHATSAPP'],
        x=[display_value],
        orientation='h',
        name='Cumplimiento',
        marker={'color': color},
        hovertemplate='%{x:.1f}%<extra></extra>',
        text=[f'{value:.1f}%'],
        textposition='inside' # Ubicación del texto de porcentaje dentro de la barra
    ))

    # Configuración de layout
    fig.update_layout(
        title={
            'text': "% CONVERSIÓN WHATSAPP (Basado en Contactos Únicos)", 
            'y':0.95, 'x':0.5, 'xanchor': 'center', 'yanchor': 'top',
            'font': {'size': 18}
        },
        plot_bgcolor=COLOR_KPI, 
        paper_bgcolor=COLOR_KPI, 
        font_color=COLOR_TEXTO,
        font_family="Arial",
        # Altura ajustada para que quepa en el contenedor de 100px
        height=90, 
        margin=dict(t=30, b=0, l=10, r=10),
        
        # Eliminar ejes y fondo del gráfico
        xaxis={'range': [0, 100], 'showgrid': False, 'showticklabels': False, 'zeroline': False},
        yaxis={'showgrid': False, 'showticklabels': False, 'automargin': True}, # automargin para ajustar el texto del KPI
        showlegend=False
    )
    
    # Añadir línea de meta (Target: 50%)
    fig.add_vline(
        x=META_CONVERSION_WHATSAPP, 
        line_width=2, 
        line_dash="dash", 
        line_color="#11fb00" # verde para la meta
    )
    fig.add_annotation(
        x=META_CONVERSION_WHATSAPP, 
        y=1.2, # Posición en la parte superior del gráfico
        yref="paper",
        text=f"KPI {META_CONVERSION_WHATSAPP}%", 
        showarrow=False, 
        font=dict(color="#ffffff", size=12),
        xshift=-5 # Mover la anotación un poco a la izquierda de la línea
    )
    
    return fig

# Reemplazamos la llamada a create_gauge por la nueva función de barra horizontal.
fig_horizontal_bar = create_horizontal_bar(conversion_whatsapp)


# --- APP LAYOUT ---
external_stylesheets = ['https://fonts.googleapis.com/css2?family=Open+Sans:wght@700&family=Arial&display=swap']
app = dash.Dash(__name__, external_stylesheets=external_stylesheets, suppress_callback_exceptions=True) # <--- CORRECCIÓN DE ERROR 1
server = app.server

# Componente para las tarjetas KPI
def tarjeta_kpi(titulo, valor, color_valor, ancho='23%'):
    return html.Div(style={
        'backgroundColor': COLOR_KPI, 'padding': '15px', 'borderRadius': KPI_BORDER_RADIUS,
        'boxShadow': KPI_BOX_SHADOW, 'width': ancho, 'textAlign': 'center', 'margin': '1%'
    }, children=[
        html.H3(titulo, style={'color': COLOR_TEXTO, 'margin': '0', 'fontSize': '14px', 'fontFamily': 'Open Sans', 'fontWeight': 'bold'}),
        html.H2(str(valor), style={'color': color_valor, 'fontSize': '28px', 'margin': '5px 0 0 0', 'fontFamily': 'Arial'})
    ])

# Controles de Orden
def control_orden(id_sufix, titulo, opciones):
    return html.Div([
        html.H4(titulo, style={'color': COLOR_TEXTO, 'fontSize': '16px', 'fontFamily': 'Open Sans', 'marginTop': '10px'}),
        dcc.RadioItems(
            id=f'radio-{id_sufix}',
            options=[{'label': opt, 'value': val} for opt, val in opciones.items()],
            value='FIJO', # Valor por defecto
            labelStyle={'display': 'inline-block', 'marginRight': '20px', 'color': COLOR_TEXTO}
        )
    ], style={'padding': '10px', 'backgroundColor': COLOR_KPI, 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'marginBottom': '20px'})

# Control para el nuevo gráfico de Rendimiento
def control_rendimiento_pos():
    return html.Div([
        html.H4("Visualizar Rendimiento por PV", style={'color': COLOR_TEXTO, 'fontSize': '16px', 'fontFamily': 'Open Sans', 'marginTop': '10px'}),
        dcc.RadioItems(
            id='radio-pos-rendimiento-display',
            options=[
                {'label': 'Ventas (Cantidad)', 'value': 'CANTIDAD'},
                {'label': 'Conversión (%)', 'value': 'PORCENTAJE'}
            ],
            value='CANTIDAD', # Valor por defecto: Cantidad de Ventas
            labelStyle={'display': 'inline-block', 'marginRight': '20px', 'color': COLOR_TEXTO}
        )
    ], style={'padding': '10px', 'backgroundColor': COLOR_KPI, 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'marginBottom': '20px'})

# --- Layout de la Página Principal (Dashboard) ---
layout_dashboard = html.Div(style={'backgroundColor': COLOR_FONDO, 'fontFamily': 'Arial', 'padding': '20px', 'minHeight': '100vh'}, children=[
    
    dcc.Interval(
        id='interval-component',
        interval=30*60*1000, # 30 minutos en milisegundos
        n_intervals=0
    ),
    dcc.Store(id='df-storage', data=None), 
    dcc.Store(id='meta-pv-storage', data=OBJETIVO_POS_VENTA_ACUMULADO),

    html.H1('Tablero de control Digital - Reino Cerámicos', 
            style={'textAlign': 'center', 'color': COLOR_TEXTO, 'fontFamily': 'Open Sans', 'fontWeight': 'bold', 'marginBottom': '5px'}),
    html.P(id='live-update-time', 
           style={'textAlign': 'center', 'color': '#aaaaaa', 'marginTop': '0'}),
           
    # Botón de Navegación a la Página de Detalle
    html.Div(style={'display': 'flex', 'justifyContent': 'center', 'margin': '10px'}, children=[
        dcc.Link(html.Button('Ver Detalle de Contactos Hoy', id='btn-navigate-detalle', 
            style={'backgroundColor': COLOR_BARRA_AZUL, 'color': COLOR_TEXTO, 'padding': '10px 20px', 
                   'border': 'none', 'borderRadius': KPI_BORDER_RADIUS, 'cursor': 'pointer',
                   'fontWeight': 'bold'}), href='/detalle'),
    ]),


    # Fila 1 de KPIs: Conversaciones y Contactos Únicos (4 tarjetas)
    html.Div(id='kpi-row-1', style={'display': 'flex', 'justifyContent': 'center', 'flexWrap': 'wrap'}, children=[
        tarjeta_kpi('Conversaciones Hoy', 0, '#17a2b8', ancho='20%'),
        tarjeta_kpi('Conversaciones Acumuladas', 0, '#007bff', ancho='20%'),
        tarjeta_kpi('Contactos Únicos Hoy', 0, '#00C4CC', ancho='20%'),
        tarjeta_kpi('Contactos Únicos Acumulados', 0, '#8000FF', ancho='20%'),
    ]),    
    
    # Fila 2 de KPIs: Ventas y Clasificaciones (5 tarjetas)
    html.Div(id='kpi-row-2', style={'display': 'flex', 'justifyContent': 'center', 'flexWrap': 'wrap'}, children=[
        tarjeta_kpi('Ventas', 0, '#28a745', ancho='15%'),
        tarjeta_kpi('Ventas a Confirmar', 0, '#ffc107', ancho='15%'),
        tarjeta_kpi('Ventas Perdidas', 0, '#dc3545', ancho='15%'),
        tarjeta_kpi('Otro Motivo', 0, '#adb5bd', ancho='15%'),
        tarjeta_kpi('Reclamos', 0, '#fd7e14', ancho='15%'),
    ]),

    # Fila 3: Barra horizontal de Conversión de WhatsApp
    html.Div(id='kpi-row-3', style={'display': 'flex', 'justifyContent': 'center', 'flexWrap': 'wrap'}, children=[    
        html.Div(dcc.Graph(id='graph-conversion-wp', figure=create_horizontal_bar(0), config={'displayModeBar': False}), 
                 style={'width': '90%', 'height': '100px', 'margin': '1%', 'backgroundColor': COLOR_KPI, 'borderRadius': KPI_BORDER_RADIUS, 'boxShadow': KPI_BOX_SHADOW, 'padding': '5px'}),
    ]),

    # Controles Interactivos
    html.Div(style={'display': 'flex', 'justifyContent': 'space-around', 'flexWrap': 'wrap', 'margin': '20px 0'}, children=[
        control_orden('canal-display', 'Participación por Canal', {'Cantidad': 'COUNT', 'Porcentaje': 'PERCENT'}),
        control_orden('dia-semana-order', 'Visualizar Conversaciones por día de:', {'Lunes - Domingo': 'FIJO', 'Mayor a Menor': 'DESC'}),
        control_orden('hora-creacion-order', 'Visualizar hora de creación de:', {'00 - 23hs': 'FIJO', 'Mayor a Menor': 'DESC'}),
        control_orden('hora-asignacion-order', 'Visualizar hora de asignación de:', {'9 - 18hs': 'FIJO', 'Mayor a Menor': 'DESC'}),
    ]),
    
    # Nuevo Control para Rendimiento PV
    html.Div(style={'display': 'flex', 'justifyContent': 'center', 'flexWrap': 'wrap', 'margin': '10px 0'}, children=[
        control_rendimiento_pos()
    ]),
    
    # Gráficos de Contenido
    html.Div(style={'display': 'flex', 'flexWrap': 'wrap', 'justifyContent': 'center'}, children=[
        dcc.Graph(id='graph-diaria-mes', style={'width': '97%', 'margin': '10px'}), 
        dcc.Graph(id='graph-canal-torta', style={'width': '48%', 'margin': '10px'}), 
        dcc.Graph(id='graph-dia-semana', style={'width': '48%', 'margin': '10px'}), 
        dcc.Graph(id='graph-hora-creacion', style={'width': '48%', 'margin': '10px'}), 
        dcc.Graph(id='graph-hora-asignacion', style={'width': '48%', 'margin': '10px'}), 
        dcc.Graph(id='graph-pos-rendimiento', style={'width': '48%', 'margin': '10px'}), 
        dcc.Graph(id='graph-agente-bar', style={'width': '48%', 'margin': '10px'}),
    ])
])

# --- Layout de la Página de Detalle de Contactos (Página 2) ---
layout_contactos_detalle = html.Div(style={'backgroundColor': COLOR_FONDO, 'fontFamily': 'Arial', 'padding': '20px', 'minHeight': '100vh'}, children=[
    
    html.H1('Detalle de Contactos Únicos (Hoy)', 
            style={'textAlign': 'center', 'color': COLOR_TEXTO, 'fontFamily': 'Open Sans', 'fontWeight': 'bold', 'marginBottom': '20px'}),
    
    dcc.Link(html.Button('← Volver al Dashboard', 
            style={'backgroundColor': COLOR_KPI, 'color': COLOR_TEXTO, 'padding': '10px 20px', 
                   'border': 'none', 'borderRadius': KPI_BORDER_RADIUS, 'cursor': 'pointer',
                   'fontWeight': 'bold', 'marginBottom': '20px'}), href='/'),
                   
    # Almacén de datos intermedio para la tabla (soluciona el error de Input non-existent)
    dcc.Store(id='detalle-df-storage-raw', data=None), 
                   
    html.Div(id='detalle-filters', style={'display': 'flex', 'justifyContent': 'flex-start', 'gap': '20px', 'marginBottom': '20px'}, children=[
        
        # Filtro por Estado
        html.Div([
            html.H4("Filtrar por Estado", style={'color': COLOR_TEXTO}),
            dcc.Dropdown(
                id='dropdown-status-filter',
                placeholder="Seleccione Estado...",
                style={'width': '300px', 'color': '#333'},
            )
        ]),
        
        # Filtro por Punto de Venta
        html.Div([
            html.H4("Filtrar por Punto de Venta", style={'color': COLOR_TEXTO}),
            dcc.Dropdown(
                id='dropdown-pv-filter',
                placeholder="Seleccione Punto de Venta...",
                style={'width': '300px', 'color': '#333'},
            )
        ]),
    ]),
    
    # Tabla de Datos (se llenará con callback)
    html.Div(id='table-container', children=[
        dash_table.DataTable(
            id='tabla-detalle',
            style_table={'overflowX': 'auto', 'backgroundColor': COLOR_KPI, 'borderRadius': KPI_BORDER_RADIUS},
            style_header={'backgroundColor': COLOR_BARRA_AZUL, 'color': 'white', 'fontWeight': 'bold'},
            style_data={'backgroundColor': COLOR_KPI, 'color': COLOR_TEXTO, 'border': f'1px solid {COLOR_FONDO}'},
            style_cell={'textAlign': 'left', 'padding': '12px'},
            page_action='native',
            page_size=20,
            sort_action='native',
            filter_action='native',
            columns=[] # Se llenan en callback
        )
    ])
])


# --- LAYOUT PRINCIPAL (Routing) ---
app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    html.Div(id='page-content')
])

# -------------------------------------------------------------------
# LÓGICA INTERACTIVA (CALLBACKS DE DASH)
# -------------------------------------------------------------------

# CALLBACK DE ROUTING: Muestra la página correcta
@app.callback(Output('page-content', 'children'),
              [Input('url', 'pathname')])
def display_page(pathname):
    if pathname == '/detalle':
        return layout_contactos_detalle
    else:
        return layout_dashboard

# CALLBACK INTERMEDIO: Transfiere y filtra los datos del día actual al store de detalle
@app.callback(
    Output('detalle-df-storage-raw', 'data'),
    [Input('df-storage', 'data'),
     Input('url', 'pathname')] # Asegura que se dispare cuando el layout cambia
)
def populate_detalle_store(data, pathname):
    if pathname != '/detalle' or data is None:
        # No estamos en la página de detalle o no hay datos cargados aún
        return None 
    
    df_mes_en_curso_callback = parse_df_from_store(data)
    if df_mes_en_curso_callback.empty:
        return None

    # Filtro: Solo contactos del día de hoy
    hoy_fecha = datetime.now().date()
    df_hoy = df_mes_en_curso_callback[df_mes_en_curso_callback['created'].dt.date == hoy_fecha].copy()
    
    # 1. Identificar la última conversación por userId (para listar contactos únicos)
    if 'userId' in df_hoy.columns and df_hoy['userId'].notna().any():
        # Ordenar por fecha de creación descendente y mantener solo la primera ocurrencia de userId
        df_detalle = df_hoy.sort_values('created', ascending=False).drop_duplicates(subset=['userId']).copy()
        # Seleccionar las columnas requeridas (mapeando client.id a userId)
        df_detalle = df_detalle[[
            'id', 'created', 'assigned', 'attentionHour', 'status', 
            'direction', 'answerTime', 'agent.name', 'userId', 'client.name', 'note', 'PuntoDeVenta'
        ]].rename(columns={'userId': 'client.id'}).copy()
    else:
        df_detalle = pd.DataFrame(columns=['id', 'created', 'assigned', 'attentionHour', 'status', 'direction', 'answerTime', 'agent.name', 'client.id', 'client.name', 'note', 'PuntoDeVenta'])

    return df_detalle.to_json(date_format='iso', orient='split') if not df_detalle.empty else None

# CALLBACK DE RECARGA DE DATOS (Dashboard)
@app.callback(
    [Output('df-storage', 'data'),
     Output('meta-pv-storage', 'data'),
     Output('live-update-time', 'children'),
     Output('kpi-row-1', 'children'),
     Output('kpi-row-2', 'children'),
     Output('graph-conversion-wp', 'figure')],
    [Input('interval-component', 'n_intervals')]
)
def update_data_and_kpis(n):
    datos_actualizados = cargar_datos_y_calcular_kpis()
    df_mes_en_curso_updated = datos_actualizados['df']
    meta_pv_acumulada_updated = datos_actualizados['meta_pv_acumulada']
    
    # Reconstruir las filas KPI con los nuevos valores
    kpi_row_1 = [
        tarjeta_kpi('Conversaciones Hoy', datos_actualizados['conv_hoy'], '#17a2b8', ancho='20%'),
        tarjeta_kpi('Conversaciones Acumuladas', datos_actualizados['conv_mes'], '#007bff', ancho='20%'),
        tarjeta_kpi('Contactos Únicos Hoy', datos_actualizados['contactos_hoy'], '#00C4CC', ancho='20%'),
        tarjeta_kpi('Contactos Únicos Acumulados', datos_actualizados['contactos_mes'], '#8000FF', ancho='20%'),
    ]

    kpi_row_2 = [
        tarjeta_kpi('Ventas', datos_actualizados['venta'], '#28a745', ancho='15%'),
        tarjeta_kpi('Ventas a Confirmar', datos_actualizados['venta_conf'], '#ffc107', ancho='15%'),
        tarjeta_kpi('Ventas Perdidas', datos_actualizados['venta_perdida'], '#dc3545', ancho='15%'),
        tarjeta_kpi('Otro Motivo', datos_actualizados['otro_motivo'], '#adb5bd', ancho='15%'),
        tarjeta_kpi('Reclamos', datos_actualizados['reclamo'], '#fd7e14', ancho='15%'),
    ]
    
    # Actualizar la barra de conversión de WhatsApp
    fig_wp_updated = create_horizontal_bar(datos_actualizados['conv_wp'])
    
    # Actualizar la hora
    time_str = f"Datos actualizados al: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    
    # Devolver el DataFrame serializado y la meta para que otros Callbacks los usen.
    return (
        df_mes_en_curso_updated.to_json(date_format='iso', orient='split') if not df_mes_en_curso_updated.empty else None,
        meta_pv_acumulada_updated,
        time_str,
        kpi_row_1,
        kpi_row_2,
        fig_wp_updated
    )


def aplicar_estilos_grafico(fig):
    """ Función auxiliar para aplicar el tema oscuro a un gráfico. """
    fig.update_layout(
        plot_bgcolor=COLOR_KPI, paper_bgcolor=COLOR_KPI, font_color=COLOR_TEXTO,
        font_family="Arial", title_font_family="Open Sans", title_font_weight="bold",
        height=400, margin=dict(t=50, b=50, l=10, r=10)
    )
    # Mostramos texto fuera de las barras para contraste en tema oscuro.
    fig.update_traces(textfont_color=COLOR_TEXTO, textposition='outside')
    return fig

# Función auxiliar para parsear el DF desde el Store
def parse_df_from_store(data):
    if data is None:
        return pd.DataFrame()
    try:
        # CORRECCIÓN: Usar io.StringIO para evitar FutureWarning
        # Asegurarse de que el input sea una cadena antes de envolver
        json_str = data if isinstance(data, str) else json.dumps(data)
        
        # Intenta leer el DF y convertir las columnas de fecha
        df = pd.read_json(io.StringIO(json_str), orient='split')
        
        # Asegurarse de que las columnas de fecha sean datetime objects
        df['created'] = pd.to_datetime(df['created'], errors='coerce')
        if 'assigned_dt' in df.columns:
            df['assigned_dt'] = pd.to_datetime(df['assigned_dt'], errors='coerce')
        return df
    except Exception as e:
        print(f"Error al parsear DataFrame desde el Store: {e}")
        return pd.DataFrame()


# CALLBACK para Gráfico Diario (Requisito 9)
@app.callback(
    Output('graph-diaria-mes', 'figure'),
    [Input('df-storage', 'data')] 
)
def update_graph_diaria(data):
    df_mes_en_curso_callback = parse_df_from_store(data)
    
    # Si no hay datos, devolvemos una figura vacía con el estilo.
    if df_mes_en_curso_callback.empty: 
        return go.Figure(layout=aplicar_estilos_grafico(go.Layout(title="Sin Datos para el Mes")))
    
    # --- 1. Crear el rango completo de días del mes ---
    hoy = datetime.now()
    if not df_mes_en_curso_callback.empty:
        min_date_raw = df_mes_en_curso_callback['created'].min()
        inicio_mes = min_date_raw.date() if pd.notna(min_date_raw) and min_date_raw.date().month == hoy.month else hoy.replace(day=1).date()
    else:
        inicio_mes = hoy.replace(day=1).date()

    
    # Crear lista de fechas desde el inicio del mes hasta hoy
    dates = [inicio_mes + timedelta(days=i) for i in range((hoy.date() - inicio_mes).days + 1)]
    dates_str = [d.strftime('%d-%m') for d in dates]
    
    df_full_month = pd.DataFrame({'dia_mes_str': dates_str})
    
    # 2. Agrupación y cuenta de datos reales
    d_real = df_mes_en_curso_callback.groupby('dia_mes_str').size().reset_index(name='conteo')
    
    # 3. Unir los datos reales con el rango completo y rellenar con 0
    d = df_full_month.merge(d_real, on='dia_mes_str', how='left').fillna(0)
    
    d['conteo'] = d['conteo'].astype(int)
    
    # Crear el gráfico
    fig = px.bar(d, x='dia_mes_str', y='conteo', 
                 title="Conversaciones Diarias (Mes en Curso)",
                 color_discrete_sequence=[COLOR_BARRA_AZUL],
                 text_auto=True,
                 category_orders={'dia_mes_str': dates_str}) 
    
    # Corregir la visualización del eje X a Categoría
    fig.update_xaxes(
        title_text="Fecha (Día-Mes)",
        type='category', 
        categoryorder='array',
        categoryarray=dates_str
    )

    return aplicar_estilos_grafico(fig)


# CALLBACK para Participación por Canal (Torta/Pie) (Requisito 10)
@app.callback(
    Output('graph-canal-torta', 'figure'),
    [Input('radio-canal-display', 'value'),
     Input('df-storage', 'data')]
)
def update_graph_canal(display_type, data):
    df_mes_en_curso_callback = parse_df_from_store(data)
    if df_mes_en_curso_callback.empty: return go.Figure(layout=aplicar_estilos_grafico(go.Layout(title="Sin Datos de Canal")))

    d = df_mes_en_curso_callback.groupby('channelType').size().reset_index(name='conteo')
    
    if display_type == 'COUNT':
        fig = px.pie(d, names='channelType', values='conteo', 
                     title="Cantidad por Canal",
                     color='channelType',
                     color_discrete_map=CANAL_COLORS)
        fig.update_traces(textinfo='value+label')
    else:
        fig = px.pie(d, names='channelType', values='conteo', 
                     title="% por Canal",
                     color='channelType',
                     color_discrete_map=CANAL_COLORS)
        fig.update_traces(textinfo='percent+label')
        
    return aplicar_estilos_grafico(fig)


# CALLBACK para Día de la Semana (Barras) (Requisito 11)
@app.callback(
    Output('graph-dia-semana', 'figure'),
    [Input('radio-dia-semana-order', 'value'),
     Input('df-storage', 'data')]
)
def update_graph_dia_semana(order_type, data):
    df_mes_en_curso_callback = parse_df_from_store(data)
    # Si no hay datos, devolvemos una figura vacía con el estilo.
    if df_mes_en_curso_callback.empty: return go.Figure(layout=aplicar_estilos_grafico(go.Layout(title="Sin Datos de Día de Semana")))
    
    d = df_mes_en_curso_callback.groupby('dia_semana').size().reset_index(name='conteo')
    shapes = [] # Para las líneas guía

    if order_type == 'FIJO':
        # Corrección: reindexar y rellenar con 0 para evitar KeyError
        d = d.set_index('dia_semana')['conteo'].reindex(ORDEN_DIAS).fillna(0).reset_index(name='conteo')
        d['dia_semana_es'] = d['dia_semana'].map(NOMBRES_DIAS_ES)
        order_list = [NOMBRES_DIAS_ES[day] for day in ORDEN_DIAS]
        
        fig = px.bar(d, x='dia_semana_es', y='conteo', 
                     title="Conversaciones por Día (Lunes - Domingo)",
                     color_discrete_sequence=[COLOR_BARRA_AZUL],
                     text_auto=True, category_orders={'x': order_list})
        
        # --- Lógica de la Línea Guía (Objetivo) ---
        for i, day in enumerate(ORDEN_DIAS):
            objetivo = OBJETIVO_SEMANAL.get(day, 0) # Obtiene el objetivo o 0 si no existe
            shapes.append(
                go.layout.Shape(
                    type="line",
                    xref="x", yref="y",
                    x0=i - 0.4, # Inicio de la barra
                    y0=objetivo,
                    x1=i + 0.4, # Fin de la barra
                    y1=objetivo,
                    line=dict(color="#fd7e14", width=2, dash="dot")
                )
            )

    else:
        d['dia_semana_es'] = d['dia_semana'].map(NOMBRES_DIAS_ES)
        d = d.sort_values('conteo', ascending=False)
        fig = px.bar(d, x='dia_semana_es', y='conteo', 
                     title="Conversaciones por Día (Mayor a Menor)",
                     color_discrete_sequence=[COLOR_BARRA_AZUL],
                     text_auto=True)
    
    fig.update_xaxes(title_text="Día de la Semana")
    
    # Añadir las formas (líneas guía) solo en modo fijo
    if order_type == 'FIJO':
        fig.update_layout(shapes=shapes)
        
    return aplicar_estilos_grafico(fig)


# CALLBACK para Hora de Creación (Requisito 12)
@app.callback(
    Output('graph-hora-creacion', 'figure'),
    [Input('radio-hora-creacion-order', 'value'),
     Input('df-storage', 'data')]
)
def update_graph_hora_creacion(order_type, data):
    df_mes_en_curso_callback = parse_df_from_store(data)
    if df_mes_en_curso_callback.empty: return go.Figure(layout=aplicar_estilos_grafico(go.Layout(title="Sin Datos de Hora de Creación")))
    
    all_hours = pd.DataFrame({'hora_inicio': range(24)})
    d = df_mes_en_curso_callback.groupby('hora_inicio').size().reset_index(name='conteo')
    d = all_hours.merge(d, on='hora_inicio', how='left').fillna(0) # Rellenar horas sin datos con 0

    if order_type == 'FIJO':
        fig = px.bar(d, x='hora_inicio', y='conteo', 
                     title="Caída de conversaciones (00 - 23hs)",
                     color_discrete_sequence=[COLOR_BARRA_AZUL],
                     text_auto=True, category_orders={'x': [str(h) for h in range(24)]})
    else:
        d = d.sort_values('conteo', ascending=False)
        fig = px.bar(d, x='hora_inicio', y='conteo', 
                     title="Caída de conversaciones (+ → -)",
                     color_discrete_sequence=[COLOR_BARRA_AZUL],
                     text_auto=True)
    
    fig.update_xaxes(title_text="Hora del Día", type='category')
    return aplicar_estilos_grafico(fig)


# CALLBACK para Hora de Asignación (Requisito 13 - CORREGIDO)
@app.callback(
    Output('graph-hora-asignacion', 'figure'),
    [Input('radio-hora-asignacion-order', 'value'),
     Input('df-storage', 'data')]
)
def update_graph_hora_asignacion(order_type, data):
    df_mes_en_curso_callback = parse_df_from_store(data)
    if df_mes_en_curso_callback.empty: return go.Figure(layout=aplicar_estilos_grafico(go.Layout(title="Sin Datos de Hora de Asignación")))
    
    # Usamos la columna 'hora_asignacion' (extraída de 'assigned') para el conteo.
    # Filtramos solo registros donde hubo asignación (no nulos)
    df_asignados = df_mes_en_curso_callback.dropna(subset=['hora_asignacion']).copy()
    
    # Rango 9 a 18 (incluyendo 9 y 18)
    d_fil = df_asignados[(df_asignados['hora_asignacion'] >= 9) & (df_asignados['hora_asignacion'] <= 18)].copy()
    
    # Contar las asignaciones por hora
    all_hours = pd.DataFrame({'hora_asignacion': range(9, 19)})
    d = d_fil.groupby('hora_asignacion').size().reset_index(name='conteo')
    d = all_hours.merge(d, on='hora_asignacion', how='left').fillna(0) # Rellenar horas sin datos con 0
    d['hora_asignacion'] = d['hora_asignacion'].astype(int)

    if order_type == 'FIJO':
        fig = px.bar(d, x='hora_asignacion', y='conteo', 
                     title="Asignación por hora (9 - 18hs)",
                     color_discrete_sequence=[COLOR_BARRA_AZUL],
                     text_auto=True, category_orders={'x': [str(h) for h in range(9, 19)]})
    else:
        d = d.sort_values('conteo', ascending=False)
        fig = px.bar(d, x='hora_asignacion', y='conteo', 
                     title="Asignación por hora (+ → -)",
                     color_discrete_sequence=[COLOR_BARRA_AZUL],
                     text_auto=True)
    
    fig.update_xaxes(title_text="Hora de Asignación", type='category')
    return aplicar_estilos_grafico(fig)


# CALLBACK para Rendimiento por Punto de Venta (NUEVO GRÁFICO INTERACTIVO)
@app.callback(
    Output('graph-pos-rendimiento', 'figure'),
    [Input('radio-pos-rendimiento-display', 'value'),
     Input('df-storage', 'data'),
     Input('meta-pv-storage', 'data')]
)
def update_graph_pos_rendimiento(display_type, data, objetivo_acumulado):
    df_mes_en_curso_callback = parse_df_from_store(data)
    if df_mes_en_curso_callback.empty: return go.Figure(layout=aplicar_estilos_grafico(go.Layout(title="Sin Datos de Rendimiento por Punto de Venta")))
    
    # Crear una lista única de todos los Puntos de Venta (PV) para asegurar la visibilidad de los PV con cero ventas
    todos_los_pv = df_mes_en_curso_callback['PuntoDeVenta'].unique()
    df_base = pd.DataFrame({'PuntoDeVenta': todos_los_pv})
    
    if display_type == 'CANTIDAD':
        # --- MODO 1: Cantidad de Ventas (Typing='VENTA') ---
        d_sales = df_mes_en_curso_callback[df_mes_en_curso_callback['typing'] == 'VENTA'].groupby('PuntoDeVenta').size().reset_index(name='Ventas')
        
        # Unir con la base de PV y rellenar nulos con 0
        d_final = df_base.merge(d_sales, on='PuntoDeVenta', how='left').fillna(0)
        d_final['Ventas'] = d_final['Ventas'].astype(int)
        
        # Ordenar de Mayor a Menor Cantidad de Ventas
        d_final = d_final.sort_values('Ventas', ascending=False)

        fig = px.bar(d_final, x='PuntoDeVenta', y='Ventas', 
                     title="Ventas (Cantidad) por Punto de Venta (Mes)",
                     color_discrete_sequence=[COLOR_BARRA_AZUL],
                     text_auto=True)
        
        fig.update_yaxes(title_text="Ventas (Unidades)")
        
        # Lógica de la Línea Guía (Objetivo Acumulado) - Se aplica solo a la Cantidad
        
        fig.add_shape(
            type="line",
            xref="paper", yref="y",
            x0=0, y0=objetivo_acumulado,
            x1=1, y1=objetivo_acumulado,
            line=dict(color="#fd7e14", width=2, dash="dot"),
            name="Objetivo Acumulado"
        )
        fig.add_annotation(
            x=0.9, y=objetivo_acumulado,
            text=f"Meta Acumulada: {objetivo_acumulado}",
            showarrow=False,
            yanchor="bottom",
            font=dict(color="#fd7e14", size=10)
        )

    else:
        # --- MODO 2: Porcentaje de Conversión sobre Contactos Únicos ---
        
        # 1. Contar Ventas por PV
        df_ventas = df_mes_en_curso_callback[df_mes_en_curso_callback['typing'] == 'VENTA'].groupby('PuntoDeVenta')['userId'].size().reset_index(name='Ventas')
        
        # 2. Contar Contactos Únicos por PV
        df_contacts = df_mes_en_curso_callback.groupby('PuntoDeVenta')['userId'].nunique().reset_index(name='Contactos_Unicos')
        
        # 3. Unir Ventas y Contactos
        d_calc = df_base.merge(df_ventas, on='PuntoDeVenta', how='left').fillna(0)
        d_calc = d_calc.merge(df_contacts, on='PuntoDeVenta', how='left').fillna(0)
        
        # Calcular Porcentaje de Conversión
        d_calc['Conversion'] = np.where(
            d_calc['Contactos_Unicos'] > 0,
            (d_calc['Ventas'] / d_calc['Contactos_Unicos']) * 100,
            0
        )
        
        # Ordenar de Mayor a Menor Porcentaje de Conversión
        d_calc = d_calc.sort_values('Conversion', ascending=False)
        
        fig = px.bar(d_calc, x='PuntoDeVenta', y='Conversion', 
                     title="Conversión (%) por PV (Ventas / Contactos Únicos)",
                     color_discrete_sequence=[COLOR_BARRA_AZUL],
                     text_auto='.2f') # Mostrar dos decimales para porcentaje

        fig.update_yaxes(title_text="Conversión (%)", range=[0, d_calc['Conversion'].max() * 1.1])
    
    # Ajustes finales del gráfico
    fig.update_xaxes(title_text="Punto de Venta")
    return aplicar_estilos_grafico(fig)


# CALLBACK para Agente (Barras) (Ordenado por defecto)
@app.callback(
    Output('graph-agente-bar', 'figure'),
    [Input('df-storage', 'data')] 
)
def update_graph_agente(data):
    df_mes_en_curso_callback = parse_df_from_store(data)
    if df_mes_en_curso_callback.empty: return go.Figure(layout=aplicar_estilos_grafico(go.Layout(title="Sin Datos de Agente")))
    
    d = df_mes_en_curso_callback.groupby('agent.name').size().reset_index(name='conteo') # CORRECCIÓN APLICADA
    d = d[d['conteo'] > 0] 
    d = d.sort_values('conteo', ascending=False).head(15) # Limitar a los 15 principales para visibilidad
    
    fig = px.bar(d, x='agent.name', y='conteo', 
                 title="Conversaciones por Agente (Mes) - Top 15",
                 color_discrete_sequence=[COLOR_BARRA_AZUL],
                 text_auto=True)
    
    fig.update_xaxes(title_text="Agente")
    return aplicar_estilos_grafico(fig)


# CALLBACK para la Página de Detalle: Cargar y Filtrar la Tabla
@app.callback(
    [Output('tabla-detalle', 'columns'),
     Output('tabla-detalle', 'data'),
     Output('dropdown-status-filter', 'options'),
     Output('dropdown-pv-filter', 'options')],
    [Input('dropdown-status-filter', 'value'),
     Input('dropdown-pv-filter', 'value')],
    [State('detalle-df-storage-raw', 'data')] # <--- CORRECCIÓN CLAVE: Leer los datos desde State
)
def update_detalle_table(selected_status, selected_pv, data):
    # Usamos el DataFrame filtrado (solo contactos únicos de hoy)
    # Se parsea el State que contiene el JSON del día actual
    df_detalle = parse_df_from_store(data)
    
    # Si el store está vacío (aún no se carga la data), retornar vacío.
    if df_detalle.empty:
        return ([], [], [], [])
        
    
    # 1. Generar Opciones de Dropdown (siempre basadas en el DF completo del día)
    status_options = [{'label': s, 'value': s} for s in df_detalle['status'].dropna().unique()]
    pv_options = [{'label': pv, 'value': pv} for pv in df_detalle['PuntoDeVenta'].dropna().unique()]
    
    
    # 2. Aplicar Filtros Interactivos (Status y PV)
    df_filtrado = df_detalle.copy()
    
    # Nota: Los filtros se aplican solo a la vista actual, sin modificar las opciones disponibles
    if selected_status:
        df_filtrado = df_filtrado[df_filtrado['status'] == selected_status]
        
    if selected_pv:
        df_filtrado = df_filtrado[df_filtrado['PuntoDeVenta'] == selected_pv]


    # 3. Configurar Columnas de la Tabla
    column_names = {
        'id': 'ID Conversación',
        'created': 'F. Creación',
        'assigned': 'F. Asignación',
        'attentionHour': 'H. Atención',
        'status': 'Estado',
        'direction': 'Dirección',
        'answerTime': 'T. Respuesta',
        'agent.name': 'Agente',
        'client.id': 'ID Cliente',
        'client.name': 'Nombre Cliente',
        'note': 'Nota'
    }
    
    # Crear la estructura de columnas para dash_table.DataTable
    # La lista de columnas se basa en el DF completo del día (`df_detalle`) para garantizar que la estructura sea estable.
    columns = [{"name": column_names.get(col, col), "id": col, "type": "datetime"}
               if col in ['created', 'assigned'] else 
               {"name": column_names.get(col, col), "id": col}
               for col in df_detalle.columns if col != 'PuntoDeVenta'] 

    # 4. Formatear y preparar datos para la tabla
    data_table = df_filtrado.to_dict('records')
    
    return (columns, data_table, status_options, pv_options)


if __name__ == '__main__':
    print("Iniciando servidor local...")
    # Asegúrate de haber ejecutado get_yesterday_sample.py antes de este paso para tener datos.
    app.run(debug=True, port=8050)
