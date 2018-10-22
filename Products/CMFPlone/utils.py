# -*- coding: utf-8 -*-
from AccessControl import ClassSecurityInfo
from AccessControl import getSecurityManager
from AccessControl import ModuleSecurityInfo
from AccessControl import Unauthorized
from AccessControl.safe_formatter import SafeFormatter
from Acquisition import aq_base
from Acquisition import aq_get
from Acquisition import aq_inner
from Acquisition import aq_parent
from App.Common import package_home
from App.Dialogs import MessageDialog
from App.ImageFile import ImageFile
from cgi import escape
from DateTime import DateTime
from DateTime.interfaces import DateTimeError
from log import log
from log import log_deprecated
from log import log_exc
from OFS.CopySupport import CopyError
from os.path import abspath
from os.path import join
from os.path import split
from plone.i18n.normalizer.interfaces import IIDNormalizer
from plone.registry.interfaces import IRegistry
from Products.CMFCore.permissions import ManageUsers
from Products.CMFCore.utils import ToolInit as CMFCoreToolInit
from Products.CMFCore.utils import getToolByName
from Products.CMFPlone import PloneMessageFactory as _
from Products.CMFPlone.interfaces.controlpanel import IImagingSchema
from Products.CMFPlone.interfaces.siteroot import IPloneSiteRoot
from types import ClassType
from urlparse import urlparse
from webdav.interfaces import IWriteLock
from zExceptions import BadRequest
from zope import schema
from zope.component import getMultiAdapter
from zope.component import getUtility
from zope.component import providedBy
from zope.component import queryUtility
from zope.component.hooks import getSite
from zope.component.interfaces import ISite
from zope.deferredimport import deprecated as deprecated_import
from zope.deprecation import deprecated
from zope.i18n import translate
from zope.interface import implementedBy
from zope.publisher.interfaces.browser import IBrowserRequest

import json
import OFS
import pkg_resources
import re
import sys
import transaction
import warnings
import zope.interface


deprecated_import(
    "Import from Products.CMFPlone.defaultpage instead",
    isDefaultPage='Products.CMFPlone.defaultpage:check_default_page_via_view',
    getDefaultPage='Products.CMFPlone.defaultpage:get_default_page_via_view',
)

security = ModuleSecurityInfo()
security.declarePrivate('deprecated')
security.declarePrivate('abspath')
security.declarePrivate('re')
security.declarePrivate('OFS')
security.declarePrivate('aq_get')
security.declarePrivate('package_home')
security.declarePrivate('ImageFile')
security.declarePrivate('CMFCoreToolInit')
security.declarePrivate('transaction')
security.declarePrivate('zope')

# Canonical way to get at CMFPlone directory
PACKAGE_HOME = package_home(globals())
security.declarePrivate('PACKAGE_HOME')
WWW_DIR = join(PACKAGE_HOME, 'www')
security.declarePrivate('WWW_DIR')

# image-scaling
QUALITY_DEFAULT = 88
pattern = re.compile(r'^(.*)\s+(\d+)\s*:\s*(\d+)$')

# Log methods
log_exc  # pyflakes.  Keep this, as someone may import it.
_marker = []


def get_portal():
    """get the Plone portal object.

    It fetched w/o any further context by using the last registered site.
    So this work only after traversal time.
    """
    closest_site = getSite()
    if closest_site is not None:
        for potential_portal in closest_site.aq_chain:
            if IPloneSiteRoot in providedBy(potential_portal):
                return potential_portal


def parent(obj):
    return aq_parent(aq_inner(obj))


def createBreadCrumbs(context, request):
    view = getMultiAdapter((context, request), name='breadcrumbs_view')
    return view.breadcrumbs()


def createSiteMap(context, request, sitemap=False):
    view = getMultiAdapter((context, request), name='sitemap_builder_view')
    return view.siteMap()


def isIDAutoGenerated(context, id):
    # In 2.1 non-autogenerated is the common case, caught exceptions are
    # expensive, so let's make a cheap check first
    if id.count('.') < 2:
        return False

    pt = getToolByName(context, 'portal_types')
    portaltypes = pt.listContentTypes()
    portaltypes.extend([t.lower() for t in portaltypes])

    try:
        parts = id.split('.')
        random_number = parts.pop()
        date_created = parts.pop()
        obj_type = '.'.join(parts)
        type = ' '.join(obj_type.split('_'))
        # New autogenerated ids may have a lower case portal type
        if ((type in portaltypes or obj_type in portaltypes) and
                DateTime(date_created) and float(random_number)):
            return True
    except (ValueError, AttributeError, IndexError, DateTimeError):
        pass

    return False


def isExpired(content):
    """ Find out if the object is expired (copied from skin script) """

    expiry = None

    # NOTE: We also accept catalog brains as 'content' so that the
    # catalog-based folder_contents will work. It's a little magic, but
    # it works.

    # ExpirationDate should have an ISO date string, which we need to
    # convert to a DateTime

    # Try DC accessor first
    if base_hasattr(content, 'ExpirationDate'):
        expiry = content.ExpirationDate

    # Try the direct way
    if not expiry and base_hasattr(content, 'expires'):
        expiry = content.expires

    # See if we have a callable
    if safe_callable(expiry):
        expiry = expiry()

    # Convert to DateTime if necessary, ExpirationDate may return 'None'
    if expiry and expiry != 'None' and isinstance(expiry, basestring):
        expiry = DateTime(expiry)

    if isinstance(expiry, DateTime) and expiry.isPast():
        return 1
    return 0


def pretty_title_or_id(context, obj, empty_value=_marker):
    """Return the best possible title or id of an item, regardless
       of whether obj is a catalog brain or an object, but returning an
       empty title marker if the id is not set (i.e. it's auto-generated).
    """
    # if safe_hasattr(obj, 'aq_explicit'):
    #    obj = obj.aq_explicit
    # title = getattr(obj, 'Title', None)
    title = None
    if base_hasattr(obj, 'Title'):
        title = getattr(obj, 'Title', None)
    if safe_callable(title):
        title = title()
    if title:
        return title
    item_id = getattr(obj, 'getId', None)
    if safe_callable(item_id):
        item_id = item_id()
    if item_id and not isIDAutoGenerated(context, item_id):
        return item_id
    if empty_value is _marker:
        empty_value = getEmptyTitle(context)
    return empty_value


def getSiteEncoding(context):
    return 'utf-8'
deprecated('getSiteEncoding',
           ('`getSiteEncoding` is deprecated. Plone only supports UTF-8 '
            'currently. This method always returns "utf-8"'))


# XXX portal_utf8 and utf8_portal probably can go away
def portal_utf8(context, str, errors='strict'):
    # Test
    unicode(str, 'utf-8', errors)
    return str


# XXX this is the same method as above
def utf8_portal(context, str, errors='strict'):
    # Test
    unicode(str, 'utf-8', errors)
    return str


def getEmptyTitle(context, translated=True):
    """Returns string to be used for objects with no title or id"""
    # The default is an extra fancy unicode elipsis
    empty = unicode('\x5b\xc2\xb7\xc2\xb7\xc2\xb7\x5d', 'utf-8')
    if translated:
        if context is not None:
            if not IBrowserRequest.providedBy(context):
                context = aq_get(context, 'REQUEST', None)
        empty = translate('title_unset', domain='plone',
                          context=context, default=empty)
    return empty


def typesToList(context):
    registry = getUtility(IRegistry)
    return registry.get('plone.displayed_types', ())


def normalizeString(text, context=None, encoding=None):
    # The relaxed mode was removed in Plone 4.0. You should use either the url
    # or file name normalizer from the plone.i18n package instead.
    return queryUtility(IIDNormalizer).normalize(text)


class RealIndexIterator(object):
    """The 'real' version of the IndexIterator class, that's actually
    used to generate unique indexes.
    """
    __allow_access_to_unprotected_subobjects__ = 1

    def __init__(self, pos=0):
        self.pos = pos

    def next(self):
        result = self.pos
        self.pos = self.pos + 1
        return result


@security.private
class ToolInit(CMFCoreToolInit):

    def getProductContext(self, context):
        name = '_ProductContext__prod'
        return getattr(context, name, getattr(context, '__prod', None))

    def getPack(self, context):
        name = '_ProductContext__pack'
        return getattr(context, name, getattr(context, '__pack__', None))

    def getIcon(self, context, path):
        pack = self.getPack(context)
        icon = None
        # This variable is just used for the log message
        icon_path = path
        try:
            icon = ImageFile(path, pack.__dict__)
        except (IOError, OSError):
            # Fallback:
            # Assume path is relative to CMFPlone directory
            path = abspath(join(PACKAGE_HOME, path))
            try:
                icon = ImageFile(path, pack.__dict__)
            except (IOError, OSError):
                # if there is some problem loading the fancy image
                # from the tool then  tell someone about it
                log(('The icon for the product: %s which was set to: %s, '
                     'was not found. Using the default.' %
                     (self.product_name, icon_path)))
        return icon

    def initialize(self, context):
        # Wrap the CMFCore Tool Init method.
        CMFCoreToolInit.initialize(self, context)
        for tool in self.tools:
            # Get the icon path from the tool
            path = getattr(tool, 'toolicon', None)
            if path is not None:
                pc = self.getProductContext(context)
                if pc is not None:
                    pid = pc.id
                    name = split(path)[1]
                    icon = self.getIcon(context, path)
                    if icon is None:
                        # Icon was not found
                        return
                    icon.__roles__ = None
                    tool.icon = 'misc_/%s/%s' % (self.product_name, name)
                    misc = OFS.misc_.misc_
                    Misc = OFS.misc_.Misc_
                    if not hasattr(misc, pid):
                        setattr(misc, pid, Misc(pid, {}))
                    getattr(misc, pid)[name] = icon


def _createObjectByType(type_name, container, id, *args, **kw):
    """Create an object without performing security checks

    invokeFactory and fti.constructInstance perform some security checks
    before creating the object. Use this function instead if you need to
    skip these checks.

    This method uses
    CMFCore.TypesTool.FactoryTypeInformation._constructInstance
    to create the object without security checks.
    """
    id = str(id)
    typesTool = getToolByName(container, 'portal_types')
    fti = typesTool.getTypeInfo(type_name)
    if not fti:
        raise ValueError('Invalid type %s' % type_name)

    return fti._constructInstance(container, id, *args, **kw)


def safeToInt(value, default=0):
    """Convert value to integer or just return 0 if we can't

       >>> safeToInt(45)
       45

       >>> safeToInt("42")
       42

       >>> safeToInt("spam")
       0

       >>> safeToInt([])
       0

       >>> safeToInt(None)
       0

       >>> safeToInt(None, default=-1)
       -1
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

release_levels = ('alpha', 'beta', 'candidate', 'final')
rl_abbr = {'a': 'alpha', 'b': 'beta', 'rc': 'candidate'}


def versionTupleFromString(v_str):
    """Returns version tuple from passed in version string

        >>> versionTupleFromString('1.2.3')
        (1, 2, 3, 'final', 0)

        >>> versionTupleFromString('2.1-final1 (SVN)')
        (2, 1, 0, 'final', 1)

        >>> versionTupleFromString('3-beta')
        (3, 0, 0, 'beta', 0)

        >>> versionTupleFromString('2.0a3')
        (2, 0, 0, 'alpha', 3)

        >>> versionTupleFromString('foo') is None
        True
        """
    regex_str = "(^\d+)[.]?(\d*)[.]?(\d*)[- ]?(alpha|beta|candidate|final|a|b|rc)?(\d*)"  # noqa
    v_regex = re.compile(regex_str)
    match = v_regex.match(v_str)
    if match is None:
        v_tpl = None
    else:
        groups = list(match.groups())
        for i in (0, 1, 2, 4):
            groups[i] = safeToInt(groups[i])
        if groups[3] is None:
            groups[3] = 'final'
        elif groups[3] in rl_abbr.keys():
            groups[3] = rl_abbr[groups[3]]
        v_tpl = tuple(groups)
    return v_tpl


def getFSVersionTuple():
    """Returns Products.CMFPlone version tuple"""
    version = pkg_resources.get_distribution('Products.CMFPlone').version
    return versionTupleFromString(version)


def transaction_note(note):
    """Write human legible note"""
    T = transaction.get()
    if isinstance(note, unicode):
        # Convert unicode to a regular string for the backend write IO.
        # UTF-8 is the only reasonable choice, as using unicode means
        # that Latin-1 is probably not enough.
        note = note.encode('utf-8', 'replace')

    if (len(T.description) + len(note)) >= 65533:
        log('Transaction note too large omitting %s' % str(note))
    else:
        T.note(str(note))


def base_hasattr(obj, name):
    """Like safe_hasattr, but also disables acquisition."""
    return safe_hasattr(aq_base(obj), name)


def safe_hasattr(obj, name, _marker=object()):
    """Make sure we don't mask exceptions like hasattr().

    We don't want exceptions other than AttributeError to be masked,
    since that too often masks other programming errors.
    Three-argument getattr() doesn't mask those, so we use that to
    implement our own hasattr() replacement.
    """
    return getattr(obj, name, _marker) is not _marker


def safe_callable(obj):
    """Make sure our callable checks are ConflictError safe."""
    if safe_hasattr(obj, '__class__'):
        if safe_hasattr(obj, '__call__'):
            return True
        else:
            return isinstance(obj, ClassType)
    else:
        return callable(obj)


def safe_unicode(value, encoding='utf-8'):
    """Converts a value to unicode, even it is already a unicode string.

        >>> from Products.CMFPlone.utils import safe_unicode

        >>> safe_unicode('spam')
        u'spam'
        >>> safe_unicode(u'spam')
        u'spam'
        >>> safe_unicode(u'spam'.encode('utf-8'))
        u'spam'
        >>> safe_unicode('\xc6\xb5')
        u'\u01b5'
        >>> safe_unicode(u'\xc6\xb5'.encode('iso-8859-1'))
        u'\u01b5'
        >>> safe_unicode('\xc6\xb5', encoding='ascii')
        u'\u01b5'
        >>> safe_unicode(1)
        1
        >>> print safe_unicode(None)
        None
    """
    if isinstance(value, unicode):
        return value
    elif isinstance(value, basestring):
        try:
            value = unicode(value, encoding)
        except (UnicodeDecodeError):
            value = value.decode('utf-8', 'replace')
    return value


def safe_encode(value, encoding='utf-8'):
    """Convert unicode to the specified encoding.
    """
    if isinstance(value, unicode):
        value = value.encode(encoding)
    return value


def tuplize(value):
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _detuplize(interfaces, append):
    if isinstance(interfaces, (tuple, list)):
        for sub in interfaces:
            _detuplize(sub, append)
    else:
        append(interfaces)


def flatten(interfaces):
    flattened = []
    _detuplize(interfaces, flattened.append)
    return tuple(flattened)


def directlyProvides(obj, *interfaces):
    return zope.interface.directlyProvides(obj, *interfaces)


def classImplements(class_, *interfaces):
    return zope.interface.classImplements(class_, *interfaces)


def classDoesNotImplement(class_, *interfaces):
    # convert any Zope 2 interfaces to Zope 3 using fromZ2Interface
    interfaces = flatten(interfaces)
    implemented = implementedBy(class_)
    for iface in interfaces:
        implemented = implemented - iface
    return zope.interface.classImplementsOnly(class_, implemented)


def webdav_enabled(obj, container):
    """WebDAV check used in externalEditorEnabled.py"""

    # Object implements lock interface
    if IWriteLock.providedBy(obj):
        return True

    return False


# Copied 'unrestricted_rename' from ATCT migrations to avoid
# a dependency.


security.declarePrivate('sys')


def _unrestricted_rename(container, id, new_id):
    """Rename a particular sub-object

    Copied from OFS.CopySupport

    Less strict version of manage_renameObject:
        * no write lock check
        * no verify object check from PortalFolder so it's allowed to rename
          even unallowed portal types inside a folder
    """
    try:
        container._checkId(new_id)
    except:
        raise CopyError(MessageDialog(
            title='Invalid Id',
            message=sys.exc_info()[1],
            action='manage_main'))
    ob = container._getOb(id)
    if not ob.cb_isMoveable():
        raise CopyError('Not Supported {}'.format(escape(id)))
    try:
        ob._notifyOfCopyTo(container, op=1)
    except:
        raise CopyError(MessageDialog(
            title='Rename Error',
            message=sys.exc_info()[1],
            action='manage_main'))
    container._delObject(id)
    ob = aq_base(ob)
    ob._setId(new_id)

    # Note - because a rename always keeps the same context, we
    # can just leave the ownership info unchanged.
    container._setObject(new_id, ob, set_owner=0)
    ob = container._getOb(new_id)
    ob._postCopy(container, op=1)

    return None


# Copied '_getSecurity' from Archetypes.utils to avoid a dependency.

security.declarePrivate('ClassSecurityInfo')


def _getSecurity(klass, create=True):
    # a Zope 2 class can contain some attribute that is an instance
    # of ClassSecurityInfo. Zope 2 scans through things looking for
    # an attribute that has the name __security_info__ first
    info = vars(klass)
    security = None
    for k, v in info.items():
        if hasattr(v, '__security_info__'):
            security = v
            break
    # Didn't found a ClassSecurityInfo object
    if security is None:
        if not create:
            return None
        # we stuff the name ourselves as __security__, not security, as this
        # could theoretically lead to name clashes, and doesn't matter for
        # zope 2 anyway.
        security = ClassSecurityInfo()
        setattr(klass, '__security__', security)
    return security


def isLinked(obj):
    """Check if the given content object is linked from another one."""
    log_deprecated("utils.isLinked is deprecated, you should use plone.app.linkintegrity.utils.hasIncomingLinks")  # noqa
    from plone.app.linkintegrity.utils import hasIncomingLinks
    return hasIncomingLinks(obj)


def set_own_login_name(member, loginname):
    """Allow the user to set his/her own login name.

    If you have the Manage Users permission, you can update the login
    name of another member too, though the name of this function is a
    bit weird then.  Historical accident.
    """
    pas = getToolByName(member, 'acl_users')
    mt = getToolByName(member, 'portal_membership')
    if member.getId() == mt.getAuthenticatedMember().getId():
        pas.updateOwnLoginName(loginname)
        return
    secman = getSecurityManager()
    if not secman.checkPermission(ManageUsers, member):
        raise Unauthorized('You can only change your OWN login name.')
    pas.updateLoginName(member.getId(), loginname)


def ajax_load_url(url):
    if url and 'ajax_load' not in url:
        sep = '?' in url and '&' or '?'  # url parameter seperator
        url = '%s%sajax_load=1' % (url, sep)
    return url


def validate_json(value):
    warnings.warn(
        'Moved to the only place where it was used in order to avoid circular '
        'imports between ./interfaces/* and ./utils. Now relocated to '
        '"./interfaces/controlpanel.py"',
        DeprecationWarning)
    try:
        json.loads(value)
    except ValueError, exc:
        class JSONError(schema.ValidationError):
            __doc__ = _(u"Must be empty or a valid JSON-formatted "
                        u"configuration – ${message}.", mapping={
                            'message': unicode(exc)})

        raise JSONError(value)

    return True


def bodyfinder(text):
    """ Return body or unchanged text if no body tags found.

    Always use html_headcheck() first.
    """
    lowertext = text.lower()
    bodystart = lowertext.find('<body')
    if bodystart == -1:
        return text
    bodystart = lowertext.find('>', bodystart) + 1
    if bodystart == 0:
        return text
    bodyend = lowertext.rfind('</body>', bodystart)
    if bodyend == -1:
        return text
    return text[bodystart:bodyend]


def getAllowedSizes():
    registry = queryUtility(IRegistry)
    if not registry:
        return None
    settings = registry.forInterface(
        IImagingSchema, prefix="plone", check=False)
    if not settings.allowed_sizes:
        return None
    sizes = {}
    for line in settings.allowed_sizes:
        line = line.strip()
        if line:
            name, width, height = pattern.match(line).groups()
            name = name.strip().replace(' ', '_')
            sizes[name] = int(width), int(height)
    return sizes


def getQuality():
    registry = queryUtility(IRegistry)
    if registry:
        settings = registry.forInterface(
            IImagingSchema, prefix="plone", check=False)
        return settings.quality or QUALITY_DEFAULT
    return QUALITY_DEFAULT


def getRetinaScales():
    warnings.warn(
        'use getHighPixelDensityScales instead',
        DeprecationWarning)
    return getHighPixelDensityScales()

def getHighPixelDensityScales():
    from plone.namedfile.utils import getHighPixelDensityScales as func
    return func()


def getSiteLogo(site=None):
    from Products.CMFPlone.interfaces import ISiteSchema
    from plone.formwidget.namedfile.converter import b64decode_file
    if site is None:
        site = getSite()
    registry = getUtility(IRegistry)
    settings = registry.forInterface(ISiteSchema, prefix="plone", check=False)
    site_url = site.absolute_url()

    if getattr(settings, 'site_logo', False):
        filename, data = b64decode_file(settings.site_logo)
        return '{}/@@site-logo/{}'.format(
            site_url, filename)
    else:
        return '%s/logo.png' % site_url


def get_installer(context, request=None):
    if request is None:
        request = aq_get(context, 'REQUEST', None)
    view = getMultiAdapter((context, request), name='installer')
    return view


def get_top_request(request):
    """Get highest request from a subrequest.
    """

    def _top_request(req):
        parent_request = req.get('PARENT_REQUEST', None)
        return _top_request(parent_request) if parent_request else req
    return _top_request(request)


def get_top_site_from_url(context, request):
    """Find the top-most site, which is still in the url path.

    If the current context is within a subsite within a PloneSiteRoot and no
    virtual hosting is in place, the PloneSiteRoot is returned.
    When at the same context but in a virtual hosting environment with the
    virtual host root pointing to the subsite, it returns the subsite instead
    the PloneSiteRoot.

    For this given content structure:

    /Plone/Subsite

    It should return the following in these cases:

    - No virtual hosting, URL path: /Plone, Returns: Plone Site
    - No virtual hosting, URL path: /Plone/Subsite, Returns: Plone
    - Virtual hosting roots to Subsite, URL path: /, Returns: Subsite
    """
    site = getSite()
    try:
        url_path = urlparse(context.absolute_url()).path.split('/')
        for idx in range(len(url_path)):
            _path = '/'.join(url_path[:idx + 1]) or '/'
            site_path = request.physicalPathFromURL(_path)
            site_path = safe_encode('/'.join(site_path)) or '/'
            _site = context.restrictedTraverse(site_path)
            if ISite.providedBy(_site):
                break
        if _site:
            site = _site
    except (ValueError, AttributeError):
        # On error, just return getSite.
        # Refs: https://github.com/plone/plone.app.content/issues/103
        # Also, TestRequest doesn't have physicalPathFromURL
        pass
    return site


def _safe_format(inst, method):
    """Use our SafeFormatter that uses guarded_getattr for attribute access.

    This is for use with AccessControl.allow_type,
    as we do in CMFPlone/__init__.py.
    """
    return SafeFormatter(inst).safe_format


SIZE_CONST = {'KB': 1024, 'MB': 1024 * 1024, 'GB': 1024 * 1024 * 1024}
SIZE_ORDER = ('GB', 'MB', 'KB')


def human_readable_size(size):
    """ Get a human readable size string. """
    smaller = SIZE_ORDER[-1]

    # if the size is a float, then make it an int
    # happens for large files
    try:
        size = int(size)
    except (ValueError, TypeError):
        pass

    if not size:
        return '0 %s' % smaller

    if isinstance(size, (int, long)):
        if size < SIZE_CONST[smaller]:
            return '1 %s' % smaller
        for c in SIZE_ORDER:
            if size // SIZE_CONST[c] > 0:
                break
        return '%.1f %s' % (float(size / float(SIZE_CONST[c])), c)
    return size


def check_id(
        context, id=None, required=0, alternative_id=None, contained_by=None,
        **kwargs):
    """Test an id to make sure it is valid.

    Returns an error message if the id is bad or None if the id is good.

    In Plone 5.2, this function will replace
    Products/CMFPlone/skins/plone_scripts/check_id.py.
    But here in Plone 5.1, the function calls that same script,
    so that there should be no subtle differences with permissions.
    See https://github.com/plone/Products.CMFPlone/issues/2582

    For more info on the keyword arguments, see that script.

    We need to fall back to a basic check though, otherwise
    several tests that rely on this fallback will fail,
    for example simple content added in a way where the script is
    not available.  Several packages have their own fallback code
    for the case that 'check_id' does not exist:

    - Products.Archetypes and Products.ATContentTypes both simply check if
      id is in parent.objectIds().
    - plone.app.content tries parent._checkId(newid) from OFS.ObjectManager
      and catches a possible BadRequest exception to return True instead.
      This method checks for stuff like not allowing '..' as name,
      or names starting with an underscore.  This includes a check for
      an existing item when called with allow_dup=False.
    - Products.validation has an IdValidator which disallows a space in the id,
      checks if the id is given to a different object already,
      and calls ObjectManager.checkValidId, which is the same as _checkId.

    Note that Products.validation is the only one that needs to
    do special stuff for checking if the conflicting item is the same as
    the current item being edited.  All others are about adding a new one.

    We do a fallback that should cover all these cases.
    """
    script = getattr(context, 'check_id', None)
    if script is not None:
        # We have found Products/CMFPlone/skins/plone_scripts/check_id.py
        # or an override.  This is the expected standard case.
        return script(
            id=id, required=required, alternative_id=alternative_id,
            contained_by=contained_by,
            **kwargs)
    if contained_by is None:
        contained_by = aq_parent(aq_inner(context))
    if contained_by is None:
        return
    # Check for existence.
    if (id in contained_by.objectIds() and
            getattr(aq_base(contained_by), id) is not aq_base(context)):
        return _(u'There is already an item named ${name} in this folder.',
                  mapping={u'name': safe_unicode(id)})
    # The container may have the _checkId method from OFS or plone.folder.
    # We use this only to check for invalid characters, not for duplicates,
    # because we did that already.
    script = getattr(contained_by, '_checkId', None)
    if script is not None:
        try:
            return contained_by._checkId(id, allow_dup=True)
        except BadRequest as exc:
            return str(exc)
        return
