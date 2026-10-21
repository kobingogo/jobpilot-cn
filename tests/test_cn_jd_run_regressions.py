"""Compact location/enrollment wording from fictional Codex/Grok local JDs."""
import unittest

from tools import cn_jd_check as checker


def row(report, name):
    return next(r for r in report['hard_filters'] if r['name'] == name)


class CompactJdRequirements(unittest.TestCase):
    def test_city_district_with_or_without_administrative_suffixes(self):
        for city, district in [('上海', '浦东'), ('杭州', '余杭'), ('北京', '海淀'),
                               ('深圳', '南山'), ('广州', '天河')]:
            for location in (city + district, city + '市' + district, city + district + '区'):
                for jd in ('工作地点：' + location, '虚构公司 | 后端实习生 | ' + location + ' | 200元/天',
                           '虚构岗位（' + location + '）'):
                    with self.subTest(jd=jd):
                        report = checker.check_jd(jd, {'city': {'accept': [city]}})
                        self.assertEqual(report['parsed']['cities'], [city])
                        self.assertEqual(row(report, 'city')['status'], 'pass')
            report = checker.check_jd('工作地点：' + city + district, {'city': {'accept': ['成都']}})
            self.assertEqual(row(report, 'city')['status'], 'fail')
            report = checker.check_jd('工作地点：' + city, {'city': {'accept': [city + district]}})
            self.assertEqual(row(report, 'city')['status'], 'pass')

    def test_districts_alone_and_unrecognized_compact_fields_do_not_imply_city(self):
        for place in ('浦东', '余杭', '海淀', '朝阳', '朝阳区', '南山', '天河',
                      '上海未知片区名', '北京大学', '杭州项目经验'):
            # Unlabelled fields must match a conservative place normalization,
            # not any occurrence of a city name inside prose or a school name.
            for jd in (place, '虚构公司 | ' + place + ' | 虚构岗位'):
                self.assertEqual(checker.parse_cities(jd, checker.BUILTIN_CITIES), [], jd)
        for place in ('浦东', '余杭', '海淀', '朝阳区'):
            report = checker.check_jd('工作地点：' + place, {'city': {'accept': ['北京']}})
            self.assertEqual(row(report, 'city')['status'], 'unknown')

    def test_student_word_orders_share_required_preferred_and_negation_rules(self):
        for degree in ('本科', '硕士'):
            for phrase in (degree + '在读', '在读' + degree):
                for student, status in ((True, 'pass'), (False, 'fail'), (None, 'unknown')):
                    report = checker.check_jd('虚构实习岗位；仅招' + phrase,
                                              {'labor': {'candidate_is_student': student}})
                    self.assertTrue(report['parsed']['campus']['student_required'])
                    self.assertIn(phrase, report['parsed']['campus']['student_evidence'])
                    self.assertEqual(row(report, 'student_status')['status'], status)
                report = checker.check_jd(phrase + '优先', {'labor': {'candidate_is_student': False}})
                self.assertEqual(row(report, 'student_status')['status'], 'flag')
                self.assertFalse(report['hard_fail'])
                for jd in ('不要求' + phrase, '无需' + phrase, phrase + '身份不限'):
                    report = checker.check_jd(jd, {'labor': {'candidate_is_student': False}})
                    self.assertFalse(report['parsed']['campus']['student_required'], jd)


