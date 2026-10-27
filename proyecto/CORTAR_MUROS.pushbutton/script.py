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
import System.Windows.Input as Input
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
COLUMNAS = ((u"Id", 72, None), (u"Tipo", None, 1.2), (u"Nivel", 90, None), (u"Largo × alto", 96, None),
            (u"P/V", 40, None), (u"Tramos (m)", None, 1.5), (u"Estado", None, 1.8))


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


# Atajos de cada modo: (texto del boton, valor que escribe).
ATAJOS = {
    "una": ((u"1.20", u"1.20"), (u"1.30 · E.070", u"1.30"), (u"1.50 · obra", u"1.50"), (u"2.40", u"2.40")),
    "varias": ((u"1.20; 2.40", u"1.20; 2.40"), (u"1.30; 2.60", u"1.30; 2.60"), (u"1.50; 3.00", u"1.50; 3.00")),
    "alzadas": ((u"1.20", u"1.20"), (u"1.30 · E.070", u"1.30"), (u"1.50 · obra", u"1.50")),
}
CRUCES = (LC.CRUCE_HUECO, LC.CRUCE_AJUSTAR, LC.CRUCE_OMITIR)
EXPLICA_CRUCE = {
    LC.CRUCE_HUECO: u"La puerta o ventana queda entera en el tramo de su base y en el tramo de arriba se abre un hueco "
                    u"del mismo ancho, para que el muro no la tape. Los muros cortina embebidos no se mueven: se abre "
                    u"hueco en los tramos que atraviesan. Recomendado.",
    LC.CRUCE_AJUSTAR: u"En ese muro, el corte se mueve al borde más cercano de la puerta o ventana (su antepecho o su "
                      u"dintel), para no partirla. Los demás muros se cortan a la altura pedida. La vista previa "
                      u"muestra dónde queda cada corte.",
    LC.CRUCE_OMITIR: u"Los muros donde un corte atravesaría una puerta, ventana o muro cortina se dejan como están. "
                     u"La lista indica cuáles y por qué.",
}
INICIAL = {u"puerta": u"P", u"ventana": u"V", u"muro cortina": u"MC", u"muro embebido": u"ME", u"hueco": u"H",
           u"inserto": u"I"}


class VentanaCorte(forms.WPFWindow):
    def __init__(self, xaml, infos):
        forms.WPFWindow.__init__(self, xaml)
        from apariencia import aplicar_tipografia
        aplicar_tipografia(self)
        self.infos = infos
        self.proceder = False
        self.resultado = None
        self._planes = None
        self._modo_atajos = None
        validos = [j for j, i in enumerate(infos) if not i.get("omitir")]
        self._actual = validos[0] if validos else 0          # muro de la vista «Uno a uno»
        area = Win.SystemParameters.WorkArea
        self.Width = min(self.Width, area.Width)
        self.Height = min(self.Height, area.Height)
        n_omit = len(infos) - len(validos)
        self.TxtElementos.Text = u"{} muro{} elegido{}{}".format(
            len(infos), _s(len(infos)), _s(len(infos)),
            u"" if not n_omit else u"  ·  {} no se puede{} cortar".format(n_omit, u"" if n_omit == 1 else u"n"))
        for nombre in parametros_comunes(infos):
            self.CmbParamTramo.Items.Add(nombre)
        self._armar_encabezado()
        self._restaurar(CFG.cargar())

        for rb in (self.RbUna, self.RbVarias, self.RbAlzadas):
            rb.Checked += lambda s, e: self.actualizar()
        for rb in (self.RbVistaTodos, self.RbVistaUno):
            rb.Checked += lambda s, e: self._refrescar_vista()
        for tb in (self.TxtAltura, self.TxtAlturas, self.TxtAlzada, self.TxtMinimo, self.TxtPrefijo):
            tb.TextChanged += lambda s, e: self.actualizar()
        for cmb in (self.CmbReferencia, self.CmbOriginal, self.CmbParamTramo, self.CmbCruce):
            cmb.SelectionChanged += lambda s, e: self.actualizar()
        for chk in (self.ChkMarca, self.ChkParamTramo, self.ChkSeleccionar):
            chk.Click += lambda s, e: self.actualizar()
        self.BtnAnterior.Click += lambda s, e: self._mover(-1)
        self.BtnSiguiente.Click += lambda s, e: self._mover(1)
        self.CanvasPrevia.SizeChanged += lambda s, e: self._dibujar()
        self.CmbTema.SelectionChanged += self._tema_elegido
        self.BtnCancelar.Click += lambda s, e: self.Close()
        self.BtnCortar.Click += self.aceptar
        self.actualizar()

    # ---- configuracion ----
    def _restaurar(self, cfg):
        {"una": self.RbUna, "varias": self.RbVarias, "alzadas": self.RbAlzadas}[cfg["modo"]].IsChecked = True
        (self.RbVistaUno if cfg["vista"] == "uno" else self.RbVistaTodos).IsChecked = True
        self.TxtAltura.Text = cfg["altura"]
        self.TxtAlturas.Text = cfg["alturas"]
        self.TxtAlzada.Text = cfg["alzada"]
        self.TxtMinimo.Text = cfg["minimo_cm"]
        self.TxtPrefijo.Text = cfg["prefijo"]
        self.CmbReferencia.SelectedIndex = 1 if cfg["referencia"] == LC.REF_NIVEL else 0
        self.CmbOriginal.SelectedIndex = 1 if cfg["original"] == LC.ORIGINAL_SUPERIOR else 0
        self.CmbCruce.SelectedIndex = CRUCES.index(cfg["cruce"])
        self.ChkMarca.IsChecked = cfg["copiar_marca"]
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

    def _cruce(self):
        i = self.CmbCruce.SelectedIndex
        return CRUCES[i] if 0 <= i < len(CRUCES) else LC.CRUCE_HUECO

    def _uno(self):
        return self.RbVistaUno.IsChecked == True

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
                "copiar_marca": self.ChkMarca.IsChecked == True, "cruce": self._cruce(),
                "param_tramo": param, "prefijo": self.TxtPrefijo.Text or u"",
                "seleccionar": self.ChkSeleccionar.IsChecked == True}

    def config_actual(self):
        return {"modo": self._modo(), "altura": self.TxtAltura.Text, "alturas": self.TxtAlturas.Text,
                "alzada": self.TxtAlzada.Text, "minimo_cm": self.TxtMinimo.Text, "prefijo": self.TxtPrefijo.Text,
                "referencia": LC.REF_NIVEL if self.CmbReferencia.SelectedIndex == 1 else LC.REF_BASE,
                "original": LC.ORIGINAL_SUPERIOR if self.CmbOriginal.SelectedIndex == 1 else LC.ORIGINAL_INFERIOR,
                "copiar_marca": self.ChkMarca.IsChecked == True, "cruce": self._cruce(),
                "vista": "uno" if self._uno() else "todos",
                "escribir_tramo": self.ChkParamTramo.IsChecked == True,
                "param_tramo": self.CmbParamTramo.SelectedItem or u"",
                "seleccionar": self.ChkSeleccionar.IsChecked == True}

    # ---- estado de la ventana ----
    def actualizar(self):
        """Recalcula los tramos de cada muro con lo escrito y refresca indicadores, lista, vista previa y pie."""
        modo = self._modo()
        visible, oculto = Win.Visibility.Visible, Win.Visibility.Collapsed
        self.FilaAltura.Visibility = visible if modo == LC.MODO_UNA else oculto
        self.FilaAlturas.Visibility = visible if modo == LC.MODO_VARIAS else oculto
        self.FilaAlzada.Visibility = visible if modo == LC.MODO_ALZADAS else oculto
        self.FilaReferencia.Visibility = oculto if modo == LC.MODO_ALZADAS else visible
        if modo != self._modo_atajos:
            self._armar_atajos(modo)
        self.TxtExplicaCruce.Text = EXPLICA_CRUCE[self._cruce()]
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
            est = {"muros": len(self.infos), "cortan": u"—", "tramos": u"—", "cruces": u"—"}
        else:
            self._planes = LC.planificar(self.infos, op_)
            self.TxtResumen.Text = LC.resumen_planes(self._planes)
            self.BtnCortar.IsEnabled = any(not p["omitir"] for p in self._planes)
            est = LC.estadisticas(self._planes)
        self.TxtStatMuros.Text = u"{}".format(est["muros"])
        self.TxtStatCortan.Text = u"{}".format(est["cortan"])
        self.TxtStatTramos.Text = u"{}".format(est["tramos"])
        self.TxtStatCruces.Text = u"{}".format(est["cruces"])
        self._refrescar_vista()

    def _refrescar_vista(self):
        self._llenar_lista()
        self._dibujar()

    def _armar_atajos(self, modo):
        """Botones con valores frecuentes para el modo elegido: un clic escribe el valor en su campo."""
        self._modo_atajos = modo
        self.PanelAtajos.Children.Clear()
        campo = {LC.MODO_UNA: self.TxtAltura, LC.MODO_VARIAS: self.TxtAlturas, LC.MODO_ALZADAS: self.TxtAlzada}[modo]
        for texto, valor in ATAJOS[modo]:
            b = Controls.Button()
            b.Content = texto
            b.Style = self.FindResource("Atajo")
            b.ToolTip = u"Escribe {} m".format(valor)
            b.Click += (lambda v: (lambda s, e: setattr(campo, "Text", v)))(valor)
            self.PanelAtajos.Children.Add(b)

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

    def _plan(self, j):
        return self._planes[j] if self._planes else None

    def _llenar_lista(self):
        self.PanelMuros.Children.Clear()
        self.TxtTituloLista.Text = u"Muros ({})".format(len(self.infos))
        resaltado = Media.SolidColorBrush(Media.Color.FromArgb(38, 0, 128, 128))
        for j, info in enumerate(self.infos):
            plan = self._plan(j)
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
            fila.Padding = Win.Thickness(6, 6, 0, 6)
            fila.CornerRadius = Win.CornerRadius(4)
            fila.Cursor = Input.Cursors.Hand
            fila.Background = resaltado if (self._uno() and j == self._actual) else Media.Brushes.Transparent
            fila.MouseLeftButtonUp += (lambda k: (lambda s, e: self._ver_muro(k)))(j)
            g = Controls.Grid()
            self._columnas(g)
            n_ins = len([i for i in info.get("insertos") or [] if i.get("tipo") != u"hueco"])
            valores = (u"{}".format(info["id"]), info.get("tipo") or u"", info.get("nivel") or u"",
                       u"{:.2f} × {:.2f}".format(info.get("largo_m") or 0.0, info.get("altura_m") or 0.0),
                       u"{}".format(n_ins) if n_ins else u"—", tramos, estado)
            for i, v in enumerate(valores):
                tb = self._texto(v, "TextoAcento" if i == 6 and not motivo and plan else color)
                tb.Margin = Win.Thickness(0, 0, 8, 0)
                tb.ToolTip = v
                Controls.Grid.SetColumn(tb, i)
                g.Children.Add(tb)
            fila.Child = g
            self.PanelMuros.Children.Add(fila)

    def _ver_muro(self, j):
        """Clic en una fila: ese muro, en grande."""
        self._actual = j
        if self._uno():
            self._refrescar_vista()
        else:
            self.RbVistaUno.IsChecked = True

    def _mover(self, paso):
        if not self.infos:
            return
        self._actual = (self._actual + paso) % len(self.infos)
        if not self._uno():
            self.RbVistaUno.IsChecked = True
        else:
            self._refrescar_vista()

    # ---- vista previa en elevacion ----
    def _figura(self, figura, relleno=None, trazo="Texto", grosor=1.0, opacidad=1.0):
        if relleno:figura.SetResourceReference(Shapes.Shape.FillProperty, relleno)
        figura.SetResourceReference(Shapes.Shape.StrokeProperty, trazo)
        figura.StrokeThickness = grosor
        figura.Opacity = opacidad
        self.CanvasPrevia.Children.Add(figura)
        return figura

    def _guiones(self, figura):
        guiones = Media.DoubleCollection()
        guiones.Add(5.0)
        guiones.Add(3.0)
        figura.StrokeDashArray = guiones

    def _linea(self, x1, y1, x2, y2, trazo="Borde", grosor=1.0, discontinua=False, opacidad=1.0):
        ln = Shapes.Line()
        ln.X1, ln.Y1, ln.X2, ln.Y2 = x1, y1, x2, y2
        if discontinua:self._guiones(ln)
        return self._figura(ln, None, trazo, grosor, opacidad)

    def _rect(self, x, y, w, h, relleno, trazo, grosor=1.0, opacidad=1.0, discontinua=False):
        r = Shapes.Rectangle()
        r.Width, r.Height = max(w, 1.0), max(h, 1.0)
        Controls.Canvas.SetLeft(r, x)
        Controls.Canvas.SetTop(r, y)
        if discontinua:self._guiones(r)
        return self._figura(r, relleno, trazo, grosor, opacidad)

    def _rotulo(self, texto, x, y, color="Texto", tamano=11.0, negrita=False, centrado=False, derecha=False):
        tb = self._texto(texto, color, negrita, tamano)
        tb.TextTrimming = getattr(Win.TextTrimming, "None")       # 'None' no se puede escribir como atributo en Python
        tb.Measure(Win.Size(1e4, 1e4))
        w, h = tb.DesiredSize.Width, tb.DesiredSize.Height
        Controls.Canvas.SetLeft(tb, x - w / 2.0 if centrado else (x - w if derecha else x))
        Controls.Canvas.SetTop(tb, y - h / 2.0)
        self.CanvasPrevia.Children.Add(tb)
        return tb

    def _regla(self, izq, der, y0, escala, hmax, ancho):
        """Lineas cada 0.50 m con su cota, de fondo."""
        z = 0.0
        while z <= hmax + 1e-6:
            y = y0 - z * escala
            self._linea(izq - 6, y, ancho - der, y, "Borde", 1.0, opacidad=0.55 if z else 1.0)
            self._rotulo(u"{:.2f}".format(z), izq - 10, y, "TextoSuave", 10.0, derecha=True)
            z += 0.5

    def _muro(self, info, plan, x0, y0, escala, cotas):
        """Un muro en elevacion: sus tramos, sus puertas y ventanas a escala y las lineas de corte. Con 'cotas' (vista
        Uno a uno) tambien las alturas de cada tramo y de cada inserto."""
        largo = max(info.get("largo_m") or 0.0, 0.3)
        altura = info.get("altura_m") or 0.0
        w = largo * escala
        corta = plan is not None and not plan["omitir"]
        tramos = plan["tramos"] if corta else [(0.0, altura)]
        for i, (a, b) in enumerate(tramos):
            y, h = y0 - b * escala, (b - a) * escala
            original = corta and plan["original"] == i
            self._rect(x0, y, w, h, "Acento", "Acento", 0.0, (0.28 + 0.22 * (i % 2)) if corta else 0.12)
            self._rect(x0, y, w, h, None, "Acento" if original else "Texto", 2.5 if original else 1.0)
            if corta and h > 16:
                etiqueta = LC.nombre_tramo(u"A", i)
                if cotas:
                    etiqueta += u" · {:.2f} m{}".format(b - a, u" · original" if original else u"")
                    self._rotulo(etiqueta, x0 + w + 12, y + h / 2.0, "Texto", 11.5, True)
                elif w > 26:
                    self._rotulo(etiqueta, x0 + 6, y + 10, "Texto", 10.5, True)
        for ins in info.get("insertos") or []:
            cruzado = corta and ins.get("tipo") in LC.TIPOS_BLOQUEO and \
                any(LC.cruza(a, ins["zi"], ins["zs"]) for a, _ in tramos[1:])
            x, y = x0 + ins["s0"] * escala, y0 - ins["zs"] * escala
            wi, hi = (ins["s1"] - ins["s0"]) * escala, (ins["zs"] - ins["zi"]) * escala
            self._rect(x, y, wi, hi, "FondoLienzo", "Acento" if cruzado else "Texto", 2.2 if cruzado else 1.0,
                       discontinua=ins.get("tipo") == u"hueco")
            if wi > 14 and hi > 14:
                self._rotulo(INICIAL.get(ins.get("tipo"), u"I"), x + wi / 2.0, y + hi / 2.0,
                             "TextoAcento" if cruzado else "TextoSuave", 10.5, True, centrado=True)
            if cotas and wi > 10:
                self._rotulo(u"{:.2f}–{:.2f}".format(ins["zi"], ins["zs"]), x + wi / 2.0, y - 9, "TextoSuave", 10.0,
                             centrado=True)
        for a, _ in tramos[1:]:
            y = y0 - a * escala
            self._linea(x0 - 10, y, x0 + w + 10, y, "Acento", 1.8, discontinua=True)
            if cotas:
                self._rotulo(u"corte {:.2f}".format(a), x0 - 14, y, "TextoAcento", 11.0, True, derecha=True)
        self._linea(x0 - 6, y0, x0 + w + 6, y0, "Texto", 2.0)
        if not corta:
            motivo = (plan["omitir"] if plan else None) or info.get("omitir") or u""
            self._rotulo(u"Se omite" + (u": " + motivo if cotas and motivo else u""), x0 + w / 2.0,
                         y0 - altura * escala / 2.0, "TextoSuave", 11.0, True, centrado=True)
        return w

    def _dibujar(self):
        c = self.CanvasPrevia
        c.Children.Clear()
        ancho, alto = c.ActualWidth, c.ActualHeight
        uno = self._uno()
        self.BtnAnterior.IsEnabled = self.BtnSiguiente.IsEnabled = len(self.infos) > 1
        self.TxtMuroActual.Text = u"Muro {} de {}".format(self._actual + 1, len(self.infos)) if uno else \
            u"{} muros".format(len(self.infos))
        if ancho < 160 or alto < 140 or not self.infos:
            return
        if uno:
            self._dibujar_uno(ancho, alto)
        else:
            self._dibujar_todos(ancho, alto)

    def _dibujar_todos(self, ancho, alto):
        """Los muros que se cortan, uno al lado del otro y a la misma escala."""
        if self._planes:
            muestras = [(i, p) for i, p in zip(self.infos, self._planes) if not p["omitir"]]
        else:
            muestras = [(i, None) for i in self.infos if not i.get("omitir")]
        if not muestras:
            self._rotulo(u"Ningún muro se corta con estas opciones. Revisa la lista: dice por qué.", ancho / 2.0,
                         alto / 2.0, "TextoSuave", 12.5, centrado=True)
            return
        resto = len(muestras) - MAX_PREVIA
        muestras = muestras[:MAX_PREVIA]
        izq, der, arriba, abajo, hueco = 50.0, 16.0, 30.0, 40.0, 26.0
        hmax = max(i.get("altura_m") or 0.0 for i, _ in muestras) or 1.0
        largos = [max(i.get("largo_m") or 0.0, 0.3) for i, _ in muestras]
        disponible = ancho - izq - der - hueco * (len(muestras) - 1)
        escala = min((alto - arriba - abajo) / hmax, disponible / sum(largos))
        y0 = alto - abajo
        self._regla(izq, der, y0, escala, hmax, ancho)
        x = izq + (disponible - sum(largos) * escala) / 2.0
        for (info, plan), largo in zip(muestras, largos):
            w = self._muro(info, plan, x, y0, escala, False)
            self._rotulo(u"Id {}".format(info["id"]), x + w / 2.0, y0 + 14, "TextoSuave", 10.5, centrado=True)
            x += w + hueco
        nota = u"A la misma escala. Clic en la lista o «Uno a uno» para ver las cotas de un muro."
        if resto > 0:
            nota += u"  ·  {} muro{} más en la lista".format(resto, _s(resto))
        self._rotulo(nota, izq, 12, "TextoSuave", 10.5)

    def _dibujar_uno(self, ancho, alto):
        """Un muro grande, con la altura de cada tramo, cada corte y cada puerta o ventana."""
        j = min(self._actual, len(self.infos) - 1)
        info, plan = self.infos[j], self._plan(j)
        altura = info.get("altura_m") or 0.0
        largo = max(info.get("largo_m") or 0.0, 0.3)
        izq, der, arriba, abajo = 100.0, 190.0, 44.0, 40.0
        escala = min((alto - arriba - abajo) / (altura or 1.0), (ancho - izq - der) / largo)
        y0 = alto - abajo
        x0 = izq + (ancho - izq - der - largo * escala) / 2.0
        self._regla(izq, 10.0, y0, escala, altura, ancho)
        self._muro(info, plan, x0, y0, escala, True)
        self._rotulo(u"Id {}  ·  {}  ·  {}".format(info["id"], info.get("tipo") or u"", info.get("nivel") or u""),
                     12, 14, "Texto", 12.0, True)
        self._rotulo(u"Largo {:.2f} m  ·  Altura {:.2f} m".format(largo, altura), 12, 32, "TextoSuave", 11.0)


def _s(n):
    return u"" if n == 1 else u"s"


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
