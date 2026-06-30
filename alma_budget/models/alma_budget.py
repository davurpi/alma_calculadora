from odoo import api, fields, models


class AlmaBudget(models.Model):
    """Cabecera de presupuesto de mantelería (pestaña DATOS del Excel).
    Puede vincularse a un pedido de venta de Odoo."""
    _name = 'alma.budget'
    _description = 'Presupuesto Mantelería'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char('Nº Presupuesto', required=True, copy=False,
                       default=lambda self: self.env['ir.sequence'].next_by_code('alma.budget'))
    partner_id = fields.Many2one('res.partner', string='Cliente', required=True, tracking=True)
    date = fields.Date('Fecha', default=fields.Date.today, required=True)
    commercial_id = fields.Many2one('res.users', string='Comercial',
                                    default=lambda self: self.env.user)
    reference = fields.Char('Referencia')

    # Datos fiscales del cliente (mirror de la pestaña DATOS)
    vat = fields.Char(related='partner_id.vat', string='NIF')
    street = fields.Char(related='partner_id.street', string='Dirección')
    email = fields.Char(related='partner_id.email', string='Correo')
    phone = fields.Char(related='partner_id.phone', string='Teléfono')

    line_ids = fields.One2many('alma.budget.line', 'budget_id', string='Líneas')

    total_amount = fields.Float('Total Presupuesto', compute='_compute_total', store=True)

    state = fields.Selection([
        ('draft', 'Borrador'),
        ('confirmed', 'Confirmado'),
        ('sent', 'Enviado'),
        ('done', 'Realizado'),
        ('cancel', 'Cancelado'),
    ], default='draft', string='Estado', tracking=True)

    notes = fields.Text('Notas / Condiciones',
                        default='Todas las prendas serán identificadas con etiqueta color, según medida.\n'
                                'Estos precios no incluyen I.V.A.\n'
                                'Considerado encogimiento.\n'
                                'Confección a Capet\n'
                                'F. Pago: 50% a la aceptación de presupuesto.\n'
                                'Resto a la entrega de mercancía.\n'
                                'La cantidad de prendas puede variar en un +/- 10%.')

    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
        string='Moneda', readonly=True)

    sale_order_id = fields.Many2one('sale.order', string='Pedido de Venta vinculado')

    @api.depends('line_ids.line_total')
    def _compute_total(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped('line_total'))

    def action_confirm(self):
        self.state = 'confirmed'

    def action_send(self):
        self.state = 'sent'

    def action_done(self):
        self.state = 'done'

    def action_cancel(self):
        self.state = 'cancel'

    def action_draft(self):
        self.state = 'draft'

    def action_print_budget(self):
        return self.env.ref('alma_budget.action_report_budget_client').report_action(self)

    def action_print_production(self):
        return self.env.ref('alma_budget.action_report_production_order').report_action(self)
