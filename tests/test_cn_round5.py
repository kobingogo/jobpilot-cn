"""Round 5: fictional local JDs, explicit opt-ins and compatibility boundaries."""
import json
from pathlib import Path
import tempfile
import unittest

from tools import cn_jd_check as checker
from tools.rank_state import cn_adjust

ROOT = Path(__file__).resolve().parent.parent


def row(report, name):
    return next(r for r in report['hard_filters'] if r['name'] == name)


class ProductDecisions(unittest.TestCase):
    def test_employer_requires_opt_in_self_description_and_never_changes_scores(self):
        for kind in ('国企', '央企', '事业单位', '外企', '民企'):
            for text in (f'虚构单位\n企业性质：{kind}', f'本公司是一家{kind}。'):
                with self.subTest(text=text):
                    legacy = checker.check_jd(text, {})
                    enabled = checker.check_jd(text, {'employer': {'detect_self_description': True}})
                    self.assertEqual(legacy['parsed']['employer']['mentions'], [])
                    hit = enabled['parsed']['employer']['mentions'][0]
                    self.assertEqual(hit['type'], kind)
                    self.assertIn(hit['evidence'], text)
                    self.assertFalse(hit['verified'])
                    self.assertEqual((enabled['score'], enabled['verdict']), (legacy['score'], legacy['verdict']))
        for text in ('服务国企客户', '国企项目外包', '本公司不是国企', '本公司是国企服务商',
                     '企业性质：央企子公司', '本公司是国企控股公司', '我们是一家由国企控股的民企',
                     '毕业于虚构事业单位大学', '虚构中国某某集团'):
            self.assertEqual(checker.check_jd(text, {'employer': {'detect_self_description': True}})
                             ['parsed']['employer']['mentions'], [], text)

    def test_internship_constraints_are_off_by_default_and_soft_when_enabled(self):
        jd = '虚构实习岗位；每周至少四天；实习3-6个月；最晚2027年2月1日到岗'
        legacy = checker.check_jd(jd, {})
        self.assertEqual(legacy['verdict'], 'pass')
        self.assertFalse(any(r['name'].startswith('availability_') for r in legacy['hard_filters']))
        filters = {'availability': {'days_per_week': 3, 'duration_months': 2, 'start_date': '2027-02-02'}}
        report = checker.check_jd(jd, filters)
        for key in filters['availability']:
            self.assertEqual(row(report, 'availability_' + key)['status'], 'flag')
        self.assertEqual((report['score'], report['hard_fail'], report['verdict']), (100, False, 'caution'))
        # Rank receives the existing penalty/veto contract, no new penalty dimension.
        self.assertEqual(cn_adjust(report, 80), (80, False, False, 0, 0, 0))
        filters['availability'] = {'days_per_week': 4, 'duration_months': 3, 'start_date': '2027-02-01'}
        report = checker.check_jd(jd, filters)
        for key in filters['availability']:
            self.assertEqual(row(report, 'availability_' + key)['status'], 'pass')

    def test_internship_unknown_negation_and_non_intern_boundary(self):
        filters = {'availability': {'days_per_week': 4, 'duration_months': 3, 'start_date': '2027-02-01'}}
        for jd in ('虚构实习岗位；到岗时间2月1日；长期实习',
                   '虚构实习岗位；无需每周5天；不要求实习6个月；不要求最晚2027-01-01到岗',
                   '虚构实习岗位；每周4天以下；实习3个月以内；最晚2027-02-30到岗'):
            report = checker.check_jd(jd, filters)
            for key in filters['availability']:
                self.assertEqual(row(report, 'availability_' + key)['status'], 'unknown', jd)
        report = checker.check_jd('虚构社招；每周5天', filters)
        self.assertFalse(any(r['name'].startswith('availability_') for r in report['hard_filters']))
        parsed = checker.parse_availability('每周到岗4-5天，实习至少三个月，2027-01-01前到岗')
        self.assertEqual(parsed['days_per_week']['value'], 4)
        self.assertEqual(parsed['duration_months']['value'], 3)
        self.assertEqual(parsed['start_date']['value'], '2027-01-01')

    def test_annual_comparison_preserves_default_and_can_be_disabled(self):
        filters = {'salary': {'min_monthly_k': 20}}
        legacy = checker.check_jd('虚构岗位；年包12万', filters)
        self.assertEqual(row(legacy, 'salary')['status'], 'fail')
        filters['salary']['compare_annual_as_monthly'] = False
        opted = checker.check_jd('虚构岗位；年包12万', filters)
        self.assertFalse(opted['hard_fail'])
        self.assertNotIn('salary_below_floor', row(opted, 'salary')['codes'])
        self.assertEqual(checker.check_jd('虚构岗位；月薪10K', filters)['verdict'], 'reject')
        filters['salary']['min_months'] = 14
        self.assertIn('salary_months_below_floor', row(checker.check_jd('年包12万·13薪', filters), 'salary')['codes'])

    def test_optional_annual_total_is_explicit_soft_and_independent_of_base(self):
        filters = {'salary': {'min_annual_total_k': 300}}
        for text, status in [('年包20-28万', 'flag'), ('年薪30万', 'pass'),
                             ('年度总包30万', 'pass'), ('240000-300000 CNY/year', 'pass'),
                             ('年包40万，底薪8K+提成', 'pass'), ('年包29.999万', 'flag'),
                             ('月薪25K·12薪', 'unknown'), ('年终奖30万', 'unknown'),
                             ('年终奖300000元/年', 'unknown'), ('年薪30万元/月', 'unknown'),
                             ('年薪面议', 'unknown'), ('年包30万以上', 'unknown'),
                             ('不提供年包30万', 'unknown'), ('200元/天', 'unknown')]:
            with self.subTest(text=text):
                report = checker.check_jd('虚构岗位；' + text, filters)
                self.assertEqual(row(report, 'salary_annual_total')['status'], status)
                self.assertFalse(report['hard_fail'])
                self.assertEqual(report['score'], 100)
        both = checker.check_jd('年包20万', {'salary': {'min_annual_total_k': 300, 'min_monthly_k': 20}})
        self.assertTrue(both['hard_fail'])  # Legacy monthly floor still independently applies.

    def test_flexible_work_default_and_overtime_opt_in(self):
        filters = {'jargon': {'flexible_work_overtime_only': True}}
        for text, default, opted in [('弹性工作制', 6, 0), ('弹性工作', 6, 0),
                                     ('弹性工作制，不加班，965', 6, 0),
                                     ('弹性工作制，需要加班', 6, 6),
                                     ('弹性工作制，996', 26, 26),
                                     ('弹性工作制；其他岗位需要加班', 6, 0),
                                     ('拒绝弹性工作制', 0, 0)]:
            self.assertEqual(checker.check_jd(text, {})['jargon_penalty'], default)
            self.assertEqual(checker.check_jd(text, filters)['jargon_penalty'], opted)
        for text, count in [('965', 1), ('不实行965', 0), ('400-965-1234', 0), ('1965年', 0)]:
            report = checker.check_jd(text, {})
            self.assertEqual(len(report['parsed']['working_hours']), count)
            self.assertEqual((report['score'], report['verdict']), (100, 'pass'))

    def test_new_config_validation_is_shared_by_cli_loader_and_direct_api(self):
        invalid = [{'employer': {'detect_self_description': 'false'}},
                   {'jargon': {'flexible_work_overtime_only': None}},
                   {'salary': {'compare_annual_as_monthly': 0}},
                   {'salary': {'min_annual_total_k': True}}, {'salary': {'min_annual_total_k': float('inf')}},
                   {'availability': {'days_per_week': 8}}, {'availability': {'days_per_week': 4.5}},
                   {'availability': {'duration_months': -1}}, {'availability': {'duration_months': '3'}},
                   {'availability': {'start_date': '2027-02-30'}}, {'availability': {'start_date': True}}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fictional.json'
            for filters in invalid:
                with self.subTest(filters=filters):
                    with self.assertRaises(ValueError):
                        checker.check_jd('虚构JD', filters)
                    path.write_text(json.dumps(filters), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        checker.load_filters(path)


class HouseholdAbbreviations(unittest.TestCase):
    def test_required_places_and_config_normalization(self):
        for short, place in [('京', '北京'), ('沪', '上海'), ('津', '天津'), ('渝', '重庆'), ('粤', '广东'), ('浙', '浙江')]:
            for have, status in [([place], 'pass'), ([short], 'pass'), ([short + '籍'], 'pass'), ([], 'fail')]:
                report = checker.check_jd(f'虚构岗位；限{short}籍', {'hukou': {'has': have}})
                self.assertEqual(report['parsed']['hukou']['places'], [place])
                self.assertEqual(row(report, 'hukou')['status'], status)
            # Standard abbreviations and full city names already normalize on config side.
        report = checker.check_jd('需京籍', {'hukou': {'has': ['京']}})
        self.assertEqual(row(report, 'hukou')['status'], 'pass')

    def test_waivers_preferences_and_negative_requirements(self):
        for text in ('不限京籍', '不要求沪籍', '无需津籍', '京籍不限', '京籍户籍不限', '非京籍也可',
                     '非沪籍可报', '京籍非京籍均可', '无须京籍', '非京籍优先', '非沪籍优先', '非京籍可'):
            self.assertEqual(checker.check_jd(text, {})['parsed']['hukou']['mode'], 'none', text)
        preferred = checker.check_jd('京籍优先', {'hukou': {'has': []}})
        self.assertEqual(row(preferred, 'hukou')['status'], 'flag')
        preferred = checker.check_jd('户籍不限，京籍优先', {'hukou': {'has': []}})
        self.assertEqual(row(preferred, 'hukou')['status'], 'flag')
        for text in ('仅限非京籍', '京籍勿投', '不招京籍', '不接受沪籍'):
            report = checker.check_jd(text, {'hukou': {'has': []}})
            self.assertEqual(report['parsed']['hukou']['mode'], 'review', text)
            self.assertEqual((row(report, 'hukou')['status'], report['hard_fail']), ('flag', False))

    def test_rejecting_non_local_applicants_requires_local_hukou(self):
        for short, place in [('京', '北京'), ('沪', '上海')]:
            for phrase in (f'仅限{short}籍', f'非{short}籍勿投', f'非{short}籍不要',
                           f'非{short}籍不考虑', f'非{short}籍谢绝'):
                for prefix in ('', f'仅限{short}籍，'):
                    text = f'{prefix}{phrase}。{place} 15-20K'
                    for have, status in [([place], 'pass'), ([], 'fail')]:
                        with self.subTest(text=text, have=have):
                            report = checker.check_jd(text, {'hukou': {'has': have}})
                            parsed = report['parsed']['hukou']
                            self.assertTrue(parsed['required'])
                            self.assertEqual((parsed['mode'], parsed['places']), ('required', [place]))
                            self.assertEqual(parsed.get('excluded_places', []), [])
                            self.assertEqual(row(report, 'hukou')['status'], status)

    def test_unwanted_local_hukou_remains_an_exclusion(self):
        for text in ('京籍勿投', '不招京籍'):
            with self.subTest(text=text):
                parsed = checker.check_jd(text, {})['parsed']['hukou']
                self.assertFalse(parsed['required'])
                self.assertEqual((parsed['mode'], parsed['places']), ('review', []))
                self.assertEqual(parsed['excluded_places'], ['北京'])

    def test_precedence_and_no_inference_from_school(self):
        for text in ('沪籍优先；限京籍', '不要求沪籍；必须京籍', '限京籍；沪籍优先',
                     '沪籍优先，必须京籍', '限京籍，不要求沪籍'):
            parsed = checker.check_jd(text, {})['parsed']['hukou']
            self.assertEqual((parsed['mode'], parsed['places']), ('required', ['北京']))
            self.assertIn('京籍', parsed['evidence'])
        for text in ('需京籍；仅限非京籍', '京籍优先；限非沪籍'):
            self.assertEqual(checker.check_jd(text, {})['parsed']['hukou']['mode'], 'review')
        for text in ('毕业院校：虚构北京大学', '学校：虚构上海理工大学', '需户籍本复印件'):
            self.assertEqual(checker.check_jd(text, {})['parsed']['hukou']['mode'], 'none')
        example = checker.check_jd('限京籍', config_path=checker.EXAMPLE_CONFIG)
        self.assertEqual(row(example, 'hukou')['status'], 'flag')

    def test_explicit_alternatives_are_not_treated_as_simultaneous_hukou(self):
        for text in ('京籍或沪籍', '京籍/沪籍', '京籍、沪籍均可'):
            report = checker.check_jd(text, {'hukou': {'has': ['北京']}})
            self.assertEqual(row(report, 'hukou')['status'], 'pass', text)
            report = checker.check_jd(text, {'hukou': {'has': ['天津']}})
            self.assertEqual(row(report, 'hukou')['status'], 'fail', text)
        report = checker.check_jd('京籍或沪籍；另需津籍', {'hukou': {'has': ['北京']}})
        self.assertEqual(row(report, 'hukou')['status'], 'flag')
