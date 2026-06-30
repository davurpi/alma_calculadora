from odoo import api, fields, models


class AlmaFabric(models.Model):
    """Catálogo de tejidos (pestaña ARTICULOS del Excel, cols D-I).
    Cada tejido tiene un código numérico REF1, un prefijo REF2 (ej. TVR, GRT)
    y porcentajes de encogimiento en largo y ancho."""
    _name = 'alma.fabric'
    _description = 'Tejido'
    _order = 'name'

    ref1 = fields.Integer('REF 1 (numérico)', required=True)
    ref2 = fields.Char('REF 2 (prefijo)', required=True, size=10)
    name = fields.Char('Nombre del Tejido', required=True)
    ref_combined = fields.Char(
        'REF Combinada', compute='_compute_ref_combined', store=True,
        help='Concatenación REF1+REF2, ej. "1TVR". Es la clave de búsqueda en la tabla COLORES.')

    shrinkage_length = fields.Float(
        'Encogimiento Largo (%)', digits=(6, 4),
        help='Factor de encogimiento en largo, ej. 0.03 = 3%.')
    shrinkage_width = fields.Float(
        'Encogimiento Ancho (%)', digits=(6, 4),
        help='Factor de encogimiento en ancho, ej. 0.02 = 2%.')

    color_ids = fields.One2many('alma.fabric.color', 'fabric_id', string='Colores disponibles')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('ref_combined_uniq', 'unique(ref1, ref2)', 'La combinación REF1+REF2 debe ser única.'),
    ]

    @api.depends('ref1', 'ref2')
    def _compute_ref_combined(self):
        for rec in self:
            rec.ref_combined = f"{rec.ref1}{rec.ref2}" if rec.ref1 and rec.ref2 else ''
