
from __future__ import with_statement
#from functools import lru_cache
from functools32 import lru_cache
from simpledate.utils import HashableDict
from itertools import imap

try:
    from thread import allocate_lock as _thread_allocate_lock
except ImportError:
    from _dummy_thread import allocate_lock as _thread_allocate_lock
from _strptime import LocaleTime, _calc_julian_from_U_or_W
from collections import defaultdict
from datetime import date
import time
from re import sub, escape, compile, IGNORECASE


# extend the usual date parsing with:
# - optional matching by adding a trailing %?
# - more catholic matching with a leading %!
# - nestable grouping and alternatives as %(A%|B%|C%)
# - generation of the "equivalent format" for display after parsing

# so the following are similar:
#   ISO_8601 = add_timezone('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d', '%Y')
#   %Y%(-%m%(-%d%(%( %|T%)%H:%M%(:%S%(.%f%)%?%)%?%)%?%)%?%)%? %(%!Z%|%z%)
# and we also support, via `invert`, the easier-to-read:
#   Y(-m(-d(( |%T)H:M(:S(.f)?)?)?)?)? (!Z|z)


def tokenizer(fmt):
    u'''
    Split a format into a series of tokens, adding parens for optional values.

    For example,
      '%(%H:%)%?%M %!Z%?'
    will become
      '%(', '%H', ':', '%)', '%?', '%M', ' ', '%(', '%!Z', '%)', '%?'
    '''

    i = 0
    n = len(fmt)

    while i < n:
        j = i + 1

        # if we have a symbol, include that
        if fmt[i] == u'%':
            j += 1
            if j > n:
                raise ValueError(u'Incomplete token - nothing follows %')

            # include a ! prefix
            if fmt[j-1] == u'!':
                j += 1
                if j > n:
                    raise ValueError(u'Incomplete token - nothing follows %!')

        # if we have a trailing ? then enclose anything not in parens so
        # that we generate the regexp marker to test for inclusion
        optional = j + 1 < n and fmt[j:j+2] == u'%?'
        single = fmt[i:j] != u'%)'
        if optional and single:
            yield u'%('

        # the token itself
        yield fmt[i:j]

        # additional tokens to handle optional values as above
        if optional:
            if single:
                yield u'%)'
            yield u'%?'
            j += 2

        i = j


def _to_regexp(fmt, to_regex=None, to_write=None):
    u'''
    Given a format, construct the equivalent regexp (and compile it) and
    the information needed to reconstruct a matching template after use.

    The reconstruction works by embedding empty matches in the regexp that
    record which parts of the expression were matched.  For example, a
    template like
      %(%H:%)%?%M
    is translated to
      ((?P<G1>)(?P<H>2[0-3]|[0-1]\d|\d)[^\w]+)(?P<M>[0-5]\d|\d)
    where the (?P<G1>) defines a group, named G1, that is defined only if
    hours are matched.  The reconstruction dictionary looks like:
      {'G0': '%G1%%M', 'G1': '%H:'}
    and reconstruction starts with G0.  If G1 was matched, then %G1% is
    substituted with the given reconstruction (and we repeat); if it was
    not matched then %G1% is simply dropped.
    '''

    if to_regex is None: to_regex = DEFAULT_TO_REGEX
    if to_write is None: to_write = DEFAULT_TO_WRITE

    # escape things that are related to regexps
    fmt = sub(ur'([\^$*+?\(\){}\[\]|])(?<!%.)', ur'\\\1', fmt)
    fmt = sub(ur'([\.])(?<!%!.)', ur'\\\1', fmt)

    # we build a set of templates that can be used to construct the pattern
    # that would match the data.  we do this by tracking whether each group
    # is matched (by adding a unique name that matches the empty string) and
    # substituting the template for that group when it does (that comes later -
    # here we're just constructing the templates).  see the tests for
    # examples that might help clarify how it works.
    count = 0  # latest group
    stack = [0]  # nested groups
    rebuild = defaultdict(lambda: u'')  # group substitutions

    _to_regexp.regex = u''
    tokens = tokenizer(fmt)

    def append(token, write=None):
        #nonlocal regex
        _to_regexp.regex += to_regex.get(token, token)
        if write is None:
            write = token
        rebuild[u'G%d' % stack[-1]] += to_write.get(write, write)

    try:
        while True:
            token = tokens.next()
            append(token)
            if token == u'%(':
                count += 1
                append(u'((?P<G%d>)' % count, u'%%G%d%%' % count)
                stack.append(count)
            elif token == u'%|':
                if not stack.pop():
                    raise ValueError(u'Unexpected %| - must be within %(...%)')
                count += 1
                append(u'|(?P<G%d>)' % count, u'%%G%d%%' % count)
                stack.append(count)
            elif token == u'%)':
                if not stack.pop():
                    raise ValueError(u'Unmatched %)')
                append(u')', u'')
    except StopIteration:
        pass
    if stack != [0]:
        raise ValueError(u'Unmatched %(')

    return _to_regexp.regex, rebuild, compile(_to_regexp.regex, IGNORECASE)


TAG = compile(ur'(?:^|[^%])%(G\d+)%')

def reconstruct(rebuild, found_dict):
    u'''
    Implement the reconstruction described above, using the rebuild dictionary
    and the group information from a particular match.
    '''
    fmt = rebuild[u'G0']
    while True:
        match = TAG.search(fmt)
        if not match:
            return sub(ur'\\(.)', ur'\1', fmt)
        index = match.group(1)
        if found_dict.get(index) is None:
            replacement = u''
        else:
            replacement = rebuild[index]
        fmt = fmt[:match.start(1)-1] + replacement + fmt[match.end(1)+1:]


LOCALE_TIME = LocaleTime()


def seq_to_re(to_convert, directive):
    u'''Copied from strptime method'''
    to_convert = sorted(to_convert, key=len, reverse=True)
    for value in to_convert:
        if value != u'':
            break
    else:
        return u''
    regex = u'|'.join(escape(stuff) for stuff in to_convert)
    regex = u'(?P<%s>%s' % (directive, regex)
    return u'%s)' % regex


WEEK_NUMBER = lambda x: ur'(?P<%s>5[0-3]|[0-4]\d|\d)' % x
WORD = lambda x: ur'(?P<%s>(?:\w(?<=[^\d_]))+)' % x
SYMBOL = ur'\W+'


# these are the definitions used in the standard Python implementation
# (use hashable dict for cache around _to_regex).

BASE_TO_REGEX = HashableDict({
    u' ': u'\s+',
    u'%a': seq_to_re(LOCALE_TIME.a_weekday, u'a'),
    u'%A': seq_to_re(LOCALE_TIME.f_weekday, u'A'),
    u'%b': seq_to_re(LOCALE_TIME.a_month[1:], u'b'),
    u'%B': seq_to_re(LOCALE_TIME.f_month[1:], u'B'),
    u'%d': ur'(?P<d>3[0-1]|[1-2]\d|0[1-9]|[1-9]| [1-9])',
    u'%f': ur'(?P<f>[0-9]{1,6})',
    u'%H': ur'(?P<H>2[0-3]|[0-1]\d|\d)',
    u'%I': ur'(?P<I>1[0-2]|0[1-9]|[1-9])',
    u'%j': ur'(?P<j>36[0-6]|3[0-5]\d|[1-2]\d\d|0[1-9]\d|00[1-9]|[1-9]\d|0[1-9]|[1-9])',
    u'%m': ur'(?P<m>1[0-2]|0[1-9]|[1-9])',
    u'%p': seq_to_re(LOCALE_TIME.am_pm, u'p'),
    u'%M': ur'(?P<M>[0-5]\d|\d)',
    u'%S': ur'(?P<S>6[0-1]|[0-5]\d|\d)',
    u'%U': WEEK_NUMBER(u'U'),
    u'%w': ur'(?P<w>[0-6])',
    u'%W': WEEK_NUMBER(u'W'),
    u'%y': ur'(?P<y>\d\d)',
    u'%Y': ur'(?P<Y>\d\d\d\d)',
    u'%z': ur'(?P<z>[+-]\d\d[0-5]\d)',
    u'%Z': ur'(?P<Z>[A-Z][A-Za-z_]+(?:/[A-Z][A-Za-z_]+)+|[A-Z]{3,})',
    u'%%': u'%',
})

PYTHON_TO_REGEX= HashableDict(BASE_TO_REGEX)
PYTHON_TO_REGEX.update({
    u'%c': _to_regexp(LOCALE_TIME.LC_date_time, BASE_TO_REGEX, {})[0],
    u'%x': _to_regexp(LOCALE_TIME.LC_date, BASE_TO_REGEX, {})[0],
    u'%X': _to_regexp(LOCALE_TIME.LC_time, BASE_TO_REGEX, {})[0],
})


# extra definitions allowing more flexible matching.

FLEXIBLE_REGEX = HashableDict({
    u'%! ': SYMBOL,  # these match any symbol but will write as the name
    u'%!:': SYMBOL,
    u'%!.': SYMBOL,
    u'%!,': SYMBOL,
    u'%!-': SYMBOL,
    u'%!/': SYMBOL,
    u'%!a': WORD(u'a'),  # match any word, but write from local
    u'%!A': WORD(u'A'),
    u'%!b': WORD(u'b'),
    u'%!B': WORD(u'B'),
    u'%!d': ur'(?P<d>3[0-1]|[1-2]\d|0[1-9])',  # 2 digits only
    u'%!H': ur'(?P<H>2[0-3]|[0-1]\d)',         # 2 digits only
    u'%!m': ur'(?P<m>1[0-2]|0[1-9])',          # 2 digits only
    u'%!M': ur'(?P<M>[0-5]\d)',                # 2 digits only
    u'%!S': ur'(?P<S>6[0-1]|[0-5]\d)',         # 2 digits only
    u'%!y': ur'(?P<y50>\d\d)',                 # switch at 1950
    u'%!z': ur'(?P<z>[+-]\d\d\W?[0-5]\d)',      # character between h + m
    u'%!Z': ur'(?P<Z>[A-Z][A-Za-z_]+(?:/[A-Z][A-Za-z_]+)+|[A-Z]{3,}|Z)',
    u'%?': u'?',
})

HIDE_CHOICES = HashableDict({
    u'%(': u'',
    u'%|': u'',
    u'%)': u'',
})

DEFAULT_TO_REGEX = HashableDict(PYTHON_TO_REGEX)
DEFAULT_TO_REGEX.update(FLEXIBLE_REGEX)
DEFAULT_TO_REGEX.update(HIDE_CHOICES)


def auto_convert(key):
    u'''
    Infer transformations needed to generate a write template from an
    extended read template by using the information in the transformations
    needed to generate a regex from an extended read template.
    '''
    symbol = key[0] + key[-1]
    # if it's know to python, return it
    if symbol in PYTHON_TO_REGEX:
        return key, symbol
    # if it's an extended match, return the unextended version
    elif len(key) == 3 and key[0:2] == u'%!':
        return key, key[-1]
    # otherwise, remove it
    else:
        return key, u''

DEFAULT_TO_WRITE = dict(imap(auto_convert, FLEXIBLE_REGEX.keys()))
DEFAULT_TO_WRITE.update(HIDE_CHOICES)


# thread-safe caching

CACHE_MAX_SIZE = 100
_CACHE_LOCK = _thread_allocate_lock()
_CACHED_REGEXP = lru_cache(maxsize=CACHE_MAX_SIZE)(_to_regexp)

def to_regexp(fmt, substitutions=None):
    with _CACHE_LOCK:
        return _CACHED_REGEXP(fmt, substitutions)


# the main logic to construct a date/time from the matched data, lifted
# verbatim from the python source.  the only changes are to check that
# a group has actually matched (since now some may be optional), the
# modified handling for y50, and uzing -ve indices for z minutes.

def to_time_tuple(found_dict):
    u'''Closely based on _strptime in standard Python.'''
    year = None
    month = day = 1
    hour = minute = second = fraction = 0
    tz = -1
    tzoffset = None
    # Default to -1 to signify that values not known; not critical to have
    week_of_year = -1
    week_of_year_start = -1
    # weekday and julian defaulted to -1 so as to signal need to calculate
    weekday = julian = -1
    for group_key in (key for key in found_dict.keys() if found_dict[key] is not None):
        # Directives not explicitly handled below:
        #   c, x, X
        #      handled by making out of other directives
        #   U, W
        #      worthless without day of the week
        if group_key == u'y':
            year = int(found_dict[u'y'])
            # Open Group specification for strptime() states that a %y
            #value in the range of [00, 68] is in the century 2000, while
            #[69,99] is in the century 1900
            if year <= 68:
                year += 2000
            else:
                year += 1900
        elif group_key == u'y50':
            year = int(found_dict[u'y50'])
            # ASN.1 / RFC 3852
            if year < 50:
                year += 2000
            else:
                year += 1900
        elif group_key == u'Y':
            year = int(found_dict[u'Y'])
        elif group_key == u'm':
            month = int(found_dict[u'm'])
        elif group_key == u'B':
            month = LOCALE_TIME.f_month.index(found_dict[u'B'].lower())
        elif group_key == u'b':
            month = LOCALE_TIME.a_month.index(found_dict[u'b'].lower())
        elif group_key == u'd':
            day = int(found_dict[u'd'])
        elif group_key == u'H':
            hour = int(found_dict[u'H'])
        elif group_key == u'I':
            hour = int(found_dict[u'I'])
            ampm = found_dict.get(u'p', u'').lower()
            # If there was no AM/PM indicator, we'll treat this like AM
            if ampm in (u'', LOCALE_TIME.am_pm[0]):
                # We're in AM so the hour is correct unless we're
                # looking at 12 midnight.
                # 12 midnight == 12 AM == hour 0
                if hour == 12:
                    hour = 0
            elif ampm == LOCALE_TIME.am_pm[1]:
                # We're in PM so we need to add 12 to the hour unless
                # we're looking at 12 noon.
                # 12 noon == 12 PM == hour 12
                if hour != 12:
                    hour += 12
        elif group_key == u'M':
            minute = int(found_dict[u'M'])
        elif group_key == u'S':
            second = int(found_dict[u'S'])
        elif group_key == u'f':
            s = found_dict[u'f']
            # Pad to always return microseconds.
            s += u"0" * (6 - len(s))
            fraction = int(s)
        elif group_key == u'A':
            weekday = LOCALE_TIME.f_weekday.index(found_dict[u'A'].lower())
        elif group_key == u'a':
            weekday = LOCALE_TIME.a_weekday.index(found_dict[u'a'].lower())
        elif group_key == u'w':
            weekday = int(found_dict[u'w'])
            if weekday == 0:
                weekday = 6
            else:
                weekday -= 1
        elif group_key == u'j':
            julian = int(found_dict[u'j'])
        elif group_key in (u'U', u'W'):
            week_of_year = int(found_dict[group_key])
            if group_key == u'U':
                # U starts week on Sunday.
                week_of_year_start = 6
            else:
                # W starts week on Monday.
                week_of_year_start = 0
        elif group_key == u'z':
            z = found_dict[u'z']
            tzoffset = int(z[1:3]) * 60 + int(z[-2:])
            if z.startswith(u"-"):
                tzoffset = -tzoffset
        elif group_key == u'Z':
            # Since -1 is default value only need to worry about setting tz if
            # it can be something other than -1.
            found_zone = found_dict[u'Z'].lower()
            for value, tz_values in enumerate(LOCALE_TIME.timezone):
                if found_zone in tz_values:
                    # Deal with bad locale setup where timezone names are the
                    # same and yet time.daylight is true; too ambiguous to
                    # be able to tell what timezone has daylight savings
                    if (time.tzname[0] == time.tzname[1] and
                       time.daylight and found_zone not in (u"utc", u"gmt")):
                        break
                    else:
                        tz = value
                        break
    leap_year_fix = False
    if year is None and month == 2 and day == 29:
        year = 1904  # 1904 is first leap year of 20th century
        leap_year_fix = True
    elif year is None:
        year = 1900
    # If we know the week of the year and what day of that week, we can figure
    # out the Julian day of the year.
    if julian == -1 and week_of_year != -1 and weekday != -1:
        week_starts_Mon = True if week_of_year_start == 0 else False
        julian = _calc_julian_from_U_or_W(year, week_of_year, weekday,
                                            week_starts_Mon)
    # Cannot pre-calculate date() since can change in Julian
    # calculation and thus could have different value for the day of the week
    # calculation.
    if julian == -1:
        # Need to add 1 to result since first day of the year is 1, not 0.
        julian = date(year, month, day).toordinal() - \
                  date(year, 1, 1).toordinal() + 1
    else:  # Assume that if they bothered to include Julian day it will
           # be accurate.
        datetime_result = date.fromordinal((julian - 1) + date(year, 1, 1).toordinal())
        year = datetime_result.year
        month = datetime_result.month
        day = datetime_result.day
    if weekday == -1:
        weekday = date(year, month, day).weekday()
    # Add timezone info
    tzname = found_dict.get(u'Z')
    if tzoffset is not None:
        gmtoff = tzoffset * 60
    else:
        gmtoff = None

    if leap_year_fix:
        # the caller didn't supply a year but asked for Feb 29th. We couldn't
        # use the default of 1900 for computations. We set it back to ensure
        # that February 29th is smaller than March 1st.
        year = 1900

    return (year, month, day,
            hour, minute, second,
            weekday, julian, tz, tzname, gmtoff), fraction


def strptime(data_string, format=u"%a %b %d %H:%M:%S %Y"):
    u'''
    Parse the input and return date/time tuple, fractional seconds, and
    a format that matched the input.
    '''

    for index, arg in enumerate([data_string, format]):
        if not isinstance(arg, unicode):
            msg = u"strptime() argument {} must be str, not {}"
            raise TypeError(msg.format(index, type(arg)))

    _, rebuild, format_regex = to_regexp(format)
    found = format_regex.match(data_string)
    if not found:
        raise ValueError(u"time data %r does not match format %r" %
                         (data_string, format))
    if len(data_string) != found.end():
        raise ValueError(u"unconverted data remains: %s" %
                          data_string[found.end():])

    date_time, fraction = to_time_tuple(found.groupdict())
    write_format = reconstruct(rebuild, found.groupdict())

    return date_time, fraction, write_format


def _strip(fmt, to_write=DEFAULT_TO_WRITE):
    u'''
    Remove extensions from  a format, taking the first choice and including
    optional parts.
    '''
    choice = []
    for tok in tokenizer(fmt):
        if tok == u'%(':
            choice.append(0)
        elif tok == u'%|':
            if not choice:
                raise ValueError(u'Unexpected %| - must be within %(...%)')
            choice[-1] += 1
        elif tok == u'%)':
            try:
                choice.pop()
            except IndexError:
                raise ValueError(u'Unmatched %)')
        elif tok == u'%?':
            pass
        else:
            if not any(choice):
                yield to_write.get(tok, tok)
    if choice:
        raise ValueError(u'Unmatched %(')


def strip(fmt):
    u'''
    Remove extensions from  a format, taking the first choice and including
    optional parts.
    '''
    if not u'(' in fmt and not u'!' in fmt:
        return fmt
    else:
        return u''.join(_strip(fmt))


def _invert(fmt, to_regex=DEFAULT_TO_REGEX):
    u'''
    In general, add % where it's missing, and remove it where it's present.
    Actually, the implementation is a little smarter, only adding where it
    makes sense.
    '''
    i = 0
    n = len(fmt)
    while i < n:
        j = i + 1
        if fmt[i] == u'%':
            j += 1
            if j > n:
                raise ValueError(u'Missing token (nothing follows %)')
            yield fmt[i+1]
        elif fmt[i] == u'!':
            j += 1
            if j > n:
                raise ValueError(u'Missing token (nothing follows !)')
            yield u'%' + fmt[i:j]
        elif fmt[i] in u'(|)?':
            yield u'%' + fmt[i]
        elif u'%' + fmt[i] in to_regex:
            yield u'%' + fmt[i]
        else:
            yield fmt[i]
        i = j


def invert(fmt, to_regex=DEFAULT_TO_REGEX):
    u'''
    Replace each character c by %c, if %c appears in `to_regex`.  The !
    character is considered as a prefix, so !x becomes %!x if it appears in
    `to_regex`.  The % character is an escape, so %y becomes y.

    This effectively "inverts" a template, meaning that a template that
    would have been written as `T%(%H%!:%)%M` can be written as `%T(H!:)M`.
    '''
    if isinstance(fmt, unicode):
        return u''.join(_invert(fmt, to_regex))
    else:
        return tuple(invert(f, to_regex) for f in fmt)


def _auto_invert(fmt, log=None):
    u'''
    Apply `invert` automatically when needed.
    '''

    if fmt is None or u'%' in fmt:
        return fmt
    else:
        inverted = invert(fmt)
        if log:
            log(u'Inverted {0!r} to {1!r}', fmt, inverted)
        return inverted


def auto_invert(fmt, log=None):
    u'''
    Apply `invert` automatically when needed (handling tuples).
    '''
    if fmt is None or isinstance(fmt, unicode):
        return _auto_invert(fmt, log)
    else:
        return tuple(imap(lambda f: _auto_invert(f, log), fmt))

