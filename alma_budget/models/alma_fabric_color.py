from odoo import api, fields, models


class AlmaFabricColor(models.Model):
    """Combinaciones tejido + color con precio y ancho (pestaña COLORES del Excel).
    La clave de búsqueda es ref3 = ref_combined + str(color_code), ej. '1TVR1'."""
    _name = 'alma.fabric.color'
    _description = 'Tejido - Color'
    _order = 'fabric_id, color_code'

    fabric_id = fields.Many2one('alma.fabric', string='Tejido', required=True, ondelete='cascade')
    fabric_name = fields.Char(related='fabric_id.name', store=True)
    fabric_ref_combined = fields.Char(related='fabric_id.ref_combined', store=True)

    color_code = fields.Integer('Código Color', required=True)
    color_name = fields.Char('Color', required=True)
    ref3 = fields.Char(
        'REF 3 (clave)', compute='_compute_ref3', store=True,
        help='Clave única = REF_COMBINED + color_code. Ej: "1TVR1" = Satén 50/50, color Blanco.')

    cost = fields.Float('Coste (€/m lineal)', digits=(10, 4), required=True,
                        help='Precio de coste por metro lineal al ancho completo del tejido.')
    width = fields.Float('Ancho tejido (m)', digits=(6, 3), required=True,
                         help='Ancho de la pieza en metros, ej. 3.20 = 320 cm.')
    composition = fields.Char('Composición')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('ref3_uniq', 'unique(fabric_id, color_code)', 'La combinación tejido+color debe ser única.'),
    ]

    @api.depends('fabric_id.ref_combined', 'color_code')
    def _compute_ref3(self):
        for rec in self:
            if rec.fabric_id and rec.fabric_id.ref_combined and rec.color_code:
                rec.ref3 = f"{rec.fabric_id.ref_combined}{rec.color_code}"
            else:
                rec.ref3 = ''

    def name_get(self):
        return [(r.id, f"{r.fabric_name} - {r.color_name}") for r in self]

    @api.model
    def _name_search(self, name='', domain=None, operator='ilike', limit=100, order=None):
        domain = domain or []
        if name:
            domain = ['|', '|',
                      ('fabric_name', operator, name),
                      ('color_name', operator, name),
                      ('ref3', operator, name)] + domain
        return self._search(domain, limit=limit, order=order)
