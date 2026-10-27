# -*- coding: utf-8 -*-
"""CORTAR MUROS -- parte uno o varios muros a una o varias alturas sin perder sus parametros.

Flujo: se eligen los muros (los ya seleccionados en Revit o, si no hay, se seleccionan ahora), la ventana muestra cada
muro con sus tramos en una vista previa en elevacion, y al pulsar «Cortar muros» cada muro queda partido en tramos
apilados: el original conserva su Id en uno de ellos y los demas son copias con los mismos parametros de instancia.

  logica_corte.py   las alturas, los tramos y que inserto va en cada tramo (sin Revit: se prueba en CPython)
  revit_corte.py    el corte en el modelo: copias, alturas, parametros, insertos, huecos y verificacion
  config_cortar.py  lo ultimo que se uso (ultima_configuracion.json)
  apariencia.py     la tipografia Open Sans de la extension"""
from pyrevit import forms
import Autodesk.Revit.DB as DB
import Autodesk.Revit.UI.Selection as UISelection
import System.Windows as Win
import System.Windows.Controls as Controls
import System.Windows.Media as Media
import System.Windows.Shapes as Shapes
from System.Collections.Generic import List
import os.path as op

import logica_corte as LC
import config_cortar as CFG

AQUI = op.dirname(op.abspath(__file__))
TITULO = u"DENOVA - Cortar muros"
MAX_PREVIA = 12                     # muros dibujados en la vista previa (la lista los muestra todos)

# Paleta DENOVA (claro, oscuro): la misma de COLUMNAS y PLACA. Cada clave es un recurso dinamico del XAML.
COLORES_TEMA = {
    "FondoVentana":("#FFFFFF", "#000000"),
    "FondoPanel":("#FFFFFF", "#404040"),
    "FondoControl":("#FFFFFF", "#000000"),
    "FondoTarjeta":("#FFFFFF", "#404040"),
    "Borde":("#404040", "#FFFFFF"),
    "BordeControl":("#404040", "#FFFFFF"),
    "Texto":("#000000", "#FFFFFF"),
    "TextoSuave":("#404040", "#FFFFFF"),
    "Acento":("#008080", "#008080"),
    "Resaltado":("#008080", "#008080"),
    "TextoAcento":("#008080", "#FFFFFF"),
    "Deshabilitado":("#404040", "#FFFFFF"),
    "FondoDeshabilitado":("#FFFFFF", "#404040"),
    "Hover":("#008080", "#008080"),
    "Error":("#000000", "#FFFFFF"),
    "FondoLienzo":("#FFFFFF", "#000000"),
}
# Columnas de la lista de muros: (titulo, ancho en px o None = proporcional con ese peso).
COLUMNAS = ((u"Id", 72, None), (u"Tipo", None, 1.3), (u"Nivel", 96, None), (u"Altura", 62, None),
            (u"Tramos (m)", None, 1.6), (u"Estado", None, 1.5))


def es_muro(elem):
    return isinstance(elem, DB.Wall)


class FiltroMuros(UISelection.ISelectionFilter):
    def AllowElement(self, e):return es_muro(e)
    def AllowReference(self, r, p):return False


def elegir_muros(uidoc):
    """Los muros ya seleccionados en Revit (lo demas de la seleccion se ignora); si no hay, los que se elijan ahora."""
    doc = uidoc.Document
    muros = [e for e in (doc.GetElement(i) for i in uidoc.Selection.GetElementIds()) if es_muro(e)]
    if muros:
        return muros
    refs = uidoc.Selection.PickObjects(UISelection.ObjectType.Element, FiltroMuros(),
                                       "Selecciona los muros a cortar y pulsa Finalizar.")
    return [doc.GetElement(r.ElementId) for r in refs]


def _cancelado(ex):
    """El usuario salio de la seleccion de Revit (Esc): no es un error que haya que mostrar."""
    return "operationcanceled" in type(ex).__name__.lower() or "user aborted" in str(ex).lower()


def parametros_comunes(infos):
    """Parametros de texto que tienen todos los muros que se van a cortar, en el orden del primero."""
    listas = [i.get("textos") or [] for i in infos if not i.get("omitir")]
    if not listas:
        return []
    resto = [set(l) for l in listas[1:]]
    return sorted(set(n for n in listas[0] if all(n in s for s in resto)), key=lambda n: n.lower())


class VentanaCorte(forms.WPFWindow):
    def __init__(self, xaml, infos):
        forms.WPFWindow.__init__(self, xaml)
        from apariencia import aplicar_tipografia
        aplicar_tipografia(self)
        self.infos = infos
        self.proceder = False
        self.resultado = None
        self._planes = None
        area = Win.SystemParameters.WorkArea
        self.Width = min(self.Width, area.Width)
        self.Height = min(self.Height, area.Height)
        validos = len([i for i in infos if not i.get("omitir")])
        self.TxtElementos.Text = u"{} muro{} elegido{}{}".format(
            len(infos), u"" if len(infos) == 1 else u"s", u"" if len(infos) == 1 else u"s",
            u"" if validos == len(infos) else u"  ·  {} no se puede{} cortar".format(
                len(infos) - validos, u"" if len(infos) - validos == 1 else u"n"))
        for nombre in parametros_comunes(infos):
            self.CmbParamTramo.Items.Add(nombre)
        self._armar_encabezado()
        self._restaurar(CFG.cargar())

        for rb in (self.RbUna, self.RbVarias, self.RbAlzadas):
            rb.Checked += lambda s, e: self.actualizar()
        for tb in (self.TxtAltura, self.TxtAlturas, self.TxtAlzada, self.TxtMinimo, self.TxtPrefijo):
            tb.TextChanged += lambda s, e: self.actualizar()
        for cmb in (self.CmbReferencia, self.CmbOriginal, self.CmbParamTramo):
            cmb.SelectionChanged += lambda s, e: self.actualizar()
        for chk in (self.ChkMarca, self.ChkHuecos, self.ChkParamTramo, self.ChkSeleccionar):
            chk.Click += lambda s, e: self.actualizar()
        self.CanvasPrevia.SizeChanged += lambda s, e: self._dibujar()
        self.CmbTema.SelectionChanged += self._tema_elegido
        self.BtnCancelar.Click += lambda s, e: self.Close()
        self.BtnCortar.Click += self.aceptar
        self.actualizar()

    # ---- configuracion ----
    def _restaurar(self, cfg):
        {"una": self.RbUna, "varias": self.RbVarias, "alzadas": self.RbAlzadas}[cfg["modo"]].IsChecked = True
        self.TxtAltura.Text = cfg["altura"]
        self.TxtAlturas.Text = cfg["alturas"]
        self.TxtAlzada.Text = cfg["alzada"]
        self.TxtMinimo.Text = cfg["minimo_cm"]
        self.TxtPrefijo.Text = cfg["prefijo"]
        self.CmbReferencia.SelectedIndex = 1 if cfg["referencia"] == LC.REF_NIVEL else 0
        self.CmbOriginal.SelectedIndex = 1 if cfg["original"] == LC.ORIGINAL_SUPERIOR else 0
        self.ChkMarca.IsChecked = cfg["copiar_marca"]
        self.ChkHuecos.IsChecked = cfg["huecos"]
        self.ChkSeleccionar.IsChecked = cfg["seleccionar"]
        hay = cfg["param_tramo"] in list(self.CmbParamTramo.Items)
        if hay:
            self.CmbParamTramo.SelectedItem = cfg["param_tramo"]
        self.ChkParamTramo.IsChecked = cfg["escribir_tramo"] and hay
        self.CmbTema.SelectedIndex = 1 if cfg["TemaInterfaz"] == "Oscuro" else 0
        self._aplicar_tema(cfg["TemaInterfaz"])

    def _modo(self):
        if self.RbVarias.IsChecked == True:return LC.MODO_VARIAS
        if self.RbAlzadas.IsChecked == True:return LC.MODO_ALZADAS
        return LC.MODO_UNA

    def opciones(self):
        """Las opciones de corte tal como estan en la ventana (las mismas claves que usan logica_corte y revit_corte)."""
        modo = self._modo()
        error = None
        if modo == LC.MODO_VARIAS:
            valores, error = LC.leer_lista(self.TxtAlturas.Text)
        else:
            texto = (self.TxtAltura if modo == LC.MODO_UNA else self.TxtAlzada).Text or u""
            v = LC.leer_numero(texto)
            valores = [v] if v is not None else []
            if v is None and texto.strip():
                error = texto.strip()
        param = None
        if self.ChkParamTramo.IsChecked == True:
            param = self.CmbParamTramo.SelectedItem or u""
        return {"modo": modo, "valores": valores or [], "error_valores": error,
                "referencia": LC.REF_NIVEL if self.CmbReferencia.SelectedIndex == 1 else LC.REF_BASE,
                "minimo_cm": LC.leer_numero(self.TxtMinimo.Text),
                "original": LC.ORIGINAL_SUPERIOR if self.CmbOriginal.SelectedIndex == 1 else LC.ORIGINAL_INFERIOR,
                "copiar_marca": self.ChkMarca.IsChecked == True, "huecos": self.ChkHuecos.IsChecked == True,
                "param_tramo": param, "prefijo": self.TxtPrefijo.Text or u"",
                "seleccionar": self.ChkSeleccionar.IsChecked == True}

    def config_actual(self):
        return {"modo": self._modo(), "altura": self.TxtAltura.Text, "alturas": self.TxtAlturas.Text,
                "alzada": self.TxtAlzada.Text, "minimo_cm": self.TxtMinimo.Text, "prefijo": self.TxtPrefijo.Text,
                "referencia": LC.REF_NIVEL if self.CmbReferencia.SelectedIndex == 1 else LC.REF_BASE,
                "original": LC.ORIGINAL_SUPERIOR if self.CmbOriginal.SelectedIndex == 1 else LC.ORIGINAL_INFERIOR,
                "copiar_marca": self.ChkMarca.IsChecked == True, "huecos": self.ChkHuecos.IsChecked == True,
                "escribir_tramo": self.ChkParamTramo.IsChecked == True,
                "param_tramo": self.CmbParamTramo.SelectedItem or u"",
                "seleccionar": self.ChkSeleccionar.IsChecked == True}

    # ---- estado de la ventana ----
    def actualizar(self):
        """Recalcula los tramos de cada muro con lo escrito y refresca la lista, la vista previa y el pie."""
        modo = self._modo()
        visible, oculto = Win.Visibility.Visible, Win.Visibility.Collapsed
        self.FilaAltura.Visibility = visible if modo == LC.MODO_UNA else oculto
        self.FilaAlturas.Visibility = visible if modo == LC.MODO_VARIAS else oculto
        self.FilaAlzada.Visibility = visible if modo == LC.MODO_ALZADAS else oculto
        self.FilaReferencia.Visibility = oculto if modo == LC.MODO_ALZADAS else visible
        con_param = self.ChkParamTramo.IsChecked == True
        self.CmbParamTramo.IsEnabled = con_param and self.CmbParamTramo.Items.Count > 0
        self.TxtPrefijo.IsEnabled = con_param
        self.ChkParamTramo.IsEnabled = self.CmbParamTramo.Items.Count > 0

        op_ = self.opciones()
        error = LC.validar_opciones(op_)
        if error:
            self._planes = None
            self.TxtResumen.Text = error
            self.BtnCortar.IsEnabled = False
        else:
            self._planes = LC.planificar(self.infos, op_)
            self.TxtResumen.Text = LC.resumen_planes(self._planes)
            self.BtnCortar.IsEnabled = any(not p["omitir"] for p in self._planes)
        self._llenar_lista()
        self._dibujar()

    def aceptar(self, sender, args):
        op_ = self.opciones()
        if LC.validar_opciones(op_):
            return
        self.resultado = op_
        self.proceder = True
        try:CFG.guardar(self.config_actual())
        except Exception:pass
        self.Close()

    # ---- lista de muros ----
    def _columnas(self, grid):
        for _, px, peso in COLUMNAS:
            cd = Controls.ColumnDefinition()
            cd.Width = Win.GridLength(px) if px else Win.GridLength(peso, Win.GridUnitType.Star)
            grid.ColumnDefinitions.Add(cd)

    def _texto(self, texto, color="Texto", negrita=False, tamano=12.0):
        tb = Controls.TextBlock()
        tb.Text = texto
        tb.FontSize = tamano
        tb.TextTrimming = Win.TextTrimming.CharacterEllipsis
        tb.VerticalAlignment = Win.VerticalAlignment.Center
        if negrita:tb.FontWeight = Win.FontWeights.SemiBold
        tb.SetResourceReference(Controls.TextBlock.ForegroundProperty, color)
        return tb

    def _armar_encabezado(self):
        g = Controls.Grid()
        self._columnas(g)
        for i, (titulo, _, _) in enumerate(COLUMNAS):
            tb = self._texto(titulo, "TextoSuave", True, 11.5)
            Controls.Grid.SetColumn(tb, i)
            g.Children.Add(tb)
        self.EncabezadoLista.Children.Add(g)

    def _llenar_lista(self):
        self.PanelMuros.Children.Clear()
        self.TxtTituloLista.Text = u"Muros ({})".format(len(self.infos))
        for j, info in enumerate(self.infos):
            plan = self._planes[j] if self._planes else None
            motivo = (plan["omitir"] if plan else None) or info.get("omitir")
            if motivo:
                estado, color, tramos = u"Se omite: " + motivo, "TextoSuave", u"—"
            elif plan:
                estado = u"Se corta en {} tramos".format(len(plan["tramos"]))
                if plan["avisos"]:estado += u" · " + u"; ".join(plan["avisos"])
                color, tramos = "Texto", LC.texto_tramos(plan["tramos"])
            else:
                estado, color, tramos = u"—", "TextoSuave", u"—"
            fila = Controls.Border()
            fila.BorderThickness = Win.Thickness(0, 0, 0, 1)
            fila.SetResourceReference(Controls.Border.BorderBrushProperty, "Borde")
            fila.Padding = Win.Thickness(0, 5, 0, 5)
            g = Controls.Grid()
            self._columnas(g)
            valores = (u"{}".format(info["id"]), info.get("tipo") or u"", info.get("nivel") or u"",
                       u"{:.2f}".format(info.get("altura_m") or 0.0), tramos, estado)
            for i, v in enumerate(valores):
                tb = self._texto(v, "TextoAcento" if i == 5 and not motivo and plan else color)
                tb.Margin = Win.Thickness(0, 0, 8, 0)
                tb.ToolTip = v
                Controls.Grid.SetColumn(tb, i)
                g.Children.Add(tb)
            fila.Child = g
            self.PanelMuros.Children.Add(fila)

    # ---- vista previa en elevacion ----
    def _figura(self, figura, relleno=None, trazo="Texto", grosor=1.0, opacidad=1.0):
        if relleno:figura.SetResourceReference(Shapes.Shape.FillProperty, relleno)
        figura.SetResourceReference(Shapes.Shape.StrokeProperty, trazo)
        figura.StrokeThickness = grosor
        figura.Opacity = opacidad
        self.CanvasPrevia.Children.Add(figura)
        return figura

    def _linea(self, x1, y1, x2, y2, trazo="Borde", grosor=1.0, discontinua=False, opacidad=1.0):
        ln = Shapes.Line()
        ln.X1, ln.Y1, ln.X2, ln.Y2 = x1, y1, x2, y2
        if discontinua:
            guiones = Media.DoubleCollection()
            guiones.Add(5.0)
            guiones.Add(3.0)
            ln.StrokeDashArray = guiones
        return self._figura(ln, None, trazo, grosor, opacidad)

    def _rotulo(self, texto, x, y, color="Texto", tamano=11.0, negrita=False, centrado=False, derecha=False):
        tb = self._texto(texto, color, negrita, tamano)
        tb.TextTrimming = getattr(Win.TextTrimming, "None")       # 'None' no se puede escribir como atributo en Python
        tb.Measure(Win.Size(1e4, 1e4))
        w, h = tb.DesiredSize.Width, tb.DesiredSize.Height
        Controls.Canvas.SetLeft(tb, x - w / 2.0 if centrado else (x - w if derecha else x))
        Controls.Canvas.SetTop(tb, y - h / 2.0)
        self.CanvasPrevia.Children.Add(tb)
        return tb

    def _dibujar(self):
        """Cada muro como una barra a escala con sus tramos (A1, A2... desde abajo) y las lineas de corte. El borde
        grueso marca el tramo que conserva el muro original."""
        c = self.CanvasPrevia
        c.Children.Clear()
        ancho, alto = c.ActualWidth, c.ActualHeight
        if ancho < 120 or alto < 120:
            return
        if self._planes:
            muestras = [(i, p) for i, p in zip(self.infos, self._planes) if not p["omitir"]]
        else:
            muestras = [(i, None) for i in self.infos if not i.get("omitir")]
        if not muestras:
            self._rotulo(u"Ningún muro se corta con estas opciones.", ancho / 2.0, alto / 2.0, "TextoSuave", 12.5,
                         centrado=True)
            return
        resto = len(muestras) - MAX_PREVIA
        muestras = muestras[:MAX_PREVIA]
        hmax = max(i.get("altura_m") or 0.0 for i, _ in muestras) or 1.0
        izq, der, arriba, abajo = 54.0, 16.0, 26.0, 44.0
        escala = (alto - arriba - abajo) / hmax
        y0 = alto - abajo
        # regla: una linea cada 0.50 m
        paso, z = 0.5, 0.0
        while z <= hmax + 1e-6:
            y = y0 - z * escala
            self._linea(izq - 6, y, ancho - der, y, "Borde", 1.0, opacidad=0.6 if z else 1.0)
            self._rotulo(u"{:.2f}".format(z), izq - 10, y, "TextoSuave", 10.5, derecha=True)
            z += paso
        hueco = (ancho - izq - der) / len(muestras)
        barra = max(18.0, min(78.0, hueco * 0.5))
        for j, (info, plan) in enumerate(muestras):
            x = izq + hueco * j + (hueco - barra) / 2.0
            tramos = plan["tramos"] if plan else [(0.0, info.get("altura_m") or 0.0)]
            for i, (a, b) in enumerate(tramos):
                original = plan is not None and plan["original"] == i
                # relleno translucido y contorno aparte: la opacidad del relleno no debe apagar el borde
                for relleno, trazo, grosor, opacidad in (("Acento", "Acento", 0.0, 0.30 + 0.25 * (i % 2)),
                                                         (None, "Acento" if original else "Texto",
                                                          2.5 if original else 1.0, 1.0)):
                    r = Shapes.Rectangle()
                    r.Width, r.Height = barra, max(1.0, (b - a) * escala)
                    Controls.Canvas.SetLeft(r, x)
                    Controls.Canvas.SetTop(r, y0 - b * escala)
                    self._figura(r, relleno, trazo, grosor, opacidad)
                if r.Height > 16 and plan:
                    self._rotulo(LC.nombre_tramo(u"A", i), x + barra / 2.0, y0 - (a + b) / 2.0 * escala, "Texto",
                                 11.0, True, centrado=True)
                if i > 0:
                    y = y0 - a * escala
                    self._linea(x - 8, y, x + barra + 8, y, "Acento", 1.6, discontinua=True)
                    if hueco > barra + 44:
                        self._rotulo(u"{:.2f}".format(a), x + barra + 10, y, "TextoAcento", 10.5)
            self._rotulo(u"Id {}".format(info["id"]), x + barra / 2.0, y0 + 14, "TextoSuave", 10.5, centrado=True)
            self._rotulo(u"H {:.2f}".format(info.get("altura_m") or 0.0), x + barra / 2.0, y0 + 30, "TextoSuave", 10.5,
                         centrado=True)
        nota = u"Borde grueso: tramo que conserva el muro original"
        if resto > 0:
            nota += u"  ·  {} muro{} más en la lista".format(resto, u"" if resto == 1 else u"s")
        self._rotulo(nota, izq, 12, "TextoSuave", 10.5)

    # ---- tema ----
    def _tema_elegido(self, sender, args):
        tema = "Oscuro" if self.CmbTema.SelectedIndex == 1 else "Claro"
        self._aplicar_tema(tema)
        CFG.guardar_tema(tema)

    def _aplicar_tema(self, tema):
        conv = Media.BrushConverter()
        i = 1 if tema == "Oscuro" else 0
        for nombre, par in COLORES_TEMA.items():
            pincel = conv.ConvertFromString(par[i])
            if nombre == "Borde":pincel.Opacity = 0.22
            elif nombre == "BordeControl":pincel.Opacity = 0.55
            self.Resources[nombre] = pincel


def ejecutar(uidoc):
    doc = uidoc.Document
    if doc.IsFamilyDocument:
        forms.alert(u"Abre un proyecto: en el editor de familias no hay muros que cortar.", title=TITULO)
        return
    try:
        muros = elegir_muros(uidoc)
    except Exception as ex:
        if not _cancelado(ex):
            forms.alert(u"No se pudieron seleccionar los muros:\n{}".format(ex), title=TITULO)
        return
    if not muros:
        return
    import revit_corte as RC
    try:
        infos = [RC.analizar_muro(doc, m) for m in muros]
        ventana = VentanaCorte(op.join(AQUI, "ui_cortar_muros.xaml"), infos)
        ventana.ShowDialog()
    except Exception as ex:
        forms.alert(u"Error en la ventana:\n{}\n\nTipo: {}".format(ex, type(ex).__name__), title=TITULO)
        return
    if not ventana.proceder:
        return
    try:
        rep = RC.cortar_muros(doc, infos, ventana.resultado)
    except Exception as ex:
        forms.alert(u"No se cortó ningún muro (se deshizo todo):\n{}\n\nTipo: {}".format(ex, type(ex).__name__),
                    title=TITULO)
        return
    if ventana.resultado.get("seleccionar") and rep["ids_resultado"]:
        try:uidoc.Selection.SetElementIds(List[DB.ElementId](rep["ids_resultado"]))
        except Exception:pass
    revisar = rep["fallidos"] or any(c.get("diferencias") or c.get("param_fallos") for c in rep["cortados"])
    forms.alert(LC.texto_reporte(rep), title=TITULO, warn_icon=bool(revisar))


if __name__ == "__main__":
    ejecutar(__revit__.ActiveUIDocument)
