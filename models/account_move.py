import logging

from markupsafe import Markup

from odoo import models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_post(self):
        try:
            with self.env.cr.savepoint():
                return super().action_post()
        except Exception:
            self._yaguven_intentar_recuperar_cae()
            raise

    def _yaguven_intentar_recuperar_cae(self):
        """Best-effort: nunca debe tapar la excepción original del posteo fallido."""
        propuesta_model = self.env['yaguven.recuperar_cae.propuesta'].sudo()
        for move in self:
            journal = move.journal_id
            if move.state != 'draft':
                continue
            if not journal.l10n_ar_afip_ws or move.move_type not in ('out_invoice', 'out_refund'):
                continue
            if not move.l10n_latam_document_type_id:
                continue
            try:
                propuestas = propuesta_model._escanear_journal(
                    journal, doc_types=move.l10n_latam_document_type_id, move_origen=move)
                if not propuestas:
                    continue
                note = Markup(''.join(
                    p.mensaje or '' for p in propuestas.sorted('numero_afip')))
                move.sudo().activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary='Comprobante fantasma detectado — revisar propuesta de '
                            'recuperación de CAE',
                    note=note,
                    user_id=self.env.user.id,
                )
            except Exception:
                _logger.exception(
                    'Recuperar CAE: fallo la detección automática para journal %s (move %s)',
                    journal.id, move.id)
                continue
            else:
                # El posteo que disparó esto ya hizo rollback dentro del savepoint de
                # action_post; comiteamos acá aparte para que la propuesta y la actividad
                # sobrevivan al rollback que el framework hace sobre la excepción original
                # al volver a levantarla más abajo.
                self.env.cr.commit()
