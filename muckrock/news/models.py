"""
Models for the News application
"""

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.cache.utils import make_template_fragment_key
from django.core.urlresolvers import reverse
from django.db import models
from django.db.models import Prefetch

from datetime import datetime
from easy_thumbnails.fields import ThumbnailerImageField
from taggit.managers import TaggableManager

from muckrock.foia.models import FOIARequest
from muckrock.tags.models import TaggedItemBase
from muckrock.utils import get_image_storage


class ArticleQuerySet(models.QuerySet):
    """Object manager for news articles"""
    # pylint: disable=too-many-public-methods

    def get_published(self):
        """Get all published news articles"""
        return self.filter(publish=True, pub_date__lte=datetime.now())

    def get_drafts(self):
        """Get all draft news articles"""
        return self.filter(publish=False)

    def _prefetch_users(self, field):
        """Prefetch authors or editors"""
        return self.prefetch_related(
                Prefetch(field,
                    queryset=User.objects.select_related('profile')))

    def prefetch_authors(self):
        """Prefetch authors"""
        return self._prefetch_users('authors')

    def prefetch_editors(self):
        """Prefetch editors"""
        return self._prefetch_users('editors')


class Article(models.Model):
    """A news article"""

    pub_date = models.DateTimeField('Publish date', default=datetime.now)
    title = models.CharField(max_length=200)
    kicker = models.CharField(max_length=200, blank=True)
    slug = models.SlugField(unique=True,
            help_text='A "Slug" is a unique URL-friendly title for an object.')
    summary = models.TextField(help_text='A single paragraph summary or preview of the article.')
    body = models.TextField('Body text')
    authors = models.ManyToManyField(User, related_name='authored_articles')
    editors = models.ManyToManyField(
            User,
            related_name='edited_articles',
            blank=True,
            )
    publish = models.BooleanField(
        'Publish on site',
        default=False,
        help_text='Articles do not appear on the site until their publish date.'
    )
    foias = models.ManyToManyField(
        FOIARequest,
        related_name='articles',
        blank=True,
    )
    image = ThumbnailerImageField(
        upload_to='news_images/%Y/%m/%d',
        blank=True,
        null=True,
        resize_source={'size': (1600, 1200), 'crop': 'smart'},
        storage=get_image_storage(),
    )
    objects = ArticleQuerySet.as_manager()
    tags = TaggableManager(through=TaggedItemBase, blank=True)

    def __unicode__(self):
        return self.title

    def get_absolute_url(self):
        """The url for this object"""
        kwargs = {
            'year': self.pub_date.strftime('%Y'),
            'month': self.pub_date.strftime('%b').lower(),
            'day': self.pub_date.strftime('%d'),
            'slug': self.slug,
        }
        return reverse('news-detail', kwargs=kwargs)

    def save(self, *args, **kwargs):
        """Save the news article"""
        # epiceditor likes to stick non breaking spaces in here for some reason
        self.body = self.body.replace(u'\xa0', ' ')
        # invalidate the template cache for the page on a save
        if self.pk:
            cache.delete(make_template_fragment_key('article_detail', [self.pk]))
        super(Article, self).save(*args, **kwargs)

    def get_authors_names(self):
        """Get all authors names for a byline"""
        authors = list(self.authors.all())
        names = ', '.join(a.get_full_name() for a in authors[:-1])
        if names:
            names = ' & '.join([names, authors[-1].get_full_name()])
        else:
            names = authors[-1].get_full_name()
        return names

    class Meta:
        # pylint: disable=too-few-public-methods
        ordering = ['-pub_date']
        get_latest_by = 'pub_date'


class Photo(models.Model):
    """A photograph to embed in a news article"""

    image = models.ImageField(
            upload_to='news_photos/%Y/%m/%d',
            storage=get_image_storage(),
            )

    def __unicode__(self):
        return self.image.name
