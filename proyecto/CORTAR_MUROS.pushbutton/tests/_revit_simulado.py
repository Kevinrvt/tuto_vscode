# -*- coding: utf-8 -*-
"""Un Revit de juguete para probar el corte completo en CPython (revit_corte.cortar_muros), con lo que se vio en el
journal de Revit 2026 al cortar muros con puertas y ventanas:

  * copiar un muro copia sus puertas y ventanas (CopyElement devuelve la copia y lo que copio con ella);
  * despues de cambiar la altura de un muro, FindInserts deja de devolver sus insertos (los tramos apilados quedan
    unidos y Revit los trata como compartidos): por eso las copias quedaban sin borrar;
  * dos puertas o ventanas identicas en el mismo lugar, o una que no toca su muro, son un ERROR al confirmar
    ("Hay ejemplares de ... que no cortan nada") y la transaccion se deshace;
  * con rechazar_partidos=True tambien es error una puerta o ventana que su muro cubre solo en parte (por si Revit
    lo rechaza en algun caso: el corte debe reintentarse moviendo el corte).

No pretende ser Revit: solo lo que usa revit_corte.py, con alturas en pies."""
import types

DOC = None


class ElementId(object):
    def __init__(self, v):self.Value = v


ElementId.InvalidElementId = ElementId(-1)


class XYZ(object):
    def __init__(self, x, y, z):self.X, self.Y, self.Z = x, y, z
    def Normalize(self):
        n = (self.X ** 2 + self.Y ** 2 + self.Z ** 2) ** 0.5
        return XYZ(self.X / n, self.Y / n, self.Z / n)
    def Add(self, o):return XYZ(self.X + o.X, self.Y + o.Y, self.Z + o.Z)
    def Multiply(self, k):return XYZ(self.X * k, self.Y * k, self.Z * k)


XYZ.Zero = XYZ(0.0, 0.0, 0.0)


class Line(object):
    def __init__(self, a, b):
        self.a, self.b = a, b
        self.Length = ((b.X - a.X) ** 2 + (b.Y - a.Y) ** 2) ** 0.5
        self.Direction = XYZ(b.X - a.X, b.Y - a.Y, 0.0).Normalize()
    def GetEndPoint(self, i):return self.a if i == 0 else self.b
    def Evaluate(self, t, normalizado):
        return XYZ(self.a.X + (self.b.X - self.a.X) * t, self.a.Y + (self.b.Y - self.a.Y) * t, self.a.Z)


class LocationCurve(object):
    def __init__(self, c):self.Curve = c


class LocationPoint(object):
    def __init__(self, p):self.Point = p


class InternalDefinition(object):
    def __init__(self, nombre, bip):self.Name, self.BuiltInParameter = nombre, bip


class ExternalDefinition(object):
    def __init__(self, nombre):self.Name = nombre


StorageType = types.SimpleNamespace(String="String", Integer="Integer", Double="Double", ElementId="ElementId")
BuiltInParameter = types.SimpleNamespace(
    WALL_BASE_CONSTRAINT=1, WALL_BASE_OFFSET=2, WALL_HEIGHT_TYPE=3, WALL_TOP_OFFSET=4, WALL_USER_HEIGHT_PARAM=5,
    ALL_MODEL_MARK=6, IFC_GUID=7, ELEM_TYPE_PARAM=8, ALL_MODEL_INSTANCE_COMMENTS=9, INSTANCE_SILL_HEIGHT_PARAM=10,
    INSTANCE_HEAD_HEIGHT_PARAM=11, FAMILY_ROUGH_WIDTH_PARAM=12)
BuiltInCategory = types.SimpleNamespace(OST_Doors=-2000023, OST_Windows=-2000014)
WallKind = types.SimpleNamespace(Basic="Basic", Curtain="Curtain")
FailureSeverity = types.SimpleNamespace(Warning="W", Error="E")
FailureProcessingResult = types.SimpleNamespace(Continue="continuar", ProceedWithRollBack="deshacer")
TransactionStatus = types.SimpleNamespace(Started="Started", Committed="Committed", RolledBack="RolledBack")
IFailuresPreprocessor = object
GEOMETRIA = (1, 2, 3, 4, 5)


class Parametro(object):
    def __init__(self, definicion, st, valor, solo_lectura=False):
        self.Definition, self.StorageType, self.valor, self.IsReadOnly = definicion, st, valor, solo_lectura
        self.dueno = None

    @property
    def HasValue(self):return self.valor is not None
    def AsString(self):return self.valor
    def AsInteger(self):return self.valor
    def AsDouble(self):return self.valor
    def AsElementId(self):return self.valor

    def Set(self, v):
        if getattr(self.Definition, "BuiltInParameter", None) in GEOMETRIA and DOC is not None:
            DOC.registro.append(("altura", self.dueno.Id.Value))
            DOC.modificados.add(self.dueno.Id.Value)
        self.valor = v
        return True


class Elemento(object):
    def __init__(self, eid, params=(), tipo=500, categoria=None, nombre=u""):
        self.Id = ElementId(eid)
        self.Parameters = list(params)
        for p in self.Parameters:
            p.dueno = self
        self._tipo, self.Name = tipo, nombre
        self.Category = types.SimpleNamespace(Id=ElementId(categoria), Name=u"cat {}".format(categoria)) \
            if categoria is not None else None

    def GetTypeId(self):return ElementId(self._tipo)

    def get_Parameter(self, clave):
        for p in self.Parameters:
            d = p.Definition
            if d is clave or (isinstance(d, InternalDefinition) and d.BuiltInParameter == clave):
                return p
        return None

    def LookupParameter(self, nombre):
        for p in self.Parameters:
            if p.Definition.Name == nombre:return p
        return None

    def valor(self, bip):
        p = self.get_Parameter(bip)
        return p.valor if p is not None else None


class Level(Elemento):
    def __init__(self, eid, cota, nombre):
        Elemento.__init__(self, eid, nombre=nombre)
        self.ProjectElevation = cota


class Wall(Elemento):
    def __init__(self, eid, params, curva, tipo=500):
        Elemento.__init__(self, eid, params, tipo, -2000011, u"Tabique 14")
        self.Location = LocationCurve(curva)
        self.WallType = types.SimpleNamespace(Kind=WallKind.Basic)
        self.GroupId = ElementId(-1)
        self.SketchId = ElementId(-1)

    def get_BoundingBox(self, vista):return None

    def FindInserts(self, rect, sombras, embebidos, compartidos):
        # el comportamiento visto en Revit: un tramo ya modificado deja de devolver sus insertos
        if self.Id.Value in DOC.modificados:
            return []
        return [e.Id for e in list(DOC.els.values()) if getattr(e, "Host", None) is self]

    def rango(self):
        base = DOC.GetElement(self.valor(1)).ProjectElevation + self.valor(2)
        tope = self.valor(3)
        if tope.Value != -1:
            return base, DOC.GetElement(tope).ProjectElevation + self.valor(4)
        return base, base + self.valor(5)


class FamilyInstance(Elemento):
    def __init__(self, eid, host, punto, antepecho, dintel, ancho, categoria, tipo):
        D = InternalDefinition
        Elemento.__init__(self, eid, [Parametro(D(u"Antepecho", 10), StorageType.Double, antepecho),
                                      Parametro(D(u"Dintel", 11), StorageType.Double, dintel),
                                      Parametro(D(u"Ancho bruto", 12), StorageType.Double, ancho)],
                          tipo, categoria, u"familia {}".format(tipo))
        self.Host, self.LevelId, self.Location = host, host.valor(1), LocationPoint(punto)

    def cotas(self):
        z = DOC.GetElement(self.LevelId).ProjectElevation
        return z + self.valor(10), z + self.valor(11)

    def get_BoundingBox(self, vista):
        zi, zs = self.cotas()
        p, a = self.Location.Point, self.valor(12) / 2.0
        return types.SimpleNamespace(Min=XYZ(p.X - a, p.Y - 0.3, zi), Max=XYZ(p.X + a, p.Y + 0.3, zs))


class Opening(Elemento):
    def __init__(self, eid, host, a, b):
        Elemento.__init__(self, eid)
        self.Host, self.IsRectBoundary, self.BoundaryRect = host, True, [a, b]


class _Copiador(object):
    @staticmethod
    def CopyElement(doc, eid, vector):
        o = doc.GetElement(eid)
        params = [Parametro(p.Definition, p.StorageType, p.valor, p.IsReadOnly) for p in o.Parameters]
        params[[p.Definition.Name for p in params].index(u"Marca")].valor = None     # Revit no copia la Marca
        copia = doc.agregar(Wall(doc.nuevo_id(), params, o.Location.Curve, o._tipo))
        ids = [copia.Id]
        for e in [e for e in list(doc.els.values()) if getattr(e, "Host", None) is o]:
            if isinstance(e, FamilyInstance):
                c = FamilyInstance(doc.nuevo_id(), copia, e.Location.Point, e.valor(10), e.valor(11), e.valor(12),
                                   e.Category.Id.Value, e._tipo)
            else:
                c = Opening(doc.nuevo_id(), copia, e.BoundaryRect[0], e.BoundaryRect[1])
            ids.append(doc.agregar(c).Id)
        return ids


ElementTransformUtils = _Copiador


class Documento(object):
    def __init__(self, rechazar_partidos=False):
        global DOC
        DOC = self
        self.els, self._id, self.registro, self.modificados = {}, 1000, [], set()
        self.rechazar_partidos = rechazar_partidos
        self.Create = self

    def nuevo_id(self):
        self._id += 1
        return self._id

    def agregar(self, e):
        self.els[e.Id.Value] = e
        return e

    def GetElement(self, eid):
        return self.els.get(eid.Value) if eid is not None else None

    def Delete(self, lista):
        for eid in lista:
            self.registro.append(("borrar", eid.Value))
            self.els.pop(eid.Value, None)

    def Regenerate(self):
        self.registro.append(("regenerar", None))

    def NewOpening(self, muro, a, b):
        return self.agregar(Opening(self.nuevo_id(), muro, a, b))

    @property
    def huecos(self):
        """(muro, z inferior, z superior) de los huecos de muro que hay en el modelo (se deshacen con la transaccion)."""
        return sorted((e.Host.Id.Value, min(e.BoundaryRect[0].Z, e.BoundaryRect[1].Z),
                       max(e.BoundaryRect[0].Z, e.BoundaryRect[1].Z))
                      for e in self.els.values() if isinstance(e, Opening))

    def fallas(self):
        """Lo que Revit diria al confirmar: errores de puertas y ventanas que no cortan su muro."""
        errores, vistos = [], {}
        for e in list(self.els.values()):
            if not isinstance(e, FamilyInstance):
                continue
            clave = (e._tipo, e.Location.Point.X, e.Location.Point.Y)
            lo, hi = e.Host.rango()
            zi, zs = e.cotas()
            dentro = min(zs, hi) - max(zi, lo)
            entero = zi >= lo - 1e-6 and zs <= hi + 1e-6
            if clave in vistos or dentro <= 1e-6 or (self.rechazar_partidos and not entero):
                errores.append(u"Hay ejemplares de {} que no cortan nada.".format(e.Name))
            vistos[clave] = e
        return errores

    def foto(self):
        return dict((i, (e, dict(e.__dict__), [(p, p.valor) for p in e.Parameters])) for i, e in self.els.items())

    def restaurar(self, foto):
        self.els = {}
        for i, (e, estado, valores) in foto.items():
            e.__dict__.clear()
            e.__dict__.update(estado)
            for p, v in valores:
                p.valor = v
            self.els[i] = e


class _Falla(object):
    def __init__(self, texto):self.texto = texto
    def GetDescriptionText(self):return self.texto
    def GetSeverity(self):return FailureSeverity.Error


class _Accesor(object):
    def __init__(self, fallas):self.fallas = fallas
    def GetFailureMessages(self):return [_Falla(t) for t in self.fallas]
    def DeleteWarning(self, f):pass


class _Opciones(object):
    def SetFailuresPreprocessor(self, pre):self.pre = pre
    def SetClearAfterRollback(self, v):pass


class Transaction(object):
    def __init__(self, doc, nombre):self.doc, self.estado, self.opciones = doc, None, _Opciones()
    def GetFailureHandlingOptions(self):return self.opciones
    def SetFailureHandlingOptions(self, o):self.opciones = o
    def Start(self):
        self._foto, self._modificados = self.doc.foto(), set(self.doc.modificados)
        self.estado = TransactionStatus.Started
    def GetStatus(self):return self.estado
    def RollBack(self):
        self.doc.restaurar(self._foto)
        self.doc.modificados = self._modificados
        self.estado = TransactionStatus.RolledBack
    def Commit(self):
        fallas = self.doc.fallas()
        if fallas and self.opciones.pre.PreprocessFailures(_Accesor(fallas)) == FailureProcessingResult.ProceedWithRollBack:
            self.RollBack()
            return self.estado
        self.estado = TransactionStatus.Committed
        return self.estado


class TransactionGroup(object):
    def __init__(self, doc, nombre):pass
    def Start(self):pass
    def Assimilate(self):return TransactionStatus.Committed
    def RollBack(self):pass


class Lista(list):
    def Add(self, x):self.append(x)
