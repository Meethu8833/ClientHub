"""
Billing API (docs/billing-module.md):

    /invoices/                      list/create/retrieve/patch;
                                    DELETE only while DRAFT
    /invoices/from-quotation/       POST {quotation_id} → 201 draft copied
                                    from an ACCEPTED quotation
    /invoices/{id}/items/           GET lines, POST add line (draft only)
    /invoice-items/{id}/            PATCH/DELETE one line (flat, draft only)
    /invoices/{id}/issue/           POST  draft → issued (number assigned HERE)
    /invoices/{id}/void/            POST  {reason}  issued → void (no payments)
    /invoices/{id}/payments/        GET receipts, POST record money
                                    (status pending|completed, default completed)
    /payments/                      GET the global payments register
                                    (filter: status/method/reconciled/dates/…)
    /payments/summary/              GET cash summary for a date range
    /payments/{id}/                 GET one; DELETE a mis-entered receipt
    /payments/{id}/clear/           POST  pending → completed (money counts NOW)
    /payments/{id}/bounce/          POST  pending → bounced (kept on record)
    /payments/{id}/reconcile/       POST  matched to a bank-statement line
    /payments/{id}/unreconcile/     POST  undo a wrong match
    /payments/{id}/refunds/         GET refunds, POST send money back {reason}
    /refunds/{id}/                  DELETE a mis-entered refund (flat)

Visibility is the §8 matrix's Billing row: ADMIN/MANAGER full, STAFF nothing
— not even read. Billing is the company's money position; a developer
resolving tickets has no business need to see who owes what. One permission
class on every route, no queryset scoping needed.
"""

from django.db.models import Count, Sum
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.permissions import IsManagerOrAdmin

from . import services
from .filters import InvoiceFilter, PaymentFilter
from .models import Invoice, InvoiceItem, Payment, Refund
from .serializers import (
    FromQuotationSerializer,
    InvoiceDetailSerializer,
    InvoiceItemSerializer,
    InvoiceItemWriteSerializer,
    InvoiceListSerializer,
    InvoiceWriteSerializer,
    PaymentListSerializer,
    PaymentSerializer,
    PaymentWriteSerializer,
    RefundSerializer,
    RefundWriteSerializer,
    VoidSerializer,
)


class InvoiceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsManagerOrAdmin]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]  # no PUT (§6)
    filterset_class = InvoiceFilter
    search_fields = ["invoice_number", "client__name"]
    ordering_fields = ["created_at", "issue_date", "due_date", "grand_total", "amount_paid"]
    ordering = ["-created_at"]

    def get_queryset(self):
        # §6 N+1 discipline: every FK the serializers touch is joined; items
        # and payments are prefetched for the detail shape.
        return Invoice.objects.select_related(
            "client", "contact", "project", "created_by"
        ).prefetch_related(
            "items",
            "payments",
            "payments__recorded_by",
            "payments__reconciled_by",
            "payments__refunds",
            "payments__refunds__recorded_by",
        )

    def get_serializer_class(self):
        if self.action == "list":
            return InvoiceListSerializer
        if self.action in ("create", "partial_update", "update"):
            return InvoiceWriteSerializer
        return InvoiceDetailSerializer

    def _detail(self, invoice, http_status=status.HTTP_200_OK):
        """Every mutation answers with the same full-detail shape."""
        serializer = InvoiceDetailSerializer(invoice, context=self.get_serializer_context())
        return Response(serializer.data, status=http_status)

    # -- create / update / delete → services ---------------------------------

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice = services.create_invoice(
            invoice=Invoice(**serializer.validated_data), actor=request.user
        )
        return self._detail(invoice, http_status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(instance, field, value)
        return self._detail(services.update_invoice(invoice=instance, actor=request.user))

    def perform_destroy(self, instance):
        # A numberless draft is scrap paper. Anything issued is a ledger
        # entry — the gapless series depends on it staying put; void instead.
        if instance.status != Invoice.Status.DRAFT:
            raise ValidationError(
                {"detail": "Only drafts can be deleted — void the invoice instead."}
            )
        instance.delete()

    # -- from quotation -------------------------------------------------------

    @action(detail=False, methods=["post"], url_path="from-quotation")
    def from_quotation(self, request):
        """201: creates the draft invoice copied from an accepted quotation."""
        serializer = FromQuotationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice = services.create_from_quotation(
            quotation=serializer.validated_data["quotation"], actor=request.user
        )
        return self._detail(invoice, http_status=status.HTTP_201_CREATED)

    # -- line items -----------------------------------------------------------

    @action(detail=True, methods=["get", "post"])
    def items(self, request, pk=None):
        invoice = self.get_object()
        if request.method == "GET":
            return Response(InvoiceItemSerializer(invoice.items.all(), many=True).data)

        serializer = InvoiceItemWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = services.add_item(
            invoice=invoice,
            item=InvoiceItem(**serializer.validated_data),
            actor=request.user,
        )
        return Response(InvoiceItemSerializer(item).data, status=status.HTTP_201_CREATED)

    # -- lifecycle verbs ------------------------------------------------------

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        return self._detail(services.issue_invoice(invoice=self.get_object(), actor=request.user))

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        serializer = VoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._detail(
            services.void_invoice(
                invoice=self.get_object(),
                actor=request.user,
                reason=serializer.validated_data["reason"],
            )
        )

    # -- payments -------------------------------------------------------------

    @action(detail=True, methods=["get", "post"])
    def payments(self, request, pk=None):
        invoice = self.get_object()
        if request.method == "GET":
            return Response(PaymentSerializer(invoice.payments.all(), many=True).data)

        serializer = PaymentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = services.record_payment(
            invoice=invoice,
            payment=Payment(**serializer.validated_data),
            actor=request.user,
        )
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class InvoiceItemViewSet(
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Flat writes for one line (§6: nested is read/create only; update/delete
    hit the flat resource). Draft-only, enforced in services.
    """

    permission_classes = [IsManagerOrAdmin]
    serializer_class = InvoiceItemWriteSerializer
    http_method_names = ["patch", "delete", "head", "options"]
    queryset = InvoiceItem.objects.select_related("invoice")

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(instance, field, value)
        item = services.update_item(item=instance, actor=request.user)
        return Response(InvoiceItemSerializer(item).data)

    def perform_destroy(self, instance):
        services.delete_item(item=instance, actor=self.request.user)


class PaymentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    The payments REGISTER — payments as first-class rows across all invoices,
    which is how finance actually works a bank statement (statement-side in,
    not invoice-side). List/retrieve/filter, the pending-payment lifecycle
    verbs, reconciliation, and nested refunds.

    Still no PATCH, and no POST-create here: a receipt is a fact — a wrong
    fact is removed and re-entered (both on the trail), and money is only
    ever recorded THROUGH its invoice (/invoices/{id}/payments/), because a
    payment without an invoice is money we can't explain.
    """

    permission_classes = [IsManagerOrAdmin]
    filterset_class = PaymentFilter
    http_method_names = ["get", "post", "delete", "head", "options"]  # post = actions only
    ordering_fields = ["received_on", "amount", "created_at"]
    ordering = ["-received_on", "-id"]

    def get_queryset(self):
        return Payment.objects.select_related(
            "invoice", "invoice__client", "recorded_by", "reconciled_by"
        ).prefetch_related("refunds", "refunds__recorded_by")

    def get_serializer_class(self):
        return PaymentListSerializer

    def perform_destroy(self, instance):
        services.delete_payment(payment=instance, actor=self.request.user)

    def _one(self, payment):
        """Every lifecycle verb answers with the updated register row."""
        return Response(PaymentListSerializer(payment).data)

    # -- lifecycle verbs ------------------------------------------------------

    @action(detail=True, methods=["post"])
    def clear(self, request, pk=None):
        return self._one(services.clear_payment(payment=self.get_object(), actor=request.user))

    @action(detail=True, methods=["post"])
    def bounce(self, request, pk=None):
        return self._one(services.bounce_payment(payment=self.get_object(), actor=request.user))

    # -- reconciliation -------------------------------------------------------

    @action(detail=True, methods=["post"])
    def reconcile(self, request, pk=None):
        return self._one(
            services.reconcile_payment(payment=self.get_object(), actor=request.user)
        )

    @action(detail=True, methods=["post"])
    def unreconcile(self, request, pk=None):
        return self._one(
            services.unreconcile_payment(payment=self.get_object(), actor=request.user)
        )

    # -- refunds --------------------------------------------------------------

    @action(detail=True, methods=["get", "post"])
    def refunds(self, request, pk=None):
        payment = self.get_object()
        if request.method == "GET":
            return Response(RefundSerializer(payment.refunds.all(), many=True).data)

        serializer = RefundWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refund = services.record_refund(
            payment=payment,
            refund=Refund(**serializer.validated_data),
            actor=request.user,
        )
        return Response(RefundSerializer(refund).data, status=status.HTTP_201_CREATED)

    # -- the cash summary -----------------------------------------------------

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """
        GET /payments/summary/?received_after=&received_before=

        The reconciliation dashboard in one response: what came in (by
        method), what's still promised, what's unmatched against the bank,
        what went back out. Aggregated in SQL — the DB counts, we don't page.
        """
        from django.utils.dateparse import parse_date

        window = {}
        for param, lookup in (
            ("received_after", "received_on__gte"),
            ("received_before", "received_on__lte"),
        ):
            raw = request.query_params.get(param)
            if raw:
                parsed = parse_date(raw)
                if parsed is None:
                    raise ValidationError({param: "Use YYYY-MM-DD."})
                window[lookup] = parsed

        payments = Payment.objects.filter(**window)
        completed = payments.filter(status=Payment.Status.COMPLETED)

        def agg(qs):
            data = qs.aggregate(total=Sum("amount"), count=Count("id"))
            return {"total": str(data["total"] or 0), "count": data["count"]}

        refund_window = {k.replace("received_on", "refunded_on"): v for k, v in window.items()}
        return Response(
            {
                "received": agg(completed),
                "by_method": {
                    row["method"]: {"total": str(row["total"]), "count": row["count"]}
                    for row in completed.values("method")
                    .annotate(total=Sum("amount"), count=Count("id"))
                    .order_by("method")
                },
                "pending": agg(payments.filter(status=Payment.Status.PENDING)),
                "bounced": agg(payments.filter(status=Payment.Status.BOUNCED)),
                "unreconciled": agg(completed.filter(reconciled_at__isnull=True)),
                "refunded": agg(Refund.objects.filter(**refund_window)),
            }
        )


class RefundViewSet(mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Flat DELETE for one mis-entered refund — same append-then-correct
    shape as payments: no edits, the correction goes on the trail."""

    permission_classes = [IsManagerOrAdmin]
    serializer_class = RefundSerializer
    http_method_names = ["delete", "head", "options"]
    queryset = Refund.objects.select_related("payment", "payment__invoice")

    def perform_destroy(self, instance):
        services.delete_refund(refund=instance, actor=self.request.user)
