# -*- coding: utf-8 -*-
"""CORTAR MUROS -- recuerda lo ultimo que se uso (modo, alturas, opciones y tema) en ultima_configuracion.json, junto
al script, igual que los config_*.py de los otros botones: la proxima vez la ventana abre con esos valores.

Cada valor se valida al cargar: lo que falte o tenga otra forma se reemplaza por el de DEFECTO, asi que nunca se
propaga a la ventana un valor roto y recordar nunca impide cortar. Ninguna funcion lanza."""
import json
import os.path as op

import json_seguro as JS

NOMBRE_ARCHIVO = "ultima_configuracion.json"
RUTA_CONFIG = op.join(op.dirname(op.abspath(__file__)), NOMBRE_ARCHIVO)
TEMAS = ("Claro", "Oscuro")

DEFECTO = {
    "modo": "una",               # una | varias | alzadas
    "altura": u"1.50",
    "alturas": u"1.20; 2.40",
    "alzada": u"1.30",
    "referencia": "base",        # base | nivel
    "minimo_cm": u"5",
    "original": "inferior",      # inferior | superior
    "copiar_marca": True,
    "cruce": "hueco",            # hueco | ajustar | omitir: puertas y ventanas que cruzan el corte
    "vista": "todos",            # todos | uno: modo de la vista previa
    "escribir_tramo": False,
    "param_tramo": u"",
    "prefijo": u"A",
    "seleccionar": True,
    "TemaInterfaz": "Claro",
}
_OPCIONES = {"modo": ("una", "varias", "alzadas"), "referencia": ("base", "nivel"),
             "cruce": ("hueco", "ajustar", "omitir"), "vista": ("todos", "uno"),
             "original": ("inferior", "superior"), "TemaInterfaz": TEMAS}


def _leer():
    try:
        with open(RUTA_CONFIG, "r") as f:
            crudo = json.load(f)
    except Exception:
        return {}
    return crudo if isinstance(crudo, dict) else {}


def cargar():
    """La configuracion completa (todas las claves de DEFECTO), con lo guardado que sea valido."""
    guardado = _leer()
    cfg = dict(DEFECTO)
    for clave, defecto in DEFECTO.items():
        v = guardado.get(clave)
        if clave in _OPCIONES:
            if v in _OPCIONES[clave]:cfg[clave] = v
        elif isinstance(defecto, bool):
            if isinstance(v, bool):cfg[clave] = v
        elif isinstance(v, (type(u""), str)):
            cfg[clave] = v
    return cfg


def guardar(cfg):
    """Guarda solo las claves conocidas. Best effort: si no se puede escribir, falla en silencio."""
    if not isinstance(cfg, dict):
        return
    datos = cargar()
    for clave in DEFECTO:
        if clave in cfg:
            datos[clave] = cfg[clave]
    try:
        with open(RUTA_CONFIG, "w") as f:
            f.write(JS.a_json(datos))           # no json.dump: en IronPython falla con tildes (ver json_seguro.py)
    except Exception:
        pass


def guardar_tema(tema):
    """Cambiar el tema se recuerda al momento, sin esperar a cortar."""
    if tema in TEMAS:
        guardar({"TemaInterfaz": tema})
