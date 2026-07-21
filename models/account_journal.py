from odoo import models
from odoo.exceptions import UserError


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    def action_recuperar_cae_escanear(self):
        self.ensure_one()
        propuestas = self.env['yaguven.recuperar_cae.propuesta']._escanear_journal(self)
        if not propuestas:
            raise UserError(
                'No se encontraron comprobantes fantasma en este diario — AFIP y Odoo '
                'están alineados.')
        action = self.env['ir.actions.act_window']._for_xml_id(
            'yaguven_recuperar_cae.action_recuperar_cae_propuesta')
        action['domain'] = [('id', 'in', propuestas.ids)]
        return action
