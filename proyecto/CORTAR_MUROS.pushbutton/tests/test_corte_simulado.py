# -*- coding: utf-8 -*-
"""El corte COMPLETO (revit_corte.cortar_muros) sobre el Revit de juguete de _revit_simulado.py: los tres muros de la
prueba en Revit 2026 (uno con ventana de 1.00 a 2.20 m, uno con puerta de 0.00 a 2.10 m y uno liso), cortados a
1.50 m. Reproduce lo que paso en el journal -- copias de puertas y ventanas sin borrar y Revit rechazando esos muros
-- y comprueba que ahora cada puerta y ventana queda una sola vez, en su tramo y con su Id."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

AQUI = Path(__file__).resolve().parent
ROOT = AQUI.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(AQUI))
import _revit_simulado as R

PIE = 0.3048
D, E, ST = R.InternalDefinition, R.ExternalDefinition, R.StorageType


def ft(m):
    return m / PIE


def cargar_revit_corte():
    generic = types.ModuleType("System.Collections.Generic")
    generic.List = {R.ElementId: R.Lista}
    dobles = {"Autodesk": types.ModuleType("Autodesk"), "Autodesk.Revit": types.ModuleType("Autodesk.Revit"),
              "Autodesk.Revit.DB": R, "System": types.ModuleType("System"),
              "System.Collections": types.ModuleType("System.Collections"), "System.Collections.Generic": generic}
    spec = importlib.util.spec_from_file_location("revit_corte_simulado", str(ROOT / "revit_corte.py"))
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, dobles):
        spec.loader.exec_module(mod)
    return mod


RC = cargar_revit_corte()


def modelo(rechazar_partidos=False, copia_sin_insertos=False, rechazar_sobresale_arriba=False):
    doc = R.Documento(rechazar_partidos, copia_sin_insertos, rechazar_sobresale_arriba)
    doc.agregar(R.Level(1, 0.0, u"Nivel 1"))
    doc.agregar(R.Level(2, ft(2.60), u"Nivel 2"))

    def muro(eid, y):
        params = [R.Parametro(D(u"Restricción de base", 1), ST.ElementId, R.ElementId(1)),
                  R.Parametro(D(u"Desfase de base", 2), ST.Double, 0.0),
                  R.Parametro(D(u"Restricción superior", 3), ST.ElementId, R.ElementId(2)),
                  R.Parametro(D(u"Desfase superior", 4), ST.Double, 0.0),
                  R.Parametro(D(u"Altura desconectada", 5), ST.Double, ft(2.60)),
                  R.Parametro(D(u"Marca", 6), ST.String, u"M-{}".format(eid)),
                  R.Parametro(D(u"Comentarios", 9), ST.String, u"tabique"),
                  R.Parametro(E(u"00_SECTOR"), ST.String, u"S1")]
        return doc.agregar(R.Wall(eid, params, R.Line(R.XYZ(0.0, y, 0.0), R.XYZ(ft(6.0), y, 0.0))))

    con_ventana, con_puerta, liso = muro(10, 0.0), muro(20, 30.0), muro(30, 60.0)
    doc.agregar(R.FamilyInstance(11, con_ventana, R.XYZ(ft(2.5), 0.0, 0.0), ft(1.0), ft(2.2), ft(1.2),
                                 R.BuiltInCategory.OST_Windows, 600))
    doc.agregar(R.FamilyInstance(21, con_puerta, R.XYZ(ft(1.5), 30.0, 0.0), 0.0, ft(2.1), ft(0.8),
                                 R.BuiltInCategory.OST_Doors, 700))
    return doc, [con_ventana, con_puerta, liso]


def opciones(**k):
    op = {"modo": "una", "valores": [1.5], "referencia": "base", "minimo_cm": 5.0, "original": "inferior",
          "copiar_marca": True, "cruce": "hueco", "param_tramo": None, "prefijo": u"A"}
    op.update(k)
    return op


def cortar(doc, muros, **k):
    infos = [RC.analizar_muro(doc, m) for m in muros]
    return infos, RC.cortar_muros(doc, infos, opciones(**k))


def puertas_y_ventanas(doc):
    """{id: id del muro que la hospeda} de las puertas y ventanas que quedan en el modelo."""
    return dict((e.Id.Value, e.Host.Id.Value) for e in doc.els.values() if isinstance(e, R.FamilyInstance))


def altura_m(muro):
    lo, hi = muro.rango()
    return round(lo * PIE, 3), round(hi * PIE, 3)


class AnalisisTests(unittest.TestCase):
    def test_lee_puertas_y_ventanas_antes_de_cortar(self):
        doc, muros = modelo()
        infos = [RC.analizar_muro(doc, m) for m in muros]
        ventana = infos[0]["insertos"][0]
        self.assertEqual(ventana["tipo"], u"ventana")
        self.assertAlmostEqual(ventana["zi"], 1.0)
        self.assertAlmostEqual(ventana["zs"], 2.2)
        self.assertAlmostEqual(ventana["s1"] - ventana["s0"], 1.2)
        self.assertEqual(infos[1]["insertos"][0]["tipo"], u"puerta")
        self.assertEqual(infos[2]["insertos"], [])
        self.assertAlmostEqual(infos[0]["altura_m"], 2.6)
        self.assertAlmostEqual(infos[0]["largo_m"], 6.0)


class CorteTests(unittest.TestCase):
    def test_cortar_y_abrir_hueco_conserva_cada_puerta_y_ventana_una_vez(self):
        doc, muros = modelo()
        _, rep = cortar(doc, muros)
        self.assertEqual(rep["fallidos"], [])
        self.assertEqual(len(rep["cortados"]), 3)
        # la ventana y la puerta ORIGINALES siguen (mismo Id) en el tramo inferior, que es el muro original
        self.assertEqual(puertas_y_ventanas(doc), {11: 10, 21: 20})
        self.assertEqual(altura_m(muros[0]), (0.0, 1.5))
        # en el tramo de arriba se abrio un hueco donde cruzan el corte
        copias = dict((c["id"], c["piezas"][1]) for c in rep["cortados"])
        huecos = sorted((m, round(a * PIE, 2), round(b * PIE, 2)) for m, a, b in doc.huecos)
        self.assertEqual(huecos, sorted([(copias[10], 1.5, 2.2), (copias[20], 1.5, 2.1)]))
        for c in rep["cortados"]:
            self.assertEqual(c["diferencias"], [])
        self.assertEqual(doc.GetElement(R.ElementId(copias[10])).valor(6), u"M-10")      # la Marca se copio

    def test_copyelement_que_no_devuelve_las_puertas_copiadas(self):
        # Lo que paso con la version 2.2 en Revit 2026: la copia de la puerta no estaba en lo que devolvio
        # CopyElement, no se borro y Revit rechazo el muro ("no cortan nada"), tambien al reintentar.
        doc, muros = modelo(copia_sin_insertos=True)
        _, rep = cortar(doc, muros)
        self.assertEqual(rep["fallidos"], [])
        self.assertEqual(puertas_y_ventanas(doc), {11: 10, 21: 20})

    def test_copyelement_sin_puertas_y_revit_que_rechaza_la_puerta_abajo(self):
        doc, muros = modelo(rechazar_sobresale_arriba=True, copia_sin_insertos=True)
        _, rep = cortar(doc, muros)
        self.assertEqual(rep["fallidos"], [])
        self.assertEqual(len(puertas_y_ventanas(doc)), 2)
        for m in muros:
            self.assertEqual(altura_m(m), (0.0, 1.5))

    def test_las_copias_sobrantes_se_borran_antes_de_cambiar_alturas(self):
        # Revit ve el modelo al regenerar: si al cambiar alturas aun hay dos ventanas iguales, las rechaza
        doc, muros = modelo()
        cortar(doc, muros[:1])
        borrar = [i for i, r in enumerate(doc.registro) if r[0] == "borrar"]
        alturas = [i for i, r in enumerate(doc.registro) if r[0] == "altura"]
        self.assertTrue(borrar)
        self.assertLess(max(borrar), min(alturas))

    def test_si_revit_no_la_acepta_abajo_queda_entera_arriba_sin_mover_el_corte(self):
        # Se parten los muros, no las puertas ni las ventanas, y la altura de corte se respeta siempre.
        doc, muros = modelo(rechazar_sobresale_arriba=True)
        _, rep = cortar(doc, muros)
        self.assertEqual(rep["fallidos"], [])
        por_id = dict((c["id"], c) for c in rep["cortados"])
        self.assertTrue(any(u"tramo de arriba" in a for a in por_id[10]["avisos"]))
        for m in muros:
            self.assertEqual(altura_m(m), (0.0, 1.5))                 # el corte sigue a 1.50 en los tres
        vivos = puertas_y_ventanas(doc)
        self.assertEqual(sorted(vivos.values()), sorted([por_id[10]["piezas"][1], por_id[20]["piezas"][1]]))
        # el espacio de la puerta y de la ventana queda libre en el tramo de abajo (el original)
        huecos = sorted((m, round(a * PIE, 2), round(b * PIE, 2)) for m, a, b in doc.huecos)
        self.assertEqual(huecos, [(10, 1.0, 1.5), (20, 0.0, 1.5)])

    def test_si_revit_no_acepta_ninguna_el_muro_queda_como_estaba(self):
        doc, muros = modelo(rechazar_partidos=True)
        _, rep = cortar(doc, muros)
        self.assertEqual(sorted(i for i, _ in rep["fallidos"]), [10, 20])
        self.assertEqual(altura_m(muros[0]), (0.0, 2.6))              # sin cambios: ni partido ni con otro corte
        self.assertEqual(altura_m(muros[1]), (0.0, 2.6))
        self.assertEqual(puertas_y_ventanas(doc), {11: 10, 21: 20})
        self.assertEqual(doc.huecos, [])
        self.assertEqual(altura_m(muros[2]), (0.0, 1.5))              # el muro liso si se corta

    def test_mover_el_corte_desde_el_inicio(self):
        doc, muros = modelo(rechazar_partidos=True)
        _, rep = cortar(doc, muros, cruce="ajustar")
        self.assertEqual(rep["fallidos"], [])
        self.assertFalse(any(u"Revit no aceptó" in a for c in rep["cortados"] for a in c["avisos"]))
        self.assertEqual(altura_m(muros[0]), (0.0, 1.0))

    def test_no_cortar_ese_muro(self):
        doc, muros = modelo()
        _, rep = cortar(doc, muros, cruce="omitir")
        self.assertEqual(sorted(i for i, _ in rep["omitidos"]), [10, 20])
        self.assertEqual(len(rep["cortados"]), 1)
        self.assertEqual(altura_m(muros[0]), (0.0, 2.6))
        self.assertEqual(puertas_y_ventanas(doc), {11: 10, 21: 20})

    def test_original_arriba(self):
        doc, muros = modelo()
        _, rep = cortar(doc, muros[:2], original="superior")
        self.assertEqual(rep["fallidos"], [])
        vivos = puertas_y_ventanas(doc)
        self.assertEqual(len(vivos), 2)
        # el original es el tramo de arriba: la ventana y la puerta (base abajo) pasan a la copia de abajo
        for c in rep["cortados"]:
            self.assertIn(c["piezas"][0], vivos.values())
        self.assertEqual(altura_m(muros[0]), (1.5, 2.6))


if __name__ == "__main__":
    unittest.main()
