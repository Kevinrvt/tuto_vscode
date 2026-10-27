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
  4. Puertas, ventanas y muros embebidos: copiar un muro copia sus insertos, asi que cada uno queda solo en el tramo
     donde cae su borde inferior y se borran sus copias de los demas tramos. Donde un inserto cruza un corte, se abre
     un hueco rectangular en el tramo que atraviesa (opcional). Los huecos de muro (Opening) se recortan a cada tramo.
  5. Al terminar, se verifica parametro por parametro que cada tramo tenga los valores de la foto.
Las advertencias de Revit se aceptan y se informan; un error deshace solo ese muro, que queda como estaba."""
from __future__ import division

import Autodesk.Revit.DB as DB
from System.Collections.Generic import List

import logica_corte as LC

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
            "tope_enlazado": False, "base_enlazada": False, "recto": False, "textos": []}
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
    except Exception as ex:
        info["omitir"] = u"no se pudo leer su altura ({})".format(ex)
    return info


# ---- corte -------------------------------------------------------------------------------------------------------
class Preprocesador(DB.IFailuresPreprocessor):
    """Acepta las advertencias de Revit (y las anota para el informe); ante un error, deshace la transaccion."""

    def __init__(self):
        self.avisos = []
        self.errores = []

    def PreprocessFailures(self, fa):
        error = False
        for f in list(fa.GetFailureMessages()):
            try:texto = f.GetDescriptionText()
            except Exception:texto = u"(sin descripción)"
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
    try:ids = list(muro.FindInserts(True, False, True, True))
    except Exception:ids = []
    return [e for e in (doc.GetElement(i) for i in ids) if e is not None]


def _borrar(doc, eids):
    if not eids:
        return 0
    lista = List[DB.ElementId]()
    for eid in eids:
        lista.Add(eid)
    doc.Delete(lista)
    return len(eids)


def cortar_muro(doc, info, plan, op):
    """Parte el muro segun su plan, dentro de la transaccion abierta. Devuelve el resultado para el informe y la foto
    de parametros (para verificarla despues del Commit)."""
    muro = info["elemento"]
    tramos = [(m_a_ft(a), m_a_ft(b)) for a, b in plan["tramos"]]
    n, k = len(tramos), plan["original"]
    foto = leer_parametros(muro, excluidos(op.get("copiar_marca", True)))
    res = {"id": info["id"], "piezas": [], "param_copiados": 0, "param_fallos": [], "insertos_borrados": 0,
           "insertos_sin_ubicar": 0, "huecos": 0, "huecos_fallidos": 0, "otros_borrados": {},
           "avisos": list(plan.get("avisos", []))}

    # 1. copias (antes de cambiar nada del original) con la foto de parametros
    piezas, restos = [], []
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
        restos.extend(resto)

    # 2. altura de cada tramo
    for i, (a, b) in enumerate(tramos):
        ajustar_tramo(piezas[i], a, b, i == n - 1, info)
    doc.Regenerate()
    rangos = [(info["base_z"] + a, info["base_z"] + b) for a, b in tramos]

    # 3. insertos: cada uno en el tramo de su base; los huecos de muro, recortados a cada tramo
    por_tramo, aberturas, conocidos = [], [], set()
    for pieza in piezas:
        fam, abert = [], []
        for e in _insertos(doc, pieza):
            conocidos.add(_id_num(e.Id))
            if isinstance(e, DB.Opening):
                abert.append(e)
            else:
                d = _datos_inserto(doc, e)
                if d is not None:fam.append(d)
        por_tramo.append(fam)
        aberturas.append(abert)
    datos = dict((d["id"], d) for fam in por_tramo for d in fam)
    conservar, borrar, sin_ubicar = LC.asignar_insertos(
        rangos, [[(d["id"], d["clave"], d["z_inf"]) for d in fam] for fam in por_tramo], TOL_FT)
    res["insertos_sin_ubicar"] = len(sin_ubicar)
    pedidos = LC.huecos_para_insertos(rangos, [(i, datos[i]["z_inf"], datos[i]["z_sup"]) for i in conservar], TOL_FT) \
        if op.get("huecos", True) else []
    res["insertos_borrados"] = _borrar(doc, [datos[i]["eid"] for i in borrar])

    # Lo demas que Revit copio con el muro y no es un inserto (armaduras hospedadas, por ejemplo) quedaria duplicado:
    # se borra de las copias; el original sigue en el muro original.
    otros = []
    for eid in restos:
        e = doc.GetElement(eid)
        if e is None or _id_num(eid) in conocidos:
            continue
        cat = _nombre(e.Category, u"otros") if e.Category is not None else u"otros"
        res["otros_borrados"][cat] = res["otros_borrados"].get(cat, 0) + 1
        otros.append(eid)
    _borrar(doc, otros)

    for i, iid, zlo, zhi in pedidos:
        d = datos[iid]
        ancho = d["ancho"]
        try:
            if not ancho and info["recto"]:
                c = piezas[i].Location.Curve
                ancho = _ancho_caja(d["caja"], DB.XYZ(c.Direction.X, c.Direction.Y, 0).Normalize())
            if _crear_hueco(doc, piezas[i], d["punto"], ancho, zlo, zhi) is None:
                res["huecos_fallidos"] += 1
            else:
                res["huecos"] += 1
        except Exception:
            res["huecos_fallidos"] += 1
    if pedidos and not info["recto"]:
        res["avisos"].append(u"es curvo: los huecos donde las puertas o ventanas cruzan el corte hay que abrirlos a mano")

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

    # 4. el tramo en un parametro de texto (A1, A2...), si se pidio
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
    return res, foto


def cortar_muros(doc, infos, op):
    """Corta todos los muros (una transaccion por muro dentro de un grupo: un solo Deshacer) y devuelve el reporte
    para logica_corte.texto_reporte, con los Id de los tramos en 'ids_resultado'."""
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
            pre = Preprocesador()
            tr = DB.Transaction(doc, u"{} · Id {}".format(TITULO_DESHACER, info["id"]))
            opciones = tr.GetFailureHandlingOptions()
            opciones.SetFailuresPreprocessor(pre)
            opciones.SetClearAfterRollback(True)
            tr.SetFailureHandlingOptions(opciones)
            tr.Start()
            try:
                res, foto = cortar_muro(doc, info, plan, op)
                estado = tr.Commit()
            except Exception as ex:
                if tr.GetStatus() == DB.TransactionStatus.Started:
                    tr.RollBack()
                rep["fallidos"].append((info["id"], u"{}".format(ex)))
                continue
            if estado != DB.TransactionStatus.Committed:
                rep["fallidos"].append((info["id"], u"; ".join(pre.errores) or u"Revit no confirmó el cambio"))
                continue
            for a in pre.avisos:
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
