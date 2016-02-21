"""
Models for the Task application
"""

from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Prefetch, Q

import actstream
from datetime import datetime
import email
import logging

from muckrock.agency.models import Agency, STALE_DURATION
from muckrock.foia.models import FOIACommunication, FOIAFile, FOIANote, FOIARequest, STATUS
from muckrock.jurisdiction.models import Jurisdiction
from muckrock.message.notifications import SupportNotification

def generate_status_action(foia):
    """Generate activity stream action for agency response"""
    if not foia.agency:
        return
    verbs = {
        'rejected': 'rejected',
        'done': 'completed',
        'partial': 'partially completed',
        'processed': 'acknowledged',
        'no_docs': 'has no responsive documents',
        'fix': 'requires fix',
        'payment': 'requires payment',
    }
    verb = verbs.get(foia.status, 'is processing')
    actstream.action.send(foia.agency, verb=verb, action_object=foia)

class TaskQuerySet(models.QuerySet):
    """Object manager for all tasks"""
    def get_unresolved(self):
        """Get all unresolved tasks"""
        return self.filter(resolved=False)

    def get_resolved(self):
        """Get all resolved tasks"""
        return self.filter(resolved=True)

    def filter_by_foia(self, foia, user):
        """
        Get tasks that relate to the provided FOIA request.
        If user is staff, get all tasks.
        If user is advanced, get response tasks.
        For all users, get new agency task.
        """
        # pylint:disable=no-self-use
        tasks = []
        # infer foia from communication
        communication_task_types = []
        if user.is_staff:
            communication_task_types.append(ResponseTask)
            communication_task_types.append(SnailMailTask)
            communication_task_types.append(FailedFaxTask)
        for task_type in communication_task_types:
            tasks += list(task_type.objects
                    .filter(communication__foia=foia)
                    .select_related('communication__foia', 'resolved_by')
                    .prefetch_related(
                        Prefetch('communication__files',
                            queryset=FOIAFile.objects.select_related('foia__jurisdiction')),
                        Prefetch('communication__foia__communications',
                            queryset=FOIACommunication.objects.order_by('-date'),
                            to_attr='reverse_communications'),
                        'communication__foia__communications__files',
                        )
                    )
        # these tasks have a direct foia attribute
        foia_task_types = [RejectedEmailTask, FlaggedTask, StatusChangeTask]
        if user.is_staff:
            for task_type in foia_task_types:
                tasks += list(task_type.objects
                        .filter(foia=foia)
                        .select_related('foia', 'resolved_by'))
        # try matching foia agency with task agency
        if foia.agency:
            tasks += list(NewAgencyTask.objects
                    .filter(agency=foia.agency)
                    .select_related('agency', 'resolved_by'))
        return tasks


class OrphanTaskQuerySet(models.QuerySet):
    """Object manager for orphan tasks"""
    def get_from_sender(self, sender):
        """Get all orphan tasks from a specific sender"""
        return self.filter(communication__priv_from_who__icontains=sender)


class Task(models.Model):
    """A base task model for fields common to all tasks"""
    date_created = models.DateTimeField(auto_now_add=True)
    date_done = models.DateTimeField(blank=True, null=True)
    resolved = models.BooleanField(default=False, db_index=True)
    assigned = models.ForeignKey(User, blank=True, null=True, related_name="assigned_tasks")
    resolved_by = models.ForeignKey(User, blank=True, null=True, related_name="resolved_tasks")

    objects = TaskQuerySet.as_manager()

    class Meta:
        ordering = ['date_created']

    def __unicode__(self):
        # pylint:disable=no-self-use
        return u'Task'

    def resolve(self, user=None):
        """Resolve the task"""
        self.resolved = True
        self.resolved_by = user
        self.date_done = datetime.now()
        self.save()
        logging.info('User %s resolved task %s', user, self.pk)


class GenericTask(Task):
    """A generic task"""
    # pylint: disable=no-member
    subject = models.CharField(max_length=255)
    body = models.TextField(blank=True)

    def __unicode__(self):
        return u'Generic Task'


class OrphanTask(Task):
    """A communication that needs to be approved before showing it on the site"""
    # pylint: disable=no-member
    type = 'OrphanTask'
    reasons = (('bs', 'Bad Sender'),
               ('ib', 'Incoming Blocked'),
               ('ia', 'Invalid Address'))
    reason = models.CharField(max_length=2, choices=reasons)
    communication = models.ForeignKey('foia.FOIACommunication')
    address = models.CharField(max_length=255)

    objects = OrphanTaskQuerySet.as_manager()
    template_name = 'task/orphan.html'

    def __unicode__(self):
        return u'Orphan Task'

    def move(self, foia_pks):
        """Moves the comm and creates a ResponseTask for it"""
        moved_comms = self.communication.move(foia_pks)
        for moved_comm in moved_comms:
            ResponseTask.objects.create(
                communication=moved_comm,
                created_from_orphan=True
            )
            moved_comm.make_sender_primary_contact()
        return

    def reject(self, blacklist=False):
        """If blacklist is true, should blacklist the sender's domain."""
        if blacklist:
            self.blacklist()
        return

    def get_sender_domain(self):
        """Gets the domain of the sender's email address."""
        _, email_address = email.utils.parseaddr(self.communication.priv_from_who)
        if '@' not in email_address:
            return None
        else:
            return email_address.split('@')[1]

    def blacklist(self):
        """Adds the communication's sender's domain to the email blacklist."""
        domain = self.get_sender_domain()
        if domain is None:
            return
        try:
            blacklist, _ = BlacklistDomain.objects.get_or_create(domain=domain)
        except BlacklistDomain.MultipleObjectsReturned:
            blacklist = BlacklistDomain.objects.filter(domain=domain).first()
        blacklist.resolve_matches()
        return


class SnailMailTask(Task):
    """A communication that needs to be snail mailed"""
    # pylint: disable=no-member
    type = 'SnailMailTask'
    categories = (
        ('a', 'Appeal'),
        ('n', 'New'),
        ('u', 'Update'),
        ('f', 'Followup'),
        ('p', 'Payment')
    )
    category = models.CharField(max_length=1, choices=categories)
    communication = models.ForeignKey('foia.FOIACommunication')
    user = models.ForeignKey(User, blank=True, null=True)
    amount = models.DecimalField(default=0.00, max_digits=8, decimal_places=2)

    def __unicode__(self):
        return u'Snail Mail Task'

    def set_status(self, status):
        """Set the status of the comm and FOIA affiliated with this task"""
        comm = self.communication
        comm.status = status
        comm.save()
        comm.foia.status = status
        comm.foia.save()
        comm.foia.update()

    def update_date(self):
        """Sets the date of the communication to today"""
        comm = self.communication
        comm.date = datetime.now()
        comm.save()
        comm.foia.update()

    def update_text(self, new_text):
        """Sets the body text of the communication"""
        comm = self.communication
        comm.communication = new_text
        comm.save()

    def record_check(self, number, user):
        """Records the check to a note on the request"""
        foia = self.communication.foia
        text = "A check (#%(number)d) of $%(amount).2f was mailed to the agency." % {
            'number': number,
            'amount': self.amount
        }
        note = FOIANote.objects.create(foia=foia, note=text, author=user)
        return note


class RejectedEmailTask(Task):
    """A FOIA request has had an outgoing email rejected"""
    type = 'RejectedEmailTask'
    categories = (('b', 'Bounced'), ('d', 'Dropped'))
    category = models.CharField(max_length=1, choices=categories)
    foia = models.ForeignKey('foia.FOIARequest', blank=True, null=True)
    email = models.EmailField(blank=True)
    error = models.TextField(blank=True)

    def __unicode__(self):
        return u'Rejected Email Task'

    def agencies(self):
        """Get the agencies who use this email address"""
        return Agency.objects.filter(Q(email__iexact=self.email) |
                                     Q(other_emails__icontains=self.email))

    def foias(self):
        """Get the FOIAs who use this email address"""
        return FOIARequest.objects\
                .filter(Q(email__iexact=self.email) |
                        Q(other_emails__icontains=self.email))\
                .filter(status__in=['ack', 'processed', 'appealing',
                                    'fix', 'payment'])


class StaleAgencyTask(Task):
    """An agency has gone stale"""
    type = 'StaleAgencyTask'
    agency = models.ForeignKey(Agency)

    def __unicode__(self):
        return u'Stale Agency Task'

    def resolve(self, user=None):
        """Mark the agency as stale when resolving"""
        self.agency.stale = False
        self.agency.save()
        super(StaleAgencyTask, self).resolve(user)

    def stale_requests(self):
        """Returns a list of stale requests associated with the task's agency"""
        requests = FOIARequest.objects.get_open().filter(agency=self.agency)
        stale_requests = []
        for foia_request in requests:
            if foia_request.latest_response() >= STALE_DURATION:
                stale_requests.append(foia_request)
        return requests

    def stalest_request(self):
        """Returns the stalest of all the stale requests"""
        stale_requests = self.stale_requests()
        stalest_request = stale_requests[0]
        for stale_request in stale_requests:
            if stale_request.latest_response() >= stalest_request.latest_response():
                stalest_request = stale_request
        return stalest_request

    def latest_response(self):
        """Returns the latest response from the agency"""
        all_requests = FOIARequest.objects.filter(agency=self.agency)
        latest_response = all_requests.first().last_response()
        for foia_request in all_requests:
            comm = foia_request.last_response()
            if comm.date > latest_response.date:
                latest_response = comm
        return latest_response

    def update_email(self, new_email, foia_list=None):
        """Updates the email on the agency and the provided requests."""
        self.agency.email = new_email
        self.agency.save()
        for foia in foia_list:
            foia.email = new_email
            foia.followup(automatic=True, show_all_comms=False)

class FlaggedTask(Task):
    """A user has flagged a request, agency or jurisdiction"""
    type = 'FlaggedTask'
    text = models.TextField()
    user = models.ForeignKey(User, blank=True, null=True)
    foia = models.ForeignKey('foia.FOIARequest', blank=True, null=True)
    agency = models.ForeignKey(Agency, blank=True, null=True)
    jurisdiction = models.ForeignKey(Jurisdiction, blank=True, null=True)

    def __unicode__(self):
        return u'Flagged Task'

    def flagged_object(self):
        """Return the object that was flagged (should only ever be one, and never none)"""
        if self.foia:
            return self.foia
        elif self.agency:
            return self.agency
        elif self.jurisdiction:
            return self.jurisdiction
        else:
            raise AttributeError('No flagged object.')

    def reply(self, text):
        """Send an email reply to the user that raised the flag."""
        support_email = SupportNotification(self.user, {'message': text, 'task': self})
        support_email.send()


class NewAgencyTask(Task):
    """A new agency has been created and needs approval"""
    type = 'NewAgencyTask'
    user = models.ForeignKey(User, blank=True, null=True)
    agency = models.ForeignKey(Agency)

    def __unicode__(self):
        return u'New Agency Task'

    def pending_requests(self):
        """Returns the requests to be acted on"""
        return FOIARequest.objects.filter(agency=self.agency).exclude(status='started')

    def approve(self):
        """Approves agency, resends pending requests to it"""
        self.agency.status = 'approved'
        self.agency.save()
        # resend the first comm of each foia associated to this agency
        for foia in self.pending_requests():
            comms = foia.communications.all()
            if comms.count():
                first_comm = comms[0]
                first_comm.resend(self.agency.get_email())

    def reject(self, replacement_agency):
        """Resends pending requests to replacement agency"""
        self.agency.status = 'rejected'
        self.agency.save()
        for foia in self.pending_requests():
            # first switch foia to use replacement agency
            foia.agency = replacement_agency
            foia.save()
            comms = foia.communications.all()
            if comms.count():
                first_comm = comms[0]
                first_comm.resend(replacement_agency.email)


class ResponseTask(Task):
    """A response has been received and needs its status set"""
    # pylint: disable=no-member
    type = 'ResponseTask'
    communication = models.ForeignKey('foia.FOIACommunication')
    created_from_orphan = models.BooleanField(default=False)
    # for predicting statuses
    predicted_status = models.CharField(max_length=10, choices=STATUS, blank=True, null=True)
    status_probability = models.IntegerField(blank=True, null=True)

    def __unicode__(self):
        return u'Response Task'

    def move(self, foia_pks):
        """Moves the associated communication to a new request"""
        return self.communication.move(foia_pks)

    def set_tracking_id(self, tracking_id):
        """Sets the tracking ID of the communication's request"""
        if type(tracking_id) is not type(unicode()):
            raise ValueError('Tracking ID should be a unicode string.')
        comm = self.communication
        if not comm.foia:
            raise ValueError('The task communication is an orphan.')
        foia = comm.foia
        foia.tracking_id = tracking_id
        foia.save()

    def set_status(self, status, set_foia=True):
        """Sets status of comm and foia, with option for only setting comm stats"""
        comm = self.communication
        # check that status is valid
        if status not in [status_set[0] for status_set in STATUS]:
            raise ValueError('Invalid status.')
        # save comm first
        comm.status = status
        comm.save()
        # save foia next, unless just updating comm status
        if set_foia:
            foia = comm.foia
            foia.status = status
            if status in ['rejected', 'no_docs', 'done', 'abandoned']:
                foia.date_done = comm.date
            foia.update()
            foia.save()
            logging.info('Request #%d status changed to "%s"', foia.id, status)
            generate_status_action(foia)

    def set_price(self, price):
        """Sets the price of the communication's request"""
        price = float(price)
        comm = self.communication
        if not comm.foia:
            raise ValueError('This tasks\'s communication is an orphan.')
        foia = comm.foia
        foia.price = price
        foia.save()

    def set_date_estimate(self, date_estimate):
        """Sets the estimated completion date of the communication's request."""
        foia = self.communication.foia
        foia.date_estimate = date_estimate
        foia.update()
        foia.save()
        logging.info('Estimated completion date set to %s', date_estimate)


class FailedFaxTask(Task):
    """A fax for this communication failed"""
    # pylint: disable=no-member
    type = 'FailedFaxTask'
    communication = models.ForeignKey('foia.FOIACommunication')

    def __unicode__(self):
        return u'Failed Fax Task'


class StatusChangeTask(Task):
    """A user has the status on a request"""
    type = 'StatusChangeTask'
    user = models.ForeignKey(User)
    old_status = models.CharField(max_length=255)
    foia = models.ForeignKey('foia.FOIARequest')

    def __unicode__(self):
        return u'Status Change Task'


class CrowdfundTask(Task):
    """Created when a crowdfund is finished"""
    crowdfund = models.ForeignKey('crowdfund.CrowdfundRequest')

    def __unicode__(self):
        return u'Crowdfund Task'


class GenericCrowdfundTask(Task):
    """Created when a crowdfund is finished"""
    type = 'GenericCrowdfundTask'
    content_type = models.ForeignKey(ContentType)
    object_id = models.PositiveIntegerField()
    crowdfund = GenericForeignKey('content_type', 'object_id')

    def __unicode__(self):
        return u'Crowdfund Task'


class MultiRequestTask(Task):
    """Created when a multirequest is created and needs approval."""
    type = 'MultiRequestTask'
    multirequest = models.ForeignKey('foia.FOIAMultiRequest')

    def __unicode__(self):
        return u'Multi-Request Task'


# Not a task, but used by tasks
class BlacklistDomain(models.Model):
    """A domain to be blacklisted from sending us emails"""
    domain = models.CharField(max_length=255)

    def __unicode__(self):
        return self.domain

    def resolve_matches(self):
        """Resolves any orphan tasks that match this blacklisted domain."""
        tasks_to_resolve = OrphanTask.objects.get_from_sender(self.domain)
        for task in tasks_to_resolve:
            task.resolve()
        return
