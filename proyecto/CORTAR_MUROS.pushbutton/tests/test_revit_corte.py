# -*- coding: utf-8 -*-
"""revit_corte.py con un Revit simulado (CPython): la foto de parametros, su copia y verificacion, el orden en que se
fija la altura de cada tramo y el manejo de advertencias y errores de Revit. Lo que necesita el modelo real (copiar
muros, insertos, huecos) se prueba en Revit."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ElementId(object):
    def __init__(self, v):self.Value = v


ElementId.InvalidElementId = ElementId(-1)


class InternalDefinition(object):
    def __init__(self, nombre, bip):
        self.Name, self.BuiltInParameter = nombre, bip


class ExternalDefinition(object):
    def __init__(self, nombre):self.Name = nombre


ST = types.SimpleNamespace(String="String", Integer="Integer", Double="Double", ElementId="ElementId")
# Solo algunos BuiltInParameter: los que faltan (WALL_TOP_IS_ATTACHED, DOOR_WIDTH...) prueban que revit_corte los
# busca con getattr y no truena en versiones de Revit que no los tengan.
BIP = types.SimpleNamespace(WALL_BASE_CONSTRAINT=1, WALL_BASE_OFFSET=2, WALL_HEIGHT_TYPE=3, WALL_TOP_OFFSET=4,
                            WALL_USER_HEIGHT_PARAM=5, ALL_MODEL_MARK=6, IFC_GUID=7, ELEM_TYPE_PARAM=8,
                            ALL_MODEL_INSTANCE_COMMENTS=9)


class Parametro(object):
    def __init__(self, definicion, st, valor, solo_lectura=False, registro=None):
        self.Definition, self.StorageType, self.valor = definicion, st, valor
        self.IsReadOnly = solo_lectura
        self.registro = registro if registro is not None else []

    @property
    def HasValue(self):return self.valor is not None

    def AsString(self):return self.valor
    def AsInteger(self):return self.valor
    def AsDouble(self):return self.valor
    def AsElementId(self):return self.valor

    def Set(self, v):
        self.registro.append((self.Definition.Name, v))
        self.valor = v
        return True


class Elemento(object):
    def __init__(self, params, eid=1):
        self.Parameters = params
        self.Id = ElementId(eid)

    def get_Parameter(self, clave):
        for p in self.Parameters:
            d = p.Definition
            if p.Definition is clave or (isinstance(d, InternalDefinition) and d.BuiltInParameter == clave):
                return p
        return None

    def LookupParameter(self, nombre):
        for p in self.Parameters:
            if p.Definition.Name == nombre:return p
        return None


def cargar_revit_corte():
    severidad = types.SimpleNamespace(Warning="W", Error="E")
    resultado = types.SimpleNamespace(Continue="continuar", ProceedWithRollBack="deshacer")
    db = types.ModuleType("Autodesk.Revit.DB")
    for nombre, valor in dict(ElementId=ElementId, InternalDefinition=InternalDefinition, StorageType=ST,
                              BuiltInParameter=BIP, IFailuresPreprocessor=object, FailureSeverity=severidad,
                              FailureProcessingResult=resultado).items():
        setattr(db, nombre, valor)
    generic = types.ModuleType("System.Collections.Generic")
    generic.List = {}
    dobles = {"Autodesk": types.ModuleType("Autodesk"), "Autodesk.Revit": types.ModuleType("Autodesk.Revit"),
              "Autodesk.Revit.DB": db, "System": types.ModuleType("System"),
              "System.Collections": types.ModuleType("System.Collections"), "System.Collections.Generic": generic}
    spec = importlib.util.spec_from_file_location("revit_corte_prueba", str(ROOT / "revit_corte.py"))
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, dobles):
        spec.loader.exec_module(mod)
    return mod


RC = cargar_revit_corte()
D_MARCA = InternalDefinition(u"Marca", BIP.ALL_MODEL_MARK)
D_COMENT = InternalDefinition(u"Comentarios", BIP.ALL_MODEL_INSTANCE_COMMENTS)
D_OFFSET = InternalDefinition(u"Desfase de base", BIP.WALL_BASE_OFFSET)
D_AREA = InternalDefinition(u"Área", 99)
D_PISO = ExternalDefinition(u"00_PISO")
D_SECTOR = ExternalDefinition(u"00_SECTOR")
D_CF = ExternalDefinition(u"CF")
D_FASE = InternalDefinition(u"Fase de creación", 50)


def original():
    return Elemento([Parametro(D_MARCA, ST.String, u"M-01"), Parametro(D_COMENT, ST.String, u"tabique baño"),
                     Parametro(D_OFFSET, ST.Double, 0.0), Parametro(D_AREA, ST.Double, 60.0, solo_lectura=True),
                     Parametro(D_PISO, ST.String, u"P03"), Parametro(D_SECTOR, ST.Integer, 4),
                     Parametro(D_CF, ST.Integer, None), Parametro(D_FASE, ST.ElementId, ElementId(77))])


def copia():
    """Como la deja Revit al copiar: sin Marca y con valores distintos (para ver que se escriben)."""
    return Elemento([Parametro(D_MARCA, ST.String, None), Parametro(D_COMENT, ST.String, u""),
                     Parametro(D_OFFSET, ST.Double, 0.0), Parametro(D_AREA, ST.Double, 60.0, solo_lectura=True),
                     Parametro(D_PISO, ST.String, u"P03"), Parametro(D_SECTOR, ST.Integer, 0),
                     Parametro(D_CF, ST.Integer, None), Parametro(D_FASE, ST.ElementId, ElementId(1))], eid=2)


class FotoTests(unittest.TestCase):
    def test_la_foto_lleva_lo_que_se_puede_escribir_salvo_la_geometria(self):
        nombres = [f[1] for f in RC.leer_parametros(original(), RC.excluidos())]
        self.assertEqual(nombres, [u"Marca", u"Comentarios", u"00_PISO", u"00_SECTOR", u"CF", u"Fase de creación"])
        self.assertNotIn(u"Marca", [f[1] for f in RC.leer_parametros(original(), RC.excluidos(copiar_marca=False))])

    def test_copiar_y_verificar(self):
        o, c = original(), copia()
        foto = RC.leer_parametros(o, RC.excluidos())
        self.assertTrue(RC.diferencias(c, foto))
        copiados, fallos = RC.escribir_parametros(c, foto)
        self.assertEqual(fallos, [])
        self.assertEqual(copiados, 5)            # CF no tiene valor en el original: no se toca
        self.assertEqual(RC.diferencias(c, foto), [])
        self.assertEqual(c.LookupParameter(u"Marca").valor, u"M-01")
        self.assertEqual(c.LookupParameter(u"00_SECTOR").valor, 4)
        self.assertEqual(c.LookupParameter(u"Fase de creación").valor.Value, 77)

    def test_lo_que_no_se_puede_escribir_se_informa(self):
        c = copia()
        c.LookupParameter(u"00_PISO").IsReadOnly = True
        _, fallos = RC.escribir_parametros(c, RC.leer_parametros(original(), RC.excluidos()))
        self.assertEqual(fallos, [u"00_PISO"])

    def test_diferencias_ignora_lo_pedido(self):
        c = copia()
        foto = RC.leer_parametros(original(), RC.excluidos())
        RC.escribir_parametros(c, foto)
        c.LookupParameter(u"Comentarios").valor = u"A2"
        self.assertEqual(RC.diferencias(c, foto), [u"Comentarios"])
        self.assertEqual(RC.diferencias(c, foto, ignorar=(u"Comentarios",)), [])


class AlturaTests(unittest.TestCase):
    def muro(self):
        registro = []
        defs = [(u"tope", BIP.WALL_HEIGHT_TYPE, ST.ElementId, ElementId(30)),
                (u"desfase", BIP.WALL_BASE_OFFSET, ST.Double, 0.5),
                (u"altura", BIP.WALL_USER_HEIGHT_PARAM, ST.Double, 8.0)]
        return Elemento([Parametro(InternalDefinition(n, b), st, v, registro=registro) for n, b, st, v in defs]), \
            registro

    def test_tramo_inferior_desconecta_el_tope_antes_de_subir_la_base(self):
        m, registro = self.muro()
        RC.ajustar_tramo(m, 1.0, 4.0, False, {"base_offset": 0.5, "tope_restringido": True, "tope_enlazado": False})
        self.assertEqual([r[0] for r in registro], [u"tope", u"desfase", u"altura"])
        self.assertEqual(registro[0][1].Value, -1)
        self.assertEqual(registro[1][1], 1.5)
        self.assertEqual(registro[2][1], 3.0)

    def test_tramo_superior_conserva_el_tope_del_original(self):
        m, registro = self.muro()
        RC.ajustar_tramo(m, 4.0, 8.2, True, {"base_offset": 0.5, "tope_restringido": True, "tope_enlazado": False})
        self.assertEqual(registro, [(u"desfase", 4.5)])
        m, registro = self.muro()
        RC.ajustar_tramo(m, 4.0, 8.2, True, {"base_offset": 0.5, "tope_restringido": False, "tope_enlazado": False})
        self.assertEqual([r[0] for r in registro], [u"desfase", u"altura"])
        self.assertAlmostEqual(registro[1][1], 4.2)

    def test_parametro_de_solo_lectura_detiene_el_corte(self):
        m, _ = self.muro()
        m.LookupParameter(u"desfase").IsReadOnly = True
        with self.assertRaises(Exception):
            RC.ajustar_tramo(m, 1.0, 4.0, False, {"base_offset": 0.5, "tope_restringido": True,
                                                  "tope_enlazado": False})


class Falla(object):
    def __init__(self, texto, severidad):self.texto, self.severidad = texto, severidad
    def GetDescriptionText(self):return self.texto
    def GetSeverity(self):return self.severidad


class Accesor(object):
    def __init__(self, fallas):self.fallas, self.borradas = fallas, []
    def GetFailureMessages(self):return list(self.fallas)
    def DeleteWarning(self, f):self.borradas.append(f)


class PreprocesadorTests(unittest.TestCase):
    def test_advertencias_se_aceptan_y_errores_deshacen(self):
        pre = RC.Preprocesador()
        aviso = Falla(u"Marca duplicada", "W")
        self.assertEqual(pre.PreprocessFailures(Accesor([aviso, Falla(u"Marca duplicada", "W")])), "continuar")
        self.assertEqual(pre.avisos, [u"Marca duplicada"])
        acc = Accesor([Falla(u"No se puede cortar", "E")])
        self.assertEqual(pre.PreprocessFailures(acc), "deshacer")
        self.assertEqual(pre.errores, [u"No se puede cortar"])


class UnidadesTests(unittest.TestCase):
    def test_metros_y_pies(self):
        self.assertAlmostEqual(RC.m_a_ft(1.5), 4.92126, places=4)
        self.assertAlmostEqual(RC.ft_a_m(RC.m_a_ft(2.37)), 2.37)


if __name__ == "__main__":
    unittest.main()
