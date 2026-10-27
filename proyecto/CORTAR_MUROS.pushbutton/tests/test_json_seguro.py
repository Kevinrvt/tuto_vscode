# -*- coding: utf-8 -*-
"""json_seguro: el JSON que escribe el boton es ASCII puro y se lee igual con json.load, con tildes y todo.

El modulo json de IronPython 2.7 falla al escribir textos con tildes ("UnicodeDecodeError ... byte 0xf3", con un tipo
de muro llamado "Partición..."); en CPython no, asi que las pruebas no pueden reproducirlo. Por eso, ademas de probar
json_seguro, se exige que ningun modulo del boton escriba con json.dump / json.dumps."""
import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config_cortar as CFG
import diagnostico as DG
import json_seguro as JS

CON_TILDES = {u"tipo": u"Partición con capa de acabado", u"ñandú": [u"«A1»", u"ó", u"€", u"😀"],
              u"comillas": u'dice "hola" \\ fin', u"control": u"a\nb\tc\x01", u"números": [1, -2, 1.5, 1e-05, 0.0],
              u"vacíos": [{}, [], u""], u"logicos": [True, False, None]}


class JsonSeguroTests(unittest.TestCase):
    def test_ida_y_vuelta_con_tildes(self):
        texto = JS.a_json(CON_TILDES)
        self.assertTrue(all(ord(c) < 128 for c in texto), "el texto escrito tiene que ser ASCII puro")
        self.assertEqual(json.loads(texto), CON_TILDES)

    def test_valores_raros(self):
        self.assertEqual(json.loads(JS.a_json({"inf": float("inf"), "nan": float("nan"), 3: (1, 2), "s": {7}})),
                         {"inf": None, "nan": None, "3": [1, 2], "s": [7]})
        self.assertEqual(JS.cadena(u"ó"), u'"\\u00f3"')

    def test_ningun_modulo_escribe_con_json_dump(self):
        for ruta in sorted(ROOT.glob("*.py")):
            for nodo in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))):
                if isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name) and nodo.value.id == "json":
                    self.assertNotIn(nodo.attr, ("dump", "dumps"),
                                     "{}:{} usa json.{}: en IronPython falla con tildes, usa json_seguro.a_json"
                                     .format(ruta.name, nodo.lineno, nodo.attr))


class ArchivosConTildesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_diagnostico_con_tipo_de_muro_con_tilde(self):
        d = DG.Diagnostico()
        d.poner("muros", [{"tipo": u"Partición con capa", "estado": u"Revit no confirmó"}])
        ruta = d.guardar(self.tmp.name)
        with open(ruta) as f:
            self.assertEqual(json.load(f)["muros"][0]["tipo"], u"Partición con capa")

    def test_diagnostico_nunca_lanza(self):
        d = DG.Diagnostico()
        d.datos["raro"] = object()
        with mock.patch.object(DG.JS, "a_json", side_effect=[ValueError("roto"), u'{"error": 1}']):
            ruta = d.guardar(self.tmp.name)
        with open(ruta) as f:
            self.assertEqual(json.load(f), {"error": 1})
        with mock.patch.object(DG.JS, "a_json", side_effect=ValueError("roto")):
            self.assertIsNone(d.guardar(self.tmp.name))

    def test_configuracion_con_parametro_con_tilde(self):
        with mock.patch.object(CFG, "RUTA_CONFIG", os.path.join(self.tmp.name, "cfg.json")):
            CFG.guardar({"param_tramo": u"Descripción", "escribir_tramo": True})
            cfg = CFG.cargar()
        self.assertEqual((cfg["param_tramo"], cfg["escribir_tramo"]), (u"Descripción", True))


if __name__ == "__main__":
    unittest.main()
