# -*- coding: utf-8 -*-
"""Open Sans local, como en COLUMNAS: la interfaz no depende de las fuentes instaladas en Windows.
Busca la carpeta fuentes/ junto a este boton y, si no esta, la del boton COLUMNAS del mismo panel (asi no hace falta
duplicar los .ttf). Sin ninguna de las dos, usa Segoe UI."""
import os.path as op

_FUENTE = None
AQUI = op.dirname(op.abspath(__file__))
CANDIDATAS = (op.join(AQUI, "fuentes"), op.join(op.dirname(AQUI), "COLUMNAS.pushbutton", "fuentes"))


def carpeta_fuentes():
    for carpeta in CANDIDATAS:
        if op.isfile(op.join(carpeta, "OpenSans-Regular.ttf")):
            return carpeta
    return None


def fuente_interfaz():
    global _FUENTE
    if _FUENTE is None:
        from System import Uri
        from System.Windows.Media import FontFamily
        carpeta = carpeta_fuentes()
        _FUENTE = FontFamily(Uri(carpeta + op.sep), "./#Open Sans") if carpeta else FontFamily("Segoe UI")
    return _FUENTE


def aplicar_tipografia(ventana):
    fuente = fuente_interfaz()
    ventana.Resources["FuenteInterfaz"] = fuente
    ventana.FontFamily = fuente
