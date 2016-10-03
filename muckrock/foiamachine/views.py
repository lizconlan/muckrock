"""
FOIAMachine views
"""

from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.generic import TemplateView, FormView, CreateView, DetailView, UpdateView
from django.utils.decorators import method_decorator

from django_hosts.resolvers import reverse

from muckrock.accounts.forms import RegisterForm
from muckrock.accounts.views import create_new_user
from muckrock.foiamachine.forms import FoiaMachineRequestForm
from muckrock.foiamachine.models import FoiaMachineRequest

class Homepage(TemplateView):
    """FOIAMachine homepage"""
    template_name = 'foiamachine/homepage.html'

    def dispatch(self, *args, **kwargs):
        """If the user is authenticated, redirect to their profile."""
        if self.request.user.is_authenticated():
            return redirect(reverse('profile', host='foiamachine'))
        return super(Homepage, self).dispatch(*args, **kwargs)


class Signup(FormView):
    """Signs up new users"""
    template_name = 'foiamachine/registration/signup.html'
    form_class = RegisterForm

    def get_success_url(self):
        return reverse('profile', host='foiamachine')

    def form_valid(self, form):
        """Create the user and sign them in."""
        user = create_new_user(self.request, form)
        return super(Signup, self).form_valid(form)


class Profile(TemplateView):
    """Detail for a user."""
    template_name = 'foiamachine/profile.html'

    def dispatch(self, *args, **kwargs):
        """If the user is unauthenticated, redirect them to the login view."""
        if self.request.user.is_anonymous():
            return redirect(reverse('login', host='foiamachine') +
                '?next=' + reverse('profile', host='foiamachine'))
        return super(Profile, self).dispatch(*args, **kwargs)


class FoiaMachineRequestCreateView(CreateView):
    """Create a new request."""
    form_class = FoiaMachineRequestForm
    template_name = 'foiamachine/foi/create.html'

    def dispatch(self, *args, **kwargs):
        """If the user is unauthenticated, redirect them to the login view."""
        if self.request.user.is_anonymous():
            return redirect(reverse('login', host='foiamachine') +
                '?next=' + reverse('foi-create', host='foiamachine'))
        return super(FoiaMachineRequestCreateView, self).dispatch(*args, **kwargs)

    def form_valid(self, form):
        """Create the request then redirect to it."""
        foi = form.save(commit=False)
        foi.user = self.request.user
        foi.save()
        return redirect(reverse('foi-detail', host='foiamachine', kwargs={
            'slug': foi.slug,
            'pk': foi.pk,
        }))


class FoiaMachineRequestDetailView(DetailView):
    """Show the detail of a FOIA Machine request."""
    model = FoiaMachineRequest
    template_name = 'foiamachine/foi/detail.html'


class FoiaMachineRequestUpdateView(UpdateView):
    """Update the information saved to a FOIA Machine request."""
    model = FoiaMachineRequest
    form_class = FoiaMachineRequestForm
    template_name = 'foiamachine/foi/update.html'

    def dispatch(self, *args, **kwargs):
        """Only the request's owner may update it."""
        foi = self.get_object()
        # Redirect logged out users to the login page
        if self.request.user.is_anonymous():
            return redirect(reverse('login', host='foiamachine') +
                '?next=' + reverse('foi-update', host='foiamachine', kwargs=kwargs))
        # Redirect non-owner users to the detail page
        if self.request.user != foi.user:
            return redirect(reverse('foi-detail', host='foiamachine', kwargs=kwargs))
        return super(FoiaMachineRequestUpdateView, self).dispatch(*args, **kwargs)

