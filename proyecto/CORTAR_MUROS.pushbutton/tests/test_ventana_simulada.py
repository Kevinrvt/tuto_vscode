# -*- coding: utf-8 -*-
"""La ventana COMPLETA en CPython, con WPF simulado (MagicMock): se construye, se cambian modos, politica de cruce,
vista y tema, se navega entre muros, se dibuja la vista previa en los dos modos y se acepta. No prueba como se ve
(eso solo en Revit), pero si que ningun camino del codigo de la ventana truene: un metodo faltante, un nombre mal
escrito o una cuenta con None aparecen aqui y no al abrirla dentro de Revit."""
import importlib.util
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

DOM = xml.dom.minidom.parse(str(ROOT / "ui_cortar_muros.xaml"))


class Items(list):
    def Add(self, x):self.append(x)
    def Clear(self):del self[:]
    @property
    def Count(self):return len(self)


class Evento(object):
    """Evento de WPF: += agrega manejadores; disparar() los llama."""
    def __init__(self):self.manejadores = []
    def __iadd__(self, f):
        self.manejadores.append(f)
        return self
    def disparar(self, *a):
        for f in list(self.manejadores):
            f(None, None) if not a else f(*a)


class Control(object):
    def __init__(self, tipo):
        self.tipo = tipo
        self.Text = u""
        self.IsChecked = False
        self.IsEnabled = True
        self.SelectedIndex = 0
        self.SelectedItem = None
        self.Items = Items()
        self.Children = Items()
        self.ActualWidth, self.ActualHeight = 900.0, 520.0
        for ev in ("Click", "Checked", "TextChanged", "SelectionChanged", "SizeChanged"):
            setattr(self, ev, Evento())

    def __setattr__(self, k, v):
        object.__setattr__(self, k, v)
        if k == "IsChecked" and v is True and getattr(self, "tipo", "") == "RadioButton" and hasattr(self, "Checked"):
            self.Checked.disparar()
        if k == "Text" and hasattr(self, "TextChanged"):
            self.TextChanged.disparar()


def wpf_falso():
    m = mock.MagicMock()
    return m


def cargar():
    def modulo(nombre, **attrs):
        mm = types.ModuleType(nombre)
        for k, v in attrs.items():
            setattr(mm, k, v)
        return mm

    controles_xaml = dict((n.getAttribute("x:Name"), n.tagName) for n in DOM.getElementsByTagName("*")
                          if n.hasAttribute("x:Name"))

    class WPFWindow(object):
        def __init__(self, xaml, **k):
            self.Width, self.Height = 1240.0, 780.0
            self.Resources = {}
            self.cerrada = False
            for nombre, tipo in controles_xaml.items():
                setattr(self, nombre, Control(tipo))
        def Close(self):self.cerrada = True
        def FindResource(self, clave):return clave

    win = mock.MagicMock()
    win.SystemParameters.WorkArea.Width, win.SystemParameters.WorkArea.Height = 1920.0, 1040.0
    forms = modulo("pyrevit.forms", WPFWindow=WPFWindow, alert=lambda *a, **k: None)
    db = modulo("Autodesk.Revit.DB", Wall=type("Wall", (), {}), ElementId=object)
    sel = modulo("Autodesk.Revit.UI.Selection", ISelectionFilter=object,
                 ObjectType=types.SimpleNamespace(Element="Element"))
    dobles = {"pyrevit": modulo("pyrevit", forms=forms), "pyrevit.forms": forms, "Autodesk": modulo("Autodesk"),
              "Autodesk.Revit": modulo("Autodesk.Revit", DB=db), "Autodesk.Revit.DB": db,
              "Autodesk.Revit.UI": modulo("Autodesk.Revit.UI", Selection=sel), "Autodesk.Revit.UI.Selection": sel,
              "System": modulo("System", Windows=win), "System.Windows": win,
              "System.Collections": modulo("System.Collections"),
              "System.Collections.Generic": modulo("System.Collections.Generic", List={}),
              "apariencia": modulo("apariencia", aplicar_tipografia=lambda v: None)}
    for sub in ("Controls", "Input", "Media", "Shapes"):
        dobles["System.Windows." + sub] = mock.MagicMock()
    spec = importlib.util.spec_from_file_location("script_cortar_simulado", str(ROOT / "script.py"))
    mod = importlib.util.module_from_spec(spec)
    parche = mock.patch.dict(sys.modules, dobles)
    parche.start()
    spec.loader.exec_module(mod)
    return mod, parche


def infos():
    ventana = {"tipo": u"ventana", "zi": 1.0, "zs": 2.2, "s0": 2.0, "s1": 3.0}
    puerta = {"tipo": u"puerta", "zi": 0.0, "zs": 2.1, "s0": 1.0, "s1": 1.9}
    hueco = {"tipo": u"hueco", "zi": 0.5, "zs": 0.9, "s0": 3.5, "s1": 4.0}
    base = {"tipo": u"Tabique 14", "nivel": u"Nivel 1", "base_offset_m": 0.0, "tope_enlazado": False,
            "base_enlazada": False, "recto": True, "textos": [u"Comentarios", u"00_SECTOR"], "omitir": None}
    muros = []
    for i, (alto, largo, ins) in enumerate(((2.59, 6.0, [ventana, hueco]), (2.59, 4.2, [puerta]), (2.59, 3.0, []))):
        d = dict(base, id=100 + i, altura_m=alto, largo_m=largo, insertos=ins)
        muros.append(d)
    muros.append(dict(base, id=200, omitir=u"es un muro cortina", altura_m=0.0, largo_m=0.0, insertos=[]))
    return muros


class VentanaSimuladaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.parche = cargar()

    @classmethod
    def tearDownClass(cls):
        cls.parche.stop()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(CFG, "RUTA_CONFIG", str(Path(self.tmp.name) / "cfg.json"))
        self.p.start()
        self.v = self.mod.VentanaCorte("ui.xaml", infos())

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_abre_con_los_valores_por_defecto(self):
        v = self.v
        self.assertEqual(v.TxtStatMuros.Text, u"4")
        self.assertEqual(v.TxtStatCortan.Text, u"3")
        self.assertEqual(v.TxtStatTramos.Text, u"6")
        self.assertEqual(v.TxtStatCruces.Text, u"2")         # la ventana y la puerta cruzan 1.50
        self.assertTrue(v.BtnCortar.IsEnabled)
        self.assertEqual(len(v.PanelMuros.Children), 4)
        self.assertEqual(len(v.PanelAtajos.Children), 4)
        self.assertTrue(v.TxtExplicaCruce.Text)
        self.assertIn(u"Comentarios", list(v.CmbParamTramo.Items))
        self.assertTrue(len(v.CanvasPrevia.Children) > 10)

    def test_modos_politicas_vistas_y_tema(self):
        v = self.v
        v.RbAlzadas.IsChecked = True
        v.TxtAlzada.Text = u"1,30"
        self.assertEqual(v.TxtStatTramos.Text, u"6")
        v.RbVarias.IsChecked = True
        v.TxtAlturas.Text = u"1.20; 2.40"
        self.assertEqual(v.TxtStatTramos.Text, u"9")
        v.RbUna.IsChecked = True
        for i, cortan in ((1, u"3"), (2, u"1"), (0, u"3")):      # mover el corte, no cortar, hueco
            v.CmbCruce.SelectedIndex = i
            v.CmbCruce.SelectionChanged.disparar()
            self.assertEqual(v.TxtStatCortan.Text, cortan)
        v.RbVistaUno.IsChecked = True
        v.BtnSiguiente.Click.disparar()
        v.BtnSiguiente.Click.disparar()
        v.BtnSiguiente.Click.disparar()                           # el muro omitido tambien se dibuja
        v.BtnAnterior.Click.disparar()
        self.assertTrue(v.TxtMuroActual.Text.startswith(u"Muro "))
        v._ver_muro(0)
        v.RbVistaTodos.IsChecked = True
        v.CmbTema.SelectedIndex = 1
        v.CmbTema.SelectionChanged.disparar()
        self.assertEqual(CFG.cargar()["TemaInterfaz"], "Oscuro")

    def test_error_desactiva_cortar_y_aceptar_guarda(self):
        v = self.v
        v.TxtAltura.Text = u"abc"
        self.assertFalse(v.BtnCortar.IsEnabled)
        self.assertIn(u"«abc»", v.TxtResumen.Text)
        v.TxtAltura.Text = u"1.40"
        v.ChkParamTramo.IsChecked = True
        v.CmbParamTramo.SelectedItem = u"00_SECTOR"
        v.ChkParamTramo.Click.disparar()
        v.aceptar(None, None)
        self.assertTrue(v.proceder and v.cerrada)
        self.assertEqual(v.resultado["valores"], [1.4])
        self.assertEqual(v.resultado["param_tramo"], u"00_SECTOR")
        self.assertEqual(CFG.cargar()["altura"], u"1.40")

    def test_canvas_pequeno_no_dibuja(self):
        self.v.CanvasPrevia.ActualWidth = 50.0
        self.v._dibujar()
        self.assertEqual(len(self.v.CanvasPrevia.Children), 0)


if __name__ == "__main__":
    unittest.main()
