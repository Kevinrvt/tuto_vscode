# -*- coding: utf-8 -*-
"""El diagnostico (diagnostico.py): que el JSON se escriba siempre, que traiga cada paso del corte con los elementos
que Revit rechazo, y que no se acumulen archivos sin fin."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
sys.path.insert(0, str(AQUI))
import diagnostico as DG
import test_corte_simulado as T


class ObjetoDeNet(object):
    def __str__(self):return "Autodesk.Revit.DB.XYZ(1, 2, 3)"


class DiagnosticoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_limpio_convierte_lo_que_json_no_sabe_escribir(self):
        datos = DG.limpio({"a": (1, 2.1234567891), 3: {ObjetoDeNet()}, "b": [None, True, u"ñ"]})
        self.assertEqual(datos, {"a": [1, 2.123457], "3": ["Autodesk.Revit.DB.XYZ(1, 2, 3)"], "b": [None, True, u"ñ"]})
        json.dumps(datos)

    def test_guarda_con_fecha_y_ultimo(self):
        d = DG.Diagnostico()
        d.paso("prueba", valor=ObjetoDeNet())
        ruta = d.guardar(self.tmp.name)
        self.assertTrue(os.path.basename(ruta).startswith("cortar_muros_"))
        with open(os.path.join(self.tmp.name, "ultimo.json")) as f:
            datos = json.load(f)
        self.assertEqual(datos["version"], DG.VERSION)
        self.assertEqual(datos["pasos"][0]["paso"], "prueba")

    def test_si_no_puede_escribir_usa_temp(self):
        d = DG.Diagnostico()
        bloqueada = os.path.join(self.tmp.name, "archivo")
        open(bloqueada, "w").close()                       # una carpeta que en realidad es un archivo
        with mock.patch.dict(os.environ, {"TEMP": self.tmp.name}):
            ruta = d.guardar(os.path.join(bloqueada, "sub"))
        self.assertIn("DENOVA_cortar_muros", ruta)

    def test_conserva_solo_los_ultimos(self):
        for i in range(DG.MAX_ARCHIVOS + 5):
            open(os.path.join(self.tmp.name, "{}2026010{:02d}.json".format(DG.PREFIJO, i)), "w").close()
        DG._podar(self.tmp.name)
        self.assertEqual(len([n for n in os.listdir(self.tmp.name) if n.startswith(DG.PREFIJO)]), DG.MAX_ARCHIVOS)

    def test_registra_el_corte_paso_a_paso(self):
        doc, muros = T.modelo(rechazar_partidos=True, copia_sin_insertos=True)
        infos = [T.RC.analizar_muro(doc, m) for m in muros[1:2]]
        d = DG.Diagnostico()
        rep = T.RC.cortar_muros(doc, infos, T.opciones(), d)
        self.assertEqual(rep["fallidos"], [])
        pasos = [p["paso"] for p in d.datos["pasos"]]
        for esperado in ("intento", "plan", "originales", "copia", "hospedados_tras_copiar", "asignacion",
                         "tras_alturas", "antes_de_confirmar", "confirmar"):
            self.assertIn(esperado, pasos)
        # el primer intento (corte a 1.50, puerta partida) lo rechazo Revit: el diagnostico dice que elemento fue
        confirmaciones = [p for p in d.datos["pasos"] if p["paso"] == "confirmar"]
        self.assertEqual(len(confirmaciones), 2)
        falla = confirmaciones[0]["fallas"][0]
        self.assertIn(u"no cortan nada", falla["texto"])
        json.dumps(DG.limpio(d.datos))


if __name__ == "__main__":
    unittest.main()
