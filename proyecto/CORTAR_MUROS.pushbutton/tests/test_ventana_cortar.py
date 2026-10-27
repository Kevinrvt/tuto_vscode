# -*- coding: utf-8 -*-
"""El boton sin Revit ni WPF (CPython): el XAML y los nombres que usa script.py, la paleta de los dos temas, la
configuracion recordada, la eleccion de parametros comunes y que el codigo no use sintaxis que IronPython 2.7 no
entiende (el motor de pyRevit)."""
import ast
import importlib.util
import json
import re
import sys
import tempfile
import types
import unittest
import xml.dom.minidom
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config_cortar as CFG

SCRIPT = (ROOT / "script.py").read_text(encoding="utf-8")
XAML = (ROOT / "ui_cortar_muros.xaml").read_text(encoding="utf-8")
DOM = xml.dom.minidom.parseString(XAML.encode("utf-8"))
FUENTES = sorted(ROOT.glob("*.py"))


def nombres_xaml():
    nombres = set()
    for nodo in DOM.getElementsByTagName("*"):
        if nodo.hasAttribute("x:Name"):
            nombres.add(nodo.getAttribute("x:Name"))
    return nombres


def constante(nombre):
    for n in ast.parse(SCRIPT).body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == nombre for t in n.targets):
            return ast.literal_eval(n.value)
    raise KeyError(nombre)


def cargar_script():
    """script.py con dobles de pyRevit, de la API de Revit y de WPF (solo lo que se usa al cargarlo)."""
    def modulo(nombre, **attrs):
        m = types.ModuleType(nombre)
        for k, v in attrs.items():
            setattr(m, k, v)
        return m

    class WPFWindow(object):
        def __init__(self, xaml, **opciones):self.xaml = xaml

    forms = modulo("pyrevit.forms", WPFWindow=WPFWindow, alert=lambda *a, **k: None)
    db = modulo("Autodesk.Revit.DB", Wall=type("Wall", (), {}), ElementId=object)
    sel = modulo("Autodesk.Revit.UI.Selection", ISelectionFilter=object,
                 ObjectType=types.SimpleNamespace(Element="Element"))
    dobles = {"pyrevit": modulo("pyrevit", forms=forms), "pyrevit.forms": forms, "Autodesk": modulo("Autodesk"),
              "Autodesk.Revit": modulo("Autodesk.Revit", DB=db), "Autodesk.Revit.DB": db,
              "Autodesk.Revit.UI": modulo("Autodesk.Revit.UI", Selection=sel), "Autodesk.Revit.UI.Selection": sel,
              "System": modulo("System"), "System.Windows": modulo("System.Windows"),
              "System.Collections": modulo("System.Collections"),
              "System.Collections.Generic": modulo("System.Collections.Generic", List={})}
    for sub in ("Controls", "Media", "Shapes"):
        dobles["System.Windows." + sub] = modulo("System.Windows." + sub)
    spec = importlib.util.spec_from_file_location("script_cortar_cpython", str(ROOT / "script.py"))
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, dobles):
        spec.loader.exec_module(mod)
    return mod, db


class XamlTests(unittest.TestCase):
    def test_todo_control_que_usa_script_existe_en_el_xaml(self):
        usados = set(re.findall(r"self\.((?:Txt|Cmb|Chk|Rb|Btn|Canvas|Panel|Fila|Encabezado)\w+)", SCRIPT))
        faltan = usados - nombres_xaml()
        self.assertFalse(faltan, "script.py usa controles que no estan en ui_cortar_muros.xaml: {}".format(faltan))

    def test_cada_color_del_xaml_cambia_con_el_tema(self):
        colores = set(re.findall(r'<SolidColorBrush x:Key="(\w+)"', XAML))
        tema = constante("COLORES_TEMA")
        self.assertEqual(colores - set(tema), set(), "colores que el tema oscuro no cambiaria")
        usados = set(re.findall(r"DynamicResource (\w+)", XAML)) | set(re.findall(r'SetResourceReference\([^,]+, *"(\w+)"', SCRIPT))
        self.assertEqual(usados - set(tema) - {"FuenteInterfaz"}, set(), "recursos sin definir")
        for par in tema.values():
            self.assertEqual(len(par), 2)

    def test_modos_de_corte_son_radios_del_mismo_grupo(self):
        radios = [n for n in DOM.getElementsByTagName("RadioButton")]
        self.assertEqual(sorted(r.getAttribute("x:Name") for r in radios), ["RbAlzadas", "RbUna", "RbVarias"])


class ScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.db = cargar_script()

    def test_parametros_comunes(self):
        infos = [{"textos": [u"Comentarios", u"00_SECTOR", u"Marca"]}, {"textos": [u"00_SECTOR", u"Comentarios"]},
                 {"textos": [u"otro"], "omitir": u"muro cortina"}]
        self.assertEqual(self.mod.parametros_comunes(infos), [u"00_SECTOR", u"Comentarios"])
        self.assertEqual(self.mod.parametros_comunes([{"omitir": u"x"}]), [])

    def test_es_muro_y_cancelado(self):
        self.assertTrue(self.mod.es_muro(self.db.Wall()))
        self.assertFalse(self.mod.es_muro(object()))
        self.assertTrue(self.mod._cancelado(type("OperationCanceledException", (Exception,), {})()))
        self.assertFalse(self.mod._cancelado(ValueError("otro")))


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ruta = str(Path(self.tmp.name) / "cfg.json")
        self.parche = mock.patch.object(CFG, "RUTA_CONFIG", self.ruta)
        self.parche.start()

    def tearDown(self):
        self.parche.stop()
        self.tmp.cleanup()

    def test_sin_archivo_usa_los_valores_por_defecto(self):
        self.assertEqual(CFG.cargar(), CFG.DEFECTO)

    def test_valores_rotos_se_reemplazan(self):
        with open(self.ruta, "w") as f:
            json.dump({"modo": "diagonal", "altura": 3, "copiar_marca": "si", "alzada": u"1.50",
                       "TemaInterfaz": "Oscuro"}, f)
        cfg = CFG.cargar()
        self.assertEqual(cfg["modo"], CFG.DEFECTO["modo"])
        self.assertEqual(cfg["altura"], CFG.DEFECTO["altura"])
        self.assertEqual(cfg["copiar_marca"], True)
        self.assertEqual(cfg["alzada"], u"1.50")
        self.assertEqual(cfg["TemaInterfaz"], "Oscuro")

    def test_guardar_y_tema(self):
        CFG.guardar({"modo": "alzadas", "alzada": u"1.30", "clave_desconocida": 1})
        CFG.guardar_tema("Oscuro")
        cfg = CFG.cargar()
        self.assertEqual((cfg["modo"], cfg["alzada"], cfg["TemaInterfaz"]), ("alzadas", u"1.30", "Oscuro"))
        with open(self.ruta) as f:
            self.assertNotIn("clave_desconocida", json.load(f))

    def test_las_opciones_por_defecto_son_validas_para_la_ventana(self):
        self.assertIn(CFG.DEFECTO["modo"], ("una", "varias", "alzadas"))


class CompatibilidadIronPythonTests(unittest.TestCase):
    """pyRevit corre el boton en IronPython 2.7; estas pruebas en CPython 3. Una sintaxis de Python 3 pasaria todas
    las pruebas y solo fallaria dentro de Revit (como paso en PLACA con max(..., default=...))."""

    def test_sin_sintaxis_de_python3(self):
        for ruta in FUENTES:
            arbol = ast.parse(ruta.read_text(encoding="utf-8"))
            for nodo in ast.walk(arbol):
                donde = "{}:{}".format(ruta.name, getattr(nodo, "lineno", "?"))
                self.assertNotIsInstance(nodo, (ast.JoinedStr, ast.NamedExpr, ast.Nonlocal, ast.YieldFrom,
                                                ast.AnnAssign, ast.AsyncFunctionDef, ast.Await), donde)
                if isinstance(nodo, ast.Starred):
                    self.fail("{} -- desempaquetado con * (Python 3)".format(donde))
                if isinstance(nodo, ast.arguments):
                    self.assertFalse(nodo.kwonlyargs, "{} -- argumentos solo-por-nombre".format(donde))
                if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id in ("max", "min"):
                    self.assertFalse([k for k in nodo.keywords if k.arg == "default"], donde)
                if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id == "print":
                    self.fail("{} -- print()".format(donde))

    def test_cada_modulo_declara_utf8(self):
        for ruta in FUENTES:
            primera = ruta.read_text(encoding="utf-8").splitlines()[0]
            self.assertIn("coding: utf-8", primera, ruta.name)


if __name__ == "__main__":
    unittest.main()
