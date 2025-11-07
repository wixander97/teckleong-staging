# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError, AccessError

class TeckleongNotificationWizard(models.TransientModel):
    _name = 'teckleong.notification.wizard'
    _description = 'Notification Wizard'

    @api.model
    def default_get(self, fields):
        res = super(TeckleongNotificationWizard, self).default_get(fields)
        sale_obj = self.env['sale.order'].browse(self._context.get('active_ids'))
        context = self._context
        res['name'] = context['text']

        return res

    def action_confirm(self):
        return
               
    name = fields.Html('Reference')