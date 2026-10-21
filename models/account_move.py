import logging

from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SALTAR = 'yaguven_recuperar_cae_saltar'


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        """El enganche va en `_post` y no en `action_post` porque el punto de venta postea
        la factura del ticket llamando a `_post()` directo (`pos.order._generate_pos_order_invoice`),
        mientras que `action_post()` termina llamando a `_post(soft=False)`. Un solo override
        cubre las dos puntas; en `action_post` el POS quedaba afuera.
        """
        if self.env.context.get(SALTAR):
            return super()._post(soft=soft)
        try:
            with self.env.cr.savepoint():
                return super()._post(soft=soft)
        except Exception as original:
            # El savepoint ya deshizo lo del posteo fallido, así que la transacción sigue usable.
            arreglados = self._yaguven_recuperar_cae(original)
            if not arreglados:
                raise
            # Reintento: el fantasma ya tiene su número y CAE, así que la numeración quedó
            # alineada y este comprobante puede pedir el suyo.
            return super(AccountMove, self.with_context(**{SALTAR: True}))._post(soft=soft)

    # ------------------------------------------------------------------

    def _yaguven_recuperar_cae(self, original):
        """Intenta destrabar la numeración sin intervención humana.

        Devuelve True sólo si el fantasma quedó resuelto y vale la pena reintentar el posteo.
        Si el apareo no es único, deja la propuesta anotada para revisión y devuelve False:
        aplicar a ciegas significaría ponerle el CAE de ARCA a un comprobante que no es el que
        ARCA autorizó, y eso no se corrige después.
        """
        propuesta_model = self.env['yaguven.recuperar_cae.propuesta'].sudo()
        resuelto = False
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
            except Exception:
                _logger.exception(
                    'Recuperar CAE: falló la consulta a AFIP para el diario %s (comprobante %s)',
                    journal.id, move.id)
                continue
            if not propuestas:
                continue
            for propuesta in propuestas.sorted('numero_afip'):
                if propuesta._aplicar_automatica():
                    resuelto = True
                else:
                    propuesta._dejar_para_revision(original)
        return resuelto
