import math
from odoo import api, fields, models

# ---------------------------------------------------------------------------
# Tarifa de confección (tabla CONFECCION del Excel)
# ---------------------------------------------------------------------------
_CONF_BASE = [0.36, 0.45, 0.54, 0.63, 0.72, 0.81, 0.90, 1.00, 1.08, 1.17,
              1.26, 1.35, 1.44, 1.53, 1.62, 1.71, 1.80, 1.89, 1.98, 2.07]
_CONF_MULT = 1.035
_FESTON_RATE = 0.75  # €/metro lineal


# Mapa tipo artículo (code) → (default_code producto, nombre fallback)
ARTICLE_PRODUCT = {
    1:  ('MESA-MAN-001', 'Mantel'),
    2:  ('MESA-CUB-001', 'Cubre'),
    3:  ('MESA-SER-002', 'Servilleta'),
    4:  ('MESA-CAM-001', 'Camino de Mesa'),
    5:  ('MESA-MUL-001', 'Muletón'),
    6:  ('MESA-GUE-001', 'Gueridón'),
    7:  ('MESA-LIT-001', 'Lito'),
    8:  ('MESA-IND-001', 'Individual'),
    9:  ('MESA-ACC-001', 'Accesorio'),
    10: ('MESA-FUN-001', 'Funda'),
}


def _confection_rate(cut_w, cut_l):
    """Tarifa de confección por pieza según tabla Excel CONFECCION."""
    idx = max(0, math.ceil(cut_w / 50) + math.ceil(cut_l / 50) - 2)
    base = _CONF_BASE[idx] if idx < len(_CONF_BASE) else (
        _CONF_BASE[-1] + (idx - len(_CONF_BASE) + 1) * 0.09)
    return round(base * _CONF_MULT, 4)


class AlmaCalculatorWizard(models.TransientModel):
    """Calculadora rápida de presupuesto — se abre desde un pedido de venta."""
    _name = 'alma.calculator.wizard'
    _description = 'Calculadora Rápida Mantelería'

    sale_order_id = fields.Many2one('sale.order', string='Pedido', required=True, ondelete='cascade')

    # ── Artículo y tejido ──────────────────────────────────────────────────
    fabric_id = fields.Many2one('alma.fabric', string='Tejido')
    fabric_color_id = fields.Many2one(
        'alma.fabric.color', string='Color',
        domain="[('fabric_id', '=', fabric_id)]")
    article_type_id = fields.Many2one('alma.article.type', string='Tipo de artículo')
    quantity = fields.Float('Cantidad', default=1.0, digits=(10, 0))
    margin_pct = fields.Float(
        'Margen (%)', default=1.0,
        help='1.0 = 100 %. Precio venta = coste × (1 + margen).')

    # ── Forma de la mesa ───────────────────────────────────────────────────
    mesa_form = fields.Selection([
        ('rect', 'Rectangular / Cuadrada'),
        ('round', 'Redonda'),
    ], string='Forma de la mesa', default='rect', required=True)

    # ── Medidas ────────────────────────────────────────────────────────────
    width_mesa = fields.Float(
        'Ancho mesa (cm)', digits=(10, 1),
        help='Cuando la forma es Redonda, introduce aquí el diámetro.')
    length_mesa = fields.Float('Largo mesa (cm)', digits=(10, 1))   # oculto si redonda
    table_height = fields.Float('Alto de la mesa (cm)', digits=(10, 1))
    extra_length = fields.Float('Añadir largo (cm)', digits=(10, 1))
    drop = fields.Float('Caída del mantel (cm)', digits=(10, 1))

    # ── Dobladillo ─────────────────────────────────────────────────────────
    hem_type = fields.Selection([
        ('simple', 'Sencillo'),
        ('custom', 'Personalizado (cm)'),
    ], string='Dobladillo', default='simple', required=True)
    hem_cm = fields.Float('Dobladillo (cm)', digits=(10, 1), default=1.5,
                          help='Valor en cm cuando el dobladillo es Personalizado.')

    # ── Opciones ───────────────────────────────────────────────────────────
    apply_shrinkage = fields.Boolean('Encogimiento', default=False)
    round_cut = fields.Boolean('Corte redondo', default=False,
                               help='Actívalo si el corte es redondo/ovalado.')
    use_remnants = fields.Boolean('Cobra sobrante', default=False,
                                  help='Descuenta retales de servilletas.')
    has_empalme = fields.Boolean('Empalme', default=False)
    empalme_override = fields.Integer('Nº de empalmes (si son menos)', default=0)
    has_feston = fields.Boolean('Festón', default=False)
    feston_color = fields.Char('Color festón')
    rounded_corners = fields.Boolean('Picos redondeados', default=False)

    # ── Resultados calculados (sólo lectura) ───────────────────────────────
    finished_width = fields.Float('Medida terminada ancho', readonly=True, digits=(10, 1))
    finished_length = fields.Float('Medida terminada largo', readonly=True, digits=(10, 1))
    cut_width = fields.Float('Ancho corte', readonly=True, digits=(10, 1))
    cut_length = fields.Float('Largo corte', readonly=True, digits=(10, 1))
    unit_cost = fields.Float('Precio unitario (€)', readonly=True, digits=(10, 4))
    line_total = fields.Float('Total línea (€)', readonly=True, digits=(10, 2))

    # ── Onchange: recalcular al cambiar cualquier input ────────────────────
    @api.onchange('fabric_id')
    def _onchange_fabric(self):
        self.fabric_color_id = False

    @api.onchange(
        'fabric_color_id', 'article_type_id', 'margin_pct', 'quantity',
        'mesa_form', 'width_mesa', 'length_mesa', 'table_height', 'extra_length', 'drop',
        'hem_type', 'hem_cm', 'apply_shrinkage', 'round_cut',
        'use_remnants', 'has_empalme', 'empalme_override', 'has_feston',
    )
    def _onchange_recalculate(self):
        self._do_calculate()

    # ── Núcleo del cálculo ─────────────────────────────────────────────────
    def _do_calculate(self):
        """Replica la lógica de las columnas T-AA y AG/AI/AK del Excel PRESUPUESTO."""
        fc = self.fabric_color_id
        art = self.article_type_id

        if not fc:
            self.finished_width = self.finished_length = 0
            self.cut_width = self.cut_length = 0
            self.unit_cost = self.line_total = 0
            return

        # Datos del tejido
        cost_m = fc.cost or 0.0
        width_m = fc.width or 1.0
        shrink_w = (fc.fabric_id.shrinkage_width or 0.0)
        shrink_l = (fc.fabric_id.shrinkage_length or 0.0)
        sale_m = cost_m * (1 + (self.margin_pct or 0))

        # Medidas de mesa
        M = self.width_mesa or 0
        if self.mesa_form == 'round':
            # Redonda: largo = ancho = diámetro
            N = M
            O = M
        else:
            N = self.length_mesa or 0
            O = 0.0

        P = self.table_height or 0
        Q = self.extra_length or 0
        R = self.drop or 0

        # Medida terminada ancho/largo (cols T, U)
        base_w = O if O > 0 else M
        base_l = O if O > 0 else N
        T = base_w + R * 2 + P * 2 + Q * 2
        U = base_l + R * 2 + P * 2 + Q * 2

        # Dobladillo (cols W, X)
        V = 1.0 if self.hem_type == 'simple' else max(self.hem_cm or 1.5, 0.1)
        if V == 1:
            W = T + 5
            X = U + 5
        else:
            W = T + V * 4
            X = U + V * 4

        # Encogimiento (cols Z, AA)
        if self.apply_shrinkage:
            Z = math.ceil(W * (1 + shrink_w)) if shrink_w else W
            AA = math.ceil(X * (1 + shrink_l)) if shrink_l else X
        else:
            Z = W
            AA = X

        self.finished_width = T
        self.finished_length = U
        self.cut_width = Z
        self.cut_length = AA

        # Piezas por ancho
        pieces_w = int(width_m / (Z / 100)) if Z > 0 else 0

        # Coste confección (col AG)
        article_code = art.code if art else 0
        conf_base = _confection_rate(Z, AA) if Z > 0 and AA > 0 else 0.0
        is_simple = (V == 1 or article_code == 7)
        conf = conf_base * (1 if is_simple else 2)
        if self.has_empalme:
            conf *= 3

        # Coste tejido (col AI)
        fabric_cost = 0.0
        if Z > 0 and AA > 0 and width_m > 0 and sale_m > 0:
            if self.has_empalme:
                ref = f"{round(width_m * 100)}{round(Z)}"
                emp = self.env['alma.empalme'].search([('ref_empalme', '=', ref)], limit=1)
                emp_len = emp.empalme_length_cm if emp else 0
                ppw = self.empalme_override or (emp.pieces_per_width if emp else 1) or 1
                fabric_cost = AA / 100 * sale_m + emp_len / 100 * sale_m / ppw
            elif self.use_remnants and pieces_w > 0:
                used_w = (Z / 100) * pieces_w
                leftover = width_m - used_w
                serv_cols = int(leftover / 0.55)
                serv_rows = int((AA / 100) / 0.55)
                credit = (cost_m / 10) * serv_rows * serv_cols
                fabric_cost = round((sale_m * (AA / 100) - credit) / pieces_w, 4)
            elif pieces_w > 0:
                fabric_cost = round(sale_m * (AA / 100) / pieces_w, 4)

        # Coste festón (col AK)
        feston_cost = 0.0
        if self.has_feston and Z > 0 and AA > 0:
            feston_cost = round(((Z * 2) + (AA * 2)) * _FESTON_RATE / 100, 2)

        self.unit_cost = round(conf + fabric_cost + feston_cost, 4)
        self.line_total = round(self.unit_cost * (self.quantity or 0), 2)

    # ── Descripción para la línea de venta ────────────────────────────────
    def _build_description(self):
        """Formato: Mantel Saten 50/50 c/ 1 Blanco, Medida: 111 * 111 - Feston: Hilo Arena, Dobladillo: 1 cm"""
        fc = self.fabric_color_id
        art = self.article_type_id
        head = f"{art.name if art else ''} {fc.fabric_id.name if fc else ''} c/ {fc.color_code if fc else ''} {fc.color_name if fc else ''}".strip()
        medida = f"Medida: {int(self.finished_width)} * {int(self.finished_length)}" if (self.finished_width and self.finished_length) else ""
        extras = []
        if self.has_feston and self.feston_color:
            extras.append(f"Feston: {self.feston_color}")
        if self.hem_type == 'custom' and self.hem_cm:
            extras.append(f"Dobladillo: {self.hem_cm} cm")
        if self.apply_shrinkage:
            extras.append("Encogimiento: SI")
        main = ", ".join(filter(None, [head, medida]))
        return (main + " - " + " - ".join(extras)) if extras else main

    # ── Buscar o crear producto ────────────────────────────────────────────
    def _get_product(self):
        art = self.article_type_id
        ref, fallback_name = ARTICLE_PRODUCT.get(art.code if art else 0, ('MESA-ART-001', 'Artículo'))
        product = self.env['product.product'].search([('default_code', '=', ref)], limit=1)
        if not product:
            product = self.env['product.product'].create({
                'name': fallback_name,
                'default_code': ref,
                'type': 'service',
                'invoice_policy': 'order',
            })
        return product

    # ── Acciones del formulario ────────────────────────────────────────────
    def action_add_line(self):
        """Añade una línea al pedido y mantiene el wizard abierto (para seguir añadiendo)."""
        self._do_calculate()
        if self.fabric_color_id and self.article_type_id:
            self.env['sale.order.line'].create({
                'order_id': self.sale_order_id.id,
                'product_id': self._get_product().id,
                'product_uom_qty': self.quantity or 1,
                'price_unit': self.unit_cost,
                'name': self._build_description(),
            })
        # Reabre el wizard limpio para añadir más líneas
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'alma.calculator.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sale_order_id': self.sale_order_id.id,
                'dialog_size': 'large',
            },
        }

    def action_confirm_and_close(self):
        """Añade la línea y cierra el wizard (vuelve al pedido en modo edición)."""
        self._do_calculate()
        if self.fabric_color_id and self.article_type_id:
            self.env['sale.order.line'].create({
                'order_id': self.sale_order_id.id,
                'product_id': self._get_product().id,
                'product_uom_qty': self.quantity or 1,
                'price_unit': self.unit_cost,
                'name': self._build_description(),
            })
        return {'type': 'ir.actions.act_window_close'}
