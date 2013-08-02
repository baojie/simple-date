
from unittest import TestCase
from re import compile
from simpledate import DMY
from simpledate.fmt import _to_regexp, reconstruct, DEFAULT_TO_REGEX, strip, invert, HIDE_CHOICES


class RegexpTest(TestCase):

    def test_marker(self):
        # shows we can use an empty pattern to mark which option is matched
        rx = compile(ur'(?P<a1>)x')
        m = rx.match(u'x')
        assert m, u'no match'
        assert u'a1' in m.groupdict(), m.groupdict()
        assert m.groupdict()[u'a1'] is not None, m.groupdict()[u'a1']
        rx = compile(ur'((?P<a>)a|b)')
        m = rx.match(u'a')
        assert m, u'no match'
        assert u'a' in m.groupdict(), m.groupdict()
        assert m.groupdict()[u'a'] is not None, m.groupdict()[u'a']
        m = rx.match(u'b')
        assert m, u'no match'
        assert u'a' in m.groupdict(), m.groupdict()
        assert m.groupdict()[u'a'] is None, m.groupdict()[u'a']
        rx = compile(ur'((?P<a>)a|(?P<b>)b)')
        m = rx.match(u'b')
        assert m, u'no match'
        assert u'a' in m.groupdict(), m.groupdict()
        assert m.groupdict()[u'a'] is None, m.groupdict()[u'a']
        assert u'b' in m.groupdict(), m.groupdict()
        assert m.groupdict()[u'b'] is not None, m.groupdict()[u'b']


class ParserTest(TestCase):

    def assert_regexp(self, target, expr, subs):
        result, _, _ = _to_regexp(expr, subs)
        assert target == result, result

    def test_regexp(self):
        self.assert_regexp(u'abc', u'abc', {})
        self.assert_regexp(u'abXc', u'ab%xc', {u'%x': u'X'})
        self.assert_regexp(u'ab((?P<G1>)X)c', u'ab{%x}c', {u'%x': u'X'})
        self.assert_regexp(u'a((?P<G1>)b)?c', u'ab?c', {})
        self.assert_regexp(u'((?P<G1>)(?P<H>2[0-3]|[0-1]\d|\d)[^\w]+)(?P<M>[0-5]\d|\d)', u'{%H:!}%M', DEFAULT_SUBSTITUTIONS)

    def test_subs(self):
        self.assert_regexp(ur'(?P<Y>\d\d\d\d)-(?P<m>1[0-2]|0[1-9]|[1-9])-(?P<d>3[0-1]|[1-2]\d|0[1-9]|[1-9]| [1-9])', u'%Y-%m-%d', None)
        self.assert_regexp(ur'((?P<G1>)(?P<d>3[0-1]|[1-2]\d|0[1-9]|[1-9]| [1-9]))?', u'%d?', None)

    def assert_parser(self, target_regexp, target_rebuild, expr, subs):
        regexp, rebuild, _ = _to_regexp(expr, subs)
        assert target_regexp == regexp, regexp
        assert target_rebuild == rebuild, rebuild

    def test_parser(self):
        self.assert_parser(u'abc', {u'G0': u'abc'}, u'abc', {})
        self.assert_parser(u'aBc', {u'G0': u'a%bc'}, u'a%!bc', {u'%!b': u'B'})
        self.assert_parser(u'ab((?P<G1>)xyz)c', {u'G0': u'ab%G1%c', u'G1': u'xyz'}, u'ab%(xyz%)c', HIDE_CHOICES)
        self.assert_parser(u'ab((?P<G1>)xy|(?P<G2>)z)c', {u'G0': u'ab%G1%%G2%c', u'G1': u'xy', u'G2': u'z'}, u'ab%(xy%|z%)c', HIDE_CHOICES)
        self.assert_parser(u'ab((?P<G1>)c)?', {u'G0': u'ab%G1%', u'G1': u'c'}, u'abc%?', DEFAULT_TO_REGEX)
        self.assert_parser(u'ab((?P<G1>)((?P<G2>)c)?|(?P<G3>)de((?P<G4>)(?P<H>2[0-3]|[0-1]\d|\d))?)', {u'G0': u'ab%G1%%G3%', u'G1': u'%G2%', u'G2': u'c', u'G3': u'de%G4%', u'G4': u'%H'}, u'ab%(c%?%|de%H%?%)', DEFAULT_TO_REGEX)
        self.assert_parser(u'((?P<G1>)(?P<H>2[0-3]|[0-1]\d|\d)[^\w]+)(?P<M>[0-5]\d|\d)', {u'G1': u'%H:', u'G0': u'%G1%%M'}, u'%(%H%!:%)%M', DEFAULT_TO_REGEX)

    def assert_reconstruct(self, target, expr, text):
        pattern, rebuild, regexp = _to_regexp(expr)
        match = regexp.match(text)
        result = reconstruct(rebuild, match.groupdict())
        assert result == target, result

    def test_reconstruct(self):
        self.assert_reconstruct(u'ab', u'a{b|c}d?', u'ab')
        self.assert_reconstruct(u'ac', u'a{b|c}d?', u'ac')
        self.assert_reconstruct(u'abd', u'a{b|c}d?', u'abd')
        self.assert_reconstruct(u'%S', u'{{%H:}?%M:}?%S', u'56')
        self.assert_reconstruct(u'ab', u'a ?b', u'ab')
        self.assert_reconstruct(u'a b', u'a ?b', u'a b')
        self.assert_reconstruct(u'%%%M!{|}', u'%%%M%!%{%|%}', u'%59!{|}')


class StripTest(TestCase):

    def test_strip(self):
        s = strip(DMY[0])
        assert s == u'%d/%m/%Y %H:%M:%S.%f %Z', s
        s = strip(u'%! %! %?')
        assert s == u'  '
        s = strip(u'%%%M!{|}')
        assert s == u'%%%M!{|}', s
        s = strip(u'(|)!%%')
        assert s == u'(|)!%%', s


class InvertTest(TestCase):

    def test_invert(self):
        i = invert(u'a')
        assert i == u'%a', i
        i = invert(u'!a')
        assert i == u'%!a', i
        i = invert(u'a?')
        assert i == u'%a%?', i
        i = invert(u'(a|!b)?:')
        assert i == u'%(%a%|%!b%)%?:', i
        i = invert(u'(a|!b)?!:')
        assert i == u'%(%a%|%!b%)%?%!:', i
        i = invert(u'%a')
        assert i == u'a', i
        i = invert(u'%!')
        assert i == u'!', i
