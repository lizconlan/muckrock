"""
Views for the crowdfund application
"""

from django.contrib import messages
from django.core.urlresolvers import reverse
from django.http import Http404
from django.shortcuts import render_to_response, get_object_or_404, redirect
from django.template import RequestContext

from decimal import Decimal
import logging
import stripe
import sys

from muckrock.crowdfund.models import \
    CrowdfundRequest, \
    CrowdfundProject, \
    CrowdfundRequestPayment, \
    CrowdfundProjectPayment
from muckrock.foia.models import FOIARequest
from muckrock.jurisdiction.models import Jurisdiction
from muckrock.settings import STRIPE_SECRET_KEY
from muckrock.task.models import CrowdfundPaymentTask

logger = logging.getLogger(__name__)
stripe.api_key = STRIPE_SECRET_KEY

def _contribute(request, crowdfund, payment_model, redirect_url):
    """Contribute to a crowdfunding request or project"""
    amount = request.POST.get('amount', False)
    token = request.POST.get('stripe_token', False)
    desc = 'Contribute to Crowdfunding: %s %s' % (crowdfund, crowdfund.pk)
    if amount and token:
        try:
            amount = int(amount) # normalizes amount for Stripe
            if request.user.is_authenticated():
                user = request.user
                user.get_profile().pay(token, amount, desc)
                name = user.username
            else:
                desc = '%s: %s' % (request.POST.get('stripe_email'), desc)
                stripe.Charge.create(
                    amount=amount,
                    description=desc,
                    currency='usd',
                    card=token
                )
                user = None
                name = 'A visitor'
            amount = float(amount)/100
            payment = payment_model.objects.create(
                user=user,
                crowdfund=crowdfund,
                amount=amount,
                name=name,
                show=False
            )
            if isinstance(payment, CrowdfundRequestPayment):
                CrowdfundPaymentTask.objects.create(
                    request_payment=payment)
            elif isinstance(payment, CrowdfundProjectPayment):
                CrowdfundPaymentTask.objects.create(
                    project_payment=payment)
            crowdfund.payment_received += Decimal(amount)
            crowdfund.save()
            messages.success(request, 'You contributed $%.2f. Thanks!' % amount)
            messages.info(request, 'To track this request, click Follow below.')
            log_msg = ('%s has contributed to crowdfund', name)
            logger.info(log_msg)
        except stripe.CardError as exc:
            msg = 'Payment error. Your card has not been charged'
            messages.error(request, msg)
            logger.error('Payment error: %s', exc, exc_info=sys.exc_info())
    return redirect(redirect_url)

def contribute_request(request, jurisdiction, jidx, slug, idx):
    """Contribute to a crowdfunding request"""
    jmodel = get_object_or_404(
        Jurisdiction,
        slug=jurisdiction,
        pk=jidx
    )
    foia = get_object_or_404(
        FOIARequest,
        jurisdiction=jmodel,
        slug=slug,
        pk=idx
    )
    crowdfund = get_object_or_404(CrowdfundRequest, foia=foia)
    redirect_url = reverse(
        'foia-detail',
        kwargs={
            'jurisdiction': crowdfund.foia.jurisdiction.slug,
            'jidx': crowdfund.foia.jurisdiction.pk,
            'slug': crowdfund.foia.slug,
            'idx': crowdfund.foia.pk
        }
    )
    if crowdfund.expired():
        raise Http404()
    return _contribute(
        request,
        crowdfund,
        CrowdfundRequestPayment,
        redirect_url
    )

def contribute_project(request, idx):
    """Contribute to a crowdfunding project"""
    crowdfund = get_object_or_404(CrowdfundProject, pk=idx)
    redirect_url = reverse(
        'project-detail',
        kwargs={'slug': crowdfund.project.slug, 'idx': crowdfund.project.pk}
    )
    return _contribute(
        request,
        crowdfund,
        CrowdfundProjectPayment,
        redirect_url
    )

def project_detail(request, slug, idx):
    """Project details"""
    project = get_object_or_404(CrowdfundProject, slug=slug, pk=idx)
    return render_to_response(
        'crowdfund/project_detail.html',
        {'project': project},
        context_instance=RequestContext(request)
    )
