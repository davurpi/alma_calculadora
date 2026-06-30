import math
from odoo import api, fields, models

# ---------------------------------------------------------------------------
# Tarifa de confección 2003 (pestaña CONFECCION del Excel)
# La tarifa sigue el patrón: rate = BASE[n] * 1.035
# donde n = ceil(cut_width_cm/50) + ceil(cut_length_cm/50) - 2  (mínimo 0)
# BASE = [0.36, 0.45, 0.54, 0.63, 0.72, 0.81, 0.90, 1.00, 1.08, 1.17, ...]
# ---------------------------------------------------------------------------
_CONF_BASE = [0.36, 0.45, 0.54, 0.63, 0.72, 0.81, 0.90, 1.00, 1.08, 1.17,
              1.26, 1.35, 1.44, 1.53, 1.62, 1.71, 1.80, 1.89, 1.98, 2.07]
_CONF_MULTIPLIER = 1.035
_CONF_SERVILLETA_BASE = round(0.36 * _CONF_MULTIPLIER, 4)  # 0.3726 €/pieza
_FESTON_RATE = 0.75  # €/metro lineal


def _confection_rate(cut_width_cm, cut_length_cm):
    """Devuelve la tarifa de confección por pieza (sin ajustes de dobladillo/empalme)."""
    w_range = math.ceil(cut_width_cm / 50)   # 1..8 para anchos hasta 400cm
    l_range = math.ceil(cut_length_cm / 50)  # 1..14 para largos hasta 700cm
    idx = max(0, w_range + l_range - 2)
    base = _CONF_BASE[idx] if idx < len(_CONF_BASE) else _CONF_BASE[-1] + (idx - len(_CONF_BASE) + 1) * 0.09
    return round(base * _CONF_MULTIPLIER, 4)


class AlmaBudgetLine(models.Model):
    """Línea de presupuesto de mantelería.

    Replica la lógica de cada fila de la pestaña PRESUPUESTO del Excel,
    incluyendo todos los cálculos encadenados de medidas, costes de tejido,
    confección, empalme y festón.

    Columnas del Excel → campos del modelo:
      A  cantidad              → quantity
      B  margen (decimal)      → margin_pct
      C  nombre artículo       → fabric_color_id (seleccionado por nombre)
      D  color (código)        → color_code (calculado de fabric_color_id)
      E  pos. en ARTICULOS     → (interno, no almacenado)
      F  REF 2                 → fabric_ref2
      I  coste €/m             → cost_per_meter
      J  ancho pieza (m)       → fabric_width_m
      K  precio venta €/m      → sale_price_per_meter (= I*(1+B))
      L  tipo artículo (1-10)  → article_type_id
      M  ancho mesa            → width_mesa
      N  largo mesa            → length_mesa
      O  diámetro redonda      → diameter_round
      P  alto mesa             → table_height
      Q  añadir largo          → extra_length
      R  caída mantel          → drop
      S  descripción mesa      → mesa_size_display (compute)
      T  medida terminada ancho→ finished_width (compute)
      U  medida terminada largo→ finished_length (compute)
      V  dobladillo (1=sencillo, n=doble ncm) → hem_type
      W  ancho con dobl.       → width_with_hem (compute)
      X  largo con dobl.       → length_with_hem (compute)
      Y  aplicar encogimiento  → apply_shrinkage
      Z  ancho de corte        → cut_width (compute)
      AA largo de corte        → cut_length (compute)
      AB forma (1=redonda/oval, 2=rectangular) → shape_type
      AC empalme (1=sí, 2=no)  → has_empalme
      AD ref empalme           → empalme_ref (compute)
      AE piezas/ancho empalme  → empalme_id (Many2one)
      AF piezas/ancho manual   → empalme_override
      AG coste confección      → confection_cost (compute)
      AH aprovechar retales    → use_remnants
      AI coste tejido          → fabric_cost (compute)
      AJ festón (1=sí,2=no)   → has_feston
      AK coste festón          → feston_cost (compute)
      AM prototipo             → is_prototype
      AY coste unitario        → unit_cost (compute)
      AZ cantidad (= A)        → quantity (= A)
      BA total línea           → line_total (compute)
    """
    _name = 'alma.budget.line'
    _description = 'Línea de Presupuesto Mantelería'
    _order = 'sequence, id'

    budget_id = fields.Many2one('alma.budget', string='Presupuesto', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)

    # ------------------------------------------------------------------
    # ENTRADAS PRINCIPALES
    # ------------------------------------------------------------------
    quantity = fields.Float('Cantidad', default=0.0, digits=(10, 0))
    margin_pct = fields.Float(
        'Margen (%)', default=0.10,
        help='Margen sobre coste. Ej: 0.10 = 10%. Precio venta = coste × (1 + margen).')

    fabric_color_id = fields.Many2one(
        'alma.fabric.color', string='Artículo / Color',
        help='Selecciona tejido+color. El sistema cargará automáticamente coste, ancho y encogimientos.')
    article_type_id = fields.Many2one(
        'alma.article.type', string='Tipo de Artículo',
        help='Ej: 1=Mantel, 2=Cubre, 3=Servilleta. Afecta al cálculo de confección.')

    # ------------------------------------------------------------------
    # DATOS DEL TEJIDO (calculados al seleccionar fabric_color_id)
    # ------------------------------------------------------------------
    color_code = fields.Integer('Cód. Color', compute='_compute_from_fabric', store=True)
    color_name = fields.Char('Color', compute='_compute_from_fabric', store=True)
    fabric_name = fields.Char('Tejido', compute='_compute_from_fabric', store=True)
    fabric_ref2 = fields.Char('REF 2', compute='_compute_from_fabric', store=True)
    cost_per_meter = fields.Float('Coste €/m', compute='_compute_from_fabric', store=True, digits=(10, 4))
    fabric_width_m = fields.Float('Ancho Pieza (m)', compute='_compute_from_fabric', store=True, digits=(6, 3))
    shrinkage_length = fields.Float(compute='_compute_from_fabric', store=True, digits=(6, 4))
    shrinkage_width = fields.Float(compute='_compute_from_fabric', store=True, digits=(6, 4))

    sale_price_per_meter = fields.Float(
        'Precio Venta €/m', compute='_compute_sale_price', store=True, digits=(10, 4),
        help='= coste × (1 + margen %)')

    # ------------------------------------------------------------------
    # MEDIDAS DE LA MESA / ARTÍCULO (entradas manuales, equivalen a cols M-R)
    # ------------------------------------------------------------------
    width_mesa = fields.Float('Ancho Mesa (cm)', digits=(10, 1))
    length_mesa = fields.Float('Largo Mesa (cm)', digits=(10, 1))
    diameter_round = fields.Float('Diámetro Redonda (cm)', digits=(10, 1),
                                  help='Si la mesa es redonda, introducir diámetro. Deja en 0 para rectangular.')
    table_height = fields.Float('Alto Mesa (cm)', digits=(10, 1))
    extra_length = fields.Float('Añadir Largo (cm)', digits=(10, 1))
    drop = fields.Float('Caída Mantel (cm)', digits=(10, 1),
                        help='Caída a cada lado del mantel.')

    # ------------------------------------------------------------------
    # OPCIONES DE CONFECCIÓN
    # ------------------------------------------------------------------
    hem_type = fields.Float(
        'Dobladillo', default=1.0,
        help='1 = Dobladillo sencillo (+5cm). N > 1 = Dobladillo doble de N cm (+N×4cm).')
    apply_shrinkage = fields.Boolean('Aplicar Encogimiento', default=False)
    shape_type = fields.Selection([
        ('2', 'Rectangular'),
        ('1', 'Redondo / Ovalado'),
    ], string='Forma', default='2')
    has_empalme = fields.Boolean('Empalme', default=False,
                                 help='Activa cuando el ancho del mantel supera el ancho del tejido.')
    empalme_override = fields.Integer(
        'Piezas/Ancho Manual', default=0,
        help='Deja en 0 para calcular automáticamente según tabla de empalmes.')
    use_remnants = fields.Boolean('Aprovechar Retales', default=False,
                                  help='Descuenta el valor de servilletas cortables del retal sobrante.')
    has_feston = fields.Boolean('Festón', default=False,
                                help='Añade coste de festón perimetral a 0,75 €/m.')
    is_prototype = fields.Boolean('Prototipo', default=False)

    # ------------------------------------------------------------------
    # CAMPOS CALCULADOS — MEDIDAS
    # ------------------------------------------------------------------
    mesa_size_display = fields.Char('Medida Mesa', compute='_compute_dimensions', store=True)
    finished_width = fields.Float('Medida Terminada Ancho (cm)', compute='_compute_dimensions', store=True, digits=(10, 1))
    finished_length = fields.Float('Medida Terminada Largo (cm)', compute='_compute_dimensions', store=True, digits=(10, 1))
    width_with_hem = fields.Float('Ancho con Dobl. (cm)', compute='_compute_dimensions', store=True, digits=(10, 1))
    length_with_hem = fields.Float('Largo con Dobl. (cm)', compute='_compute_dimensions', store=True, digits=(10, 1))
    cut_width = fields.Float('Ancho Corte (cm)', compute='_compute_dimensions', store=True, digits=(10, 1))
    cut_length = fields.Float('Largo Corte (cm)', compute='_compute_dimensions', store=True, digits=(10, 1))

    # ------------------------------------------------------------------
    # CAMPOS CALCULADOS — EMPALME
    # ------------------------------------------------------------------
    empalme_ref = fields.Char('REF Empalme', compute='_compute_empalme', store=True)
    empalme_id = fields.Many2one('alma.empalme', string='Empalme encontrado', compute='_compute_empalme', store=True)
    empalme_length_cm = fields.Integer('Largo Empalme (cm)', compute='_compute_empalme', store=True)
    pieces_per_width = fields.Integer('Piezas por Ancho', compute='_compute_empalme', store=True)

    # ------------------------------------------------------------------
    # CAMPOS CALCULADOS — COSTES
    # ------------------------------------------------------------------
    confection_cost = fields.Float('Coste Confección (€)', compute='_compute_costs', store=True, digits=(10, 4))
    fabric_cost = fields.Float('Coste Tejido (€)', compute='_compute_costs', store=True, digits=(10, 4))
    feston_cost = fields.Float('Coste Festón (€)', compute='_compute_costs', store=True, digits=(10, 4))
    unit_cost = fields.Float('Coste Unitario (€)', compute='_compute_costs', store=True, digits=(10, 4))
    line_total = fields.Float('Total Línea (€)', compute='_compute_costs', store=True, digits=(10, 2))

    # ------------------------------------------------------------------
    # CAMPOS DE SALIDA para Orden de Producción y Presupuesto Cliente
    # ------------------------------------------------------------------
    display_article_type = fields.Char('Tipo', compute='_compute_display', store=True)
    display_dimensions = fields.Char('Medida Uso', compute='_compute_display', store=True)
    display_cut = fields.Char('Corte', compute='_compute_display', store=True)
    display_hem = fields.Char('Dobladillo', compute='_compute_display', store=True)
    display_shrinkage = fields.Char('Encogimiento', compute='_compute_display', store=True)
    display_color = fields.Char('Color (detalle)', compute='_compute_display', store=True)

    # ====================================================================
    # MÉTODOS COMPUTE
    # ====================================================================

    @api.depends('fabric_color_id')
    def _compute_from_fabric(self):
        for line in self:
            fc = line.fabric_color_id
            if fc:
                line.color_code = fc.color_code
                line.color_name = fc.color_name
                line.fabric_name = fc.fabric_id.name
                line.fabric_ref2 = fc.fabric_id.ref_combined
                line.cost_per_meter = fc.cost
                line.fabric_width_m = fc.width
                line.shrinkage_length = fc.fabric_id.shrinkage_length
                line.shrinkage_width = fc.fabric_id.shrinkage_width
            else:
                line.color_code = 0
                line.color_name = ''
                line.fabric_name = ''
                line.fabric_ref2 = ''
                line.cost_per_meter = 0.0
                line.fabric_width_m = 0.0
                line.shrinkage_length = 0.0
                line.shrinkage_width = 0.0

    @api.depends('cost_per_meter', 'margin_pct')
    def _compute_sale_price(self):
        for line in self:
            line.sale_price_per_meter = line.cost_per_meter * (1 + line.margin_pct)

    @api.depends(
        'width_mesa', 'length_mesa', 'diameter_round',
        'table_height', 'extra_length', 'drop',
        'hem_type', 'apply_shrinkage', 'shrinkage_length', 'shrinkage_width',
    )
    def _compute_dimensions(self):
        """Replica las columnas S, T, U, W, X, Z, AA del Excel PRESUPUESTO."""
        for line in self:
            M = line.width_mesa
            N = line.length_mesa
            O = line.diameter_round
            P = line.table_height
            Q = line.extra_length
            R = line.drop
            V = line.hem_type

            # --- Descripción de la mesa (col S) ---
            if P > 0:
                if O > 0:
                    mesa_desc = f"(/) {O} × {P}"
                    if Q > 0:
                        mesa_desc += f" + {Q}"
                else:
                    mesa_desc = f"{M} × {N} × {P}"
                    if Q > 0:
                        mesa_desc += f" + {Q}"
            else:
                mesa_desc = ''
            line.mesa_size_display = mesa_desc

            # --- Medida terminada (cols T, U) ---
            # T = (diámetro o ancho) + 2*caída + 2*alto mesa + 2*extra
            base_dim = O if O > 0 else M
            T = base_dim + R * 2 + P * 2 + Q * 2
            # U = (diámetro o largo) + 2*caída + 2*alto mesa + 2*extra
            base_dim_u = O if O > 0 else N
            U = base_dim_u + R * 2 + P * 2 + Q * 2
            line.finished_width = T
            line.finished_length = U

            # --- Con dobladillo (cols W, X) ---
            # V=1: dobladillo sencillo → +5cm / V=N: dobladillo doble → +N×4cm
            if V == 1:
                W = T + 5
                X = U + 5
            else:
                W = T + V * 4
                X = U + V * 4
            line.width_with_hem = W
            line.length_with_hem = X

            # --- Con encogimiento (cols Z, AA) ---
            if line.apply_shrinkage and line.shrinkage_width:
                Z = math.ceil(W * (1 + line.shrinkage_width))
            else:
                Z = W
            if line.apply_shrinkage and line.shrinkage_length:
                AA = math.ceil(X * (1 + line.shrinkage_length))
            else:
                AA = X
            line.cut_width = Z
            line.cut_length = AA

    @api.depends('fabric_width_m', 'cut_width', 'has_empalme')
    def _compute_empalme(self):
        """Replica las columnas AD y AE del Excel: busca la tabla de empalmes."""
        for line in self:
            if not line.has_empalme or not line.fabric_width_m or not line.cut_width:
                line.empalme_ref = ''
                line.empalme_id = False
                line.empalme_length_cm = 0
                line.pieces_per_width = 0
                continue

            fabric_w_cm = round(line.fabric_width_m * 100)
            cut_w = round(line.cut_width)
            ref = f"{fabric_w_cm}{cut_w}"
            line.empalme_ref = ref

            empalme = self.env['alma.empalme'].search(
                [('ref_empalme', '=', ref)], limit=1)
            line.empalme_id = empalme
            line.empalme_length_cm = empalme.empalme_length_cm if empalme else 0
            if line.empalme_override > 0:
                line.pieces_per_width = line.empalme_override
            else:
                line.pieces_per_width = empalme.pieces_per_width if empalme else 0

    @api.depends(
        'quantity', 'article_type_id', 'hem_type', 'has_empalme',
        'cut_width', 'cut_length',
        'sale_price_per_meter', 'cost_per_meter', 'fabric_width_m',
        'empalme_length_cm', 'pieces_per_width', 'empalme_override',
        'use_remnants', 'has_feston',
    )
    def _compute_costs(self):
        """Replica las columnas AG (confección), AI (tejido), AK (festón), AY, BA."""
        for line in self:
            Z = line.cut_width or 0
            AA = line.cut_length or 0
            V = line.hem_type
            K = line.sale_price_per_meter
            I = line.cost_per_meter
            J = line.fabric_width_m  # metros
            article_code = line.article_type_id.code if line.article_type_id else 0

            # ---- Coste confección (col AG) ----
            if article_code == 3:  # Servilleta
                conf_base = _CONF_SERVILLETA_BASE
            else:
                conf_base = _confection_rate(Z, AA) if Z > 0 and AA > 0 else 0.0

            # Dobladillo doble duplica la confección
            conf = conf_base * (1 if V == 1 else 2)
            # Empalme multiplica por 3
            if line.has_empalme:
                conf *= 3
            confection_cost = conf

            # ---- Coste tejido (col AI) ----
            if Z > 0 and AA > 0 and J > 0 and K > 0:
                pieces_w = int(J / (Z / 100))  # piezas que entran al ancho

                if line.has_empalme:
                    emp_len = line.empalme_length_cm
                    ppw = line.pieces_per_width or 1
                    # coste pieza principal + coste empalme / piezas por ancho
                    fabric_cost = (AA / 100 * K) + (emp_len / 100 * K / ppw)
                elif line.use_remnants and pieces_w > 0:
                    # Aprovecha retales (servilletas 55cm del retal sobrante)
                    used_width = (Z / 100) * pieces_w
                    leftover_m = J - used_width  # metros de retal
                    serv_cols = int(leftover_m / 0.55)
                    serv_rows = int((AA / 100) / 0.55)
                    credit = (I / 10) * serv_rows * serv_cols
                    fabric_cost = round((K * (AA / 100) - credit) / pieces_w, 2)
                else:
                    if pieces_w > 0:
                        fabric_cost = round(K * (AA / 100) / pieces_w, 2)
                    else:
                        fabric_cost = 0.0
            else:
                fabric_cost = 0.0

            # ---- Coste festón (col AK) ----
            if line.has_feston and Z > 0 and AA > 0:
                perimeter_m = ((Z * 2) + (AA * 2)) / 100
                feston_cost = round(perimeter_m * _FESTON_RATE, 2)
            else:
                feston_cost = 0.0

            line.confection_cost = round(confection_cost, 4)
            line.fabric_cost = round(fabric_cost, 4)
            line.feston_cost = feston_cost
            line.unit_cost = round(confection_cost + fabric_cost + feston_cost, 4)
            line.line_total = round(line.unit_cost * line.quantity, 2) if line.quantity else 0.0

    @api.depends(
        'quantity', 'article_type_id', 'finished_width', 'finished_length',
        'hem_type', 'apply_shrinkage', 'cut_width', 'cut_length',
        'fabric_name', 'color_name', 'shape_type', 'is_prototype',
    )
    def _compute_display(self):
        """Genera textos de salida para Orden de Producción y Presupuesto Cliente
        (columnas AR, AS, AT, AU, AV, AW, AX del Excel)."""
        for line in self:
            # AR: Tipo artículo
            line.display_article_type = line.article_type_id.name if line.article_type_id else ''

            # AS: Medida uso "T × U" (+ " PR" si es prototipo)
            if line.finished_width and line.finished_length:
                dim = f"{int(line.finished_width)} × {int(line.finished_length)}"
                if line.is_prototype:
                    dim += ' PR'
                line.display_dimensions = dim
            else:
                line.display_dimensions = ''

            # AX: Corte con forma
            Z = round(line.cut_width)
            AA = round(line.cut_length)
            if Z and AA:
                if line.shape_type == '2':
                    line.display_cut = f"{Z} × {AA}"
                elif Z == AA:
                    line.display_cut = f"Redondo {Z} × {AA}"
                else:
                    line.display_cut = f"Ovalado {Z} × {AA}"
            else:
                line.display_cut = ''

            # AV: Dobladillo
            V = line.hem_type
            if V == 1:
                line.display_hem = 'Dobl. Sencillo'
            elif V > 1:
                line.display_hem = f'Dobl. {int(V)} cm.'
            else:
                line.display_hem = ''

            # AW: Encogimiento
            line.display_shrinkage = 'SI' if line.apply_shrinkage else ''

            # AU: Color detalle
            line.display_color = f"c/ {line.color_name}" if line.color_name else ''
