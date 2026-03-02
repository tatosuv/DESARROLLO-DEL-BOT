import streamlit as st
from google import genai
import pandas as pd
from pdf2image import convert_from_bytes
from PIL import Image
import io
import json
import re

# --- 1. CONFIGURACIÓN DE TU POOL DE MODELOS ---
# Usamos esta lista en orden. Si uno falla por límite, salta al siguiente.
MODEL_POOL = [
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-3-flash-preview"
]

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"] #Pensaste que te iba a mostrar la API KEY? rajá de acá tontito.
    client = genai.Client(api_key=API_KEY)
except Exception as e:
    st.error("⚠️ Error: Configure su API KEY en los Secrets de Streamlit.")
    st.stop()

# --- 2. FUNCIONES DE LIMPIEZA ---
def limpiar_monto_maquina(valor):
    """Convierte el string '1234.56' de la IA a float directamente."""
    if not valor or str(valor).lower() == "null": return 0.0
    try:
        # Quitamos todo lo que no sea número o punto
        s = re.sub(r'[^\d.]', '', str(valor))
        return float(s)
    except: return 0.0

def llamar_ia_con_rotacion(prompt, imagen):
    """Intenta procesar con los modelos disponibles para maximizar consultas gratis."""
    for model_id in MODEL_POOL:
        try:
            response = client.models.generate_content(model=model_id, contents=[prompt, imagen])
            return response.text, model_id
        except Exception as e:
            msg = str(e).lower()
            if "429" in msg or "quota" in msg:
                continue # Salto al siguiente modelo si este se agotó
            else:
                return None, f"Error técnico: {e}"
    return None, "Se agotaron todos los modelos del pool por hoy."

# --- 3. LÓGICA DE EXTRACCIÓN ---
def procesar_comprobante(file):
    resultados_totales = []
    
    # Conversión de PDF o Imagen
    if file.type == "application/pdf":
        paginas = convert_from_bytes(file.read(), dpi=150)
    else:
        paginas = [Image.open(file)]

    for i, img in enumerate(paginas):
        with st.status(f"Procesando {file.name} - Pág {i+1}...") as status:
            prompt = """
            Actúa como un auditor contable de Argentina. 
            Busca el bloque de TOTALES al final de la factura.
            
            REGLAS ESTRICTAS:
            1. UN COMPROBANTE = UNA FILA. Ignora el detalle de productos/servicios.
            2. DECIMALES: Devuelve los números SIEMPRE en formato '1234.56' (usa punto para decimales).
            3. FECHA: Usa 'Fecha de emisión' o 'Fecha'. IGNORA 'Inicio de actividades'.
            4. TIPO: Solo 'A', 'B' o 'C'. Si el IVA está discriminado, es 'A'.
            5. CUIT: Extrae el CUIT del EMISOR (el que vende).

            Devuelve una lista de JSON con este formato:
            [{
                "TIPO_FACTURA": "",
                "PUNTO_VENTA": "solo números antes del guión",
                "NRO_FACTURA": "8 números después del guión",
                "CUIT_EMISOR": "",
                "FECHA_EMISION": "DD/MM/AAAA",
                "RAZON_SOCIAL": "",
                "MONTO_GRAVADO": "número.punto",
                "IVA_21": "número.punto",
                "IVA_10_5": "número.punto",
                "PERCEPCION_IVA": "número.punto",
                "MONTO_TOTAL": "número.punto"
            }]
            """

            texto, model_info = llamar_ia_con_rotacion(prompt, img)
            
            if texto:
                try:
                    limpio = texto.replace("```json", "").replace("```", "").strip()
                    data = json.loads(limpio)
                    if isinstance(data, dict): data = [data]

                    for c in data:
                        # Limpieza y cálculos 
                        total = limpiar_monto_maquina(c.get("MONTO_TOTAL"))
                        g = limpiar_monto_maquina(c.get("MONTO_GRAVADO"))
                        i21 = limpiar_monto_maquina(c.get("IVA_21"))
                        i105 = limpiar_monto_maquina(c.get("IVA_10_5"))
                        per = limpiar_monto_maquina(c.get("PERCEPCION_IVA"))
                        
                        tipo = str(c.get("TIPO_FACTURA", "")).upper()
                        if "B" in tipo:
                            tipo = "B"
                            g = round(total / 1.21, 2)
                            i21 = round(total - g, 2)
                            i105, per = 0.0, 0.0
                        elif "A" in tipo: tipo = "A"

                        # Fórmula para capturar conceptos raros (Combustibles, Tasas, etc)
                        no_grav = round(total - (g + i21 + i105 + per), 2)
                        
                        c.update({
                            "TIPO_FACTURA": tipo,
                            "MONTO_GRAVADO": g, "IVA_21": i21, "IVA_10_5": i105,
                            "PERCEPCION_IVA": per, "MONTO_TOTAL": total,
                            "MONTO_NO_GRAVADO": no_grav if no_grav > 0.05 else 0.0,
                            "ARCHIVO": file.name, "HOJA": i+1, "MODELO": model_info
                        })
                        resultados_totales.append(c)
                    status.update(label="Analizado", state="complete")
                except:
                    status.update(label="Error en formato de datos", state="error")
            else:
                st.warning(f"Aviso en {file.name}: {model_info}")
                
    return resultados_totales

# --- 4. INTERFAZ DE USUARIO ---
st.set_page_config(page_title="TatoBot, el bot de los capos", layout="wide")
st.title("📊 TatoBot Pro: Extracción de documentos")

with st.sidebar:
    st.header("⚙️ Estado del Sistema")
    st.success(f"Pool Activo: {len(MODEL_POOL)} modelos")
    st.write("Prioridad actual:", MODEL_POOL[0])

archivos = st.file_uploader("Subir Facturas de Compras o Ventas", type=["pdf","jpg","png"], accept_multiple_files=True)

if st.button("🚀 Procesar Todo") and archivos:
    lista_final = []
    progreso = st.progress(0)
    
    for idx, f in enumerate(archivos):
        res = procesar_comprobante(f)
        lista_final.extend(res)
        progreso.progress((idx + 1) / len(archivos))
    
    if lista_final:
        df = pd.DataFrame(lista_final)
        
        # Reordenar columnas para que el CUIT esté visible al principio
        cols = ["ARCHIVO", "HOJA", "FECHA_EMISION", "RAZON_SOCIAL", "CUIT_EMISOR", "TIPO_FACTURA", 
                "PUNTO_VENTA", "NRO_FACTURA", "MONTO_GRAVADO", "IVA_21", "IVA_10_5", 
                "PERCEPCION_IVA", "MONTO_NO_GRAVADO", "MONTO_TOTAL", "MODELO"]
        
        # Filtramos por si alguna columna no se generó
        df = df[[c for c in cols if c in df.columns]]
        
        st.subheader("📋 Vista Previa de los Datos")
        st.dataframe(df)
        
        # Exportar a Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)
        
        st.download_button(
            label="📥 Descargar Excel para Contabilidad",
            data=output.getvalue(),
            file_name="extraccion_tatobot.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )