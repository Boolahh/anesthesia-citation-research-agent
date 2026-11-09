"""Explicit-country extraction when PubMed appends corresponding-author emails."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from agent.research import Bibliography


class CountryTrailingEmailTests(TestCase):
    def test_explicit_colombia_before_email_is_retained(self):
        with TemporaryDirectory() as path:
            countries = {
                'CO': {'name': 'Colombia', 'region': 'Region A', 'income': 'Group B'},
                'US': {'name': 'United States', 'region': 'Region C', 'income': 'Group D'},
                'GE': {'name': 'Georgia', 'region': 'Region E', 'income': 'Group F'},
            }
            engine = Bibliography(countries, Path(path), offline=True)
            affiliation = (
                'Division of Minimally Invasive and Bariatric Surgery, '
                'Clínica Iberoamérica, Carrera 50, Barranquilla, Colombia. '
                'jorgedaez@gmail.com.')
            self.assertEqual(engine._affiliation_country(affiliation),
                             ('Colombia', 'Region A', 'Group B'))
            self.assertEqual(engine._affiliation_country(
                'Research Hospital, Boston, United States. E-mail: author@hospital.org'),
                ('United States', 'Region C', 'Group D'))

    def test_email_domain_is_not_country_evidence(self):
        with TemporaryDirectory() as path:
            countries = {
                'CO': {'name': 'Colombia', 'region': 'Region A', 'income': 'Group B'},
                'US': {'name': 'United States', 'region': 'Region C', 'income': 'Group D'},
                'GE': {'name': 'Georgia', 'region': 'Region E', 'income': 'Group F'},
            }
            engine = Bibliography(countries, Path(path), offline=True)
            self.assertEqual(engine._affiliation_country(
                'Department of Medicine, University of Georgia, researcher@colombia.edu'),
                ('NR', 'NR', 'NR'))
            self.assertEqual(engine._affiliation_country(
                'Department of Medicine, University of Colombia. author@example.com'),
                ('NR', 'NR', 'NR'))
            self.assertEqual(engine._affiliation_country(
                'School of Medicine, Research Hospital, lead@colombia.edu'),
                ('NR', 'NR', 'NR'))
