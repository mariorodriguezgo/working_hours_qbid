# working_hours_qbid

Script en Python para rellenar las horas de la "Activitat diària del dossier" en qBID (https://www.empresaiformacio.org/sBid) sin tener que hacerlo día a día a mano.

Entra con tu usuario, recorre los días desde la fecha que le indiques hasta hoy y en cada uno reparte las horas entre las actividades del plan. Si un día ya tiene las horas puestas lo deja como está, y si tiene menos de las que toca lo corrige. Los fines de semana y festivos se los salta.

Cuando termina, apunta en el propio script el último día que ha registrado, así la próxima vez empieza desde ahí.

## Instalación

Necesitas Python 3.10 o más reciente y Git. Chrome es recomendable, aunque si no lo tienes Selenium descarga uno la primera vez.

En Windows puedes instalar lo que falte desde PowerShell:

```powershell
winget install --id Python.Python.3.13 -e
winget install --id Git.Git -e
winget install --id Google.Chrome -e
```

Después de instalar, cierra y vuelve a abrir PowerShell para que reconozca los comandos nuevos.

### 1. Descargar el repositorio

```powershell
git clone https://github.com/mariorodriguezgo/working_hours_qbid.git
cd working_hours_qbid
```

### 2. Crear el entorno virtual

El entorno virtual (venv) es una carpeta donde se instalan las librerías solo para este proyecto, sin tocar el Python del sistema.

```powershell
python -m venv venv
```

### 3. Activarlo

En Windows:

```powershell
.\venv\Scripts\Activate.ps1
```

En Linux o macOS:

```bash
source venv/bin/activate
```

Sabrás que está activo porque aparece `(venv)` al principio de la línea. Hay que activarlo cada vez que abras una terminal nueva para usar el script.

Si Windows da un error de permisos al activarlo, ejecuta esto una vez y vuelve a intentarlo:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 4. Instalar las librerías

Con el venv activo:

```powershell
pip install -r requirements.txt
```

Para comprobar que se han instalado bien:

```powershell
python -c "import selenium, dotenv; print('OK')"
```

### 5. Poner tus credenciales

Copia el archivo de ejemplo y ábrelo:

```powershell
copy .env.example .env
notepad .env
```

En Linux o macOS es `cp .env.example .env` y lo editas con cualquier editor.

Rellena tu usuario y contraseña de qBID:

```ini
QBID_USER=tu_usuario
QBID_PASSWD=tu_contraseña
```

El archivo `.env` no se sube a GitHub (está en `.gitignore`).

## Antes de la primera ejecución

Abre `fill_hours_qbid.py`. Arriba del todo hay dos constantes que tienes que revisar:

```python
HORAS_A_RELLENAR = 5
FECHA_INICIO_STR = "01/09/2026"
```

`FECHA_INICIO_STR` es el primer día que se va a rellenar, en formato DD/MM/AAAA. La primera vez ponlo tú a mano. Yo recomiendo empezar con un día de la semana actual, mirar en qBID que todo ha quedado bien y después ya poner la fecha real de inicio de las prácticas. A partir de ahí no hace falta tocarla, porque el script la actualiza solo al acabar. La fecha final no se configura, siempre es el día de hoy.

`HORAS_A_RELLENAR` son las horas que se ponen cada día. El script no limita el número, pero qBID sí: cada conveni tiene unas horas máximas por día, que salen en la página de actividad diaria como "Hores màximes: 5H" (o 8H, según tu conveni). Puedes poner cualquier valor hasta ese máximo, en pasos de 15 minutos. Por ejemplo, con un máximo de 8H valen 5, 6, 6.5, 7.75 u 8. Si pones más de lo que permite tu conveni, el script se para en el primer día y te avisa sin guardar nada.

El script antiguo solo funcionaba con 5 u 8 horas y a veces se quedaba en 4h 30min o 4h 45min. Ahora calcula el reparto según el número de actividades que tenga el día, así que la suma siempre es exacta.

## Uso

Con el venv activo y desde la carpeta del proyecto:

```powershell
python fill_hours_qbid.py
```

Se abre Chrome, inicia sesión y va pasando los días. En la terminal verás algo así:

```
Iniciando QBid Automator: 5h por día
Rango: 26/10/2026 -> 28/10/2026 (hoy)

--- 26/10/2026 ---
Tenía 4h 30min; se corrige a 5h.
Reparto en 15 campos: 15min, 15min, 30min, 30min, 30min, 30min, 30min, 15min, ...
  Guardar: OK (POST HTTP 200)
  Comprobado: QBid muestra 5h guardadas.
...
Automatización finalizada.
FECHA_INICIO_STR actualizada a 28/10/2026.
```

Al terminar, Chrome se cierra solo.

## Si falla

El script se para en cuanto algo no cuadra, por ejemplo si no puede entrar, si qBID no acepta el guardado o si la página no cambia de día. En ese caso crea una carpeta `debug/` con la fecha y hora, y dentro guarda una captura de pantalla, el HTML de la página y un `motivo.txt` con el error. Esos archivos sirven para ver qué ha pasado y adaptar el script si qBID cambia su web. Pueden tener datos tuyos, por eso tampoco se suben a GitHub.

Errores habituales:

| Mensaje | Qué hacer |
|---|---|
| `cannot find Chrome binary` | Haz `git pull` para tener la última versión, o instala Chrome. |
| `Login fallido` | Revisa el usuario y la contraseña del `.env`. |
| `supera las Hores màximes` | Baja `HORAS_A_RELLENAR` al máximo de tu conveni. |
| `QBid rechazó el guardado: ...` | Es el mensaje que da qBID, normalmente por horas de más o de menos. |

## Detalles técnicos

La web de qBID carga todo dentro de dos iframes (`jspContainer` y, dentro, `contentmain`). Para saber cuándo ha terminado de cargar cada paso, el script lee el registro de red de Chrome y espera a que acaben las peticiones, en vez de usar esperas fijas. También comprueba el código HTTP de las respuestas.

En `docs/qbid_estructura.md` están apuntados los selectores, las funciones JavaScript y las peticiones de qBID que usa el script.

Es un proyecto personal y no tiene relación con qBID ni con el Departament d'Educació. Las horas que registres tienen que ser las que has hecho de verdad, así que revísalas.
