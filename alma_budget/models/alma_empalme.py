from odoo import api, fields, models


class AlmaEmpalme(models.Model):
    """Tabla de empalmes para tejidos cuyo ancho es menor que la medida de corte
    (pestaña EMPALME del Excel).
    Determina cuántas piezas de empalme son necesarias y su dimensión."""
    _name = 'alma.empalme'
    _description = 'Tabla de Empalmes'
    _order = 'fabric_width_cm, mantel_width_cm'

    fabric_width_cm = fields.Integer('Ancho Tejido (cm)', required=True,
                                     help='Ancho real del tejido en cm, ej. 280.')
    mantel_width_cm = fields.Integer('Ancho Mantel (cm)', required=True,
                                     help='Ancho del mantel terminado que requiere empalme, ej. 310.')
    ref_empalme = fields.Char(
        'REF Empalme', compute='_compute_ref', store=True,
        help='Clave = fabric_width_cm & mantel_width_cm, ej. "280310".')

    empalme_length_cm = fields.Integer('Largo Empalme (cm)',
                                       help='Longitud de la tira de empalme necesaria.')
    empalme_width_cm = fields.Float('Ancho Empalme (cm)', compute='_compute_ref', store=True,
                                    help='mantel_width - fabric_width + 2 cm de costura.')
    pieces_per_width = fields.Integer('Piezas por Ancho', compute='_compute_ref', store=True,
                                      help='Cuántas tiras de empalme salen al ancho del tejido.')

    _sql_constraints = [
        ('ref_uniq', 'unique(fabric_width_cm, mantel_width_cm)',
         'Ya existe un registro para esta combinación ancho tejido / ancho mantel.'),
    ]

    @api.depends('fabric_width_cm', 'mantel_width_cm')
    def _compute_ref(self):
        for rec in self:
            fw = rec.fabric_width_cm or 0
            mw = rec.mantel_width_cm or 0
            rec.ref_empalme = f"{fw}{mw}" if fw and mw else ''
            rec.empalme_width_cm = mw - fw + 2 if fw and mw else 0
            rec.pieces_per_width = int(fw / rec.empalme_width_cm) if rec.empalme_width_cm else 0
