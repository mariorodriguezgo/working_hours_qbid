# qBID — Activitat diària del dossier: reporte técnico para el script de Selenium

Fecha: 28/10/2026. Solo lectura: no se ha rellenado ni guardado nada en qBID. Datos personales eliminados (usuario, nº conveni/dossier, `hash_code`, `pk`, nombres).

**Claves para el script:**

- **Avanzar por URL:** las URLs llevan un `hash_code` del servidor, así que no se pueden construir a mano. Hay que navegar con clics o leer el `href` del enlace.
- **Popups `alert()`:** `save()` puede abrir popups nativos que bloquean Selenium.
- **Días futuros:** se pueden abrir, pero tienen los selects deshabilitados.

---

## Parte A — Manuales

**Fuentes que no se han podido usar:**

- El PDF de **inspeguera** y la **Guía QBID 2025 del SOC** no se pudieron leer: los dos sitios bloquean la descarga automática (robots.txt).
- El PDF de **iesffg** se leyó, pero solo describe el proceso de seguimiento en general (*"L'alumne amb l'activitat diària del dossier al dia fa la valoració…"*). No cubre ninguno de los 6 puntos.
- Todo lo de abajo sale del **MUQA**: 25 págs., un borrador de 2013 (*"ESBORRANY / PENDENT DE VALIDACIÓ"*). Puede estar desactualizado.

1. **Tras el login:** se abre directamente la "Agenda" (p. 13), sin pantalla intermedia. A la izquierda hay "Tasques" (p. 15): las 3 pendientes más antiguas y las de hoy. Se pueden filtrar por "Activitat diària", "Informes mensual", "Enquesta final de l'FCT" y "Totes les tasques".
2. **Calendario** ("Calendari", p. 14):
   - Colores: Rosat = tareas pendientes; Vermell = baja mèdica; Verd = "festiu o vacances escolars"; Groc = absència (personal, estudis, empresa); Gris = tareas ya hechas. En la p. 16, las tareas rojas son pendientes y las grises son futuras.
   - **No lo cubre:** cómo se cambia de mes ni el formato de la cabecera.
3. **Abrir un día y pasar al siguiente:**
   - La "Activitat diària" se abre desde la agenda (p. 22).
   - Dos botones llevan a la actividad siguiente o a la anterior (p. 24).
   - Si el tutor aún no ha introducido el pla d'activitats, aparece el mensaje *"encara no es troba disponible"* (p. 22).
4. **Horas** (p. 23):
   - Se asignan horas a las actividades del pla. El contador "hores introduïdes" suma el total.
   - El botón de guardar solo aparece como icono, descrito como "emmagatzemar les dades al sistema" (p. 5).
   - **No lo cubre:** los valores de los desplegables ni el mensaje de confirmación.
5. **Restricciones** (p. 23):
   - No se pueden superar las horas máximas por día del conveni.
   - *"el sistema no us permetrà introduir les activitats diàries del futur"*.
   - Si el tutor marca un día como absència, el alumno no puede revocarlo.
   - Motivos de ausencia que lista el manual: "Motius mèdics", "Dia Festiu", "Vacances escolars", "Motius Personals", "Absència relacionada amb els estudis", "Motivat per l'empresa", "Altres motius".
   - **No lo cubre:** fines de semana, días validados por el tutor ni plazos.
6. **Fecha:** solo dice que los campos de fecha usan "dd/mm/aaaa" (p. 8). **No lo cubre** para la página de actividad diaria. En la web real el formato es otro (ver Parte B.4).

---

## Parte B — Web real

### 1. Pantalla tras el login

- **URL:** la de arriba se queda en `https://www.empresaiformacio.org/sBid`. La Agenda se abre sola, sin elegir conveni.
- **Frames** (todos son `<iframe>` del mismo origen):

```
top  (https://www.empresaiformacio.org/sBid)
├── iframe#jspContainer   name="jspContainer"   → /sBid/modules/Agenda?moduleaction=changeSistema&initial=yes
│   ├── iframe#addInfoNotes                     → about:blank
│   └── iframe#contentmain  name="contentmain"  → /sBid/modules/Agenda   (aquí va todo el contenido)
└── iframe#cacheContainer name="cacheContainer" → /sBid/jsp/hidden.jsp
```

- **Enlace del menú a la Agenda:** está dentro de `jspContainer`, no de `contentmain`:

```html
<a href="javascript:top.cacheContainer.doSubmit('/sBid/modules/Agenda?moduleaction=show&clearBackStack=true', 'Agenda', '-1')">Agenda</a>
```

### 2. Calendario de la Agenda (en `contentmain`)

```html
<td class="AgHeader" onclick="javascript:popupAgenda.shiftAgenda(-12);"><i class="bi bi-rewind-fill"></i></td>
<td class="AgHeader" onclick="javascript:popupAgenda.shiftAgenda(-1);"><i class="bi bi-caret-left-fill"></i></td>
<td class="AgHeader"><font class="AgHeader" id="popupAgenda_calHeader0">octubre 2026</font></td>
<td class="AgHeader" onclick="javascript:popupAgenda.shiftAgenda(1);"><i class="bi bi-caret-right-fill"></i></td>
<td class="AgHeader" onclick="javascript:popupAgenda.shiftAgenda(12);"><i class="bi bi-fast-forward-fill"></i></td>
...
<table id="monthView">
  <tr><td class="AgMonthHeader"><font class="AgMonthHeader">Dl</font></td> ... Dg</tr>
  <!-- celda vacía (día de otro mes): sin id ni onclick -->
  <td align="center" class="AgCell"><font class="AgCell">&nbsp;&nbsp;&nbsp;</font></td>
  <!-- celda de un día normal -->
  <td align="center" id="cellDay27" class="AgCellData" onclick="popupAgenda.moveAgenda('2026', '10', '27', true);"><font class="AgCell">&nbsp;27&nbsp;</font></td>
  <td align="center" id="cellDay28" class="AgCellSelected" ...><font class="AgCellSelected">&nbsp;28&nbsp;</font></td>
```

- **Cabecera del mes:** texto exacto en minúsculas, "octubre 2026".
- **Días de otros meses:** no se pintan. Son celdas `AgCell` vacías (`&nbsp;`), sin `id`.
- **Al cambiar de mes** con `shiftAgenda(±1)` sale una petición AJAX: `GET /sBid/modules/Agenda?moduleaction=diesMarcatsMesAjax&dia=YYYYMMDD000000`. La tabla se repinta sin recargar el frame.
- **Clases de las celdas** (sacadas del CSS real):

| Clase | Color | Significado observado |
|---|---|---|
| `AgCellData` | rosa `#FBC4C4` | Tareas pendientes (27, 29, 30) |
| `AgCellInfo` | `darkgray` | Días ya rellenados (1–23, 26) |
| `AgCell` | `#F2F2F2` | Sin tareas (sábados y domingos) o celda vacía |
| `AgCellSelected` | `#484848` | Día seleccionado |
| `AgCellFesta` / `AgCellFestaF` | `chartreuse` | Festivo. El 12/10 tiene `AgCellFestaF` y su lista dice "Dia Festiu" |
| `AgCellMedic` | `crimson` | Baja médica |
| `AgCellBaixa` | `yellow` | Ausencia |
| sufijo `…F` | borde rojo de 3px | Variante con borde rojo (no confirmado qué indica) |

### 3. Al pulsar un día

`moveAgenda` lanza `GET /sBid/modules/Agenda?moduleaction=tasquesDiaAjax&dia=YYYYMMDD000000` y rellena un panel:

```html
<span id="dataTasques">Dimarts, 27 d'octubre 2026</span>
<span id="tascasDayCount" class="badge rounded-pill bg-secondary">1</span>
<ul id="tablaTasquesDia" class="list-group">
  <li><a class="list-group-item list-group-item-action ..."
         href="/sBid/modules/ActivitatFct?moduleaction=show&codi_conveni=XXXX&codi_conveni_provisional=FDXXXX&data=20261027&hash_code=XXXX"
         onclick="showLoading();"><strong>Activitat diària del dossier (XXXX)</strong></a></li>
</ul>
```

- **Texto exacto del enlace:** "Activitat diària del dossier (nº conveni)".
- **Días ya rellenados:** el `href` lleva además `conveni_activitat_pk=…`.
- **Sábados:** sin enlace; la lista dice "No hi ha tasques pendents per aquest dia".
- **Festivos:** sin enlace; la lista dice "Dia Festiu".
- **Atención, dos fechas distintas:** el panel dice "27 d'octubre 2026", sin "de" antes del año. La página de actividad sí lo lleva.

### 4. Página de actividad diaria (en `contentmain`, `/sBid/modules/ActivitatFct?moduleaction=show&…&data=YYYYMMDD&hash_code=…`)

**Fecha y flechas:**

```html
<div class="panel-heading">
 <label class="control-label">
  <a href="/sBid/modules/ActivitatFct?moduleaction=show&conveni_activitat_pk=NNNN&codi_conveni=XXXX&codi_conveni_provisional=FDXXXX&data=20261026&hash_code=XXXX" class="base" onclick="showLoading();"><img src="../images/backAlumne.png" title="Anterior" class="base" width="32px"></a>
  Dimarts, 27 d'octubre de 2026
  <a href="/sBid/modules/ActivitatFct?moduleaction=show&codi_conveni=XXXX&codi_conveni_provisional=FDXXXX&data=20261028&hash_code=XXXX" class="base" onclick="showLoading();"><img src="../images/nextAlumne.png" title="Següent" class="base" width="32px"></a>
 </label>
</div>
```

- **Formato de la fecha:** `"<Dia>, <d> d'<mes>|de <mes> de <aaaa>"`, por ejemplo "Dilluns, 2 de novembre de 2026". Usa "d'" ante vocal ("d'octubre") y "de" en el resto. Es más fiable leer `data=YYYYMMDD` del `href` o de la URL del frame.

**Selects de horas:**

- Hay **15** de horas (`id`/`name` `inp_NNNNNN`, `title="Valoracio"`). Los ids dependen del pla de cada alumno.
- Hay **2 selects más** de ausencia que no hay que tocar: `#motiuAbsencia` (10 opciones) y `#motiuAbsenciaParcial` (7 opciones).
- Un select completo:

```html
<select class="form-control fieldOk" cf:type="List" cf:required="yes" title="Valoracio" cf:onchange="updateHoresConsignades();" name="inp_107728" id="inp_107728">
 <option value="0" selected="">- - -</option>
 <option value="0.25"> 15min </option>   <option value="0.5"> 30min </option>   <option value="0.75"> 45min </option>
 <option value="1.0"> 1h </option>       <option value="1.25"> 1h 15min </option> <option value="1.5"> 1h 30min </option>
 <option value="1.75"> 1h 45min </option> <option value="2.0"> 2h </option>    <option value="2.25"> 2h 15min </option>
 <option value="2.5"> 2h 30min </option> <option value="2.75"> 2h 45min </option> <option value="3.0"> 3h </option>
 <option value="3.25"> 3h 15min </option> <option value="3.5"> 3h 30min </option> <option value="3.75"> 3h 45min </option>
 <option value="4.0"> 4h </option>       <option value="4.25"> 4h 15min </option> <option value="4.5"> 4h 30min </option>
 <option value="4.75"> 4h 45min </option> <option value="5.0"> 5h </option>
</select>
```

- **Valores:** los enteros van con ".0" (`"1.0"`, `"5.0"`). Con `Select.select_by_value` usa exactamente esas cadenas.
- **Contadores:** "Hores màximes: **5H**" y "Hores introduïdes:" en `div#horesI > span`.

**Guardar:**

- El botón de guardar es un `<span>`, no un `<button>`:

  ```html
  <span type="button" title="Emmagatzemar" class="btn btn-primary" onclick="javascript:save();"><span class="glyphicon glyphicon-floppy-disk bi bi-save"></span>&nbsp;Emmagatzemar</span>
  ```

- Ojo: hay otro `save()` en el modal de ausencias, `span[title="Absència"]`. No confundirlos.
- **Qué hace `save()`** (código leído, no ejecutado):
  1. Suma las horas de los selects con `contarHoras()`.
  2. Si la suma es 0, abre `alert("Cal introduïr hores en alguna de les tasques assignades del pla d'activitats")`.
  3. Si supera 5, abre `alert("Reviseu les hores introduïdes ja que no podeu superar 5H")`.
  4. Si está bien, hace `f.moduleaction.value="save"` y `submit()` del `form#workingForm` (POST a `/sBid/modules/ActivitatFct`). Eso recarga `contentmain`.
- **Mensaje de confirmación tras guardar:** no observado, porque no se ha guardado.
- **Campo de comentarios:** `textarea#observacionsInutilsAlumneMaiOmplira`.

### 5. Red al pulsar "Següent"

- Sale **una sola petición de documento:** `GET /sBid/modules/ActivitatFct?moduleaction=show&codi_conveni=…&codi_conveni_provisional=…&data=20261028&hash_code=… → 200`.
- Después se recargan los recursos del frame (CSS, JS, `nextAlumne.png`/`backAlumne.png`, `includeScriptHeader_js.jsp`), todos con código 200.
- **Solo se recarga `contentmain`.** Comprobado que las variables JS del `top` y de `jspContainer` siguieron vivas.
- **En Selenium:** tras cada clic, esperar a que la referencia vieja quede *stale* (desactualizada), o a que cambie `data=` en la URL del frame. Después volver a buscar los elementos.

### 6. Fines de semana, días futuros y días ya rellenados

- **Fines de semana:** no tienen página propia. La flecha "Següent" los salta: del viernes 30/10 pasa al lunes 02/11 (y "Anterior" del lunes 26 vuelve al viernes 23).
- **Festivos:** en la Agenda no tienen enlace. No comprobado si las flechas los saltan.
- **Días futuros** (29/10, 30/10, 02/11): la página se abre con 15 selects con `disabled=""` y **sin** botón "Emmagatzemar". No aparece ningún mensaje.
- **Hoy y días pasados pendientes** (27/10, 28/10): los selects están habilitados y el botón aparece.
- **Días ya rellenados** (23/10, 26/10): siguen **editables**. Los selects están habilitados con sus valores (p. ej. `0.5`, `0.25`), el total marca "5H" y el botón aparece. La URL lleva `conveni_activitat_pk`.
- **Días validados por el tutor:** no se ha encontrado ningún indicador de validación del tutor. No se puede confirmar cómo se ve un día validado.

---

## Selectores recomendados

- **Frames:** `driver.switch_to.frame("jspContainer")` y luego `driver.switch_to.frame("contentmain")`. Tras cada carga, volver a `default_content()` y repetir.
- **Menú Agenda** (en `jspContainer`): `//a[normalize-space()='Agenda']`
- **Cabecera de mes:** `#popupAgenda_calHeader0` (texto "octubre 2026").
- **Mes anterior:** `td.AgHeader[onclick*="shiftAgenda(-1)"]`
- **Mes siguiente:** `td.AgHeader[onclick*="shiftAgenda(1)"]` (incluye el `)` para no coincidir con `(12)`).
- **Celda de día:** `#monthView td[id="cellDay{N}"]`. Para elegir solo pendientes: `#monthView td[id^="cellDay"].AgCellData`. Las celdas de otros meses no tienen `id`.
- **Enlace del dossier:** `#tablaTasquesDia a[href*="ActivitatFct"]`, o por XPath `//ul[@id='tablaTasquesDia']//a[contains(.,'Activitat diària del dossier')]`.
- **Fecha del día:** `//div[contains(@class,'panel-heading')]/label[contains(@class,'control-label')]` (normalizar el texto). Mejor aún, leer `data=(\d{8})` de `driver.current_url` dentro del frame.
- **Selects de horas:** `select[id^="inp_"][title="Valoracio"]` (15 en este dossier). Para saltar días futuros, filtrar con `:not([disabled])`.
- **Flecha siguiente:** `a:has(> img[src$="nextAlumne.png"])`, o por XPath `//img[@title='Següent']/parent::a`.
- **Guardar:** `span.btn[title="Emmagatzemar"]`, que llama a `save()`. Antes de pulsarlo, preparar el script para el `alert()` (`WebDriverWait(...).until(EC.alert_is_present())`) por si salta un error.
