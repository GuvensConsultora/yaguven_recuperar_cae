import logging

from markupsafe import Markup

from odoo import api, models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_post(self):
        try:
            return super().action_post()
        except Exception:
            self._yaguven_intentar_recuperar_cae()
            raise

    def _yaguven_intentar_recuperar_cae(self):
        """Best-effort: nunca debe tapar la excepción original del posteo fallido.

        Corre en un cursor nuevo e independiente del original: el posteo que
        disparó esto pudo dejar la transacción principal en estado abortado
        (o el framework la va a rollbackear al relanzar la excepción), así que
        no podemos leer/escribir de forma confiable con self.env.cr.
        """
        move_ids = self.ids
        uid = self.env.uid
        context = self.env.context

        try:
            with self.env.registry.cursor() as new_cr:
                new_env = api.Environment(new_cr, uid, context)
                propuesta_model = new_env['yaguven.recuperar_cae.propuesta'].sudo()
                for move in new_env['account.move'].sudo().browse(move_ids):
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
                        move.activity_schedule(
                            'mail.mail_activity_data_todo',
                            summary='Comprobante fantasma detectado — revisar propuesta de '
                                    'recuperación de CAE',
                            note=note,
                            user_id=uid,
                        )
                        new_cr.commit()
                    except Exception:
                        _logger.exception(
                            'Recuperar CAE: fallo la deteccion automatica para journal %s (move %s)',
                            journal.id, move.id)
                        new_cr.rollback()
                        continue
        except Exception:
            _logger.exception(
                'Recuperar CAE: fallo el intento de deteccion en cursor nuevo para moves %s',
                move_ids)
