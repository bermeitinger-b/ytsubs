#!/usr/bin/python -m pytest
from unittest import TestCase

from ytsubs import parse_duration


class TestParse_duration(TestCase):
    def test_parse_duration(self):
        self.assertEqual("1:37:15", parse_duration("PT1H37M15S"))
        self.assertEqual("37:15", parse_duration("PT37M15S"))
        self.assertEqual("1w 54:21:32", parse_duration("P1W2DT6H21M32S"))
