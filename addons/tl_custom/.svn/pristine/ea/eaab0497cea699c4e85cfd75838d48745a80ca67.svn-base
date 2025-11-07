# -*- coding: utf-8 -*-
#################################################################################
# Author      : Webkul Software Pvt. Ltd. (<https://webkul.com/>)
# Copyright(c): 2015-Present Webkul Software Pvt. Ltd.
# License URL : https://store.webkul.com/license.html/
# All Rights Reserved.
#
#
#
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#
# You should have received a copy of the License along with this program.
# If not, see <https://store.webkul.com/license.html/>
#################################################################################

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError, AccessError
from odoo import SUPERUSER_ID
import re

import logging
_logger = logging.getLogger(__name__)

class Partner(models.Model):
    _inherit = "res.partner"

    is_driver = fields.Boolean('Driver')
    fax = fields.Char('Fax')
    is_woocommerce = fields.Boolean('Woocomerce')
    company_name = fields.Char('Company Name')

    @api.model
    def create(self, vals):
        if not vals.get('state_id'):
            vals.pop('state_id')

        if vals.get('is_woocommerce'):
            if vals.get('company_name'):
                company_parent = self.env['res.partner'].search([('name', '=', vals['company_name']), ('company_type', '=', 'company')], limit=1)

                if not company_parent:
                    company_parent = self.create({
                        'name': vals['company_name'],
                        'company_type': 'company',
                        'state_id': False,
                        'street': False,
                        'zip': False,
                        'country_id': False,
                    })


                vals['parent_id'] = company_parent.id

            else:
                vals['parent_id'] = self.env['res.company'].browse(1).sales_online_partner_id.id

        res = super(Partner, self).create(vals)

        return res