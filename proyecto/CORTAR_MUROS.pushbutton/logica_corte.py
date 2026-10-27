# -*- coding: utf-8 -*-
"""CORTAR MUROS -- la logica del corte, sin Revit ni WPF: se prueba en CPython y corre igual en el IronPython 2.7 de
pyRevit.

Un muro de altura H (medida desde su base) se parte en TRAMOS apilados segun las alturas de corte pedidas:
  una altura     1 corte                        -> 2 tramos;
  varias         lista de alturas ("1.20; 2.40") -> n + 1 tramos;
  alzadas cada   un paso p: cortes en p, 2p, 3p... desde la base (las alzadas de asentado: 1.30 m de la E.070,
                 1.50 m en obra), hasta llegar al tope.
Cada tramo es (a, b): desde a hasta b metros sobre la base del muro, con 0 <= a < b <= H. Todas las medidas de este
modulo estan en METROS; revit_corte.py convierte a pies al tocar el modelo.

Un corte que deja un tramo menor que el tramo minimo (por defecto 5 cm) no se hace: evita tiras de muro sin sentido
cuando una altura cae justo en el tope o la base. Se informa como corte ignorado."""
from __future__ import division

import re

MODO_UNA, MODO_VARIAS, MODO_ALZADAS = "una", "varias", "alzadas"
MODOS = (MODO_UNA, MODO_VARIAS, MODO_ALZADAS)
REF_BASE, REF_NIVEL = "base", "nivel"
ORIGINAL_INFERIOR, ORIGINAL_SUPERIOR = "inferior", "superior"
MINIMO_CM_DEFECTO = 5.0
# Una alzada de 1 cm en un muro de 3 m serian 300 copias: casi seguro un error de tipeo, no un pedido.
MAX_TRAMOS = 40
EPS = 1e-6

_NUMERO = re.compile(u"^\\s*([-+]?(?:\\d+(?:[.,]\\d*)?|[.,]\\d+))\\s*(?:m)?\\s*$", re.IGNORECASE)


def leer_numero(texto):
    """'1.50', '1,50', ' 1.5 m' -> 1.5; vacio o invalido -> None. La coma es decimal (teclado en espanol)."""
    if texto is None:
        return None
    m = _NUMERO.match(u"{}".format(texto))
    if not m:
        return None
    try:
        return float(m.group(1).replace(u",", u"."))
    except ValueError:
        return None


def leer_lista(texto):
    """'1.20; 2,40  3' -> ([1.2, 2.4, 3.0], None). Se separa con punto y coma o espacios (la coma es decimal).
    Si algo no es un numero: (None, el texto que fallo)."""
    valores = []
    for parte in re.split(u"[;\\s]+", u"{}".format(texto or u"").strip()):
        if not parte:
            continue
        v = leer_numero(parte)
        if v is None:
            return None, parte
        valores.append(v)
    return valores, None


def validar_opciones(op):
    """Texto del primer problema de las opciones de la ventana, o None si se puede cortar con ellas."""
    if op.get("modo") not in MODOS:
        return u"Elige cómo cortar: una altura, varias alturas o alzadas."
    valores = op.get("valores") or []
    if not valores:
        return {MODO_UNA: u"Escribe la altura de corte en metros (por ejemplo 1.50).",
                MODO_VARIAS: u"Escribe las alturas de corte separadas con punto y coma (por ejemplo 1.20; 2.40).",
                MODO_ALZADAS: u"Escribe la altura de cada alzada en metros (por ejemplo 1.30)."}[op["modo"]]
    if op.get("error_valores"):
        return u"«{}» no es una altura válida.".format(op["error_valores"])
    if op["modo"] == MODO_ALZADAS and valores[0] <= 0:
        return u"La alzada tiene que ser mayor que cero."
    if any(v <= 0 for v in valores) and op.get("referencia") != REF_NIVEL:
        return u"Las alturas se miden desde la base del muro: tienen que ser mayores que cero."
    minimo = op.get("minimo_cm")
    if minimo is None or minimo < 0:
        return u"El tramo mínimo tiene que ser un número de centímetros (0 o más)."
    if op.get("param_tramo") is not None and not op.get("param_tramo"):
        return u"Elige el parámetro donde se escribe el tramo, o desmarca esa opción."
    return None


def cortes_pedidos(op, altura, base_offset):
    """Alturas de corte medidas desde la base del muro (m), ordenadas, antes de ajustarlas al muro.
    Medidas desde el nivel de base, se les resta el desfase de la base del muro: con el muro a +0.10 m de su nivel,
    cortar a 1.50 m del nivel es cortar a 1.40 m de la base. Las alzadas siempre se cuentan desde la base: son el
    asentado de cada jornada."""
    valores = op.get("valores") or []
    if op["modo"] == MODO_ALZADAS:
        paso = valores[0] if valores else 0.0
        if paso <= 0:
            return []
        cortes = []
        k = 1
        while paso * k < altura - EPS and k < MAX_TRAMOS:
            cortes.append(paso * k)
            k += 1
        return cortes
    desplazar = base_offset if op.get("referencia") == REF_NIVEL else 0.0
    return sorted(v - desplazar for v in (valores[:1] if op["modo"] == MODO_UNA else valores))


def tramos(altura, cortes, minimo):
    """(tramos, ignorados): los tramos (a, b) en que queda un muro de altura 'altura' con esos cortes, y los cortes que
    no se hacen porque caen fuera del muro o dejan un tramo menor que 'minimo'."""
    bordes = [0.0]
    ignorados = []
    for c in sorted(cortes):
        if c < minimo - EPS or c > altura - minimo + EPS or c - bordes[-1] < minimo - EPS or c <= EPS \
                or c >= altura - EPS or len(bordes) >= MAX_TRAMOS:
            ignorados.append(c)
            continue
        bordes.append(c)
    bordes.append(altura)
    return [(bordes[i], bordes[i + 1]) for i in range(len(bordes) - 1)], ignorados


def pieza_original(n, preferencia, tope_enlazado=False, base_enlazada=False):
    """(indice, aviso): el tramo que conserva el muro ORIGINAL -- su Id, sus etiquetas, lo que tenga hospedado -- y un
    aviso si no pudo ser el pedido. Los demas tramos son copias.
    Un extremo enlazado (Attach Top/Base a una losa o cubierta) solo lo conserva el muro original, porque la copia no
    hereda el enlace: el tramo con ese extremo tiene que ser el original. Con los dos extremos enlazados y mas de un
    tramo no hay forma de conservar ambos: indice None (el muro se omite)."""
    if n < 2:
        return 0, None
    if tope_enlazado and base_enlazada:
        return None, u"tiene la base y el tope enlazados (Attach): desenlaza uno de los dos para poder cortarlo"
    pedido = 0 if preferencia == ORIGINAL_INFERIOR else n - 1
    if tope_enlazado and pedido != n - 1:
        return n - 1, u"el tope está enlazado (Attach): el muro original queda como el tramo superior"
    if base_enlazada and pedido != 0:
        return 0, u"la base está enlazada (Attach): el muro original queda como el tramo inferior"
    return pedido, None


def planificar(infos, op):
    """Un plan por muro (en el mismo orden que infos): sus tramos, los cortes ignorados, el tramo que conserva el
    original, avisos y, si no se corta, el motivo ('omitir'). infos son los diccionarios de revit_corte.analizar_muro
    (solo se usan altura_m, base_offset_m, tope_enlazado, base_enlazada y omitir)."""
    minimo = (op.get("minimo_cm") or 0.0) / 100.0
    planes = []
    for info in infos:
        plan = {"tramos": [], "ignorados": [], "original": None, "avisos": [], "omitir": info.get("omitir")}
        planes.append(plan)
        if plan["omitir"]:
            continue
        altura = info.get("altura_m") or 0.0
        if altura <= 2 * max(minimo, EPS):
            plan["omitir"] = u"es demasiado bajo para cortarlo ({:.2f} m)".format(altura)
            continue
        plan["tramos"], plan["ignorados"] = tramos(altura, cortes_pedidos(op, altura, info.get("base_offset_m") or 0.0),
                                                   minimo)
        if len(plan["tramos"]) < 2:
            plan["omitir"] = u"ningún corte cae dentro del muro (altura {:.2f} m)".format(altura)
            continue
        plan["original"], aviso = pieza_original(len(plan["tramos"]), op.get("original"),
                                                 info.get("tope_enlazado"), info.get("base_enlazada"))
        if plan["original"] is None:
            plan["omitir"] = aviso
            continue
        if aviso:
            plan["avisos"].append(aviso)
        if plan["ignorados"]:
            plan["avisos"].append(u"cortes no hechos (fuera del muro o dejan un tramo menor que el mínimo): {}".format(
                u", ".join(u"{:.2f} m".format(c) for c in plan["ignorados"])))
    return planes


def tramo_de_cota(rangos, z, tol):
    """Indice del tramo donde cae la cota z (absoluta, en las unidades de 'rangos'). Lo que esta justo en un corte
    pertenece al tramo de arriba; lo que queda por debajo del primero, al primero; por encima del ultimo, al ultimo."""
    for i, (lo, hi) in enumerate(rangos):
        if z < hi - tol:
            return i
    return len(rangos) - 1


def asignar_insertos(rangos, insertos_por_tramo, tol):
    """Que puertas, ventanas y muros embebidos se quedan y cuales se borran.

    insertos_por_tramo: una lista por tramo con (id, clave, z_inferior) de los insertos hospedados en ese tramo. Copiar
    un muro copia tambien sus insertos, asi que el mismo inserto (la misma clave: tipo y posicion) aparece en varios
    tramos. Se conserva en el tramo donde cae su borde inferior y se borra de los demas. Si ese tramo no tiene su
    ejemplar (Revit no lo copio), no se borra ninguno: mejor un duplicado a la vista que perder una puerta.
    Devuelve (conservar, borrar, sin_ubicar), listas de ids."""
    orden = []
    por_clave = {}
    for i, lista in enumerate(insertos_por_tramo):
        for iid, clave, z in lista:
            if clave not in por_clave:
                por_clave[clave] = []
                orden.append(clave)
            por_clave[clave].append((i, iid, z))
    conservar, borrar, sin_ubicar = [], [], []
    for clave in orden:
        ejemplares = por_clave[clave]
        destino = tramo_de_cota(rangos, ejemplares[0][2], tol)
        elegido = None
        for e in ejemplares:
            if e[0] == destino:
                elegido = e
                break
        if elegido is None:
            sin_ubicar.extend(e[1] for e in ejemplares)
            continue
        conservar.append(elegido[1])
        borrar.extend(e[1] for e in ejemplares if e is not elegido)
    return conservar, borrar, sin_ubicar


def recortar(zi, zs, lo, hi, tol):
    """La parte de [zi, zs] que cae en [lo, hi], o None si es menor que tol."""
    a, b = max(zi, lo), min(zs, hi)
    return (a, b) if b - a > tol else None


def huecos_para_insertos(rangos, insertos, tol):
    """Huecos que hay que abrir donde un inserto cruza un corte.

    insertos: (id, z_inferior, z_superior) de los insertos conservados. El inserto se queda en el tramo de su borde
    inferior y solo abre ese muro: en los demas tramos que atraviesa (una puerta de 2.10 m con corte a 1.50 m: de 1.50
    a 2.10 en el tramo de arriba) el muro quedaria lleno. Devuelve [(indice_tramo, id, z_lo, z_hi)]."""
    pedidos = []
    for iid, zi, zs in insertos:
        k = tramo_de_cota(rangos, zi, tol)
        for i, (lo, hi) in enumerate(rangos):
            if i == k:
                continue
            r = recortar(zi, zs, lo, hi, tol)
            if r:
                pedidos.append((i, iid, r[0], r[1]))
    return pedidos


def nombre_tramo(prefijo, indice):
    """El valor que se escribe en el parametro elegido: prefijo + numero de tramo desde abajo (A1, A2...)."""
    return u"{}{}".format(prefijo or u"", indice + 1)


def texto_tramos(lista):
    """'0.00–1.50 · 1.50–2.60' para la lista de la ventana."""
    return u" · ".join(u"{:.2f}–{:.2f}".format(a, b) for a, b in lista)


def resumen_planes(planes):
    """Una linea para el pie de la ventana: cuantos muros se cortan, en cuantos tramos, y cuantos se omiten."""
    cortan = [p for p in planes if not p["omitir"]]
    omitidos = len(planes) - len(cortan)
    partes = [u"{} muro{}".format(len(planes), u"" if len(planes) == 1 else u"s")]
    if cortan:
        n = sum(len(p["tramos"]) for p in cortan)
        partes.append(u"{} se corta{} en {} tramos".format(len(cortan), u"" if len(cortan) == 1 else u"n", n))
    if omitidos:
        partes.append(u"{} se omite{}".format(omitidos, u"" if omitidos == 1 else u"n"))
    return u" · ".join(partes)


def _s(n):
    return u"" if n == 1 else u"s"


def texto_reporte(rep):
    """El mensaje final para el usuario a partir del reporte de revit_corte.cortar_muros."""
    cortados, omitidos, fallidos = rep.get("cortados", []), rep.get("omitidos", []), rep.get("fallidos", [])
    total = len(cortados) + len(omitidos) + len(fallidos)
    lineas = [u"Muros cortados: {} de {}  ·  tramos resultantes: {}".format(
        len(cortados), total, sum(len(c.get("piezas", [])) for c in cortados))]
    if cortados:
        nuevos = sum(len(c.get("piezas", [])) - 1 for c in cortados)
        copiados = sum(c.get("param_copiados", 0) for c in cortados)
        lineas.append(u"Parámetros: {} valores copiados a {} tramo{} nuevo{} y verificados contra el muro "
                      u"original.".format(copiados, nuevos, _s(nuevos), _s(nuevos)))
        reub = sum(c.get("insertos_borrados", 0) for c in cortados)
        huecos = sum(c.get("huecos", 0) for c in cortados)
        if reub or huecos:
            lineas.append(u"Puertas y ventanas: cada una quedó en el tramo de su base ({} copia{} sobrante{} "
                          u"borrada{}); {} hueco{} abierto{} donde cruzan un corte.".format(
                              reub, _s(reub), _s(reub), _s(reub), huecos, _s(huecos), _s(huecos)))
    revisar = []
    for c in cortados:
        cosas = []
        if c.get("diferencias"):
            cosas.append(u"parámetros que no quedaron iguales: " + u", ".join(c["diferencias"]))
        if c.get("param_fallos"):
            cosas.append(u"parámetros que no se pudieron escribir: " + u", ".join(c["param_fallos"]))
        if c.get("insertos_sin_ubicar"):
            cosas.append(u"{} inserto(s) no se pudieron reubicar: quedaron duplicados".format(c["insertos_sin_ubicar"]))
        if c.get("huecos_fallidos"):
            cosas.append(u"{} hueco(s) no se pudieron abrir".format(c["huecos_fallidos"]))
        if c.get("otros_borrados"):
            cosas.append(u"se borraron copias de elementos dependientes ({}); los originales siguen en el muro "
                         u"original".format(u", ".join(u"{} {}".format(v, k) for k, v in sorted(c["otros_borrados"].items()))))
        cosas.extend(c.get("avisos", []))
        if cosas:
            revisar.append(u"  · Id {}: {}".format(c.get("id"), u"; ".join(cosas)))
    if revisar:
        lineas.append(u"\nRevisar:")
        lineas.extend(revisar)
    if omitidos:
        lineas.append(u"\nOmitidos:")
        lineas.extend(u"  · Id {}: {}".format(i, m) for i, m in omitidos)
    if fallidos:
        lineas.append(u"\nNo se pudieron cortar (quedaron como estaban):")
        lineas.extend(u"  · Id {}: {}".format(i, m) for i, m in fallidos)
    avisos = rep.get("avisos_revit") or []
    if avisos:
        lineas.append(u"\nAvisos de Revit (aceptados):")
        lineas.extend(u"  · {}".format(a) for a in avisos[:8])
        if len(avisos) > 8:
            lineas.append(u"  · ... y {} más".format(len(avisos) - 8))
    return u"\n".join(lineas)
