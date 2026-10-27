# -*- coding: utf-8 -*-
"""CORTAR MUROS -- lo que toca el modelo: analizar los muros elegidos, partir cada uno en tramos apilados y dejar en
cada tramo los MISMOS parametros del muro original.

Como se parte un muro (en una transaccion por muro, todas dentro de un TransactionGroup: un solo Deshacer):
  1. Se toma una foto de los parametros de instancia que se pueden escribir (incorporados, de proyecto y compartidos).
  2. Uno de los tramos es el muro original (conserva su Id, sus etiquetas y lo que tenga hospedado); los demas son
     copias en el mismo lugar (ElementTransformUtils.CopyElement), que ya traen sus parametros. Aun asi se les vuelve
     a escribir la foto completa: hay parametros que Revit no copia igual (la Marca, por ejemplo).
  3. Cada tramo queda con la MISMA restriccion de base (el mismo nivel: los metrados por piso no cambian) y un
     desfase de base mayor; los de abajo quedan con altura desconectada y el de arriba conserva la restriccion
     superior del original (su nivel y su desfase superior).
  4. Puertas y ventanas: copiar un muro copia sus insertos, asi que cada una queda solo en el tramo donde cae su
     borde inferior y se borran sus copias de los demas tramos, ANTES de cambiar alturas. Las del original se leen
     antes de tocar nada y las de cada copia salen de CopyElement (FindInserts no es confiable con tramos unidos).
     Solo se borra lo que este corte copio (o un original cuya copia lo reemplaza), nunca algo que se conserva.
     Donde un inserto cruza un corte, queda entero en un tramo y en el otro se abre un hueco rectangular de su vano;
     si Revit no lo acepta en el tramo de su base, se reintenta dejandolo en el de su tope. La altura de corte nunca
     cambia sola (eso es «Mover el corte», solo si el usuario lo elige). Los muros cortina
     embebidos no se tocan: se abre hueco en los tramos que atraviesan. Los huecos de muro se recortan a cada tramo.
  5. Al terminar, se verifica parametro por parametro que cada tramo tenga los valores de la foto.
Las advertencias de Revit se aceptan y se informan; un error deshace solo ese muro, que queda como estaba."""
from __future__ import division

import Autodesk.Revit.DB as DB
from System.Collections.Generic import List

import logica_corte as LC
import diagnostico as DG

PIE = 0.3048
TITULO_DESHACER = u"DENOVA - Cortar muros"
# Lo que fija la altura de cada tramo: se escribe tramo por tramo, nunca se copia.
GEOMETRIA = ("WALL_BASE_CONSTRAINT", "WALL_BASE_OFFSET", "WALL_HEIGHT_TYPE", "WALL_TOP_OFFSET",
             "WALL_USER_HEIGHT_PARAM")
# Nunca se copian: el tipo (es el mismo) y el IfcGUID (cada elemento necesita el suyo para exportar a IFC).
NUNCA_COPIAR = ("ELEM_TYPE_PARAM", "ELEM_FAMILY_AND_TYPE_PARAM", "ELEM_FAMILY_PARAM", "SYMBOL_ID_PARAM", "IFC_GUID")
MARCA = "ALL_MODEL_MARK"
ANCHOS = ("FAMILY_ROUGH_WIDTH_PARAM", "DOOR_WIDTH", "WINDOW_WIDTH", "FAMILY_WIDTH_PARAM")


def m_a_ft(m):
    return m / PIE


def ft_a_m(ft):
    return ft * PIE


TOL_FT = m_a_ft(0.001)


def _id_num(eid):
    try:return int(eid.Value)
    except:
        try:return int(eid.IntegerValue)
        except:return None


def _valido(eid):
    n = _id_num(eid) if eid is not None else None
    return n is not None and n != -1


def _bip(nombre):
    return getattr(DB.BuiltInParameter, nombre, None)


def _ids_bip(nombres):
    ids = set()
    for n in nombres:
        b = _bip(n)
        if b is not None:
            ids.add(int(b))
    return ids


def _param(elem, nombre):
    b = _bip(nombre)
    if b is None:
        return None
    try:return elem.get_Parameter(b)
    except Exception:return None


def _doble(elem, nombre, defecto=None):
    p = _param(elem, nombre)
    try:return p.AsDouble() if p is not None and p.HasValue else defecto
    except Exception:return defecto


def _entero(elem, nombre, defecto=0):
    p = _param(elem, nombre)
    try:return p.AsInteger() if p is not None and p.HasValue else defecto
    except Exception:return defecto


def _cota_nivel(doc, eid):
    nivel = doc.GetElement(eid) if _valido(eid) else None
    return (nivel.ProjectElevation, nivel) if nivel is not None else (0.0, None)


def _nombre(elem, defecto=u""):
    try:return elem.Name or defecto
    except Exception:return defecto


# ---- parametros --------------------------------------------------------------------------------------------------
def _bip_de(p):
    """El BuiltInParameter (como entero) de un parametro incorporado; None si es de proyecto o compartido."""
    try:
        d = p.Definition
        if isinstance(d, DB.InternalDefinition):
            b = int(d.BuiltInParameter)
            return b if b != -1 else None
    except Exception:
        pass
    return None


def _valor(p):
    st = p.StorageType
    if st == DB.StorageType.String:return p.AsString()
    if st == DB.StorageType.Integer:return p.AsInteger()
    if st == DB.StorageType.Double:return p.AsDouble()
    if st == DB.StorageType.ElementId:return p.AsElementId()
    return None


def _iguales(st, a, b):
    if st == DB.StorageType.String:return (a or u"") == (b or u"")
    if st == DB.StorageType.Double:return a is not None and b is not None and abs(a - b) < 1e-9
    if st == DB.StorageType.ElementId:return _id_num(a) == _id_num(b)
    return a == b


def _buscar(elem, definicion, nombre):
    """El mismo parametro en otro elemento: por su definicion (no se confunden dos parametros con el mismo nombre) y,
    si eso falla, por nombre."""
    try:
        q = elem.get_Parameter(definicion)
        if q is not None:return q
    except Exception:
        pass
    try:return elem.LookupParameter(nombre)
    except Exception:return None


def excluidos(copiar_marca=True):
    """Ids de los BuiltInParameter que la foto no lleva."""
    nombres = GEOMETRIA + NUNCA_COPIAR + (() if copiar_marca else (MARCA,))
    return _ids_bip(nombres)


def leer_parametros(elem, excluir):
    """La foto: [(definicion, nombre, tipo de almacenamiento, valor, tiene_valor)] de los parametros de instancia que se
    pueden escribir, salvo los incorporados de 'excluir'."""
    foto = []
    for p in elem.Parameters:
        try:
            if p.IsReadOnly or _bip_de(p) in excluir:
                continue
            st = p.StorageType
            if st not in (DB.StorageType.String, DB.StorageType.Integer, DB.StorageType.Double,
                          DB.StorageType.ElementId):
                continue
            foto.append((p.Definition, p.Definition.Name, st, _valor(p), bool(p.HasValue)))
        except Exception:
            continue
    return foto


def escribir_parametros(destino, foto):
    """(copiados, fallos): escribe la foto en el destino. Un parametro sin valor en el original (numero o Si/No sin
    llenar) no se toca; un texto sin valor se deja vacio. Nunca lanza: lo que no se pudo escribir se informa."""
    copiados, fallos = 0, []
    for definicion, nombre, st, valor, tiene in foto:
        if not tiene and st != DB.StorageType.String:
            continue
        q = _buscar(destino, definicion, nombre)
        if q is None or q.IsReadOnly:
            fallos.append(nombre)
            continue
        try:
            if _iguales(st, _valor(q), valor):
                copiados += 1
                continue
            ok = q.Set(valor if valor is not None else u"")
            if ok is False:
                fallos.append(nombre)
            else:
                copiados += 1
        except Exception:
            fallos.append(nombre)
    return copiados, fallos


def diferencias(elem, foto, ignorar=()):
    """Nombres de los parametros de la foto que el elemento no tiene con el mismo valor."""
    dif = []
    for definicion, nombre, st, valor, tiene in foto:
        if nombre in ignorar or (not tiene and st != DB.StorageType.String):
            continue
        q = _buscar(elem, definicion, nombre)
        try:
            if q is None or not _iguales(st, _valor(q), valor):
                dif.append(nombre)
        except Exception:
            dif.append(nombre)
    return dif


def nombres_texto(elem):
    """Parametros de texto de instancia que se pueden escribir: candidatos para anotar el tramo (A1, A2...)."""
    nombres, excluir = [], excluidos()
    for p in elem.Parameters:
        try:
            if not p.IsReadOnly and p.StorageType == DB.StorageType.String and _bip_de(p) not in excluir:
                nombres.append(p.Definition.Name)
        except Exception:
            continue
    return nombres


# ---- analisis de cada muro ---------------------------------------------------------------------------------------
def motivo_omision(muro):
    """Por que este elemento no se puede cortar con esta herramienta, o None."""
    if not isinstance(muro, DB.Wall):
        return u"no es un muro de sistema"
    try:
        if muro.WallType.Kind == DB.WallKind.Curtain:
            return u"es un muro cortina"
    except Exception:
        pass
    if getattr(muro, "IsStackedWall", False):
        return u"es un muro apilado (corta los muros que lo forman)"
    if getattr(muro, "IsStackedWallMember", False):
        return u"forma parte de un muro apilado"
    try:
        if _valido(muro.GroupId):
            return u"está dentro de un grupo (desagrúpalo o edita el grupo)"
    except Exception:
        pass
    try:
        if _valido(muro.SketchId):
            return u"tiene el perfil editado: su altura la fija el boceto, no los parámetros"
    except Exception:
        pass
    if not isinstance(getattr(muro, "Location", None), DB.LocationCurve):
        return u"no tiene una línea de ubicación"
    return None


def analizar_muro(doc, muro):
    """Lo que la ventana y el corte necesitan saber del muro (cotas en pies; altura y desfase tambien en metros)."""
    info = {"elemento": muro, "id": _id_num(muro.Id), "tipo": _nombre(muro), "nivel": u"", "omitir": None,
            "altura_m": 0.0, "base_offset_m": 0.0, "base_z": 0.0, "base_offset": 0.0, "tope_restringido": False,
            "tope_enlazado": False, "base_enlazada": False, "recto": False, "textos": [], "largo_m": 0.0,
            "insertos": []}
    info["omitir"] = motivo_omision(muro)
    if info["omitir"]:
        return info
    try:
        base_id = _param(muro, "WALL_BASE_CONSTRAINT").AsElementId()
        z_nivel, nivel = _cota_nivel(doc, base_id)
        info["nivel"] = _nombre(nivel)
        info["base_offset"] = _doble(muro, "WALL_BASE_OFFSET", 0.0)
        info["base_z"] = z_nivel + info["base_offset"]
        tope_id = _param(muro, "WALL_HEIGHT_TYPE").AsElementId()
        info["tope_restringido"] = _valido(tope_id)
        if info["tope_restringido"]:
            tope_z = _cota_nivel(doc, tope_id)[0] + _doble(muro, "WALL_TOP_OFFSET", 0.0)
        else:
            tope_z = info["base_z"] + _doble(muro, "WALL_USER_HEIGHT_PARAM", 0.0)
        info["tope_enlazado"] = _entero(muro, "WALL_TOP_IS_ATTACHED") == 1
        info["base_enlazada"] = _entero(muro, "WALL_BOTTOM_IS_ATTACHED") == 1
        if info["tope_enlazado"]:
            # enlazado a una losa o cubierta, el tope real es el de la geometria, no el de los parametros
            caja = muro.get_BoundingBox(None)
            if caja is not None:
                tope_z = caja.Max.Z
        info["altura"] = tope_z - info["base_z"]
        info["altura_m"] = ft_a_m(info["altura"])
        info["base_offset_m"] = ft_a_m(info["base_offset"])
        info["recto"] = isinstance(muro.Location.Curve, DB.Line)
        info["textos"] = nombres_texto(muro)
        curva = muro.Location.Curve
        info["largo_m"] = ft_a_m(curva.Length)
        info["insertos"] = leer_insertos(doc, muro, info["base_z"], curva)
    except Exception as ex:
        info["omitir"] = u"no se pudo leer su altura ({})".format(ex)
    return info


# ---- corte -------------------------------------------------------------------------------------------------------
class Preprocesador(DB.IFailuresPreprocessor):
    """Acepta las advertencias de Revit (y las anota para el informe); ante un error, deshace la transaccion. Para el
    diagnostico guarda tambien que elementos exactos senalo Revit en cada falla (en ese momento todavia existen)."""

    def __init__(self, doc=None):
        self.doc = doc
        self.avisos = []
        self.errores = []
        self.detalle = []

    def _elementos(self, f, metodo):
        try:return [describir(self.doc, self.doc.GetElement(i)) for i in getattr(f, metodo)()]
        except Exception:return []

    def PreprocessFailures(self, fa):
        error = False
        for f in list(fa.GetFailureMessages()):
            try:texto = f.GetDescriptionText()
            except Exception:texto = u"(sin descripción)"
            if self.doc is not None:
                self.detalle.append({"severidad": u"{}".format(f.GetSeverity()), "texto": texto,
                                     "elementos": self._elementos(f, "GetFailingElementIds"),
                                     "adicionales": self._elementos(f, "GetAdditionalElementIds")})
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                if texto not in self.avisos:self.avisos.append(texto)
                fa.DeleteWarning(f)
            else:
                if texto not in self.errores:self.errores.append(texto)
                error = True
        return DB.FailureProcessingResult.ProceedWithRollBack if error else DB.FailureProcessingResult.Continue


def _fijar(elem, nombre, valor):
    p = _param(elem, nombre)
    if p is None or p.IsReadOnly:
        raise Exception(u"no se puede cambiar {} del muro {}".format(nombre, _id_num(elem.Id)))
    if p.Set(valor) is False:
        raise Exception(u"Revit no aceptó {} = {} en el muro {}".format(nombre, valor, _id_num(elem.Id)))


def ajustar_tramo(muro, a, b, es_ultimo, info):
    """Deja el muro entre a y b pies sobre la base del original. La base sigue en el mismo nivel (solo crece su
    desfase). El tramo de arriba conserva la restriccion superior del original; los demas quedan desconectados, con
    altura b - a. Primero se desconecta el tope: asi subir la base nunca deja el tope por debajo de ella."""
    if not es_ultimo:
        _fijar(muro, "WALL_HEIGHT_TYPE", DB.ElementId.InvalidElementId)
        _fijar(muro, "WALL_BASE_OFFSET", info["base_offset"] + a)
        _fijar(muro, "WALL_USER_HEIGHT_PARAM", b - a)
    else:
        _fijar(muro, "WALL_BASE_OFFSET", info["base_offset"] + a)
        if not info["tope_restringido"] and not info["tope_enlazado"]:
            _fijar(muro, "WALL_USER_HEIGHT_PARAM", b - a)


def _copiar_muro(doc, muro):
    """(copia, otros ids copiados): la copia en el mismo lugar y lo que Revit copio con ella (sus insertos, etc.)."""
    ids = DB.ElementTransformUtils.CopyElement(doc, muro.Id, DB.XYZ.Zero)
    copia, resto = None, []
    tipo = _id_num(muro.GetTypeId())
    for eid in ids:
        e = doc.GetElement(eid)
        if copia is None and isinstance(e, DB.Wall) and _id_num(e.GetTypeId()) == tipo:
            copia = e
        else:
            resto.append(eid)
    if copia is None:
        raise Exception(u"Revit no devolvió la copia del muro")
    return copia, resto


def _primero_doble(elementos, nombres):
    for e in elementos:
        if e is None:continue
        for n in nombres:
            v = _doble(e, n)
            if v:return v
    return None


def _datos_inserto(doc, e):
    """Lo que hace falta de una puerta, ventana o muro embebido: su clave (tipo y posicion: igual en el original y en
    sus copias), sus cotas inferior y superior, su punto y su ancho."""
    caja = e.get_BoundingBox(None)
    loc = getattr(e, "Location", None)
    if isinstance(loc, DB.LocationPoint):
        punto = loc.Point
    elif isinstance(loc, DB.LocationCurve):
        punto = loc.Curve.Evaluate(0.5, True)
    elif caja is not None:
        punto = caja.Min.Add(caja.Max).Multiply(0.5)
    else:
        return None
    zi = zs = None
    z_nivel = _cota_nivel(doc, getattr(e, "LevelId", None))[0]
    antepecho, dintel = _doble(e, "INSTANCE_SILL_HEIGHT_PARAM"), _doble(e, "INSTANCE_HEAD_HEIGHT_PARAM")
    if antepecho is not None and dintel is not None and dintel > antepecho:
        zi, zs = z_nivel + antepecho, z_nivel + dintel
    elif caja is not None:
        zi, zs = caja.Min.Z, caja.Max.Z
    else:
        return None
    tipo = doc.GetElement(e.GetTypeId())
    return {"id": _id_num(e.Id), "eid": e.Id, "clave": (_id_num(e.GetTypeId()), round(punto.X, 4), round(punto.Y, 4),
                                                         round(punto.Z, 4)),
            "z_inf": zi, "z_sup": zs, "punto": punto, "ancho": _primero_doble((e, tipo), ANCHOS), "caja": caja}


def _ancho_caja(caja, d):
    """Ancho de la caja de un inserto medido a lo largo del muro (si la familia no informa su ancho)."""
    if caja is None:
        return None
    vals = [x * d.X + y * d.Y for x in (caja.Min.X, caja.Max.X) for y in (caja.Min.Y, caja.Max.Y)]
    return max(vals) - min(vals)


def _crear_hueco(doc, muro, punto, ancho, zlo, zhi):
    """Hueco rectangular de muro centrado en 'punto' (proyectado sobre la linea del muro). Solo muros rectos."""
    curva = muro.Location.Curve
    if not isinstance(curva, DB.Line) or not ancho:
        return None
    p0 = curva.GetEndPoint(0)
    d = DB.XYZ(curva.Direction.X, curva.Direction.Y, 0).Normalize()
    t = (punto.X - p0.X) * d.X + (punto.Y - p0.Y) * d.Y
    cx, cy, h = p0.X + d.X * t, p0.Y + d.Y * t, ancho / 2.0
    return doc.Create.NewOpening(muro, DB.XYZ(cx - d.X * h, cy - d.Y * h, zlo), DB.XYZ(cx + d.X * h, cy + d.Y * h, zhi))


def _insertos(doc, muro):
    """Lo que el muro HOSPEDA: puertas, ventanas, huecos y muros embebidos. Sin los insertos 'compartidos' y solo los
    que tienen a este muro como anfitrion: con dos tramos apilados y unidos, Revit devolvia la ventana de un tramo
    tambien en el otro, y se borraba como si fuera una copia sobrante."""
    try:ids = list(muro.FindInserts(True, False, True, False))
    except Exception:ids = []
    propio, lista = _id_num(muro.Id), []
    for i in ids:
        e = doc.GetElement(i)
        if e is None:
            continue
        anfitrion = getattr(e, "Host", None)
        if anfitrion is not None and _id_num(anfitrion.Id) != propio:
            continue
        lista.append(e)
    return lista


def _s_en_curva(curva, punto):
    """Distancia (pies) desde el inicio del muro hasta la proyeccion del punto sobre su linea."""
    try:
        r = curva.Project(punto)
        return curva.ComputeNormalizedParameter(r.Parameter) * curva.Length
    except Exception:
        p0, p1 = curva.GetEndPoint(0), curva.GetEndPoint(1)
        dx, dy = p1.X - p0.X, p1.Y - p0.Y
        n = (dx * dx + dy * dy) ** 0.5 or 1.0
        return ((punto.X - p0.X) * dx + (punto.Y - p0.Y) * dy) / n


def _tipo_inserto(e):
    if isinstance(e, DB.Opening):
        return u"hueco"
    if isinstance(e, DB.Wall):
        try:return u"muro cortina" if e.WallType.Kind == DB.WallKind.Curtain else u"muro embebido"
        except Exception:return u"muro embebido"
    try:
        cid = _id_num(e.Category.Id)
        if cid == int(DB.BuiltInCategory.OST_Doors):return u"puerta"
        if cid == int(DB.BuiltInCategory.OST_Windows):return u"ventana"
    except Exception:
        pass
    return u"inserto"


def leer_insertos(doc, muro, base_z, curva):
    """Lo que hospeda el muro, para la vista previa y para decidir los cortes: tipo, cotas en metros sobre la base
    (zi, zs), tramo a lo largo del muro en metros (s0, s1) y lo que hace falta para abrir huecos (en pies)."""
    lista = []
    for e in _insertos(doc, muro):
        tipo = _tipo_inserto(e)
        try:
            if tipo == u"hueco":
                if not e.IsRectBoundary:
                    continue
                r = list(e.BoundaryRect)
                zi, zs = min(r[0].Z, r[1].Z), max(r[0].Z, r[1].Z)
                sa, sb = _s_en_curva(curva, r[0]), _s_en_curva(curva, r[1])
                punto, ancho = None, abs(sb - sa)
            elif tipo in (u"muro cortina", u"muro embebido"):
                caja, c = e.get_BoundingBox(None), e.Location.Curve
                sa, sb = _s_en_curva(curva, c.GetEndPoint(0)), _s_en_curva(curva, c.GetEndPoint(1))
                zi, zs = caja.Min.Z, caja.Max.Z
                punto, ancho = c.Evaluate(0.5, True), abs(sb - sa)
            else:
                d = _datos_inserto(doc, e)
                if d is None:
                    continue
                zi, zs, punto, ancho = d["z_inf"], d["z_sup"], d["punto"], d["ancho"]
                if not ancho and isinstance(curva, DB.Line):
                    ancho = _ancho_caja(d["caja"], DB.XYZ(curva.Direction.X, curva.Direction.Y, 0).Normalize())
                centro = _s_en_curva(curva, punto)
                sa, sb = centro - (ancho or 0.0) / 2.0, centro + (ancho or 0.0) / 2.0
        except Exception:
            continue
        lista.append({"id": _id_num(e.Id), "tipo": tipo, "nombre": _nombre(e),
                      "zi": ft_a_m(zi - base_z), "zs": ft_a_m(zs - base_z),
                      "s0": ft_a_m(min(sa, sb)), "s1": ft_a_m(max(sa, sb)),
                      "zi_ft": zi, "zs_ft": zs, "punto": punto, "ancho_ft": ancho})
    return lista


def _borrar(doc, eids):
    vistos, lista = set(), List[DB.ElementId]()
    for eid in eids:
        if _id_num(eid) in vistos:
            continue
        vistos.add(_id_num(eid))
        lista.Add(eid)
    if not vistos:
        return 0
    doc.Delete(lista)
    return len(vistos)


def rango_muro(doc, muro):
    """(base, tope) absolutos del muro en pies, segun sus parametros de altura."""
    base = _cota_nivel(doc, _param(muro, "WALL_BASE_CONSTRAINT").AsElementId())[0] + _doble(muro, "WALL_BASE_OFFSET", 0.0)
    tope_id = _param(muro, "WALL_HEIGHT_TYPE").AsElementId()
    if _valido(tope_id):
        return base, _cota_nivel(doc, tope_id)[0] + _doble(muro, "WALL_TOP_OFFSET", 0.0)
    return base, base + _doble(muro, "WALL_USER_HEIGHT_PARAM", 0.0)


def describir(doc, e):
    """Lo que el diagnostico necesita saber de un elemento (cotas en metros). Nunca lanza."""
    if e is None:
        return {"id": None, "existe": False}
    d = {"id": _id_num(e.Id)}
    for clave, leer in (("clase", lambda: type(e).__name__), ("categoria", lambda: e.Category.Name),
                        ("tipo_id", lambda: _id_num(e.GetTypeId())), ("nombre", lambda: _nombre(e)),
                        ("host", lambda: _id_num(e.Host.Id))):
        try:d[clave] = leer()
        except Exception:pass
    try:
        p = e.Location.Point
        d["punto_m"] = [round(ft_a_m(p.X), 4), round(ft_a_m(p.Y), 4), round(ft_a_m(p.Z), 4)]
    except Exception:
        pass
    for clave, nombre in (("antepecho_m", "INSTANCE_SILL_HEIGHT_PARAM"), ("dintel_m", "INSTANCE_HEAD_HEIGHT_PARAM")):
        v = _doble(e, nombre)
        if v is not None:d[clave] = round(ft_a_m(v), 4)
    try:
        caja = e.get_BoundingBox(None)
        if caja is not None:d["caja_z_m"] = [round(ft_a_m(caja.Min.Z), 4), round(ft_a_m(caja.Max.Z), 4)]
    except Exception:
        pass
    if isinstance(e, DB.Wall):
        try:
            lo, hi = rango_muro(doc, e)
            d["rango_m"] = [round(ft_a_m(lo), 4), round(ft_a_m(hi), 4)]
            d["tope_conectado"] = _valido(_param(e, "WALL_HEIGHT_TYPE").AsElementId())
        except Exception:
            pass
    return d


def _hospedados(doc, ids_muros):
    """{id de muro: [puertas, ventanas y huecos que lo tienen como anfitrion]}. Se buscan por su Host, recorriendo los
    ejemplares del modelo: no depende de FindInserts (que con tramos apilados y unidos deja de devolver las copias) ni
    de lo que devuelva CopyElement."""
    res = dict((i, []) for i in ids_muros)
    for clase in (DB.FamilyInstance, DB.Opening):
        try:elementos = list(DB.FilteredElementCollector(doc).OfClass(clase))
        except Exception:elementos = []
        for e in elementos:
            try:anfitrion = _id_num(e.Host.Id)
            except Exception:continue
            if anfitrion in res:
                res[anfitrion].append(e)
    return res


def cortar_muro(doc, info, plan, op, diag=DG.NULO):
    """Parte el muro segun su plan, dentro de la transaccion abierta. Devuelve el resultado para el informe y la foto
    de parametros (para verificarla despues del Commit)."""
    muro = info["elemento"]
    tramos = [(m_a_ft(a), m_a_ft(b)) for a, b in plan["tramos"]]
    n, k = len(tramos), plan["original"]
    foto = leer_parametros(muro, excluidos(op.get("copiar_marca", True)))
    res = {"id": info["id"], "piezas": [], "param_copiados": 0, "param_fallos": [], "insertos_borrados": 0,
           "insertos_sin_ubicar": 0, "huecos": 0, "huecos_fallidos": 0, "otros_borrados": {}, "embebidos": 0,
           "avisos": list(plan.get("avisos", []))}
    rangos = [(info["base_z"] + a, info["base_z"] + b) for a, b in tramos]
    diag.paso("plan", muro=info["id"], tramos_m=plan["tramos"], original=k, cruce=op.get("cruce"))

    # 1. Lo que hospeda el original, AHORA, antes de tocar nada.
    propios = _hospedados(doc, [info["id"]])[info["id"]]
    ids_originales = set(_id_num(e.Id) for e in propios)
    embebidos = [e for e in _insertos(doc, muro) if isinstance(e, DB.Wall)]
    diag.paso("originales", muro=describir(doc, muro), hospedados=[describir(doc, e) for e in propios],
              por_findinserts=[describir(doc, e) for e in _insertos(doc, muro)])

    # 2. Copias (antes de cambiar nada del original) con la foto de parametros.
    piezas, otros = [], []
    for i in range(n):
        if i == k:
            piezas.append(muro)
            continue
        copia, resto = _copiar_muro(doc, muro)
        copiados, fallos = escribir_parametros(copia, foto)
        res["param_copiados"] += copiados
        for f in fallos:
            if f not in res["param_fallos"]:res["param_fallos"].append(f)
        piezas.append(copia)
        diag.paso("copia", tramo=i, copia=_id_num(copia.Id),
                  devuelto_por_copyelement=[describir(doc, doc.GetElement(x)) for x in resto])
        for eid in resto:
            e = doc.GetElement(eid)
            # un muro cortina embebido o armaduras hospedadas quedarian duplicados: el original sigue en su lugar
            if e is not None and not isinstance(e, (DB.FamilyInstance, DB.Opening)):
                if not isinstance(e, DB.Wall):
                    cat = _nombre(e.Category, u"otros") if e.Category is not None else u"otros"
                    res["otros_borrados"][cat] = res["otros_borrados"].get(cat, 0) + 1
                otros.append(eid)
    doc.Regenerate()              # las alturas aun no cambiaron: el modelo esta igual que antes, con las copias encima

    # 3. Puertas y ventanas de cada tramo, por su anfitrion. Cada una queda en el tramo de su base; sus copias
    # sobrantes se borran ANTES de cambiar las alturas.
    ids_piezas = [_id_num(p.Id) for p in piezas]
    hospedados = _hospedados(doc, ids_piezas)
    por_tramo, aberturas, datos = [[] for _ in range(n)], [[] for _ in range(n)], {}
    for i, pid in enumerate(ids_piezas):
        for e in hospedados[pid]:
            if isinstance(e, DB.Opening):
                aberturas[i].append(e)
                continue
            d = _datos_inserto(doc, e)
            if d is not None:
                d["copia"] = d["id"] not in ids_originales
                datos[d["id"]] = d
                por_tramo[i].append(d)
    diag.paso("hospedados_tras_copiar", rangos_m=[(ft_a_m(a), ft_a_m(b)) for a, b in rangos],
              por_tramo=[[{"id": d["id"], "copia": d["copia"], "clave": d["clave"], "z_m": (ft_a_m(d["z_inf"]),
                                                                                           ft_a_m(d["z_sup"]))}
                          for d in fam] for fam in por_tramo])
    regla = op.get("anfitrion", LC.ANFITRION_BASE)
    conservar, borrar, sin_ubicar = LC.asignar_insertos(
        rangos, [[(d["id"], d["clave"], LC.cota_referencia(d["z_inf"], d["z_sup"], regla, TOL_FT), d["copia"])
                  for d in fam] for fam in por_tramo], TOL_FT)
    res["insertos_sin_ubicar"] = len(sin_ubicar)
    pedidos = LC.huecos_para_insertos(rangos, [(i, datos[i]["z_inf"], datos[i]["z_sup"]) for i in conservar], TOL_FT,
                                      regla)
    diag.paso("asignacion", conservar=conservar, borrar=borrar, sin_ubicar=sin_ubicar, huecos_pedidos=pedidos)
    res["insertos_borrados"] = _borrar(doc, [datos[i]["eid"] for i in borrar])
    _borrar(doc, otros)

    # 4. altura de cada tramo
    for i, (a, b) in enumerate(tramos):
        ajustar_tramo(piezas[i], a, b, i == n - 1, info)
    doc.Regenerate()

    # 5. Red de seguridad: si quedo hospedada en algun tramo una COPIA que no se decidio conservar (un duplicado que
    # ningun paso anterior vio), se borra. Los originales nunca se borran aqui.
    guardar = set(conservar) | set(sin_ubicar)
    sobrantes = [e for pid in ids_piezas for e in _hospedados(doc, [pid])[pid]
                 if isinstance(e, DB.FamilyInstance) and _id_num(e.Id) not in guardar
                 and _id_num(e.Id) not in ids_originales]
    if sobrantes:
        diag.paso("red_de_seguridad", borrados=[describir(doc, e) for e in sobrantes])
        res["insertos_borrados"] += _borrar(doc, [e.Id for e in sobrantes])
        doc.Regenerate()
    diag.paso("tras_alturas", tramos=[describir(doc, p) for p in piezas],
              hospedados=dict((pid, [describir(doc, e) for e in lista])
                              for pid, lista in _hospedados(doc, ids_piezas).items()))

    def abrir(i, punto, ancho, zlo, zhi):
        try:
            if punto is not None and info["recto"] and _crear_hueco(doc, piezas[i], punto, ancho, zlo, zhi) is not None:
                res["huecos"] += 1
                return
        except Exception:
            pass
        res["huecos_fallidos"] += 1

    for i, iid, zlo, zhi in pedidos:
        d = datos[iid]
        ancho = d["ancho"]
        if not ancho and info["recto"]:
            c = piezas[i].Location.Curve
            ancho = _ancho_caja(d["caja"], DB.XYZ(c.Direction.X, c.Direction.Y, 0).Normalize())
        abrir(i, d["punto"], ancho, zlo, zhi)

    # Muros cortina embebidos: no se copian ni se mueven. Siguen embebidos en el tramo original; en los demas tramos
    # que atraviesan se abre un hueco de su tamano.
    for ins in info.get("insertos") or []:
        if ins["tipo"] not in (u"muro cortina", u"muro embebido"):
            continue
        res["embebidos"] += 1
        for i, (lo, hi) in enumerate(rangos):
            parte = LC.recortar(ins["zi_ft"], ins["zs_ft"], lo, hi, TOL_FT)
            if i != k and parte is not None:
                abrir(i, ins["punto"], ins["ancho_ft"], parte[0], parte[1])

    for i, pieza in enumerate(piezas):
        lo, hi = rangos[i]
        for o in aberturas[i]:
            try:
                if not o.IsRectBoundary:
                    res["avisos"].append(u"tiene un hueco de muro con boceto libre: revísalo en cada tramo")
                    continue
                r = list(o.BoundaryRect)
                zi, zs = min(r[0].Z, r[1].Z), max(r[0].Z, r[1].Z)
                parte = LC.recortar(zi, zs, lo, hi, TOL_FT)
                if parte is not None and abs(parte[0] - zi) < TOL_FT and abs(parte[1] - zs) < TOL_FT:
                    continue
                _borrar(doc, [o.Id])
                if parte is not None:
                    doc.Create.NewOpening(pieza, DB.XYZ(r[0].X, r[0].Y, parte[0]), DB.XYZ(r[1].X, r[1].Y, parte[1]))
            except Exception:
                res["huecos_fallidos"] += 1

    # 5. el tramo en un parametro de texto (A1, A2...), si se pidio
    nombre_param = op.get("param_tramo")
    if nombre_param:
        for i, pieza in enumerate(piezas):
            p = pieza.LookupParameter(nombre_param)
            if p is None or p.IsReadOnly or p.StorageType != DB.StorageType.String:
                res["avisos"].append(u"no se pudo escribir el tramo en «{}»".format(nombre_param))
                break
            p.Set(LC.nombre_tramo(op.get("prefijo"), i))

    res["piezas"] = [_id_num(p.Id) for p in piezas]
    res["_elementos"] = piezas
    diag.paso("antes_de_confirmar", huecos=res["huecos"], huecos_fallidos=res["huecos_fallidos"],
              hospedados=dict((pid, [describir(doc, e) for e in lista])
                              for pid, lista in _hospedados(doc, ids_piezas).items()))
    return res, foto


def _cortar_en_transaccion(doc, info, plan, op, diag=DG.NULO):
    """(res, foto, avisos) si Revit confirmo el corte de este muro; si no, lanza con el motivo. La transaccion es solo
    de este muro: si falla, el muro queda como estaba."""
    pre = Preprocesador(doc)
    tr = DB.Transaction(doc, u"{} · Id {}".format(TITULO_DESHACER, info["id"]))
    opciones = tr.GetFailureHandlingOptions()
    opciones.SetFailuresPreprocessor(pre)
    opciones.SetClearAfterRollback(True)
    tr.SetFailureHandlingOptions(opciones)
    tr.Start()
    try:
        res, foto = cortar_muro(doc, info, plan, op, diag)
        estado = tr.Commit()
    except Exception as ex:
        diag.paso("excepcion", muro=info["id"], error=u"{}".format(ex), tipo=type(ex).__name__)
        if tr.GetStatus() == DB.TransactionStatus.Started:
            tr.RollBack()
        raise
    diag.paso("confirmar", muro=info["id"], estado=u"{}".format(estado), avisos=pre.avisos, errores=pre.errores,
              fallas=pre.detalle)
    if estado != DB.TransactionStatus.Committed:
        raise Exception(u"; ".join(pre.errores) or u"Revit no confirmó el cambio")
    return res, foto, pre.avisos


def cortar_muros(doc, infos, op, diag=DG.NULO):
    """Corta todos los muros (una transaccion por muro dentro de un grupo: un solo Deshacer) y devuelve el reporte
    para logica_corte.texto_reporte, con los Id de los tramos en 'ids_resultado'.

    Si Revit rechaza un muro con una puerta o ventana que cruza el corte (entera en el tramo de su base y hueco en el
    otro), ese muro se reintenta dejandola entera en el tramo de su tope y el hueco en el de abajo. La altura de corte
    no cambia: si tampoco funciona, el muro queda como estaba y el informe y el diagnostico dicen por que."""
    planes = LC.planificar(infos, op)
    rep = {"cortados": [], "omitidos": [], "fallidos": [], "avisos_revit": [], "ids_resultado": []}
    ignorar = (op.get("param_tramo"),) if op.get("param_tramo") else ()
    grupo = DB.TransactionGroup(doc, TITULO_DESHACER)
    grupo.Start()
    try:
        for info, plan in zip(infos, planes):
            if plan["omitir"]:
                rep["omitidos"].append((info["id"], plan["omitir"]))
                continue
            intentos = [(plan, dict(op, anfitrion=LC.ANFITRION_BASE))]
            if plan.get("cruces") and op.get("cruce", LC.CRUCE_HUECO) == LC.CRUCE_HUECO:
                intentos.append((plan, dict(op, anfitrion=LC.ANFITRION_TOPE)))
            hecho, motivo = None, None
            for j, (plan_j, op_j) in enumerate(intentos):
                diag.paso("intento", muro=info["id"], numero=j + 1, cruce=op_j.get("cruce"),
                          anfitrion=op_j.get("anfitrion"), tramos_m=plan_j["tramos"])
                try:
                    hecho = _cortar_en_transaccion(doc, info, plan_j, op_j, diag)
                except Exception as ex:
                    motivo = u"{}".format(ex)
                    continue
                if j > 0:
                    hecho[0]["avisos"].insert(0, u"Revit no aceptó la puerta o ventana en el tramo de su base ({}); "
                                                 u"quedó entera en el tramo de arriba y el hueco en el de abajo, "
                                                 u"con la misma altura de corte".format(motivo))
                break
            if hecho is None:
                rep["fallidos"].append((info["id"], motivo))
                continue
            res, foto, avisos = hecho
            for a in avisos:
                if a not in rep["avisos_revit"]:rep["avisos_revit"].append(a)
            piezas = res.pop("_elementos")
            dif = []
            for pieza in piezas:
                for nombre in diferencias(pieza, foto, ignorar):
                    if nombre not in dif:dif.append(nombre)
            res["diferencias"] = dif
            rep["cortados"].append(res)
            rep["ids_resultado"].extend(p.Id for p in piezas)
        grupo.Assimilate()
    except Exception:
        try:grupo.RollBack()
        except Exception:pass
        raise
    return rep
