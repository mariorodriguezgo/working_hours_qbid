from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import Select
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv
from datetime import datetime, date
import json
import os
import re
import sys
import time

# CONSTANTES MODIFICABLES
HORAS_A_RELLENAR = 5  # Horas totales a repartir cada día (5, 8, ...)
# Se actualiza sola al final de cada ejecución con el último día registrado.
FECHA_INICIO_STR = "01/09/2026"  # Formato: DD/MM/YYYY
# La fecha final es siempre el día actual.

# CONSTANTES FIJAS
URL_LOGIN = "https://www.empresaiformacio.org/sBid"
PASO_MINUTOS = 15           # Granularidad mínima de los desplegables
TIMEOUT_RED = 30            # Máximo de segundos esperando respuestas HTTP
QUIETUD_RED = 0.6           # Segundos sin peticiones abiertas para dar la red por terminada
TIMEOUT_LOGIN_MANUAL = 180  # Si no hay credenciales, tiempo para iniciar sesión a mano

load_dotenv()
QBID_USER = os.getenv("QBID_USER", "").strip()
QBID_PASSWD = os.getenv("QBID_PASSWD", "").strip()

fecha_inicio = datetime.strptime(FECHA_INICIO_STR, "%d/%m/%Y").date()
fecha_final = date.today()
MINUTOS_OBJETIVO = int(round(HORAS_A_RELLENAR * 60))

MESES = {
    "gener": 1, "febrer": 2, "març": 3, "abril": 4, "maig": 5, "juny": 6,
    "juliol": 7, "agost": 8, "setembre": 9, "octubre": 10, "novembre": 11, "desembre": 12
}

# "2 de juny de 2026", "1 d'octubre de 2026", "5 d’agost de 2026"
REGEX_FECHA = re.compile(r"(\d{1,2})\s+(?:de\s+|d['’]\s*)([a-zç]+)\s+de\s+(\d{4})")
REGEX_MES_ANO = re.compile(r"\b([a-zç]+)\s+(?:de\s+)?(\d{4})\b")


# ---------------------------------------------------------------------------
# Monitor de red: lee el log de rendimiento de Chrome (eventos Network.*)
# para saber qué peticiones HTTP hay abiertas y con qué código respondieron.
# ---------------------------------------------------------------------------
class MonitorRed:
    def __init__(self, driver):
        self.driver = driver
        self.pendientes = {}   # requestId -> (método, url)
        self.respuestas = []   # (método, url, status) desde la última marca

    def _leer(self):
        try:
            entradas = self.driver.get_log("performance")
        except Exception:
            return
        for entrada in entradas:
            try:
                msg = json.loads(entrada["message"])["message"]
            except Exception:
                continue
            metodo, p = msg.get("method"), msg.get("params", {})
            rid = p.get("requestId")
            if metodo == "Network.requestWillBeSent":
                url = p["request"]["url"]
                if not url.startswith(("data:", "blob:")):
                    self.pendientes[rid] = (p["request"]["method"], url)
            elif metodo == "Network.responseReceived":
                metodo_http, url = self.pendientes.get(rid, ("?", p["response"]["url"]))
                self.respuestas.append((metodo_http, url, int(p["response"]["status"])))
            elif metodo in ("Network.loadingFinished", "Network.loadingFailed"):
                info = self.pendientes.pop(rid, None)
                if metodo == "Network.loadingFailed" and info and not p.get("canceled"):
                    self.respuestas.append((info[0], info[1], 0))  # 0 = fallo de red

    def marcar(self):
        """Descarta lo anterior; las respuestas posteriores pertenecen a la próxima acción."""
        self._leer()
        self.pendientes.clear()
        self.respuestas = []

    def esperar(self, requiere_respuesta=False, timeout=TIMEOUT_RED):
        """Espera a que no queden peticiones abiertas. Devuelve las respuestas recibidas."""
        inicio = time.time()
        sin_pendientes_desde = None
        while time.time() - inicio < timeout:
            self._leer()
            listo = not self.pendientes and (self.respuestas or not requiere_respuesta)
            if listo:
                sin_pendientes_desde = sin_pendientes_desde or time.time()
                if time.time() - sin_pendientes_desde >= QUIETUD_RED:
                    return list(self.respuestas)
            else:
                sin_pendientes_desde = None
            time.sleep(0.1)
        if self.pendientes:
            print(f"  Aviso: {len(self.pendientes)} petición(es) sin terminar tras {timeout}s.")
        return list(self.respuestas)

    @staticmethod
    def errores(respuestas):
        return [r for r in respuestas if r[2] == 0 or r[2] >= 400]


def accion(monitor, funcion, descripcion, requiere_respuesta=False):
    """Ejecuta una acción del navegador y espera a sus respuestas HTTP.
    Devuelve True si no hubo errores HTTP."""
    monitor.marcar()
    funcion()
    respuestas = monitor.esperar(requiere_respuesta=requiere_respuesta)
    errores = MonitorRed.errores(respuestas)
    if requiere_respuesta and not respuestas:
        print(f"  {descripcion}: sin respuesta del servidor.")
        return False
    if errores:
        for metodo, url, status in errores:
            print(f"  {descripcion}: HTTP {status or 'ERROR'} en {metodo} {url}")
        return False
    if respuestas:
        print(f"  {descripcion}: OK ({len(respuestas)} respuesta(s), última HTTP {respuestas[-1][2]})")
    return True


# ---------------------------------------------------------------------------
# Reparto de horas
# ---------------------------------------------------------------------------
def texto_a_minutos(texto):
    """Convierte "15min", "1h", "1h 30min", "1:30", "0" a minutos (None si no es duración)."""
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
    opciones = {}
    for opt in Select(select_element).options:
        texto = opt.text.strip()
        minutos = texto_a_minutos(texto)
        if minutos is not None and minutos not in opciones:
            opciones[minutos] = texto
    return opciones


def repartir_minutos(campos_opciones, objetivo, inicio):
    """Reparte `objetivo` minutos entre los campos de forma equilibrada, usando solo
    valores disponibles en cada desplegable. Devuelve lista de minutos o None."""
    n = len(campos_opciones)
    orden = [(inicio + i) % n for i in range(n)]
    base, extra = divmod(objetivo // PASO_MINUTOS, n)

    asignacion = [0] * n
    for k, idx in enumerate(orden):
        asignacion[idx] = (base + (1 if k < extra else 0)) * PASO_MINUTOS
    if all(asignacion[i] in campos_opciones[i] for i in range(n)) and sum(asignacion) == objetivo:
        return asignacion

    # Alternativa: combinación exacta más equilibrada (programación dinámica)
    media = objetivo / n
    mejor = {0: (0.0, [])}
    for idx in orden:
        nuevo = {}
        for suma, (coste, valores) in mejor.items():
            for v in campos_opciones[idx]:
                s = suma + v
                if s > objetivo:
                    continue
                c = coste + (v - media) ** 2
                if s not in nuevo or c < nuevo[s][0]:
                    nuevo[s] = (c, valores + [(idx, v)])
        mejor = nuevo
    if objetivo not in mejor:
        return None
    for idx, v in mejor[objetivo][1]:
        asignacion[idx] = v
    return asignacion


# ---------------------------------------------------------------------------
# Navegación
# ---------------------------------------------------------------------------
def entrar_frames(driver):
    driver.switch_to.default_content()
    driver.switch_to.frame("jspContainer")
    driver.switch_to.frame("contentmain")


def esperar_condicion(condicion, timeout=TIMEOUT_RED):
    inicio = time.time()
    while time.time() - inicio < timeout:
        try:
            resultado = condicion()
            if resultado:
                return resultado
        except Exception:
            pass
        time.sleep(0.2)
    return None


def buscar_password(driver):
    """Busca el campo de contraseña en la página o en sus frames (deja el foco en ese frame)."""
    driver.switch_to.default_content()
    if driver.find_elements(By.CSS_SELECTOR, "input[type='password']"):
        return driver.find_elements(By.CSS_SELECTOR, "input[type='password']")[0]
    for frame in driver.find_elements(By.CSS_SELECTOR, "iframe, frame"):
        driver.switch_to.frame(frame)
        campos = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
        if campos:
            return campos[0]
        driver.switch_to.default_content()
    return None


def login(driver, monitor):
    campo_pass = esperar_condicion(lambda: buscar_password(driver), timeout=20)
    if campo_pass is None:
        print("No se encontró el formulario de login.")
        return False
    if not QBID_USER or not QBID_PASSWD:
        print(f"No hay QBID_USER/QBID_PASSWD en .env. Inicia sesión a mano (máx. {TIMEOUT_LOGIN_MANUAL}s)...")
        return True

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

    def enviar():
        if botones:
            driver.execute_script("arguments[0].click();", botones[0])
        else:
            campo_pass.submit()

    ok = accion(monitor, enviar, "Login", requiere_respuesta=True)
    driver.switch_to.default_content()
    if buscar_password(driver) is not None:
        print("El login no se completó (sigue apareciendo el formulario). Revisa usuario/contraseña.")
        return False
    driver.switch_to.default_content()
    return ok


def calendario_visible(driver):
    try:
        entrar_frames(driver)
        return any(c.text.strip().isdigit() for c in driver.find_elements(By.TAG_NAME, "td"))
    except Exception:
        return False


def clicar_texto_en_cualquier_frame(driver, monitor, texto):
    """Busca un enlace con ese texto en la página y sus frames y lo pulsa."""
    def candidatos():
        driver.switch_to.default_content()
        yield
        for f1 in range(len(driver.find_elements(By.CSS_SELECTOR, "iframe, frame"))):
            driver.switch_to.default_content()
            driver.switch_to.frame(f1)
            yield
            for f2 in range(len(driver.find_elements(By.CSS_SELECTOR, "iframe, frame"))):
                driver.switch_to.default_content()
                driver.switch_to.frame(f1)
                driver.switch_to.frame(f2)
                yield

    for _ in candidatos():
        enlaces = driver.find_elements(By.PARTIAL_LINK_TEXT, texto)
        if enlaces:
            accion(monitor, lambda: driver.execute_script("arguments[0].click();", enlaces[0]), f"Abrir '{texto}'")
            return True
    return False


def ir_a_agenda(driver, monitor):
    timeout = TIMEOUT_LOGIN_MANUAL if not (QBID_USER and QBID_PASSWD) else TIMEOUT_RED
    if esperar_condicion(lambda: calendario_visible(driver), timeout=timeout):
        return True
    if clicar_texto_en_cualquier_frame(driver, monitor, "Agenda"):
        if esperar_condicion(lambda: calendario_visible(driver)):
            return True
    print("No se pudo llegar a la Agenda automáticamente.")
    return False


def ir_a_mes(driver, monitor, objetivo):
    """Mueve el calendario gris hasta el mes de `objetivo` (best-effort)."""
    for _ in range(36):
        entrar_frames(driver)
        actual = None
        for e in driver.find_elements(By.CSS_SELECTOR, ".datepicker-switch, th, caption, .month, .title"):
            m = REGEX_MES_ANO.search(e.text.lower())
            if m and m.group(1) in MESES:
                actual = date(int(m.group(2)), MESES[m.group(1)], 1)
                break
        if actual is None:
            return
        destino = date(objetivo.year, objetivo.month, 1)
        if actual == destino:
            return
        clase = "next" if actual < destino else "prev"
        botones = driver.find_elements(By.CSS_SELECTOR, f".{clase}, [class*='{clase}']")
        if not botones:
            return
        accion(monitor, lambda: driver.execute_script("arguments[0].click();", botones[0]), f"Calendario ({clase})")


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
            return date(int(m.group(3)), MESES[m.group(2)], int(m.group(1)))
    return None


def entrar_primer_dia(driver, monitor):
    entrar_frames(driver)
    ir_a_mes(driver, monitor, fecha_inicio)
    entrar_frames(driver)
    celda_objetivo = None
    for celda in driver.find_elements(By.TAG_NAME, "td"):
        if celda.text.strip() == str(fecha_inicio.day):
            clase_celda = str(celda.get_attribute("class"))
            if "old" not in clase_celda and "new" not in clase_celda:
                celda_objetivo = celda
                break
    if celda_objetivo is None:
        celda_objetivo = driver.find_element(By.XPATH, f"//td[normalize-space(text())='{fecha_inicio.day}']")

    accion(monitor, lambda: driver.execute_script("arguments[0].click();", celda_objetivo),
           f"Seleccionar día {fecha_inicio.day}")

    entrar_frames(driver)
    enlace = esperar_condicion(lambda: driver.find_element(By.PARTIAL_LINK_TEXT, "Activitat diària del dossier"))
    if enlace is None:
        raise RuntimeError("No aparece el enlace 'Activitat diària del dossier'.")
    if not accion(monitor, lambda: driver.execute_script("arguments[0].click();", enlace), "Abrir dossier"):
        raise RuntimeError("Error HTTP al abrir el dossier.")
    entrar_frames(driver)


def rellenar_dia(driver, monitor, posicion_inicial):
    """Rellena los desplegables. Devuelve (nueva_posición, hay_que_guardar)."""
    campos = []
    for s in driver.find_elements(By.TAG_NAME, "select"):
        if not s.is_enabled():
            continue
        opciones = opciones_duracion(s)
        if len(opciones) >= 2:
            campos.append((s, opciones))

    if not campos:
        print("No hay campos de horas editables (posible fin de semana o festivo).")
        return posicion_inicial, False

    n = len(campos)
    print(f"Detectados {n} campos de horas. Objetivo: {MINUTOS_OBJETIVO // 60}h {MINUTOS_OBJETIVO % 60:02d}min")
    posicion_inicial %= n

    asignacion = repartir_minutos([o for _, o in campos], MINUTOS_OBJETIVO, posicion_inicial)
    if asignacion is None:
        print(f"ERROR: no es posible sumar exactamente {HORAS_A_RELLENAR}h con {n} campos. Día NO guardado.")
        return posicion_inicial, False

    def seleccionar():
        for (select_element, opciones), minutos in zip(campos, asignacion):
            Select(select_element).select_by_visible_text(opciones[minutos])
            driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                                  select_element)

    accion(monitor, seleccionar, "Rellenar desplegables")

    total = sum(texto_a_minutos(Select(s).first_selected_option.text) or 0 for s, _ in campos)
    if total != MINUTOS_OBJETIVO:
        print(f"ERROR: la suma seleccionada es {total} min (esperado {MINUTOS_OBJETIVO}). Día NO guardado.")
        return posicion_inicial, False

    print("Reparto: " + ", ".join(opciones[m] for (_, opciones), m in zip(campos, asignacion)))
    return (posicion_inicial + 1) % n, True


def guardar_fecha_inicio(nueva_fecha):
    """Reescribe FECHA_INICIO_STR en este mismo archivo."""
    ruta = os.path.abspath(__file__)
    with open(ruta, encoding="utf-8") as f:
        codigo = f.read()
    nuevo, cambios = re.subn(
        r'^FECHA_INICIO_STR\s*=\s*"[^"]*"',
        f'FECHA_INICIO_STR = "{nueva_fecha.strftime("%d/%m/%Y")}"',
        codigo, count=1, flags=re.MULTILINE,
    )
    if cambios:
        tmp = ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(nuevo)
        os.replace(tmp, ruta)
        print(f"FECHA_INICIO_STR actualizada a {nueva_fecha.strftime('%d/%m/%Y')}.")


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------
print(f"Iniciando QBid Automator: {HORAS_A_RELLENAR}h por día")
print(f"Rango: {fecha_inicio.strftime('%d/%m/%Y')} -> {fecha_final.strftime('%d/%m/%Y')} (hoy)")

if fecha_inicio > fecha_final:
    print("La fecha de inicio es posterior a hoy; no hay nada que rellenar.")
    sys.exit(0)

opciones_chrome = webdriver.ChromeOptions()
opciones_chrome.set_capability("goog:loggingPrefs", {"performance": "ALL"})
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opciones_chrome)
monitor = MonitorRed(driver)
ultimo_dia_guardado = None

try:
    if not accion(monitor, lambda: driver.get(URL_LOGIN), "Cargar QBid", requiere_respuesta=True):
        raise RuntimeError("No se pudo cargar la página de QBid.")
    if not login(driver, monitor):
        raise RuntimeError("Login fallido.")
    if not ir_a_agenda(driver, monitor):
        raise RuntimeError("No se encontró el calendario de la Agenda.")

    entrar_primer_dia(driver, monitor)

    posicion_inicial = 0
    ultima_fecha = None

    while True:
        entrar_frames(driver)
        fecha_actual = leer_fecha_pantalla(driver)
        if fecha_actual is None:
            print("No se pudo leer la fecha de la página; se detiene por seguridad.")
            break
        print(f"\n--- PROCESANDO: {fecha_actual.strftime('%d/%m/%Y')} ---")
        if fecha_actual > fecha_final:
            print("Se ha llegado al día de hoy.")
            break
        if ultima_fecha and fecha_actual <= ultima_fecha:
            print("La página no ha avanzado de día; se detiene para no repetir registros.")
            break
        ultima_fecha = fecha_actual

        posicion_inicial, hay_que_guardar = rellenar_dia(driver, monitor, posicion_inicial)

        if hay_que_guardar:
            if accion(monitor, lambda: driver.execute_script("save();"), "Guardar", requiere_respuesta=True):
                ultimo_dia_guardado = fecha_actual
            else:
                print("El guardado falló; se detiene para revisar.")
                break

        if fecha_actual >= fecha_final:
            print("Día de hoy procesado.")
            break

        entrar_frames(driver)
        boton_seguent = driver.find_element(
            By.XPATH,
            "//img[contains(@src, 'next') or contains(@src, 'dreta')]/parent::a | (//a[img])[2]",
        )
        accion(monitor, lambda: driver.execute_script("arguments[0].click();", boton_seguent), "Día siguiente")
        # Además de la red, confirma que la fecha de la página ha cambiado
        anterior = fecha_actual
        if not esperar_condicion(lambda: (entrar_frames(driver), leer_fecha_pantalla(driver))[1] not in (None, anterior)):
            print("La fecha no cambió tras pulsar la flecha.")
            break

    print("\n========================================================")
    print("Automatización finalizada.")

except Exception as main_error:
    print(f"Error crítico: {main_error}")

finally:
    if ultimo_dia_guardado:
        guardar_fecha_inicio(ultimo_dia_guardado)
    else:
        print("No se guardó ningún día; FECHA_INICIO_STR no cambia.")
    driver.quit()
    print("Programa cerrado.")
