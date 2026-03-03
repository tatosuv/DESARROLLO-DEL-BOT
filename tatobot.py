import streamlit as st
from google import genai
import pandas as pd
from pdf2image import convert_from_bytes
from PIL import Image
import io
import json
import re

# --- 1. CONFIGURACIÓN DE MODELOS Y CLIENTE ---
# Solo los modelos que tenés habilitados y con soporte a futuro
MODEL_POOL = [
    "gemini-2.0-flash", 
    "gemini-2.5-flash-lite", 
    "gemini-2.5-flash", 
    "gemini-3-flash-preview"
]

# CUIT de Lubinski para evitar confusiones (IA suele tomar al comprador por error)
CUIT_CLIENTE_LUBINSKI = "20214782353"
CUIT_CLIENTE_CONSTANZA = "27263489905"
CUIT_CLIENTE_ALLENDE = "27280333242" 

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    client = genai.Client(api_key=API_KEY)
except Exception as e:
    st.error("⚠️ Error: Configure su API KEY en los Secrets de Streamlit.")
    st.stop()

# --- 2. FUNCIONES DE APOYO ---
def limpiar_monto_maquina(valor):
    """Convierte strings con cualquier formato a float puro (1234.56)."""
    if not valor or str(valor).lower() == "null": return 0.0
    try:
        # Quitamos todo lo que no sea número o punto
        s = re.sub(r'[^\d.]', '', str(valor))
        return float(s)
    except: return 0.0

def llamar_ia_con_rotacion(prompt, imagen):
    """Prueba modelos en cascada si uno falla por límite de cuota."""
    for model_id in MODEL_POOL:
        try:
            response = client.models.generate_content(model=model_id, contents=[prompt, imagen])
            return response.text, model_id
        except Exception as e:
            msg = str(e).lower()
            if "429" in msg or "quota" in msg:
                continue # Salto al siguiente modelo si se agotó el actual
            else:
                return None, f"Error técnico: {e}"
    return None, "Se agotaron todos los modelos del pool por hoy."

# --- 3. LÓGICA PRINCIPAL DE PROCESAMIENTO ---
def procesar_archivo(file):
    resultados_totales = []
    
    # Manejo de PDF o Imagen
    if file.type == "application/pdf":
        paginas = convert_from_bytes(file.read(), dpi=150)
    else:
        paginas = [Image.open(file)]

    for i, img in enumerate(paginas):
        with st.status(f"Analizando {file.name} - Pág {i+1}...") as status:
            prompt = f"""
            Actúa como un experto contable argentino. 
            Extrae los datos únicamente del EMISOR (quien vende).
            
            REGLAS CRÍTICAS:
            1. RECEPTOR: Es el COMPRADOR (CUIT {CUIT_CLIENTE_LUBINSKI}, {CUIT_CLIENTE_CONSTANZA}, {CUIT_CLIENTE_ALLENDE}). NO los pongas como emisor.
            2. UN COMPROBANTE = UNA FILA: Ignora el detalle de productos. Ve directo al pie/totales.
            3. DECIMALES: Devuelve los números SIEMPRE en formato '1234.56' (usa punto).
            4. PUNTO DE VENTA: Solo los números antes del guión.
            5. TIPO: 'A', 'B' o 'C'. Si hay IVA discriminado, es 'A'.

            Responde ÚNICAMENTE con una lista JSON:
            [{{
                "TIPO_FACTURA": "",
                "PUNTO_VENTA": "",
                "NRO_FACTURA": "",
                "CUIT_EMISOR": "",
                "FECHA_EMISION": "DD/MM/AAAA",
                "RAZON_SOCIAL": "",
                "MONTO_GRAVADO": "",
                "IVA_21": "",
                "IVA_10_5": "",
                "PERCEPCION_IVA": "",
                "MONTO_TOTAL": ""
            }}]
            """

            texto, model_info = llamar_ia_con_rotacion(prompt, img)
            
            if texto:
                try:
                    limpio = texto.replace("```json", "").replace("```", "").strip()
                    data = json.loads(limpio)
                    if isinstance(data, dict): data = [data]

                    for c in data:
                        # --- LIMPIEZA Y CÁLCULOS EN PYTHON ---
                        total = limpiar_monto_maquina(c.get("MONTO_TOTAL"))
                        g = limpiar_monto_maquina(c.get("MONTO_GRAVADO"))
                        i21 = limpiar_monto_maquina(c.get("IVA_21"))
                        i105 = limpiar_monto_maquina(c.get("IVA_10_5"))
                        per = limpiar_monto_maquina(c.get("PERCEPCION_IVA"))
                        
                        # Validación de Emisor (Lubinski no puede ser el vendedor)
                        cuit_e = str(c.get("CUIT_EMISOR", "")).replace("-", "")
                        if CUIT_CLIENTE_LUBINSKI in cuit_e:
                            c["RAZON_SOCIAL"] = f"REVISAR (IA tomó al cliente)"
                        
                        # Normalización de Punto de Venta (5 dígitos)
                        pv = re.sub(r'\D', '', str(c.get("PUNTO_VENTA", "0")))
                        c["PUNTO_VENTA"] = pv.zfill(5)[-5:]

                        # Lógica para Factura B (Recálculo automático)
                        tipo = str(c.get("TIPO_FACTURA", "")).upper()
                        if "B" in tipo:
                            g = round(total / 1.21, 2)
                            i21 = round(total - g, 2)
                            i105, per = 0.0, 0.0

                        # Cálculo de No Gravado por diferencia (Cierra siempre)
                        no_grav = round(total - (g + i21 + i105 + per), 2)
                        
                        c.update({
                            "MONTO_GRAVADO": g, "IVA_21": i21, "IVA_10_5": i105,
                            "PERCEPCION_IVA": per, "MONTO_TOTAL": total,
                            "MONTO_NO_GRAVADO": no_grav if no_grav > 0.05 else 0.0,
                            "ARCHIVO": file.name, "PAG": i+1, "MODELO_IA": model_info
                        })
                        resultados_totales.append(c)
                    status.update(label=f"Página {i+1} completada", state="complete")
                except:
                    status.update(label="Error al parsear JSON", state="error")
            else:
                st.error(f"Error: {model_info}")
                
    return resultados_totales

# --- 4. INTERFAZ DE USUARIO (STREAMLIT) ---
st.set_page_config(page_title="TatoBot", layout="wide")
st.title("📊 TatoBot Pro: El bot para los capos")

with st.sidebar:
    st.header("Configuración")
    st.info(f"Pool de modelos activo: {len(MODEL_POOL)}")
    st.write("Modelos:", ", ".join(MODEL_POOL))

archivos_subidos = st.file_uploader("Cargar facturas (PDF, JPG, PNG)", accept_multiple_files=True)

if st.button("🚀 Iniciar Extracción") and archivos_subidos:
    base_datos = []
    barra = st.progress(0)
    
    for idx, f in enumerate(archivos_subidos):
        datos_archivo = procesar_archivo(f)
        base_datos.extend(datos_archivo)
        barra.progress((idx + 1) / len(archivos_subidos))
    
    if base_datos:
        df = pd.DataFrame(base_datos)
        
        # Orden de columnas deseado
        columnas = ["ARCHIVO", "PAG", "FECHA_EMISION", "RAZON_SOCIAL", "CUIT_EMISOR", 
                    "TIPO_FACTURA", "PUNTO_VENTA", "NRO_FACTURA", "MONTO_GRAVADO", 
                    "IVA_21", "IVA_10_5", "PERCEPCION_IVA", "MONTO_NO_GRAVADO", "MONTO_TOTAL", "MODELO_IA"]
        
        df = df[[c for c in columnas if c in df.columns]]
        
        st.subheader("📋 Resultados")
        st.dataframe(df)
        
        # Exportación a Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Comprobantes')
        
        st.download_button(
            label="📥 Descargar Planilla Excel",
            data=output.getvalue(),
            file_name="contabilidad_tatobot.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )