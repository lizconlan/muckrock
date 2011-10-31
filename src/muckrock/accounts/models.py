"""
Models for the accounts application
"""

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.localflavor.us.models import PhoneNumberField, USStateField
from django.db import models

from datetime import datetime
import stripe

from foia.models import FOIARequest
from settings import MONTHLY_REQUESTS, STRIPE_SECRET_KEY

stripe.api_key = STRIPE_SECRET_KEY

class Profile(models.Model):
    """User profile information for muckrock"""

    acct_types = (
        ('admin', 'Admin'),
        ('beta', 'Beta'),
        ('community', 'Community'),
        ('pro', 'Professional'),
    )

    user = models.ForeignKey(User, unique=True)
    address1 = models.CharField(max_length=50, blank=True, verbose_name='address')
    address2 = models.CharField(max_length=50, blank=True, verbose_name='address (line 2)')
    city = models.CharField(max_length=60, blank=True)
    state = USStateField(blank=True, default='MA')
    zip_code = models.CharField(max_length=10, blank=True)
    phone = PhoneNumberField(blank=True)
    follows = models.ManyToManyField(FOIARequest, related_name='followed_by', blank=True)
    acct_type = models.CharField(max_length=10, choices=acct_types)

    # paid for requests
    num_requests = models.IntegerField(default=0)
    # for limiting # of requests / month
    monthly_requests = models.IntegerField(default=0)
    date_update = models.DateField()

    # for stripe
    stripe_id = models.CharField(max_length=255, blank=True)

    def __unicode__(self):
        return u"%s's Profile" % unicode(self.user).capitalize()

    def get_monthly_requests(self):
        """Get the number of requests left for this month"""

        if self.date_update.month != datetime.now().month or \
                self.date_update.year != datetime.now().year:
            # update requests if they have not yet been updated this month
            self.date_update = datetime.now()
            self.monthly_requests = MONTHLY_REQUESTS.get(self.acct_type, 0)
            self.save()

        return self.monthly_requests

    def make_request(self):
        """Reduce one from the user's request amount"""

        if self.get_monthly_requests() > 0:
            self.monthly_requests -= 1
            self.save()
            return True
        elif self.num_requests > 0:
            self.num_requests -= 1
            self.save()
            return True
        else:
            return False

    def can_embargo(self):
        """Is this user allowed to embargo?"""

        return self.acct_type in ['admin', 'beta', 'pro']

    def get_cc(self):
        """Get the user's CC if they have one on file"""
        try:
            local_card = StripeCC.objects.get(user=self.user)
        except StripeCC.DoesNotExist:
            local_card = None

        remote_card = getattr(self.get_customer(), 'active_card', None)

        if not local_card and remote_card:
            local_card = StripeCC.objects.create(user=self.user,
                                                 last4=remote_card.last4,
                                                 card_type=remote_card.type)
        elif local_card and not remote_card:
            local_card.delete()
            local_card = None
        elif local_card and remote_card and \
            (local_card.last4 != remote_card.last4 or local_card.card_type != remote_card.type):
            local_card.last4 = remote_card.last4
            local_card.card_type = remote_card.type
            local_card.save()

        return local_card

    def save_cc(self, form):
        """Save a credit card"""
        customer = self.get_customer()
        customer.card = form.cleaned_data['token']
        customer.save()

        try:
            card = StripeCC.objects.get(user=self.user)
            card.last4 = form.cleaned_data['last4']
            card.card_type = form.cleaned_data['card_type']
            card.save()
        except StripeCC.DoesNotExist:
            StripeCC.objects.create(user=self.user,
                                    last4=form.cleaned_data['last4'],
                                    card_type=form.cleaned_data['card_type'])

    def get_customer(self):
        """Get stripe customer"""
        try:
            customer = stripe.Customer.retrieve(self.stripe_id)
        except stripe.InvalidRequestError:
            customer = self.save_customer()

        return customer

    def save_customer(self, token=None):
        """Save stripe customer"""
        # pylint: disable-msg=E1101

        if token:
            customer = stripe.Customer.create(
                description=self.user.username,
                email=self.user.email,
                card=token,
                plan='pro')
        else:
            customer = stripe.Customer.create(
                description=self.user.username,
                email=self.user.email)

        self.stripe_id = customer.id
        self.save()

        return customer

    def pay(self, request, form, amount, desc):
        """Create a stripe charge for the user"""
        customer = self.get_customer()

        try:
            if form.cleaned_data['save_cc']:
                self.save_cc(form)
            if form.cleaned_data['use_on_file'] or form.cleaned_data['save_cc']:
                stripe.Charge.create(amount=amount, currency='usd', customer=customer.id,
                                     description=desc)
            else:
                stripe.Charge.create(amount=amount, currency='usd',
                                     card=form.cleaned_data['token'],
                                     description=desc)
            messages.success(request, 'Your payment was successful')
        except stripe.CardError as exc:
            messages.error(request, 'Payment error: %s' % exc.message)
            raise exc

class StripeCC(models.Model):
    """A CC on file from Stripe

    We only store the stripe token, the last 4 digits, and the card type
    so we do not need to be PCI compliant"""

    user = models.ForeignKey(User, unique=True)
    last4 = models.CharField(max_length=4)
    card_type = models.CharField(max_length=255)

    def __unicode__(self):
        return u"%s's %s ending in %s" % \
            (unicode(self.user).capitalize(), self.card_type, self.last4)


class Statistics(models.Model):
    """Nightly statistics"""

    date = models.DateField()

    total_requests = models.IntegerField()
    total_requests_success = models.IntegerField()
    total_requests_denied = models.IntegerField()
    total_pages = models.IntegerField()
    total_users = models.IntegerField()
    users_today = models.ManyToManyField(User)
    total_agencies = models.IntegerField()
    total_fees = models.IntegerField()

    class Meta:
        # pylint: disable-msg=R0903
        ordering = ['-date']
