import os
import fitz  # PyMuPDF
import google.generativeai as genai
from flask import Flask, request, render_template, redirect, url_for
import requests
from bs4 import BeautifulSoup
import logging  # Para un manejo de errores más robusto
import urllib.parse  # Para codificar URLs de forma segura
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time

# Configuración básica de logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Flask(__name__)

# Configuración de la aplicación
UPLOAD_FOLDER = "static/uploads"
DOWNLOAD_FOLDER = "static/downloads"  # Carpeta para guardar los PDFs descargados
ALLOWED_EXTENSIONS = {"pdf"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["DOWNLOAD_FOLDER"] = DOWNLOAD_FOLDER
app.config["ALLOWED_EXTENSIONS"] = ALLOWED_EXTENSIONS

# Configurar Gemini
try:
    GOOGLE_API_KEY = ""
    if not GOOGLE_API_KEY:
        raise ValueError("La variable de entorno GOOGLE_API_KEY no está definida.")
    genai.configure(api_key=GOOGLE_API_KEY)
    MODEL_GEMINI = "gemini-1.5-pro-latest"
    model = genai.GenerativeModel(MODEL_GEMINI)
    logging.info(f"Modelo Gemini '{MODEL_GEMINI}' cargado correctamente.")
except ValueError as e:
    logging.error(f"Error al configurar Gemini: {e}")
    model = None
except Exception as e:
    logging.exception("Error inesperado al configurar Gemini.")
    model = None

def buscar_pdfs_google(empresa):
    """Usa Selenium para buscar PDFs relacionados con la empresa en Google y visitar la primera página."""
    try:
        query = f'"{empresa}" pdf '
        url_busqueda = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"

        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")  # Abrir navegador en pantalla completa
        # Quita esta línea para modo visual (no headless)
        # options.add_argument("--headless")  

        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.get(url_busqueda)

        time.sleep(2)  # Espera que cargue la página

        # Encuentra los resultados orgánicos (evita anuncios)
        enlaces = driver.find_elements(By.CSS_SELECTOR, "a[href^='http']")

        for enlace in enlaces:
            href = enlace.get_attribute("href")
            if "google.com" not in href:  # Evita redirecciones de Google
                driver.get(href)
                time.sleep(3)  # Espera que cargue

                # Intenta encontrar botones o enlaces a PDFs
                botones = driver.find_elements(By.XPATH, "//a[contains(@href, '.pdf')]")
                if botones:
                    pdf_url = botones[0].get_attribute("href")
                    driver.quit()
                    return pdf_url
                else:
                    logging.info(f"No se encontró PDF en {href}, se prueba el siguiente.")
                    driver.back()
                    time.sleep(2)

        driver.quit()
        logging.warning(f"No se encontró PDF para {empresa} en los primeros resultados.")
        return None

    except Exception as e:
        logging.exception(f"Error con Selenium al buscar PDF para {empresa}:")
        return None



def descargar_pdf(url_pdf, empresa):
    """Descarga un PDF de una URL dada y lo guarda con un nombre específico."""
    try:
        response = requests.get(url_pdf, stream=True, timeout=10)  # Timeout
        response.raise_for_status()

        nombre_archivo = f"{empresa.replace(' ', '_')}.pdf"
        ruta_destino = os.path.join(DOWNLOAD_FOLDER, nombre_archivo)

        with open(ruta_destino, "wb") as archivo_pdf:
            for chunk in response.iter_content(chunk_size=8192):
                archivo_pdf.write(chunk)

        logging.info(f"PDF descargado con éxito para {empresa} desde {url_pdf} a {ruta_destino}")
        return ruta_destino, url_pdf  # Retornar la ruta local y la URL
    except requests.exceptions.RequestException as e:
        logging.error(f"Error al descargar PDF para {empresa} desde {url_pdf}: {e}")
        return None, None
    except Exception as e:
        logging.exception(f"Error inesperado al descargar PDF para {empresa} desde {url_pdf}:")
        return None, None


def descargar_pdfs(empresa):
    """Busca, encuentra y descarga el PDF para una empresa."""
    pdf_url = buscar_pdfs_google(empresa)  # Ahora retorna directamente la URL del PDF

    if pdf_url:
        ruta_local, url_descargada = descargar_pdf(pdf_url, empresa) # Descarga directa
        if ruta_local:
            return ruta_local, url_descargada
        else:
            return None, None
    else:
        return None, None

# El resto del código permanece igual
@app.route("/resultados", methods=["POST"])
def resultados():
    try:
        data = request.get_json()
        pages = data.get("pages", [])
        filename = data.get("filename")

        if not filename or not pages:
            return render_template(
                "resultados.html",
                texto_extraido="",
                error="Faltan datos (archivo o páginas seleccionadas).",
                todos_los_pdfs={},  # <-- Aseguramos que exista en el template
                empresas=[],
            )


        pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        texto = extract_text_from_selected_pages(pdf_path, pages)

        if model is None:
            return render_template(
                "resultados.html",
                texto_extraido="",
                error="El modelo Gemini no está inicializado. Verifica la API key.",
            )

        prompt = getCompanyExtractionPrompt(texto)
        response = model.generate_content(prompt)
        empresas_result = response.text.strip()
        print(f"Texto extraído: {empresas_result}")
        print(response)
        logging.info(f"Texto extraído: {empresas_result}")

        # Convertimos el texto plano a lista
        empresas_lista = [e.strip() for e in empresas_result.splitlines() if e.strip()]

        todos_los_pdfs = {}  # Lista de resultados
        for empresa in empresas_lista:  # Procesa la lista que genero Gemini
            ruta_local, url_pdf = descargar_pdfs(empresa)  # Llama a funcion de descarga
            if ruta_local:
                todos_los_pdfs[empresa] = {
                    "archivo": ruta_local.replace("static/", ""),  # Guardar la ruta relativa
                    "url": url_pdf,
                }  # Guarda el resultado
            else:
                todos_los_pdfs[empresa] = None  # Guarda None si no se encuentra

        return render_template(
            "resultados.html",
            empresas_result=empresas_result,
            empresas_lista=empresas_lista,
            todos_los_pdfs=todos_los_pdfs,  # Envia resultados
        )

    except Exception as e:
        logging.exception(
            "Error inesperado en la ruta /resultados:"
        )  # Log completo del error
        return render_template("resultados.html", texto_extraido="", error=str(e))


def getCompanyExtractionPrompt(text: str) -> str:
    return f"""
    Tu tarea es extraer los **nombres de empresas** mencionados en el siguiente texto.

    El resultado debe ser una lista de **nombres de empresas** que se mencionan en el texto. No incluyas información adicional, solo los nombres de las empresas, cada uno en una línea separada.

    Texto: {text}
    """


# Verificar si el archivo tiene la extensión correcta
def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
    )


# Función para convertir el PDF a imágenes (una imagen por cada página)
def convert_pdf_to_images(pdf_path):
    doc = fitz.open(pdf_path)  # Abre el archivo PDF
    images = []  # Lista para almacenar las rutas de las imágenes generadas

    # Recorre todas las páginas del PDF
    for page_num in range(doc.page_count):
        page = doc.load_page(page_num)  # Carga la página
        pix = page.get_pixmap()  # Convierte la página a una imagen
        image_filename = f"page_{page_num + 1}.png"  # Nombre para la imagen
        image_path = os.path.join(app.config["UPLOAD_FOLDER"], image_filename)
        pix.save(image_path)  # Guarda la imagen en formato PNG
        images.append(
            f"uploads/{image_filename}"
        )  # Añade la ruta de la imagen a la lista

    return images


# Verifica si la carpeta 'uploads' existe, si no, la crea
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return redirect(request.url)
    file = request.files["file"]
    if file and allowed_file(file.filename):
        filename = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
        file.save(filename)

        # Convertir el PDF a imágenes de todas las páginas
        image_filenames = convert_pdf_to_images(filename)

        # Mostrar todas las imágenes en la página
        return render_template(
            "index.html", images=image_filenames, filename=file.filename
        )

    return "Archivo no permitido", 400


def extract_text_from_selected_pages(pdf_path, selected_pages):
    doc = fitz.open(pdf_path)
    full_text = ""
    for i in selected_pages:
        page = doc.load_page(i)
        full_text += page.get_text()
    return full_text


@app.route("/procesar", methods=["POST"])
def procesar_paginas():
    data = request.json
    pages = data.get("pages", [])  # Ej: [0, 2, 4]
    filename = data.get("filename")  # nombre del PDF

    if not filename or not pages:
        return {"error": "Datos faltantes"}, 400

    pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    # Extraer texto de las páginas seleccionadas
    texto = extract_text_from_selected_pages(pdf_path, pages)

    # Prompt para Gemini
    prompt = getCompanyExtractionPrompt(texto)

    try:
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content(prompt)
        return {"empresas": response.text.strip()}
    except Exception as e:
        return {"error": str(e)}, 500


def descargar_pdf(url_pdf, empresa):
    """Descarga un PDF de una URL dada y lo guarda con un nombre específico."""
    try:
        response = requests.get(url_pdf, stream=True, timeout=10)  # Timeout
        response.raise_for_status()

        nombre_archivo = f"{empresa.replace(' ', '_')}.pdf"
        ruta_destino = os.path.join(DOWNLOAD_FOLDER, nombre_archivo)

        with open(ruta_destino, "wb") as archivo_pdf:
            for chunk in response.iter_content(chunk_size=8192):
                archivo_pdf.write(chunk)

        logging.info(f"PDF descargado con éxito para {empresa} desde {url_pdf} a {ruta_destino}")
        return ruta_destino, url_pdf  # Retornar la ruta local y la URL
    except requests.exceptions.RequestException as e:
        logging.error(f"Error al descargar PDF para {empresa} desde {url_pdf}: {e}")
        return None, None
    except Exception as e:
        logging.exception(f"Error inesperado al descargar PDF para {empresa} desde {url_pdf}:")
        return None, None

if __name__ == "__main__":
    app.run(debug=True)