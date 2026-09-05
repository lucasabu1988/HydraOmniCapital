import datetime
import xml.etree.ElementTree as ET
from xml.dom import minidom

def weeks_to_dates(first_month, weeks):
    if not weeks:
        return None, None
    base = first_month
    start = base + datetime.timedelta(weeks=min(weeks)-1)
    end = base + datetime.timedelta(weeks=max(weeks)) - datetime.timedelta(days=1)
    return start, end

projects = {
    "CEREALES QUIPYS": {
        "priority": "URGENTE",
        "status": "En curso",
        "first_month": datetime.date(2025, 11, 1),
        "notes": "Claim sin colorantes artificiales, con granos andinos, quinua, vit y minerales, sin gluten. Alto en octogono. Fecha limite: 2-2-26",
        "tasks": [
            ("INICIO", [1]),
            ("PLANTEAMIENTO DE PROYECTO", [1]),
            ("EVALUACION DE RIESGOS", [1]),
            ("REQUERIMIENTOS Y COMPRAS", [2]),
            ("PRUEBAS PILOTO", [3, 4]),
            ("ANALISIS DE PRODUCTO", [5, 6, 7, 8]),
            ("EVALUACION DE ENVASES", [5, 6]),
            ("EVALUACION DE VIDA UTIL", [5, 6, 7, 8, 9, 10, 11, 12]),
            ("REGISTRO SANITARIO", [9, 10, 11, 12]),
            ("DISENO DE ARTE", [5, 6, 7, 8, 9, 10]),
            ("COMPRA DE INSUMOS", [9, 10, 11, 12]),
            ("PRUEBA SEMI INDUSTRIAL", [13, 14]),
            ("PRUEBA INDUSTRIAL", [15, 16]),
            ("ENTREGA DE DOCUMENTOS", [17, 18]),
            ("LANZAMIENTO", [19, 20]),
            ("SEGUIMIENTO", [21, 22, 23, 24]),
        ],
    },
    "BARRAS PROTEICAS DE SUERO DE LECHE": {
        "priority": "MODERADA",
        "status": "No iniciada",
        "first_month": datetime.date(2025, 11, 1),
        "notes": "Sabores: yogurt, chocolate, galleta crema. Pendiente: dulce de leche, mani, limon, capuchino.",
        "tasks": [
            ("INICIO", [1]),
            ("PLANTEAMIENTO DE PROYECTO", [1, 2]),
            ("EVALUACION DE RIESGOS", [2, 3, 4, 5]),
            ("REQUERIMIENTOS Y COMPRAS", [3, 4]),
            ("PRUEBAS PILOTO", [4, 5, 6, 7]),
            ("EVALUACION SENSORIAL", [5, 6, 7, 8]),
            ("ANALISIS DE PRODUCTO", [9, 10, 11, 12]),
            ("EVALUACION DE ENVASES", [9, 10]),
            ("EVALUACION DE VIDA UTIL", [9, 10, 11, 12, 13, 14, 15, 16]),
            ("REGISTRO SANITARIO", [13, 14, 15, 16]),
            ("DISENO DE ARTE", [9, 10, 11, 12]),
            ("COMPRA DE INSUMOS", [13, 14, 15, 16]),
            ("PRUEBA SEMI INDUSTRIAL", [17, 18]),
            ("PRUEBA INDUSTRIAL", [19, 20]),
            ("ENTREGA DE DOCUMENTOS", [21, 22]),
            ("LANZAMIENTO", [23, 24]),
            ("SEGUIMIENTO", [25, 26, 27, 28]),
        ],
    },
    "PLANT IS (Nuts, Nutrifruits, Cacao)": {
        "priority": "URGENTE",
        "status": "En curso",
        "first_month": datetime.date(2025, 11, 1),
        "notes": "Barras y galletas. Cantidades minimas para el lanzamiento.",
        "tasks": [
            ("PRUEBAS PILOTO", [1]),
            ("EVALUACION SENSORIAL", [1]),
            ("ANALISIS DE PRODUCTO", [1, 2, 3, 4]),
            ("EVALUACION DE ENVASES", [1, 2]),
            ("EVALUACION DE VIDA UTIL", [1, 2, 3, 4, 5, 6, 7]),
            ("REGISTRO SANITARIO", [4, 5, 6, 7]),
            ("DISENO DE ARTE", [1, 2]),
            ("COMPRA DE INSUMOS", [4, 5, 6, 7]),
            ("PRUEBA SEMI INDUSTRIAL", [5, 6]),
            ("PRUEBA INDUSTRIAL", [7, 8]),
            ("ENTREGA DE DOCUMENTOS", [7, 8]),
            ("LANZAMIENTO", [9, 10]),
            ("SEGUIMIENTO", [11, 12, 13, 14, 15]),
        ],
    },
    "BARRAS DE FRUTA QUIPYS": {
        "priority": "URGENTE",
        "status": "En curso",
        "first_month": datetime.date(2025, 9, 1),
        "notes": "Lanzamiento 1er marzo. Caja display. Se envio plano mecanico caja 5 und. Enviar solicitud EAN faltante. Luna jefa de proyecto.",
        "tasks": [
            ("PRUEBAS PILOTO", [1, 2]),
            ("EVALUACION SENSORIAL", [2]),
            ("ANALISIS DE PRODUCTO", [2, 3]),
            ("EVALUACION DE ENVASES", [4, 5]),
            ("EVALUACION DE VIDA UTIL", [4, 5, 6, 7]),
            ("DISENO DE ARTE", [3, 4, 5, 6]),
            ("COMPRA DE INSUMOS", [7, 8, 9, 10]),
            ("PRUEBA SEMI INDUSTRIAL", [11, 12]),
            ("PRUEBA INDUSTRIAL", [13, 14]),
            ("ENTREGA DE DOCUMENTOS", [15, 16]),
            ("LANZAMIENTO", [17, 18]),
            ("SEGUIMIENTO", [19, 20, 21, 22, 23, 24]),
        ],
    },
    "GALLETA ARCOR SAPITO": {
        "priority": "MODERADA",
        "status": "En curso",
        "first_month": datetime.date(2025, 9, 1),
        "notes": "Envio plano mecanico 54g (6 und). Enviar observaciones prueba. Enviar costos sapito mini.",
        "tasks": [
            ("PRUEBAS PILOTO", [1, 2]),
            ("EVALUACION SENSORIAL", [2]),
            ("ANALISIS DE PRODUCTO", [2, 3, 4, 5]),
            ("EVALUACION DE ENVASES", [4, 5]),
            ("EVALUACION DE VIDA UTIL", [4, 5, 6, 7]),
            ("REGISTRO SANITARIO", [7, 8, 9, 10]),
            ("PRUEBA SEMI INDUSTRIAL", [12, 13]),
            ("PRUEBA INDUSTRIAL", [14, 15]),
            ("ENTREGA DE DOCUMENTOS", [16, 17]),
            ("LANZAMIENTO", [18, 19]),
            ("SEGUIMIENTO", [20, 21, 22, 23, 24]),
        ],
    },
    "FOUR PACK BABY FOODS": {
        "priority": "MODERADA",
        "status": "En curso",
        "first_month": datetime.date(2025, 9, 1),
        "notes": "Trabajaremos con Eurogroup. Fecha de llegada pendiente.",
        "tasks": [
            ("PRUEBAS PILOTO", [1, 2]),
            ("EVALUACION SENSORIAL", [2]),
            ("ANALISIS DE PRODUCTO", [2, 3, 4, 5]),
            ("EVALUACION DE ENVASES", [4, 5]),
            ("EVALUACION DE VIDA UTIL", [4, 5, 6, 7]),
            ("REGISTRO SANITARIO", [7, 8, 9, 10]),
            ("PRUEBA SEMI INDUSTRIAL", [12, 13]),
            ("PRUEBA INDUSTRIAL", [14, 15]),
            ("ENTREGA DE DOCUMENTOS", [16, 17]),
            ("LANZAMIENTO", [18, 19]),
            ("SEGUIMIENTO", [20, 21, 22, 23, 24]),
        ],
    },
    "DUKE LOGISTIC": {
        "priority": "ALTA",
        "status": "En curso",
        "first_month": datetime.date(2025, 9, 1),
        "notes": "Envio muestras mani chocolate 45g. Validacion contaminacion de leche.",
        "tasks": [
            ("INICIO", [3]),
            ("PLANTEAMIENTO DE PROYECTO", [3]),
            ("EVALUACION DE RIESGOS", [3, 4]),
            ("REQUERIMIENTOS Y COMPRAS", [3, 4]),
            ("PRUEBAS PILOTO", [3, 4, 5]),
            ("EVALUACION SENSORIAL", [3, 4, 5, 6]),
            ("ANALISIS DE PRODUCTO", [7, 8, 9, 10]),
            ("EVALUACION DE ENVASES", [7, 8]),
            ("EVALUACION DE VIDA UTIL", [7, 8, 9, 10]),
            ("REGISTRO SANITARIO", [11, 12, 13, 14]),
            ("DISENO DE ARTE", [7, 8, 9, 10]),
            ("COMPRA DE INSUMOS", [11, 12, 13, 14]),
            ("PRUEBA SEMI INDUSTRIAL", [15, 16]),
            ("PRUEBA INDUSTRIAL", [17, 18]),
            ("ENTREGA DE DOCUMENTOS", [19, 20]),
            ("LANZAMIENTO", [21, 22]),
            ("SEGUIMIENTO", [23, 24, 25, 26]),
        ],
    },
    "25g Y 100g CEREALES Q FOOD": {
        "priority": "MODERADA",
        "status": "En curso",
        "first_month": datetime.date(2025, 8, 1),
        "notes": "Chocolate y natural. Corroborar informacion y cereal natural.",
        "tasks": [
            ("INICIO", [3]),
            ("PLANTEAMIENTO DE PROYECTO", [3]),
            ("EVALUACION DE RIESGOS", [3, 4]),
            ("REQUERIMIENTOS Y COMPRAS", [3, 4]),
            ("PRUEBAS PILOTO", [3, 4, 5]),
            ("EVALUACION SENSORIAL", [3, 4, 5, 6]),
            ("ANALISIS DE PRODUCTO", [7, 8, 9, 10]),
            ("EVALUACION DE ENVASES", [7, 8]),
            ("EVALUACION DE VIDA UTIL", [7, 8, 9, 10]),
            ("REGISTRO SANITARIO", [11, 12, 13, 14]),
            ("COMPRA DE INSUMOS", [11, 12, 13, 14]),
            ("PRUEBA SEMI INDUSTRIAL", [15, 16]),
            ("PRUEBA INDUSTRIAL", [17, 18]),
            ("ENTREGA DE DOCUMENTOS", [19, 20]),
            ("LANZAMIENTO", [21, 22]),
            ("SEGUIMIENTO", [23, 24, 25, 26]),
        ],
    },
    "FOUR PACK BABY FOODS (Produccion)": {
        "priority": "MODERADA",
        "status": "En curso",
        "first_month": datetime.date(2025, 12, 1),
        "notes": "Fase de produccion industrial.",
        "tasks": [
            ("PRUEBA SEMI INDUSTRIAL", [18]),
            ("PRUEBA INDUSTRIAL", [19, 20]),
            ("ENTREGA DE DOCUMENTOS", [21, 22]),
            ("LANZAMIENTO", [23, 24]),
            ("SEGUIMIENTO", [25, 26, 27, 28, 29, 30, 31]),
        ],
    },
}

additional_projects = [
    {"name": "CEREALES MASS", "priority": "URGENTE", "status": "En espera",
     "notes": "Envio de muestras jueves 16 de octubre. A la espera de respuesta del cliente."},
    {"name": "BARRAS PROTEICAS GLORIA", "priority": "MODERADA", "status": "No iniciada",
     "notes": "Contactar con el cliente. Fecha limite: 23-10-25"},
    {"name": "BASTONES EXTRUIDOS PARA BEBES", "priority": "MODERADA", "status": "En curso",
     "notes": "Proyecto finalizado. Produccion industrial 3 batch x 1200 und. Estudio vida util acelerado."},
    {"name": "REEMPAQUE GALLETAS ARCOR", "priority": "MODERADA", "status": "Completado",
     "notes": "Formula ok, Lab ok, Registro ok, Prueba industrial ok, Bobinas ok."},
    {"name": "GALLETA TACO", "priority": "MODERADA", "status": "Pendiente",
     "notes": "Consultar con Gianella. Formula ok, laboratorio y registro pendientes."},
    {"name": "PAPILLAS", "priority": "MODERADA", "status": "Pendiente",
     "notes": "Visita a San Marcos de parte de Susan para evaluar area de calidad."},
    {"name": "BB QFOOD NUEVOS PRODUCTOS", "priority": "MODERADA", "status": "Pendiente",
     "notes": "Puff fresa y arandano. Crunchie zanahoria y mango. Todo pendiente."},
    {"name": "EXTRUIDO SOLAMENTE HORNEADO", "priority": "MODERADA", "status": "Pendiente",
     "notes": "Nuevo concepto. Bobinas ok, resto pendiente."},
    {"name": "REFORMULACION BARRAS ENERGETICAS QFOOD", "priority": "MODERADA", "status": "Pendiente",
     "notes": "Se enviara la formula tentativa. Bobinas ok, resto pendiente."},
    {"name": "NUEVAS GALLETAS ARCOR", "priority": "MODERADA", "status": "Pendiente",
     "notes": "Nos haran entrega de su nueva cobertura. Todo pendiente."},
    {"name": "BABY FOOD PARA MEXICO", "priority": "MODERADA", "status": "Pendiente",
     "notes": "100% peruano. Enviar minimo de compra. Todo pendiente."},
    {"name": "PRESUPUESTO DE NUEVOS PRODUCTOS", "priority": "MODERADA", "status": "Pendiente",
     "notes": "Se estimara en el presupuesto para cada proyecto."},
]

resources_list = [
    ("Gerencia", "G"),
    ("Jefe ID", "JID"),
    ("Coordinador ID", "CID"),
    ("Asistente ID", "AID"),
    ("Jefe de Calidad", "JC"),
    ("Jefe de Produccion", "JP"),
    ("Marketing", "MKT"),
    ("Area de Compras", "COMP"),
]

resource_map = {
    "INICIO": "Gerencia;Marketing",
    "PLANTEAMIENTO DE PROYECTO": "Jefe ID;Coordinador ID;Asistente ID",
    "EVALUACION DE RIESGOS": "Jefe ID;Coordinador ID",
    "REQUERIMIENTOS Y COMPRAS": "Jefe ID;Coordinador ID",
    "PRUEBAS PILOTO": "Jefe ID;Asistente ID",
    "EVALUACION SENSORIAL": "Jefe ID;Asistente ID",
    "ANALISIS DE PRODUCTO": "Jefe ID;Jefe de Calidad",
    "EVALUACION DE ENVASES": "Jefe ID;Asistente ID",
    "EVALUACION DE VIDA UTIL": "Jefe ID;Coordinador ID",
    "REGISTRO SANITARIO": "Jefe ID;Coordinador ID",
    "DISENO DE ARTE": "Jefe ID;Marketing",
    "COMPRA DE INSUMOS": "Jefe ID;Area de Compras;Marketing",
    "PRUEBA SEMI INDUSTRIAL": "Jefe ID;Jefe de Produccion",
    "PRUEBA INDUSTRIAL": "Jefe ID;Jefe de Produccion",
    "ENTREGA DE DOCUMENTOS": "Jefe ID;Coordinador ID;Asistente ID",
    "LANZAMIENTO": "Jefe ID;Jefe de Calidad;Jefe de Produccion",
    "SEGUIMIENTO": "Jefe ID;Coordinador ID;Asistente ID",
}

priority_map = {"URGENTE": 900, "ALTA": 700, "MODERADA": 500, "BAJA": 300}

def fmt_date(d):
    return d.strftime("%Y-%m-%dT08:00:00")

def fmt_duration_str(days):
    return f"PT{days * 8}H0M0S"

# Build XML
ns = "http://schemas.microsoft.com/project"
root = ET.Element("Project", xmlns=ns)
ET.SubElement(root, "Name").text = "GESTION DE PROYECTOS 2026"
ET.SubElement(root, "Company").text = "Q Food"
ET.SubElement(root, "Author").text = "Gestion de Proyecto"
ET.SubElement(root, "CreationDate").text = fmt_date(datetime.date(2026, 3, 4))
ET.SubElement(root, "StartDate").text = fmt_date(datetime.date(2025, 8, 1))
ET.SubElement(root, "FinishDate").text = fmt_date(datetime.date(2026, 7, 31))
ET.SubElement(root, "ScheduleFromStart").text = "1"
ET.SubElement(root, "CalendarUID").text = "1"
ET.SubElement(root, "MinutesPerDay").text = "480"
ET.SubElement(root, "MinutesPerWeek").text = "2400"
ET.SubElement(root, "DaysPerMonth").text = "20"

# Calendar
calendars = ET.SubElement(root, "Calendars")
cal = ET.SubElement(calendars, "Calendar")
ET.SubElement(cal, "UID").text = "1"
ET.SubElement(cal, "Name").text = "Standard"
ET.SubElement(cal, "IsBaseCalendar").text = "1"
weekdays = ET.SubElement(cal, "WeekDays")
for day_num in range(1, 8):
    wd = ET.SubElement(weekdays, "WeekDay")
    ET.SubElement(wd, "DayType").text = str(day_num)
    if day_num in (1, 7):
        ET.SubElement(wd, "DayWorking").text = "0"
    else:
        ET.SubElement(wd, "DayWorking").text = "1"
        wt = ET.SubElement(wd, "WorkingTimes")
        wt1 = ET.SubElement(wt, "WorkingTime")
        ET.SubElement(wt1, "FromTime").text = "08:00:00"
        ET.SubElement(wt1, "ToTime").text = "12:00:00"
        wt2 = ET.SubElement(wt, "WorkingTime")
        ET.SubElement(wt2, "FromTime").text = "13:00:00"
        ET.SubElement(wt2, "ToTime").text = "17:00:00"

# Resources
resources_el = ET.SubElement(root, "Resources")
res_uid = 0
res_name_to_uid = {}
for res_name, res_initials in resources_list:
    res_uid += 1
    res = ET.SubElement(resources_el, "Resource")
    ET.SubElement(res, "UID").text = str(res_uid)
    ET.SubElement(res, "ID").text = str(res_uid)
    ET.SubElement(res, "Name").text = res_name
    ET.SubElement(res, "Initials").text = res_initials
    ET.SubElement(res, "Type").text = "1"
    ET.SubElement(res, "CalendarUID").text = "1"
    res_name_to_uid[res_name] = res_uid

# Tasks
tasks_el = ET.SubElement(root, "Tasks")
assignments_el = ET.SubElement(root, "Assignments")
task_uid = 0
assign_uid = 0

for proj_name, proj_data in projects.items():
    task_uid += 1
    summary = ET.SubElement(tasks_el, "Task")
    ET.SubElement(summary, "UID").text = str(task_uid)
    ET.SubElement(summary, "ID").text = str(task_uid)
    ET.SubElement(summary, "Name").text = proj_name
    ET.SubElement(summary, "OutlineLevel").text = "1"
    ET.SubElement(summary, "Summary").text = "1"
    ET.SubElement(summary, "Priority").text = str(priority_map.get(proj_data["priority"], 500))
    ET.SubElement(summary, "Notes").text = f"[{proj_data['status']}] {proj_data['notes']}"

    fm = proj_data["first_month"]
    all_starts = []
    all_ends = []

    for task_name, weeks in proj_data["tasks"]:
        start, end = weeks_to_dates(fm, weeks)
        if start and end:
            all_starts.append(start)
            all_ends.append(end)

    if all_starts and all_ends:
        ET.SubElement(summary, "Start").text = fmt_date(min(all_starts))
        ET.SubElement(summary, "Finish").text = fmt_date(max(all_ends))

    for task_name, weeks in proj_data["tasks"]:
        task_uid += 1
        start, end = weeks_to_dates(fm, weeks)
        if not start or not end:
            continue

        task = ET.SubElement(tasks_el, "Task")
        ET.SubElement(task, "UID").text = str(task_uid)
        ET.SubElement(task, "ID").text = str(task_uid)
        ET.SubElement(task, "Name").text = task_name
        ET.SubElement(task, "OutlineLevel").text = "2"
        ET.SubElement(task, "Summary").text = "0"
        ET.SubElement(task, "Start").text = fmt_date(start)
        ET.SubElement(task, "Finish").text = fmt_date(end)
        dur_days = (end - start).days + 1
        biz_days = max(1, dur_days * 5 // 7)
        ET.SubElement(task, "Duration").text = fmt_duration_str(biz_days)
        ET.SubElement(task, "Priority").text = str(priority_map.get(proj_data["priority"], 500))

        res_names = resource_map.get(task_name, "")
        for rn in res_names.split(";"):
            rn = rn.strip()
            if rn in res_name_to_uid:
                assign_uid += 1
                assign = ET.SubElement(assignments_el, "Assignment")
                ET.SubElement(assign, "UID").text = str(assign_uid)
                ET.SubElement(assign, "TaskUID").text = str(task_uid)
                ET.SubElement(assign, "ResourceUID").text = str(res_name_to_uid[rn])

for ap in additional_projects:
    task_uid += 1
    task = ET.SubElement(tasks_el, "Task")
    ET.SubElement(task, "UID").text = str(task_uid)
    ET.SubElement(task, "ID").text = str(task_uid)
    ET.SubElement(task, "Name").text = ap["name"]
    ET.SubElement(task, "OutlineLevel").text = "1"
    ET.SubElement(task, "Summary").text = "0"
    ET.SubElement(task, "Priority").text = str(priority_map.get(ap["priority"], 500))
    ET.SubElement(task, "Notes").text = f"[{ap['status']}] {ap['notes']}"
    ET.SubElement(task, "Milestone").text = "1"
    ET.SubElement(task, "Duration").text = "PT0H0M0S"

# Write
xml_str = ET.tostring(root, encoding="unicode", xml_declaration=False)
parsed = minidom.parseString(xml_str)
pretty = parsed.toprettyxml(indent="  ", encoding="UTF-8")

output_path = "C:/Users/caslu/OneDrive/Documentos/GESTION_DE_PROYECTO_2026.xml"
with open(output_path, "wb") as f:
    f.write(pretty)

print(f"OK: {output_path}")
print(f"Tasks: {task_uid}, Assignments: {assign_uid}")
