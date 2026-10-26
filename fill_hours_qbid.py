from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import Select
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv
from datetime import datetime
import os
import time
import re

# CONSTANTES MODIFICABLES
HORAS_A_RELLENAR = 5  # Horas totales a repartir cada día (5, 8, ...)
FECHA_INICIO_STR = "01/09/2026"  # Formato: DD/MM/YYYY
FECHA_FINAL_STR = "25/09/2026"  # Formato: DD/MM/YYYY

# CONSTANTES FIJAS
URL_LOGIN = "https://www.empresaiformacio.org/sBid"
PASO_MINUTOS = 15  # Granularidad mínima de los desplegables

# Credenciales desde .env (ver .env.example)
load_dotenv()
QBID_USER = os.getenv("QBID_USER", "").strip()
QBID_PASSWD = os.getenv("QBID_PASSWD", "").strip()

fecha_limite_final = datetime.strptime(FECHA_FINAL_STR, "%d/%m/%Y")
dia_inicio_numero = datetime.strptime(FECHA_INICIO_STR, "%d/%m/%Y").day
MINUTOS_OBJETIVO = int(round(HORAS_A_RELLENAR * 60))

MESES = {
    "gener": 1, "febrer": 2, "març": 3, "abril": 4, "maig": 5, "juny": 6,
    "juliol": 7, "agost": 8, "setembre": 9, "octubre": 10, "novembre": 11, "desembre": 12
}

# "2 de juny de 2026", "1 d'octubre de 2026", "5 d’agost de 2026"
REGEX_FECHA = re.compile(r"(\d{1,2})\s+(?:de\s+|d['’]\s*)([a-zç]+)\s+de\s+(\d{4})")


def texto_a_minutos(texto):
    """Convierte el texto de una opción ("15min", "1h", "1h 30min", "1:30", "0") a minutos.
    Devuelve None si el texto no representa una duración."""
    t = texto.strip().lower().replace(" ", "")
    if not t:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", t)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)(?:min|m|'))?", t)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    if t.isdigit():
        return 0 if int(t) == 0 else None
    return None


def opciones_duracion(select_element):
    """Devuelve {minutos: texto_visible} con las opciones que son duraciones."""
    opciones = {}
    for opt in Select(select_element).options:
        texto = opt.text.strip()
        minutos = texto_a_minutos(texto)
        if minutos is not None and minutos not in opciones:
            opciones[minutos] = texto
    return opciones


def repartir_minutos(campos_opciones, objetivo, inicio):
    """Reparte `objetivo` minutos entre los campos, lo más equilibrado posible,
    usando solo valores disponibles en cada desplegable. Rota el punto de inicio
    para que los campos con más tiempo cambien cada día.
    Devuelve una lista de minutos por campo, o None si no es posible."""
    n = len(campos_opciones)
    orden = [(inicio + i) % n for i in range(n)]
    unidades = objetivo // PASO_MINUTOS
    base, extra = divmod(unidades, n)

    asignacion = [0] * n
    for k, idx in enumerate(orden):
        asignacion[idx] = (base + (1 if k < extra else 0)) * PASO_MINUTOS

    if all(asignacion[i] in campos_opciones[i] for i in range(n)) and sum(asignacion) == objetivo:
        return asignacion

    # Alternativa: programación dinámica sobre los valores disponibles en cada campo
    # buscando la combinación exacta más equilibrada.
    objetivo_medio = objetivo / n
    mejor = {0: (0.0, [])}  # suma -> (coste, valores)
    for idx in orden:
        nuevo = {}
        for suma, (coste, valores) in mejor.items():
            for v in campos_opciones[idx]:
                s = suma + v
                if s > objetivo:
                    continue
                c = coste + (v - objetivo_medio) ** 2
                if s not in nuevo or c < nuevo[s][0]:
                    nuevo[s] = (c, valores + [(idx, v)])
        mejor = nuevo
    if objetivo not in mejor:
        return None
    for idx, v in mejor[objetivo][1]:
        asignacion[idx] = v
    return asignacion


def entrar_frames(driver):
    driver.switch_to.default_content()
    driver.switch_to.frame("jspContainer")
    driver.switch_to.frame("contentmain")


def login_automatico(driver):
    """Intenta iniciar sesión con las credenciales del .env. Devuelve True si lo consigue."""
    if not QBID_USER or not QBID_PASSWD:
        print("No hay QBID_USER/QBID_PASSWD en .env; inicia sesión manualmente.")
        return False
    try:
        time.sleep(2)
        campos_pass = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
        if not campos_pass:
            # El formulario puede estar dentro de un iframe
            for frame in driver.find_elements(By.TAG_NAME, "iframe") + driver.find_elements(By.TAG_NAME, "frame"):
                driver.switch_to.frame(frame)
                campos_pass = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
                if campos_pass:
                    break
                driver.switch_to.default_content()
        if not campos_pass:
            print("No se encontró el formulario de login; inicia sesión manualmente.")
            return False

        campo_pass = campos_pass[0]
        campo_user = campo_pass.find_element(
            By.XPATH,
            "preceding::input[(@type='text' or @type='email' or not(@type)) and not(@type='hidden')][1]",
        )
        campo_user.clear()
        campo_user.send_keys(QBID_USER)
        campo_pass.clear()
        campo_pass.send_keys(QBID_PASSWD)

        botones = campo_pass.find_elements(
            By.XPATH, "following::*[self::button or (self::input and (@type='submit' or @type='button'))][1]"
        )
        if botones:
            driver.execute_script("arguments[0].click();", botones[0])
        else:
            campo_pass.submit()
        driver.switch_to.default_content()
        print("Credenciales enviadas.")
        time.sleep(3)
        return True
    except Exception as e:
        driver.switch_to.default_content()
        print(f"Login automático fallido ({e}); inicia sesión manualmente.")
        return False


def leer_fecha_pantalla(driver):
    textos = []
    for xp in ("//*[contains(@class, 'navigation')]", "//*[contains(@class, 'fecha') or contains(@class, 'date')]"):
        try:
            textos += [e.text.lower() for e in driver.find_elements(By.XPATH, xp)]
        except Exception:
            pass
    try:
        textos.append(driver.find_element(By.TAG_NAME, "body").text.lower())
    except Exception:
        pass
    for texto in textos:
        m = REGEX_FECHA.search(texto)
        if m and m.group(2) in MESES:
            return datetime(int(m.group(3)), MESES[m.group(2)], int(m.group(1)))
    return None


def rellenar_dia(driver, posicion_inicial):
    """Rellena los desplegables del día. Devuelve la nueva posición inicial."""
    selectores = driver.find_elements(By.TAG_NAME, "select")
    campos = []
    for s in selectores:
        if not s.is_enabled():
            continue
        opciones = opciones_duracion(s)
        if len(opciones) >= 2:  # Solo desplegables de horas
            campos.append((s, opciones))

    if not campos:
        print("No se encontraron campos de horas editables en este día (puede ser fin de semana).")
        return posicion_inicial, False

    n = len(campos)
    print(f"Detectados {n} campos de horas. Objetivo: {MINUTOS_OBJETIVO // 60}h {MINUTOS_OBJETIVO % 60:02d}min")
    posicion_inicial %= n

    asignacion = repartir_minutos([o for _, o in campos], MINUTOS_OBJETIVO, posicion_inicial)
    if asignacion is None:
        print(f"ERROR: no es posible sumar exactamente {HORAS_A_RELLENAR}h con {n} campos. Día NO guardado.")
        return posicion_inicial, False

    for (select_element, opciones), minutos in zip(campos, asignacion):
        Select(select_element).select_by_visible_text(opciones[minutos])
        # Lanza el evento change por si la página recalcula totales
        driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", select_element)

    # Verificación: lo que realmente quedó seleccionado
    total = 0
    for select_element, _ in campos:
        total += texto_a_minutos(Select(select_element).first_selected_option.text) or 0
    if total != MINUTOS_OBJETIVO:
        print(f"ERROR: la suma seleccionada es {total} min (esperado {MINUTOS_OBJETIVO}). Día NO guardado.")
        return posicion_inicial, False

    print("Reparto: " + ", ".join(opciones[m] for (_, opciones), m in zip(campos, asignacion)))
    return (posicion_inicial + 1) % n, True


print(f"Iniciando QBid Automator: {HORAS_A_RELLENAR}h por día")
print(f"Entrada por calendario: {FECHA_INICIO_STR} -> Avance por flechas hasta: {FECHA_FINAL_STR}")

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service)

try:
    driver.get(URL_LOGIN)
    login_automatico(driver)
    print("\nColócate en la pantalla de la Agenda (inicia sesión a mano si hace falta).")
    input("PULSA ENTER EN ESTA TERMINAL CUANDO ESTÉS VIENDO EL CALENDARIO GRIS...")

    posicion_inicial = 0
    primer_acceso = True
    ultima_fecha = None

    while True:
        try:
            entrar_frames(driver)
        except Exception as e_frames:
            print(f"Error al acceder a los marcos de la web: {e_frames}")
            break

        if primer_acceso:
            try:
                celda_objetivo = None
                for celda in driver.find_elements(By.TAG_NAME, "td"):
                    if celda.text.strip() == str(dia_inicio_numero):
                        clase_celda = str(celda.get_attribute("class"))
                        if "old" not in clase_celda and "new" not in clase_celda:
                            celda_objetivo = celda
                            break
                if celda_objetivo is None:
                    celda_objetivo = driver.find_element(By.XPATH, f"//td[normalize-space(text())='{dia_inicio_numero}']")

                driver.execute_script("arguments[0].click();", celda_objetivo)
                print(f"Día inicial {dia_inicio_numero} seleccionado en el calendario gris.")
                time.sleep(2)

                enlace_dossier = driver.find_element(By.PARTIAL_LINK_TEXT, "Activitat diària del dossier")
                driver.execute_script("arguments[0].click();", enlace_dossier)
                print("Entrando al formulario del dossier...")
                time.sleep(2.5)
                primer_acceso = False
                entrar_frames(driver)
            except Exception as e_init:
                print(f"Error crítico al intentar entrar al primer día: {e_init}")
                break

        fecha_pantalla_actual = leer_fecha_pantalla(driver)
        if fecha_pantalla_actual:
            print(f"\n--- PROCESANDO PÁGINA ACTUAL: {fecha_pantalla_actual.strftime('%d/%m/%Y')} ---")
            if fecha_pantalla_actual > fecha_limite_final:
                print("Se ha superado la fecha límite configurada.")
                break
            if ultima_fecha and fecha_pantalla_actual <= ultima_fecha:
                print("La página no ha avanzado de día; se detiene para no repetir registros.")
                break
            ultima_fecha = fecha_pantalla_actual
        else:
            print("\n--- PROCESANDO DÍA (No se pudo verificar la fecha en cabecera) ---")

        posicion_inicial, rellenado = rellenar_dia(driver, posicion_inicial)

        if rellenado:
            try:
                driver.execute_script("save();")
                print("Cambios guardados con éxito.")
                time.sleep(2)
            except Exception as e_guardar:
                print(f"Error al guardar: {e_guardar}")
                input("Revisa el día en Chrome y pulsa ENTER para continuar...")

        print("Avanzando al siguiente día utilizando la flecha de la interfaz...")
        try:
            entrar_frames(driver)
            boton_seguent = driver.find_element(
                By.XPATH,
                "//img[contains(@src, 'next') or contains(@src, 'dreta')]/parent::a | (//a[img])[2]",
            )
            driver.execute_script("arguments[0].click();", boton_seguent)
            time.sleep(2.5)
        except Exception as e_nav:
            print(f"No se pudo avanzar automáticamente con la flecha: {e_nav}")
            print("Por favor, haz clic manualmente en la flecha de la derecha en Chrome para continuar.")
            input("Una vez hayas cambiado de día a mano, pulsa ENTER en esta terminal...")

    print("\n========================================================")
    print("Automatización por flujo continuo finalizada.")

except Exception as main_error:
    print(f"Error crítico imprevisto: {main_error}")

finally:
    driver.quit()
    print("Programa cerrado de manera segura.")
