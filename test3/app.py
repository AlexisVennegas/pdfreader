import os
import fitz  # PyMuPDF
import google.generativeai as genai
from flask import Flask, request, render_template, redirect, url_for
import requests
from bs4 import BeautifulSoup
import logging
import urllib.parse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import uuid

# Configuración básica de logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Flask(__name__)

# Configuración de carpetas
UPLOAD_FOLDER = "static/uploads"
DOWNLOAD_FOLDER = "static/downloads"
ALLOWED_EXTENSIONS = {"pdf"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["DOWNLOAD_FOLDER"] = DOWNLOAD_FOLDER
app.config["ALLOWED_EXTENSIONS"] = ALLOWED_EXTENSIONS

# Configurar Gemini
try:
    GOOGLE_API_KEY = "AIzaSyAGIL6CBu3QFizVKmpuPKhpQfRuDJJIE1U"
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
    try:
        query = f'"{empresa}" pdf '
        url_busqueda = (
            f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
        )

        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        # options.add_argument("--headless")

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=options
        )
        driver.get(url_busqueda)
        time.sleep(2)

        enlaces = driver.find_elements(By.CSS_SELECTOR, "a[href^='http']")

        for enlace in enlaces:
            href = enlace.get_attribute("href")
            if "google.com" not in href:
                driver.get(href)
                time.sleep(3)

                botones = driver.find_elements(By.XPATH, "//a[contains(@href, '.pdf')]")
                if botones:
                    pdf_url = botones[0].get_attribute("href")
                    driver.quit()
                    return pdf_url
                driver.back()
                time.sleep(2)

        driver.quit()
        logging.warning(
            f"No se encontró PDF para {empresa} en los primeros resultados."
        )
        return None

    except Exception as e:
        logging.exception(f"Error con Selenium al buscar PDF para {empresa}:")
        return None


def descargar_pdf(url_pdf, empresa):
    try:
        response = requests.get(url_pdf, stream=True, timeout=10)
        response.raise_for_status()

        nombre_archivo = f"{empresa.replace(' ', '_')}.pdf"
        ruta_destino = os.path.join(DOWNLOAD_FOLDER, nombre_archivo)

        with open(ruta_destino, "wb") as archivo_pdf:
            for chunk in response.iter_content(chunk_size=8192):
                archivo_pdf.write(chunk)

        logging.info(
            f"PDF descargado con éxito para {empresa} desde {url_pdf} a {ruta_destino}"
        )
        return ruta_destino, url_pdf
    except requests.exceptions.RequestException as e:
        logging.error(f"Error al descargar PDF para {empresa} desde {url_pdf}: {e}")
        return None, None
    except Exception as e:
        logging.exception(
            f"Error inesperado al descargar PDF para {empresa} desde {url_pdf}:"
        )
        return None, None


def descargar_pdfs(empresa):
    pdf_url = buscar_pdfs_google(empresa)
    if pdf_url:
        ruta_local, url_descargada = descargar_pdf(pdf_url, empresa)
        if ruta_local:
            return ruta_local, url_descargada
    return None, None


@app.route("/", methods=["GET"])
def index():
    images = []
    filename = None

    # Buscar carpetas en /static/uploads
    uploads_dir = os.path.join("static", "uploads")
    recent_previews = []
    if os.path.exists(uploads_dir):
        for folder in sorted(os.listdir(uploads_dir), reverse=True):
            folder_path = os.path.join(uploads_dir, folder)
            if os.path.isdir(folder_path):
                preview_img = next(
                    (f for f in os.listdir(folder_path) if f.endswith(".png")), None
                )
                if preview_img:
                    # Generar ruta relativa para usar con url_for (convertimos \ por /)
                    preview_path = f"uploads/{folder}/{preview_img}".replace("\\", "/")
                    recent_previews.append({"folder": folder, "preview": preview_path})

    return render_template(
        "index.html", images=images, filename=filename, recent_previews=recent_previews
    )


@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return redirect(request.url)
    file = request.files["file"]
    if file and allowed_file(file.filename):
        unique_id = str(uuid.uuid4())[:8]
        carpeta_pdf = os.path.join(app.config["UPLOAD_FOLDER"], unique_id)
        os.makedirs(carpeta_pdf, exist_ok=True)

        filename = file.filename
        ruta_pdf = os.path.join(carpeta_pdf, filename)
        file.save(ruta_pdf)

        image_filenames = convert_pdf_to_images(ruta_pdf, carpeta_pdf)
        image_paths = [os.path.relpath(path, "static") for path in image_filenames]

        return render_template(
            "index.html", images=image_paths, filename=os.path.join(unique_id, filename)
        )

    return "Archivo no permitido", 400


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
    )


def convert_pdf_to_images(pdf_path, carpeta_destino):
    doc = fitz.open(pdf_path)
    images = []
    for page_num in range(doc.page_count):
        page = doc.load_page(page_num)
        pix = page.get_pixmap()
        image_filename = f"page_{page_num + 1}.png"
        image_path = os.path.join(carpeta_destino, image_filename)
        pix.save(image_path)
        images.append(image_path)
    return images


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
                error="Faltan datos.",
                todos_los_pdfs={},
                empresas=[],
            )

        pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        texto = extract_text_from_selected_pages(pdf_path, pages)

        if model is None:
            return render_template(
                "resultados.html",
                texto_extraido="",
                error="Gemini no está inicializado.",
            )

        prompt = getCompanyExtractionPrompt(texto)
        response = model.generate_content(prompt)
        empresas_result = response.text.strip()
        empresas_lista = [e.strip() for e in empresas_result.splitlines() if e.strip()]

        todos_los_pdfs = {}
        for empresa in empresas_lista:
            ruta_local, url_pdf = descargar_pdfs(empresa)
            if ruta_local:
                todos_los_pdfs[empresa] = {
                    "archivo": ruta_local.replace("static/", ""),
                    "url": url_pdf,
                }
            else:
                todos_los_pdfs[empresa] = None

        return render_template(
            "resultados.html",
            empresas_result=empresas_result,
            empresas_lista=empresas_lista,
            todos_los_pdfs=todos_los_pdfs,
        )

    except Exception as e:
        logging.exception("Error en /resultados")
        return render_template("resultados.html", texto_extraido="", error=str(e))


@app.route("/procesar", methods=["POST"])
def procesar_paginas():
    data = request.json
    pages = data.get("pages", [])
    filename = data.get("filename")

    if not filename or not pages:
        return {"error": "Datos faltantes"}, 400

    pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    texto = extract_text_from_selected_pages(pdf_path, pages)
    prompt = getCompanyExtractionPrompt(texto)

    try:
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content(prompt)
        return {"empresas": response.text.strip()}
    except Exception as e:
        return {"error": str(e)}, 500


def extract_text_from_selected_pages(pdf_path, selected_pages):
    doc = fitz.open(pdf_path)
    full_text = ""
    for i in selected_pages:
        page = doc.load_page(i)
        full_text += page.get_text()
    return full_text


def getCompanyExtractionPrompt(text: str) -> str:
    return f"""
    Tu tarea es extraer los **nombres de empresas** mencionados en el siguiente texto.

    El resultado debe ser una lista de **nombres de empresas** que se mencionan en el texto. No incluyas información adicional, solo los nombres de las empresas, cada uno en una línea separada.

    Texto: {text}
    """



if __name__ == "__main__":
    app.run(debug=True)
