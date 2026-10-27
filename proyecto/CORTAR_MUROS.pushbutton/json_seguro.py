# -*- coding: utf-8 -*-
"""JSON para ESCRIBIR sin el modulo json, que en el IronPython 2.7 de pyRevit falla con tildes.

En IronPython str y unicode son el mismo tipo, y el codificador de json (py_encode_basestring_ascii) toma un texto con
"ó" o "ñ" por bytes UTF-8 y trata de decodificarlo: "UnicodeDecodeError: 'unknown' codec can't decode byte 0xf3".
Paso al guardar el diagnostico de CORTAR MUROS con un tipo de muro llamado "Partición...", y antes (en silencio) al
recordar un parametro con tilde en ultima_configuracion.json. En CPython no pasa, asi que las pruebas no lo veian.

Este escritor solo conoce lo que usa el boton (dict, list, tuple, set, texto, int, float, bool, None; lo demas pasa a
texto) y escribe todo caracter que no sea ASCII como \\uXXXX: el archivo resultante es ASCII puro y json.load lo lee
igual en IronPython y en CPython. Para LEER se sigue usando json.load, que no tiene ese problema."""

try:
    _ENTEROS = (int, long)               # IronPython 2.7
except NameError:
    _ENTEROS = (int,)

_ESCAPES = {u'"': u'\\"', u'\\': u'\\\\', u'\n': u'\\n', u'\r': u'\\r', u'\t': u'\\t', u'\b': u'\\b', u'\f': u'\\f'}


def cadena(s):
    """Texto JSON entre comillas, solo con caracteres ASCII."""
    partes = [u'"']
    for ch in s:
        o = ord(ch)
        if ch in _ESCAPES:
            partes.append(_ESCAPES[ch])
        elif 0x20 <= o <= 0x7e:
            partes.append(ch)
        elif o > 0xFFFF:
            # CPython guarda estos caracteres enteros; JSON los escribe en dos mitades (IronPython ya los tiene asi)
            o -= 0x10000
            partes.append(u"\\u%04x\\u%04x" % (0xD800 + (o >> 10), 0xDC00 + (o & 0x3FF)))
        else:
            partes.append(u"\\u%04x" % o)
    partes.append(u'"')
    return u"".join(partes)


def _texto(v):
    try:
        return u"{}".format(v)
    except Exception:
        return u"(no se pudo leer)"


def a_json(v, sangria=2, nivel=0):
    """El valor como texto JSON (ASCII puro), con sangria para que se pueda leer."""
    if v is None:
        return u"null"
    if v is True:
        return u"true"
    if v is False:
        return u"false"
    if isinstance(v, _ENTEROS):
        return _texto(int(v))
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return u"null"
        return _texto(repr(v))
    margen = u"\n" + u" " * (sangria * (nivel + 1))
    cierre = u"\n" + u" " * (sangria * nivel)
    if isinstance(v, dict):
        if not v:
            return u"{}"
        return u"{" + u",".join(margen + cadena(_texto(k)) + u": " + a_json(x, sangria, nivel + 1)
                                for k, x in v.items()) + cierre + u"}"
    if isinstance(v, (list, tuple, set)):
        if not v:
            return u"[]"
        return u"[" + u",".join(margen + a_json(x, sangria, nivel + 1) for x in v) + cierre + u"]"
    return cadena(_texto(v))
