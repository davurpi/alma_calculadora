from odoo import fields, models


class AlmaArticleType(models.Model):
    """Tipos de artículo (pestaña ARTICULOS cols A-B del Excel).
    Ej: 1=Mantel, 2=Cubre, 3=Servilleta, 4=Camino de mesa..."""
    _name = 'alma.article.type'
    _description = 'Tipo de Artículo'
    _order = 'code'

    code = fields.Integer('Código', required=True)
    name = fields.Char('Nombre', required=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'El código de tipo de artículo debe ser único.'),
    ]
