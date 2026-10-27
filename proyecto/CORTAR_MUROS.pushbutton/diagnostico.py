# -*- coding: utf-8 -*-
"""CORTAR MUROS -- registro de diagnostico: cada ejecucion deja un JSON con lo que paso en el modelo, paso a paso.

Para que se usa: el corte ocurre dentro de Revit y cuando algo sale mal lo unico que se ve es el mensaje final. El
JSON guarda, para cada muro y cada intento, que puertas y ventanas tenia, que devolvio CopyElement, que quedo
hospedado en cada tramo, que se borro, las alturas que quedaron y que elementos exactos rechazo Revit. Con ese archivo
se puede corregir sin estar frente al modelo.

Donde queda: en la carpeta diagnostico/ junto a este boton (pyRevit no la toma como boton porque no termina en
.pushbutton). Si no se puede escribir ahi, en %TEMP%/DENOVA_cortar_muros. Cada ejecucion crea
cortar_muros_AAAAMMDD_HHMMSS.json y reemplaza ultimo.json; se conservan los ultimos MAX_ARCHIVOS.

Nada de este modulo interrumpe el corte: si algo falla al registrar, se anota en 'errores_diagnostico' y se sigue."""
import json
import os
import os.path as op
import time

VERSION = u"2.3"
CARPETA = op.join(op.dirname(op.abspath(__file__)), "diagnostico")
PREFIJO = "cortar_muros_"
MAX_ARCHIVOS = 30


def limpio(v, profundidad=0):
    """Lo mismo, pero que json pueda escribir: objetos de .NET o de Revit pasan a texto y los decimales se redondean."""
    if profundidad > 12:
        return u"..."
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, int):
        return v
    try:
        if isinstance(v, long):            # IronPython 2.7
            return int(v)
    except NameError:
        pass
    if isinstance(v, dict):
        return dict((u"{}".format(k), limpio(x, profundidad + 1)) for k, x in v.items())
    if isinstance(v, (list, tuple, set)):
        return [limpio(x, profundidad + 1) for x in v]
    try:
        return u"{}".format(v)
    except Exception:
        return u"(no se pudo leer)"


class Diagnostico(object):
    def __init__(self):
        self._t0 = time.time()
        self.datos = {"plugin": u"CORTAR MUROS", "version": VERSION, "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
                      "pasos": []}

    def poner(self, clave, valor):
        try:
            self.datos[clave] = limpio(valor)
        except Exception as ex:
            self._error(ex)

    def paso(self, nombre, **datos):
        try:
            d = {"paso": nombre, "t": round(time.time() - self._t0, 3)}
            d.update(datos)
            self.datos["pasos"].append(limpio(d))
        except Exception as ex:
            self._error(ex)

    def _error(self, ex):
        try:
            self.datos.setdefault("errores_diagnostico", []).append(u"{}".format(ex))
        except Exception:
            pass

    def guardar(self, carpeta=None):
        """Ruta del JSON guardado, o None si no se pudo escribir en ninguna parte."""
        texto = json.dumps(limpio(self.datos), indent=2, ensure_ascii=True)
        nombre = PREFIJO + time.strftime("%Y%m%d_%H%M%S") + ".json"
        for c in (carpeta or CARPETA, op.join(os.environ.get("TEMP") or os.environ.get("TMP") or ".",
                                               "DENOVA_cortar_muros")):
            try:
                if not op.isdir(c):
                    os.makedirs(c)
                for n in (nombre, "ultimo.json"):
                    with open(op.join(c, n), "w") as f:
                        f.write(texto)
                _podar(c)
                return op.join(c, nombre)
            except Exception:
                continue
        return None


def _podar(carpeta):
    """Deja solo los ultimos MAX_ARCHIVOS diagnosticos con fecha (ultimo.json no se cuenta)."""
    try:
        viejos = sorted(n for n in os.listdir(carpeta) if n.startswith(PREFIJO) and n.endswith(".json"))
        for n in viejos[:-MAX_ARCHIVOS]:
            os.remove(op.join(carpeta, n))
    except Exception:
        pass


class _Nulo(object):
    """Diagnostico que no hace nada: el corte no tiene que preguntar si hay uno."""
    def poner(self, *a, **k):pass
    def paso(self, *a, **k):pass


NULO = _Nulo()
