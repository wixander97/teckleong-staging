# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class QuickSearchOperator(models.Model):
    _name = "quick.search.operator"
    _description = "Quick Search Operator"

    name = fields.Char("Name")
    value = fields.Char("Value")

class QuickSearch(models.Model):
    _name = "quick.search"
    _description = "Quick Search"

    name = fields.Char("Name")
    model_id = fields.Many2one("ir.model", string="Model")
    company_id = fields.Many2one("res.company", string="Company", default=lambda self: self.env.user.company_id.id, index=1)
    line_ids = fields.One2many("quick.search.line", "quick_search_id", string="Fields")

    _sql_constraints = [
        ("model_company_uniq", "unique(model_id,company_id)", "You cannot have more than one quick search on the same model, please edit the existing one.")
    ]

    @api.onchange("model_id")
    def _onchange_model(self):
        if self.model_id:
            self.name = self.model_id.name

class QuickSearchLine(models.Model):
    _name = "quick.search.line"
    _description = "Quick Search Line"
    _order = "sequence"

    name = fields.Char("Label")
    sequence = fields.Integer(default=10, string="Sequence")
    quick_search_id = fields.Many2one("quick.search", string="Quick Search")
    field_id = fields.Many2one("ir.model.fields", string="Field", domain="[('ttype', 'not in', ['binary', 'html', 'reference']), '|', ('store', '=', True), ('related', '!=', False)]")
    field_name = fields.Char(related="field_id.name", string="Field Name", readonly=True)
    field_type = fields.Selection(related="field_id.ttype", string="Field Type")
    operator_id = fields.Many2one("quick.search.operator", string="Operator", readonly=True)
    operator_value = fields.Char(related="operator_id.value", string="Operator Value", readonly=True)

    @api.onchange("field_id")
    def _onchange_field(self):
        if self.field_id:
            values = []
            self.field_type = field_type = self.field_id.ttype
            self.operator_id = False
            if field_type in ['char', 'text', 'many2one', 'one2many', 'many2many']:
                values = ['ilike', 'not ilike', '=', '!=']
            elif field_type in ['monetary', 'float', 'integer']:
                values = ['=', '!=', '>', '<', '>=', '<=']
            elif field_type in ['date', 'datetime']:
                values = ['=', '!=', '>', '<', '>=', '<=', 'between']
            elif field_type in ['selection']:
                values = ['=', '!=']

            if values:
                return {'domain': {'operator_id': [('value', 'in', values)]}}

    @api.onchange("operator_id")
    def _onchange_operator(self):
        if self.field_id:
            values = []
            field_type = self.field_id.ttype
            if field_type in ['char', 'text', 'many2one', 'one2many', 'many2many']:
                values = ['ilike', 'not ilike', '=', '!=']
            elif field_type in ['monetary', 'float', 'integer']:
                values = ['=', '!=', '>', '<', '>=', '<=']
            elif field_type in ['date', 'datetime']:
                values = ['=', '!=', '>', '<', '>=', '<=', 'between']
            elif field_type in ['selection']:
                values = ['=', '!=']

            if values:
                return {'domain': {'operator_id': [('value', 'in', values)]}}