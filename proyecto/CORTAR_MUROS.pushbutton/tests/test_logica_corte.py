# -*- coding: utf-8 -*-
"""La logica del corte (logica_corte.py), sin Revit ni WPF.

    python -m unittest discover -s tests -p "test_*.py"
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import logica_corte as LC


def ops(**k):
    base = {"modo": LC.MODO_UNA, "valores": [1.5], "error_valores": None, "referencia": LC.REF_BASE,
            "minimo_cm": 5.0, "original": LC.ORIGINAL_INFERIOR, "param_tramo": None, "prefijo": u"A"}
    base.update(k)
    return base


def muro(altura=2.5, base_offset=0.0, **k):
    info = {"id": 1, "altura_m": altura, "base_offset_m": base_offset, "tope_enlazado": False,
            "base_enlazada": False, "omitir": None}
    info.update(k)
    return info


class LecturaTests(unittest.TestCase):
    def test_numeros_con_punto_coma_y_unidad(self):
        self.assertEqual(LC.leer_numero(u"1.50"), 1.5)
        self.assertEqual(LC.leer_numero(u"1,50"), 1.5)
        self.assertEqual(LC.leer_numero(u" 2 m "), 2.0)
        self.assertEqual(LC.leer_numero(u".5"), 0.5)
        for malo in (u"", u"abc", u"1.5.2", None, u"1,5,2"):
            self.assertIsNone(LC.leer_numero(malo), malo)

    def test_lista_separada_por_punto_y_coma_o_espacios(self):
        self.assertEqual(LC.leer_lista(u"1.20; 2,40  3"), ([1.2, 2.4, 3.0], None))
        self.assertEqual(LC.leer_lista(u""), ([], None))
        self.assertEqual(LC.leer_lista(u"1.2; x"), (None, u"x"))


class TramosTests(unittest.TestCase):
    def test_un_corte(self):
        self.assertEqual(LC.tramos(2.5, [1.5], 0.05), ([(0.0, 1.5), (1.5, 2.5)], []))

    def test_cortes_fuera_o_que_dejan_tiras_se_ignoran(self):
        tramos, ignorados = LC.tramos(2.5, [3.0, 1.5, 2.48, 1.52, 0.02, -1.0], 0.05)
        self.assertEqual(tramos, [(0.0, 1.5), (1.5, 2.5)])
        self.assertEqual(sorted(ignorados), [-1.0, 0.02, 1.52, 2.48, 3.0])

    def test_alzadas_desde_la_base_hasta_el_tope(self):
        self.assertEqual(LC.cortes_pedidos(ops(modo=LC.MODO_ALZADAS, valores=[1.2]), 2.5, 0.0), [1.2, 2.4])
        # el corte que cae justo en el tope no se hace: 2.60 / 1.30 = 2 alzadas exactas
        self.assertEqual(LC.cortes_pedidos(ops(modo=LC.MODO_ALZADAS, valores=[1.3]), 2.6, 0.0), [1.3])
        tramos, _ = LC.tramos(2.5, [1.2, 2.4], 0.05)
        self.assertEqual(len(tramos), 3)
        self.assertAlmostEqual(tramos[-1][1] - tramos[-1][0], 0.1)

    def test_alzadas_tienen_tope_de_tramos(self):
        self.assertLessEqual(len(LC.cortes_pedidos(ops(modo=LC.MODO_ALZADAS, valores=[0.01]), 3.0, 0.0)), LC.MAX_TRAMOS)

    def test_medido_desde_el_nivel_descuenta_el_desfase_de_base(self):
        cortes = LC.cortes_pedidos(ops(referencia=LC.REF_NIVEL), 2.5, 0.10)
        self.assertAlmostEqual(cortes[0], 1.40)
        self.assertEqual(LC.cortes_pedidos(ops(), 2.5, 0.10), [1.5])

    def test_una_altura_usa_solo_el_primer_valor(self):
        self.assertEqual(LC.cortes_pedidos(ops(valores=[1.5, 2.0]), 2.5, 0.0), [1.5])


class OriginalTests(unittest.TestCase):
    def test_preferencia(self):
        self.assertEqual(LC.pieza_original(3, LC.ORIGINAL_INFERIOR), (0, None))
        self.assertEqual(LC.pieza_original(3, LC.ORIGINAL_SUPERIOR), (2, None))

    def test_el_extremo_enlazado_lo_conserva_el_original(self):
        k, aviso = LC.pieza_original(2, LC.ORIGINAL_INFERIOR, tope_enlazado=True)
        self.assertEqual(k, 1)
        self.assertIn(u"tope", aviso)
        k, aviso = LC.pieza_original(2, LC.ORIGINAL_SUPERIOR, base_enlazada=True)
        self.assertEqual(k, 0)
        self.assertIsNone(LC.pieza_original(2, LC.ORIGINAL_INFERIOR, True, True)[0])


class PlanTests(unittest.TestCase):
    def test_plan_de_varios_muros(self):
        planes = LC.planificar([muro(2.5), muro(1.2), muro(2.5, omitir=u"es un muro cortina"),
                                muro(2.5, tope_enlazado=True, base_enlazada=True), muro(0.08)], ops())
        self.assertEqual(planes[0]["tramos"], [(0.0, 1.5), (1.5, 2.5)])
        self.assertEqual(planes[0]["original"], 0)
        self.assertIn(u"ningún corte", planes[1]["omitir"])
        self.assertEqual(planes[2]["omitir"], u"es un muro cortina")
        self.assertIn(u"Attach", planes[3]["omitir"])
        self.assertIn(u"demasiado bajo", planes[4]["omitir"])
        self.assertEqual(LC.resumen_planes(planes), u"5 muros · 1 se corta en 2 tramos · 4 se omiten")

    def test_avisa_los_cortes_ignorados(self):
        plan = LC.planificar([muro(2.5)], ops(modo=LC.MODO_VARIAS, valores=[1.2, 2.48]))[0]
        self.assertEqual(len(plan["tramos"]), 2)
        self.assertTrue(any(u"2.48" in a for a in plan["avisos"]))


class ValidacionTests(unittest.TestCase):
    def test_mensajes(self):
        self.assertIsNone(LC.validar_opciones(ops()))
        self.assertIn(u"altura de corte", LC.validar_opciones(ops(valores=[])))
        self.assertIn(u"«x»", LC.validar_opciones(ops(valores=[1.0], error_valores=u"x")))
        self.assertIn(u"mayor que cero", LC.validar_opciones(ops(modo=LC.MODO_ALZADAS, valores=[0.0])))
        self.assertIn(u"centímetros", LC.validar_opciones(ops(minimo_cm=None)))
        self.assertIn(u"parámetro", LC.validar_opciones(ops(param_tramo=u"")))


class InsertosTests(unittest.TestCase):
    RANGOS = [(0.0, 1.5), (1.5, 2.5)]

    def test_cada_inserto_queda_en_el_tramo_de_su_base(self):
        # puerta (base 0.0) y ventana (antepecho 1.6): el original es el tramo 0 y la copia el 1, ambos con los dos
        por_tramo = [[(10, "puerta", 0.0, False), (11, "ventana", 1.6, False)],
                     [(20, "puerta", 0.0, True), (21, "ventana", 1.6, True)]]
        conservar, borrar, sin_ubicar = LC.asignar_insertos(self.RANGOS, por_tramo, 1e-3)
        self.assertEqual(sorted(conservar), [10, 21])
        self.assertEqual(sorted(borrar), [11, 20])
        self.assertEqual(sin_ubicar, [])

    def test_ventana_repetida_en_dos_tramos_no_se_borra(self):
        # El caso real en Revit: los dos tramos quedan unidos y la MISMA ventana original (11) aparecia en los dos.
        # Antes se tomaba la segunda aparicion como copia sobrante y se borraba la ventana conservada.
        por_tramo = [[(11, "ventana", 1.0, False)], [(21, "ventana", 1.0, True), (11, "ventana", 1.0, False)]]
        conservar, borrar, _ = LC.asignar_insertos(self.RANGOS, por_tramo, 1e-3)
        self.assertEqual(conservar, [11])
        self.assertEqual(borrar, [21])

    def test_el_original_solo_se_borra_si_su_copia_lo_reemplaza(self):
        # original arriba (tramo 1); la puerta (base 0.0) debe quedar en la copia de abajo
        por_tramo = [[(20, "puerta", 0.0, True)], [(10, "puerta", 0.0, False)]]
        self.assertEqual(LC.asignar_insertos(self.RANGOS, por_tramo, 1e-3)[:2], ([20], [10]))
        # dos originales distintos en tramos distintos nunca se borran entre si
        por_tramo = [[(10, "puerta", 0.0, False)], [(11, "puerta", 0.0, False)]]
        self.assertEqual(LC.asignar_insertos(self.RANGOS, por_tramo, 1e-3)[1], [])

    def test_sin_ejemplar_en_su_tramo_no_se_borra_nada(self):
        # Revit no copio la ventana a la copia (tramo 1): la del original (tramo 0) no se borra
        conservar, borrar, sin_ubicar = LC.asignar_insertos(self.RANGOS, [[(11, "ventana", 1.6, False)], []], 1e-3)
        self.assertEqual((conservar, borrar, sin_ubicar), ([], [], [11]))

    def test_lo_que_esta_justo_en_el_corte_va_arriba(self):
        self.assertEqual(LC.tramo_de_cota(self.RANGOS, 1.5, 1e-3), 1)
        self.assertEqual(LC.tramo_de_cota(self.RANGOS, -0.2, 1e-3), 0)
        self.assertEqual(LC.tramo_de_cota(self.RANGOS, 9.0, 1e-3), 1)

    def test_hueco_donde_la_puerta_cruza_el_corte(self):
        pedidos = LC.huecos_para_insertos(self.RANGOS, [(10, 0.0, 2.1), (21, 1.6, 2.2)], 1e-3)
        self.assertEqual(pedidos, [(1, 10, 1.5, 2.1)])

    def test_recortar(self):
        self.assertEqual(LC.recortar(1.0, 2.0, 1.5, 3.0, 1e-3), (1.5, 2.0))
        self.assertIsNone(LC.recortar(0.0, 1.0, 1.5, 3.0, 1e-3))


class CruceTests(unittest.TestCase):
    """Una ventana de 1.00 a 2.20 m y un corte a 1.50 m."""
    VENTANA = {"tipo": u"ventana", "zi": 1.0, "zs": 2.2}
    PUERTA = {"tipo": u"puerta", "zi": 0.0, "zs": 2.1}
    HUECO = {"tipo": u"hueco", "zi": 1.0, "zs": 2.2}

    def plan(self, cruce, insertos, altura=2.6, **k):
        return LC.planificar([muro(altura, insertos=insertos, recto=True)], ops(cruce=cruce, **k))[0]

    def test_hueco_corta_igual_y_avisa(self):
        p = self.plan(LC.CRUCE_HUECO, [self.VENTANA])
        self.assertEqual(p["tramos"], [(0.0, 1.5), (1.5, 2.6)])
        self.assertEqual(len(p["cruces"]), 1)
        self.assertTrue(any(u"no se parte" in a for a in p["avisos"]))

    def test_tramo_anfitrion_y_hueco_segun_la_regla(self):
        rangos = [(0.0, 1.5), (1.5, 2.6)]
        # puerta de 0.00 a 2.10: en el tramo de su base, el hueco va arriba; en el de su tope, abajo
        self.assertEqual(LC.huecos_para_insertos(rangos, [(21, 0.0, 2.1)], 1e-3), [(1, 21, 1.5, 2.1)])
        self.assertEqual(LC.huecos_para_insertos(rangos, [(21, 0.0, 2.1)], 1e-3, LC.ANFITRION_TOPE),
                         [(0, 21, 0.0, 1.5)])
        self.assertEqual(LC.tramo_de_cota(rangos, LC.cota_referencia(1.0, 2.2, LC.ANFITRION_TOPE, 1e-3), 1e-3), 1)
        self.assertEqual(LC.tramo_de_cota(rangos, LC.cota_referencia(1.0, 2.2, LC.ANFITRION_BASE, 1e-3), 1e-3), 0)

    def test_ajustar_mueve_el_corte_al_borde_mas_cercano(self):
        p = self.plan(LC.CRUCE_AJUSTAR, [self.VENTANA])
        self.assertEqual(p["tramos"], [(0.0, 1.0), (1.0, 2.6)])
        self.assertEqual(p["cruces"], [])
        self.assertTrue(any(u"movido a 1.00" in a for a in p["avisos"]))
        # puerta desde el piso: el antepecho (0.00) no sirve, el corte sube al dintel
        self.assertEqual(self.plan(LC.CRUCE_AJUSTAR, [self.PUERTA])["tramos"], [(0.0, 2.1), (2.1, 2.6)])

    def test_ajustar_con_insertos_encimados_usa_el_borde_del_conjunto(self):
        otra = {"tipo": u"ventana", "zi": 2.0, "zs": 2.5}
        self.assertEqual(LC.ajustar_cortes([1.5], LC.bloqueos({"insertos": [self.VENTANA, otra]}), 2.6, 0.05)[0],
                         [1.0])
        self.assertEqual(LC.ajustar_cortes([2.1], LC.bloqueos({"insertos": [self.VENTANA, otra]}), 2.6, 0.05)[0],
                         [2.5])

    def test_ajustar_sin_lugar_no_corta(self):
        alta = {"tipo": u"puerta", "zi": 0.0, "zs": 2.58}
        p = self.plan(LC.CRUCE_AJUSTAR, [alta])
        self.assertIn(u"ningún corte", p["omitir"])

    def test_omitir_no_corta_el_muro(self):
        p = self.plan(LC.CRUCE_OMITIR, [self.VENTANA])
        self.assertIn(u"partiría ventana", p["omitir"])
        self.assertIsNone(self.plan(LC.CRUCE_OMITIR, [self.VENTANA], valores=[0.8])["omitir"])

    def test_los_huecos_de_muro_no_bloquean(self):
        self.assertEqual(self.plan(LC.CRUCE_OMITIR, [self.HUECO])["omitir"], None)

    def test_estadisticas(self):
        planes = LC.planificar([muro(2.6, insertos=[self.VENTANA], recto=True), muro(1.0)], ops())
        self.assertEqual(LC.estadisticas(planes), {"muros": 2, "cortan": 1, "tramos": 2, "cruces": 1})


class ReporteTests(unittest.TestCase):
    def test_texto_reporte(self):
        rep = {"cortados": [{"id": 5, "piezas": [5, 6], "param_copiados": 40, "insertos_borrados": 1, "huecos": 1,
                             "diferencias": [u"Comentarios"], "avisos": [], "otros_borrados": {u"Armaduras": 2}}],
               "omitidos": [(7, u"es un muro cortina")], "fallidos": [(8, u"error de Revit")],
               "avisos_revit": [u"Hay elementos con la misma Marca"]}
        texto = LC.texto_reporte(rep)
        for esperado in (u"Muros cortados: 1 de 3", u"tramos resultantes: 2", u"40 valores", u"Comentarios",
                         u"2 Armaduras", u"Id 7: es un muro cortina", u"Id 8: error de Revit", u"misma Marca",
                         u"1 hueco abierto"):
            self.assertIn(esperado, texto)

    def test_nombre_y_texto_de_tramos(self):
        self.assertEqual(LC.nombre_tramo(u"A", 0), u"A1")
        self.assertEqual(LC.texto_tramos([(0.0, 1.5), (1.5, 2.5)]), u"0.00–1.50 · 1.50–2.50")


if __name__ == "__main__":
    unittest.main()
