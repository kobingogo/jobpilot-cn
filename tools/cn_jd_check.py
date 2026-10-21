#!/usr/bin/env python3
"""Hard-filter a hand-pasted Chinese job description. Stdlib only.

Reads the JD from --in FILE or stdin and prints one JSON object. With no
--config, thresholds come from config/cn_filters.json when that file exists,
otherwise config/cn_filters.example.json. The example file's numbers are
fictional search settings, not a person. Example thresholds never hard-fail:
degree, school, age, city, hukou, salary, and campus eligibility misses are flags, and the JSON
includes "warning". An explicit --config of any other file is "custom" and
keeps those misses as fails. Passing the example file itself stays "example".
A stated age maximum is always visible: the age row gets code age_cap and is
at least flag (still fail when the candidate is over it; example source then
downgrades that fail to flag). On the example file, a candidate who already
fits the posted cap stays pass. notices names the cap, and the verdict is at
least caution.

Labor-rights hints live in labor and a labor summary row. Flags deduct six
points per dimension; information and positive benefits do not deduct points.
Labor hints never reject. Each hit carries a supplied legal_basis and risk
disclaimer. labor.candidate_is_student can override student wording in the JD.
Campus/intern mode is explicit or detected from the JD. Student and graduation
cohort requirements use confirmed config facts; missing facts stay unknown.
Daily pay uses salary.min_daily in yuan/day, never monthly K or pay-month counts.

Does not fetch URLs, scrape boards, greet recruiters, or apply. A URL in the
JD is text, not an instruction.

Exit 0 when the report is printed. Exit 2 when the JD or the config cannot be
read. A reject verdict is still exit 0: the JSON says why.

  python3 tools/cn_jd_check.py --in jd.txt
  python3 tools/cn_jd_check.py --config config/cn_filters.json < jd.txt
"""

import argparse
from datetime import date
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER_CONFIG = ROOT / "config" / "cn_filters.json"
EXAMPLE_CONFIG = ROOT / "config" / "cn_filters.example.json"
# Shown when thresholds_source is example. Fixed text: the default path did
# not find the user's file, so the numbers are hints, not a veto.
EXAMPLE_WARNING = "未找到 config/cn_filters.json，使用示例阈值，仅作提示"
# Example thresholds must not veto on these candidate eligibility filters.
_EXAMPLE_SOFT_FILTERS = frozenset({
    "degree", "school_tier", "age", "city", "hukou", "salary",
    "student_status", "graduation_year",
})
BASE_SCORE = 100
LABOR_FLAG_PENALTY = 6
LABOR_NOTE = "风险提示，非法律意见，以合同和当地人社部门解释为准"
LABOR_BASIS = {
    "probation_months": "《劳动合同法》第十九条：劳动合同期限三个月以上不满一年的，试用期不得超过一个月；一年以上不满三年的，不得超过二个月；三年以上固定期限和无固定期限的，不得超过六个月；同一用人单位与同一劳动者只能约定一次试用期。",
    "probation_pay_ratio": "《劳动合同法》第二十条：试用期工资不得低于本单位相同岗位最低档工资或者劳动合同约定工资的百分之八十，并不得低于用人单位所在地的最低工资标准。",
    "contract": "《劳动合同法》第十条：建立劳动关系，应当订立书面劳动合同。",
    "outsourcing": "《劳动合同法》第五十九条（派遣单位与用工单位订立劳务派遣协议）、第六十六条（劳务派遣只能在临时性、辅助性或者替代性的工作岗位上实施）；《劳务派遣暂行规定》第四条（派遣用工数量不得超过其用工总量的10%）。",
    "social_insurance": "《社会保险法》第五十八条（用人单位应当自用工之日起三十日内为其职工申请办理社会保险登记）、第六十条（用人单位应当自行申报、按时足额缴纳社会保险费）；《住房公积金管理条例》第二十条（单位应当按时、足额缴存住房公积金）。",
}
# Article-level links retain the supplied citation wording and distinguish the
# amended texts from older originals. Each hit carries all articles it cites.
_CONTRACT_SOURCE = "https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_0abfdd261c03417b949df19d869add8d.html"
_INSURANCE_SOURCE = "https://www.gov.cn/guoqing/2021-10/29/content_5647616.htm"
LABOR_SOURCES = {
    "probation_months": {"《劳动合同法》第十九条": _CONTRACT_SOURCE},
    "probation_pay_ratio": {"《劳动合同法》第二十条": _CONTRACT_SOURCE},
    "contract": {"《劳动合同法》第十条": _CONTRACT_SOURCE},
    "outsourcing": {
        "《劳动合同法》第五十九条": _CONTRACT_SOURCE,
        "《劳动合同法》第六十六条": _CONTRACT_SOURCE,
        "《劳务派遣暂行规定》第四条": "https://www.gov.cn/zhengce/2022-08/31/content_5711309.htm",
    },
    "social_insurance": {
        "《社会保险法》第五十八条": _INSURANCE_SOURCE,
        "《社会保险法》第六十条": _INSURANCE_SOURCE,
        "《住房公积金管理条例》第二十条": "https://www.gov.cn/zhengce/zhengceku/202608/content_7078478.htm",
    },
}

_WIDTH = str.maketrans({
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
    "Ｋ": "K", "ｋ": "k", "Ｗ": "W", "ｗ": "w",
    "＋": "+", "－": "-", "—": "-", "–": "-", "～": "~",
    "•": "·", "・": "·", "∙": "·", "･": "·",
})

DEGREE_RANK = {
    "none": 0,
    "high_school": 1,
    "associate": 2,
    "bachelor": 3,
    "master": 4,
    "doctor": 5,
}
DEGREE_ALIASES = {
    "none": "none", "不限": "none", "学历不限": "none",
    "high_school": "high_school", "高中": "high_school", "中专": "high_school",
    "associate": "associate", "大专": "associate", "专科": "associate",
    "bachelor": "bachelor", "本科": "bachelor", "学士": "bachelor",
    "master": "master", "硕士": "master", "研究生": "master",
    "doctor": "doctor", "博士": "doctor", "phd": "doctor",
}
_DEGREE_WORD = {
    "博士": "doctor",
    "硕士": "master",
    "研究生": "master",
    "本科": "bachelor",
    "学士": "bachelor",
    "大专": "associate",
    "专科": "associate",
    "高中": "high_school",
    "中专": "high_school",
}
# A floor often sits before the label ("本科及以上学历"), so the window
# reaches about 20 characters on each side. English floors use the same ranks.
_DEGREE_LABEL_PAD = 20
_EN_DEGREE = {
    "bachelor": "bachelor",
    "bachelors": "bachelor",
    "master": "master",
    "masters": "master",
    "phd": "doctor",
    "phds": "doctor",
    "doctorate": "doctor",
    "doctorates": "doctor",
}
_DEGREE_RE = re.compile(
    r"博士|硕士|研究生|本科|学士|大专|专科|高中|中专|"
    r"\b(?:doctorates?|phds?|masters?|bachelors?)\b",
    re.I,
)
_DEGREE_LABEL = re.compile(r"(?:学历|学位)(?:要求)?")
# Forward clause only, for the "学历不限" waiver. The scan window is separate.
_DEGREE_CLAUSE = re.compile(r"(?:学历|学位)(?:要求)?\s*[：:]?\s*[^。\n；;]{0,60}")
_DEGREE_ABOVE_EN = re.compile(
    r"(?:['\u2019]s)?(?:\s+degrees?)?\s+or\s+above\b",
    re.I,
)

# Longer phrases first at match time. A hit inside another hit is dropped.
JARGON = (
    ("抗压能力强", 8),
    ("抗压能力", 6),
    ("能承受较大工作压力", 8),
    ("承受较大工作压力", 8),
    ("狼性文化", 12),
    ("狼性", 12),
    ("弹性工作制", 6),
    ("弹性工作", 6),
    ("奋斗者协议", 15),
    ("奋斗者", 8),
    ("以公司为家", 10),
    ("把公司当家", 10),
    ("主人翁意识", 8),
    ("主人翁精神", 8),
    ("创业心态", 6),
    ("吃苦耐劳", 6),
    ("能吃苦", 6),
    ("随时待命", 10),
    ("随叫随到", 10),
    ("无偿加班", 15),
    ("强制加班", 15),
    ("加班文化", 12),
    ("周末加班", 10),
    ("大小周", 15),
    ("单休", 12),
    ("我们是一家人", 8),
    ("拥抱变化", 4),
    ("base加期权", 10),
    ("低base", 8),
    ("期权为主", 10),
    ("996", 20),
    ("007", 25),
    ("995", 12),
)
_BASE_OPTION = re.compile(r"base\s*\+\s*期权")
_NUMERIC_JARGON = {"996", "007", "995"}

SCAM = (
    ("虚假招聘", ("虚假招聘", "假招聘", "虚假岗位")),
    ("培训贷", ("培训贷款", "培训贷", "贷款培训", "以训代工")),
    ("收费入职", ("收费入职", "入职收费", "付费入职", "缴费入职", "有偿入职", "缴纳报名费", "报名费")),
    ("押金", ("入职押金", "服装押金", "风险金", "押金", "保证金", "履约金")),
    ("刷单", ("兼职刷单", "网店刷单", "刷信誉", "刷好评", "刷单")),
    # Fee nouns need a pay verb in the same clause. An amount may sit between
    # them ("缴纳298元培训资料费"). 公司承担/支付体检费 is not a demand.
    ("收费", (
        "培训资料费", "培训费", "资料费", "教材费",
        "代理费", "中介费", "介绍费",
        "服装费", "工装费", "置装费",
        "体检费", "工本费", "办证费", "建档费",
    )),
    ("招转培", ("招聘转培训", "招转培训", "招转培")),
    # Long form first so "谨防刷单返利" also blocks the inner 返利.
    ("刷单返利", ("刷单返利", "刷单返佣", "返利", "返佣")),
    ("盗刷", ("绑定银行卡", "提供验证码", re.compile(r"下载.{0,6}app\s*试岗"))),
    ("扣证件", ("扣押身份证", "押身份证")),
)
SCAM_PENALTY = 30
_PAY_ONLY = frozenset({"保证金", "风险金", "履约金", "报名费", "押金"})
_FEE_WORDS = frozenset(
    phrase for phrase in next(words for name, words in SCAM if name == "收费")
    if isinstance(phrase, str)
)
# Same clause, verb then noun, with room for "298元" / "人民币298元".
_FEE_VERB = re.compile(r"缴纳|交纳|先交|需交|要交|收取|支付(?!宝)")
_FEE_COMPANY = re.compile(r"(?:公司|单位|企业|用人单位)$")
_CLAUSE = "。；;！!？?\n，,"

# One side alone is slang, not a scam. 高薪诱导 needs one bait and one contact.
# 日入 skips 当日入职; 日结 skips 按日结算. Penalties are the light deductions.
LURE = (
    ("月入过万", 6, "bait", None),
    ("轻松高薪", 6, "bait", None),
    ("加微信详聊", 6, "hook", re.compile(r"加\s*微信详聊")),
    ("加qq详聊", 6, "hook", re.compile(r"加\s*qq详聊")),
    ("无需经验", 4, "hook", None),
    ("加微信", 4, "hook", re.compile(r"加\s*微信")),
    ("加qq", 4, "hook", re.compile(r"加\s*qq")),
    ("私聊", 4, "hook", None),
    ("日结", 4, "bait", re.compile(r"日结(?!算)")),
    ("日入", 4, "bait", re.compile(r"日入(?!职)")),
)

# 免/包/零 waive a following fee ("免押金"). 难免 is not a waiver.
# 红包/钱包/礼包 are not "the company covers this".
# Pay verbs are fillers so "不收取任何培训费" and "无需支付培训费" stay waived.
_NEG = re.compile(
    r"(?:谨防|防范|预防|拒绝|严禁|禁止|杜绝|不要|不用|无需|无须|没有|不存在|从不|"
    r"不收|不收取|不需要|不要求|免收|免费|免除|并非|不是|无|非|未|勿|莫|"
    r"(?<![不难未])免|(?<![红钱礼])包|零|不)"
    r"(?:任何|形式|的|和|与|及|再|做|搞|收|收取|缴纳|交纳|支付|先交|需交|要交|交|"
    r"存在|接受|提供|属于|是|有|很){0,3}$"
)

BUILTIN_CITIES = {
    "北京", "上海", "深圳", "广州", "杭州", "成都", "南京", "武汉", "西安",
    "苏州", "天津", "重庆", "长沙", "郑州", "青岛", "合肥", "厦门", "福州",
    "济南", "大连", "沈阳", "哈尔滨", "昆明", "宁波", "无锡", "东莞", "佛山",
    "珠海", "远程", "全国", "不限",
}
# Chinese labels still need ：:在于. "Base 北京" / "base北京" have no colon,
# so base may be followed by whitespace only. Location: Shanghai is the
# English form of the same label.
_CITY_LABEL = re.compile(
    r"(?:"
    r"(?:工作地点|工作城市|工作地|办公地点|办公城市|坐标|城市|地点|(?<![A-Za-z])location)"
    r"\s*[：:在于]"
    r"|(?<![A-Za-z])base\s*[：:在于]?"
    r")\s*([^\n。；;]{1,40})",
    re.I,
)
# English names only apply to a token already cut out as a place (a label
# value or a title parenthetical). They are not scanned in free prose.
_EN_CITIES = {
    "beijing": "北京",
    "shanghai": "上海",
    "shenzhen": "深圳",
    "guangzhou": "广州",
    "hangzhou": "杭州",
    "chengdu": "成都",
    "nanjing": "南京",
    "wuhan": "武汉",
    "xian": "西安",
    "xi'an": "西安",
    "suzhou": "苏州",
    "tianjin": "天津",
    "chongqing": "重庆",
    "changsha": "长沙",
    "zhengzhou": "郑州",
    "qingdao": "青岛",
    "hefei": "合肥",
    "xiamen": "厦门",
    "fuzhou": "福州",
    "jinan": "济南",
    "dalian": "大连",
    "shenyang": "沈阳",
    "harbin": "哈尔滨",
    "kunming": "昆明",
    "ningbo": "宁波",
    "wuxi": "无锡",
    "dongguan": "东莞",
    "foshan": "佛山",
    "zhuhai": "珠海",
}
_HEAD_CITY = re.compile(r"[【\[（(]([^】\]）)\n]{1,12})[】\]）)]")
_REMOTE = re.compile(r"远程办公|可远程|支持远程|居家办公|远程工作")
_OPEN_LOCATION = re.compile(r"(?:工作地点|工作城市|地点|城市)\s*不限|地点不限")

_SCHOOL_RE = re.compile(r"985|211|双一流|一本")
_SCHOOL_IMPLIES = {
    "985": {"985", "211", "双一流", "一本"},
    "211": {"211", "一本"},
    "双一流": {"双一流", "一本"},
    "一本": {"一本"},
}
_TIER_ALIASES = {"double_first_class": "双一流", "双一流": "双一流", "985": "985", "211": "211", "一本": "一本"}

_AGE_RANGE = re.compile(r"(?<!\d)(\d{2})\s*[-~到至]\s*(\d{2})\s*(?:周岁|岁)")
# "年龄：25-35" has the label and no 岁. The label keeps it off salary ranges.
_AGE_RANGE_LABELED = re.compile(
    r"年龄\s*[:：]?\s*(?<!\d)(\d{2})\s*[-~到至]\s*(\d{2})(?!\d)"
)
# A bare "N岁" is not a cap. "N岁左右" is an approximate cap at N.
# "内" is not "内推".
_AGE_MAX = re.compile(
    r"(?:不超过|不高于|小于|低于|≤|<=)\s*(?<!\d)(\d{2})\s*(?:周岁|岁)"
    r"|(?<!\d)(\d{2})\s*(?:周岁|岁)\s*(?:及以下|以下|以内|内(?!推)|左右)"
)
_AGE_MIN = re.compile(
    r"(?:年满|不少于|不低于|≥|>=)\s*(?<!\d)(\d{2})\s*(?:周岁|岁)"
    r"|(?<!\d)(\d{2})\s*(?:周岁|岁)\s*(?:及以上|以上)"
)

_PAY_UNIT = r"(?:[kK千万wW]元?|元|RMB|CNY)"
_PAY_PERIOD = r"(?:月|年|month|year)"
_SALARY_RANGE = re.compile(
    rf"(?<![\d.])(?P<min>\d+(?:\.\d+)?)\s*(?P<u1>{_PAY_UNIT})?"
    r"\s*[-~到至]\s*"
    rf"(?P<max>\d+(?:\.\d+)?)\s*(?P<u2>{_PAY_UNIT})"
    rf"(?:\s*(?:RMB|CNY))?(?:\s*[/／]\s*(?P<period>{_PAY_PERIOD}))?", re.I,
)
_SALARY_SINGLE = re.compile(
    rf"(?<![\d.])(?P<min>\d+(?:\.\d+)?)\s*(?P<u>{_PAY_UNIT})\s*(?P<open>以上|起|\+)?"
    rf"(?:\s*(?:RMB|CNY))?(?:\s*[/／]\s*(?P<period>{_PAY_PERIOD}))?", re.I,
)
# Short-period pay must be consumed before monthly parsing, even at 1000元/天.
_SHORT_PAY = re.compile(
    r"(?:(?P<label>日薪|时薪)\s*[:：]?\s*)?(?<![\d.])(?P<low>\d+(?:\.\d+)?)\s*"
    r"(?:[-~到至]\s*(?P<high>\d+(?:\.\d+)?)\s*)?元"
    r"(?:\s*[/／]\s*(?P<period>天|日|小时|时))?"
)
_STUDENT = re.compile(r"在校(?:大学)?生|在(?:校|读)(?:学生|本科|硕士|博士|大学生|研究生)|(?:本科|硕士|博士|研究生)在读")
_COHORT = re.compile(
    r"(?<!\d)(?P<first>20\d{2}|\d{2})\s*届?\s*"
    r"(?:[-~至到/、]\s*(?P<last>20\d{2}|\d{2})\s*)?届"
)
_MONTHS_TAIL = re.compile(r"^\s*(?:[·*x×/／]|（|\()?\s*(?P<m>\d{1,2})(?:\s*[-~到至]\s*\d{1,2})?\s*薪\s*[）)]?")
# "13 months" is a pay count, same as 13薪. "RMB/month" has no number in front.
_MONTHS_ANY = re.compile(r"(?<!\d)(\d{1,2})(?:\s*[-~到至]\s*\d{1,2})?\s*(?:薪|months?\b)", re.I)
_BASE_PAY = re.compile(r"(?:无责底薪|底薪|保底|基本工资|固定工资)\s*[:：为是]?\s*$")
_VARIABLE_PAY = re.compile(r"无责底薪|底薪|保底|提成|佣金")
_HUKOU = re.compile(r"(?P<prefix>.{0,12})(?P<kind>户口|户籍)")
_HUKOU_SHORT_PLACES = dict(zip("京沪津渝粤冀晋辽吉黑苏浙皖闽赣鲁豫鄂湘琼川黔滇陕甘青台桂宁新藏蒙",
                              ("北京", "上海", "天津", "重庆", "广东", "河北", "山西", "辽宁", "吉林", "黑龙江",
                               "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "海南",
                               "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾", "广西", "宁夏", "新疆", "西藏", "内蒙古")))
_HUKOU_SHORT = re.compile(r"(?P<non>非)?(?P<place>[" + "".join(_HUKOU_SHORT_PLACES) + r"])籍")

_CN_DIGITS = "零一二三四五六七八九"
_LABOR_NUMBER = r"(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百]+)"
_PROBATION = re.compile(r"试用期(?:间|内)?")
_PROBATION_MONTHS = re.compile(
    r"试用期(?:限)?\s*(?:[：:]|为期|为|是|长达|共|约定为)?\s*"
    rf"(?P<duration>半年|半个?月|{_LABOR_NUMBER}\s*(?:个半月|个?月半?|年半?))"
)
_PROBATION_RATIO = re.compile(
    rf"(?P<discount>打?\s*(?P<fold>\d+(?:\.\d+)?|[一二三四五六七八九]{{1,2}})\s*折)"
    r"|(?P<percent>\d+(?:\.\d+)?\s*[%％])"
    rf"|百分之(?P<cn_percent>{_LABOR_NUMBER})"
)
_LABOR_BREAK = re.compile(r"[。；;！!？?\n]")
_INSURANCE = r"(?:五险一金|五险|社保|社会保险|住房公积金|公积金)"
_LABOR_PHRASES = (
    ("social_insurance", "flag", "insurance_minimum_base",
     re.compile(r"按\s*最低\s*(?:基数|标准)(?:\s*(?:缴纳|缴存|缴费))?"
                r"|最低\s*(?:基数|标准)\s*(?:缴纳|缴存|缴费)"),
     "出现最低缴纳基数或标准表述，建议核对实际工资、缴费基数及当地口径"),
    ("social_insurance", "flag", "insurance_after_probation",
     re.compile(rf"转正后\s*(?:才|再|开始)?\s*(?:缴纳|缴存|缴|购买|买|交纳|交)\s*{_INSURANCE}"),
     "出现转正后起缴表述，建议核对入职起缴安排"),
    ("social_insurance", "flag", "insurance_unpaid_probation",
     re.compile(rf"试用期(?:间|内)?\s*(?:不|未)(?:予|予以)?\s*(?:缴纳|缴存|缴|购买|买|交纳|交)\s*{_INSURANCE}"),
     "出现试用期未缴表述，建议核对入职起缴安排"),
    ("social_insurance", "flag", "insurance_waived",
     re.compile(r"自愿放弃\s*(?:社保|社会保险|五险一金)"),
     "出现自愿放弃社保表述，建议核对用工及缴费安排"),
    ("social_insurance", "flag", "housing_fund_unpaid",
     re.compile(r"不\s*(?:交纳|缴纳|缴存|购买|交|缴|买)\s*(?:住房)?公积金"),
     "出现不缴公积金表述，建议核对缴存安排"),
    ("social_insurance", "info", "insurance_positive",
     re.compile(r"六险二金|全额缴纳|按实际工资缴纳|补充公积金"),
     "正向福利表述，建议在合同或福利说明中核对缴纳项目及基数"),
    ("outsourcing", "info", "outsourcing_stated",
     re.compile(r"人力外包|劳务派遣|派遣制|外包|驻场"),
     "出现外包、驻场或派遣表述，建议核对签约主体及用工形式；派遣相关依据仅供核对派遣安排"),
    ("contract", "flag", "contract_missing",
     re.compile(r"不\s*签(?:订|署)?\s*(?:书面)?\s*(?:劳动)?合同|以实习协议代替劳动合同"),
     "出现不签合同或以实习协议代替劳动合同表述，建议核对劳动关系及书面合同安排"),
)

NOTE = "仅检查手工粘贴的 JD，不抓取、不打招呼、不投递。Pasted JD only. Does not scrape, greet, or apply."


def _force_utf8_output():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)  # absent on a StringIO under test
        if reconfigure:
            reconfigure(encoding="utf-8")


def fold(text: str) -> str:
    """Width-fold only. Case is kept so salary evidence still shows 15-25K."""
    return text.translate(_WIDTH)


def _negated(text: str, index: int) -> bool:
    window = text[max(0, index - 12):index]
    return _NEG.search(window) is not None


def _round_num(value):
    if value is None:
        return None
    rounded = round(float(value), 2)
    if abs(rounded - round(rounded)) < 1e-9:
        return int(round(rounded))
    return rounded


def _section(filters: dict, key: str) -> dict:
    value = filters.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a JSON object")
    return value


def _number(section: dict, key: str):
    if key not in section or section[key] is None or section[key] == "":
        return None
    try:
        return float(section[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc


def _same_path(left: Path, right: Path) -> bool:
    """True when both paths are the same file, including a non-canonical spelling."""
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def resolve_config(path=None) -> tuple[Path, str]:
    """Pick the filter file and the thresholds_source label.

    No path: config/cn_filters.json when it exists, else the example file.
    An explicit path that is the example file is still "example" (hints only).
    The user's own file, passed explicitly, stays "user". Any other file is
    "custom" and keeps hard fails, even if its numbers were copied from the example.
    """
    if path is None:
        if USER_CONFIG.is_file():
            return USER_CONFIG, "user"
        return EXAMPLE_CONFIG, "example"
    chosen = Path(path)
    if _same_path(chosen, EXAMPLE_CONFIG):
        return chosen, "example"
    if _same_path(chosen, USER_CONFIG):
        return chosen, "user"
    return chosen, "custom"


def load_filters(path=None) -> dict:
    """Load hard-filter thresholds.

    With no path, reads config/cn_filters.json when it exists and otherwise
    config/cn_filters.example.json. Does not soften example misses; check_jd does.
    """
    config_path, _source = resolve_config(path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise OSError(f"cannot read {config_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{config_path} must contain a JSON object")
    # Touch each section so a mistyped object fails here, not halfway through a JD.
    for key in ("degree", "school_tier", "age", "city", "hukou", "salary", "labor", "campus"):
        _section(data, key)
    _labor_student(data)
    _campus_settings(data)
    _round5_settings(data)
    return data


def _canon_degree(value) -> str:
    if value is None:
        return "none"
    key = str(value).strip().lower()
    if key in DEGREE_ALIASES:
        return DEGREE_ALIASES[key]
    if str(value).strip() in DEGREE_ALIASES:
        return DEGREE_ALIASES[str(value).strip()]
    raise ValueError(f"unknown degree {value!r}")


_CITY_GROUPS = {"北上广深": ("北京", "上海", "广州", "深圳"),
                "北上深广": ("北京", "上海", "深圳", "广州"),
                "北上": ("北京", "上海")}
_CITY_ALIASES = {"京": "北京", "沪": "上海", "穗": "广州", "深": "深圳"}
# Explicit city+district pairs only. A district by itself is never a city hint.
_CITY_DISTRICTS = {
    "上海": ("浦东", "黄浦", "徐汇", "长宁", "静安", "普陀", "虹口", "杨浦", "闵行", "宝山", "嘉定", "松江", "青浦", "奉贤", "金山", "崇明"),
    "杭州": ("余杭", "西湖", "上城", "拱墅", "滨江", "萧山", "临平", "钱塘", "富阳", "临安"),
    "北京": ("海淀", "朝阳", "东城", "西城", "丰台", "石景山", "通州", "顺义", "昌平", "大兴", "房山", "门头沟", "怀柔", "平谷", "密云", "延庆"),
    "深圳": ("南山", "福田", "罗湖", "宝安", "龙岗", "龙华", "盐田", "坪山", "光明"),
    "广州": ("天河", "越秀", "海珠", "荔湾", "白云", "黄埔", "番禺", "花都", "南沙", "增城", "从化"),
}


def _norm_city(name: str) -> str:
    name = name.strip().strip("的").strip()
    mapped = _EN_CITIES.get(name.lower()) or _CITY_ALIASES.get(name)
    if mapped:
        return mapped
    for city, districts in _CITY_DISTRICTS.items():
        if re.fullmatch(re.escape(city) + r"市?(?:" + "|".join(districts) + r")", name):
            return city
    # Only qualified administrative forms; don't infer a city from a district
    # alone (e.g. 朝阳区 exists in more than one city).
    for city in sorted(BUILTIN_CITIES - {"远程", "全国", "不限"}, key=len, reverse=True):
        if name == city or re.fullmatch(re.escape(city) + r"市?(?:[\u4e00-\u9fff]+区)?", name):
            return city
    for suffix in ("特别行政区", "市", "省"):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)]
    return name


def _expand_city(name: str) -> list:
    name = name.strip()
    return list(_CITY_GROUPS[name]) if name in _CITY_GROUPS else [_norm_city(name)]


def _degree_level(word: str) -> str:
    if word in _DEGREE_WORD:
        return _DEGREE_WORD[word]
    return _EN_DEGREE[word.lower()]


def _degree_regions(text: str) -> list:
    """Windows around 学历/学位, or the whole JD when that misses.

    The label window covers about 20 characters on each side, because
    "本科及以上学历" puts the floor before the label. A window with no
    degree word falls back to the full text. A pure waiver ("学历不限")
    still scans the rest of the JD for a real floor.
    """
    labels = list(_DEGREE_LABEL.finditer(text))
    if not labels:
        return [(text, 0)]
    regions = []
    for match in labels:
        start = max(0, match.start() - _DEGREE_LABEL_PAD)
        end = min(len(text), match.end() + _DEGREE_LABEL_PAD)
        regions.append((text[start:end], start))
    clauses = list(_DEGREE_CLAUSE.finditer(text))
    waiver = bool(clauses) and all(
        "不限" in clause.group(0) and not re.search(r"及以上|以上", clause.group(0))
        for clause in clauses
    )
    if waiver or not any(_DEGREE_RE.search(region) for region, _offset in regions):
        return [(text, 0)]
    return regions


def _known_cities(filters: dict) -> set:
    accept = _section(filters, "city").get("accept") or []
    known = set(BUILTIN_CITIES)
    for city in accept:
        known.update(_expand_city(str(city)))
    return known


def _city_tokens(chunk: str, known: set) -> list:
    chunk = re.sub(r"[（(]([^）)]*)[）)]", r" \1 ", chunk)
    parts = re.split(r"[、/,，|]|或|和|及|\s+", chunk)
    found = []
    for part in parts:
        part = part.strip(" ：:；;。.")
        if not part:
            continue
        part = re.sub(r"(base|办公|工作|地点)$", "", part, flags=re.I)
        if part in _CITY_GROUPS:
            found.extend(_expand_city(part))
            continue
        norm = _norm_city(part)
        if norm in known or norm in {"远程", "全国", "不限"}:
            found.append(norm)
            continue
        for city in sorted(known, key=len, reverse=True):
            if len(city) >= 2 and city in part:
                found.append(city)
                break
    return found


def _unique(items) -> list:
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def parse_degree(text: str) -> dict:
    regions = _degree_regions(text)
    floors = []
    bare = []
    evidence = ""
    for region, offset in regions:
        mentions = list(_DEGREE_RE.finditer(region))
        if not mentions:
            continue
        required = []
        for match in mentions:
            absolute = offset + match.start()
            if _negated(text, absolute):
                continue
            before = text[max(0, absolute - 6):absolute]
            # 培养/面向 describe the role. 在校/在读/应届 name the applicant
            # ("在校硕士研究生"), not a degree floor.
            if re.search(r"培养|指导|招收|面向|服务|在校|在读|应届", before):
                continue
            after = region[match.end():match.end() + 8]
            if re.search(r"优先|为佳|加分|最好", after):
                continue
            # "及以上" is the Chinese floor. "Bachelor's degree or above" is
            # the same mark; the extra words sit further out than 8 characters.
            tail = region[match.end():match.end() + 32]
            above_match = re.match(r"\s*(?:及)?以上", tail) or _DEGREE_ABOVE_EN.match(tail)
            above = above_match is not None
            extra = above_match.end() if above_match else 0
            snippet = text[absolute:absolute + len(match.group(0)) + extra]
            required.append((DEGREE_RANK[_degree_level(match.group(0))], above, snippet))
        if not required:
            continue
        if any(item[1] for item in required):
            best = max(item for item in required if item[1])
            floors.append(best[0])
            evidence = best[2]
        else:
            ranks = [item[0] for item in required]
            span = region[mentions[0].start():mentions[-1].end()]
            level = min(ranks) if re.search(r"或|、|/", span) and len(ranks) > 1 else max(ranks)
            bare.append(level)
            evidence = span
    level = max(floors) if floors else (max(bare) if bare else None)
    if level is None:
        if re.search(r"学历不限|不限学历|学位不限", text):
            return {"required": "none", "evidence": "学历不限"}
        return {"required": None, "evidence": ""}
    name = next(key for key, rank in DEGREE_RANK.items() if rank == level)
    return {"required": name, "evidence": evidence}


def _satisfied_tiers(candidate_tiers) -> set:
    have = set()
    for tier in candidate_tiers or []:
        canon = _TIER_ALIASES.get(str(tier).strip(), _TIER_ALIASES.get(str(tier).strip().lower()))
        if canon is None:
            raise ValueError(f"unknown school tier {tier!r}")
        have |= _SCHOOL_IMPLIES[canon]
    return have


def parse_school(text: str) -> dict:
    required = []
    preferred = []
    for match in _SCHOOL_RE.finditer(text):
        tier = match.group(0)
        if tier in {"985", "211"}:
            before = text[match.start() - 1] if match.start() else ""
            after_char = text[match.end()] if match.end() < len(text) else ""
            if before.isdigit() or after_char.isdigit():
                continue
        if tier == "一本":
            ctx = text[match.end():match.end() + 4]
            pre = text[max(0, match.start() - 4):match.start()]
            if not re.search(r"院校|大学|以上|学历", ctx) and "要求" not in pre and "限" not in pre:
                continue
        if _negated(text, match.start()):
            continue
        after = text[match.end():match.end() + 10]
        before = text[max(0, match.start() - 6):match.start()]
        if re.search(r"优先|加分|为佳|最好", after) or "优先" in before:
            preferred.append(tier)
        else:
            required.append(tier)
    required = _unique(required)
    preferred = [tier for tier in _unique(preferred) if tier not in required]
    if required:
        return {"required": required, "mode": "required", "evidence": "/".join(required)}
    if preferred:
        return {"required": preferred, "mode": "preferred", "evidence": "/".join(preferred)}
    return {"required": [], "mode": "none", "evidence": ""}


def _age_number(match: re.Match) -> int:
    return int(next(group for group in match.groups() if group is not None))


def _age_bounds(low: int, high: int, evidence: str) -> dict:
    if low > high:
        low, high = high, low
    return {"min": low, "max": high, "evidence": evidence}


def parse_age(text: str) -> dict:
    # Bounds are inclusive: "35岁以下" and "35周岁及以下" both keep 35.
    # "30岁左右" keeps 30. "35岁内" / "35岁以内" keep 35.
    match = _AGE_RANGE.search(text)
    if match:
        return _age_bounds(int(match.group(1)), int(match.group(2)), match.group(0))
    labeled = _AGE_RANGE_LABELED.search(text)
    if labeled:
        return _age_bounds(int(labeled.group(1)), int(labeled.group(2)), labeled.group(0))
    max_match = _AGE_MAX.search(text)
    min_match = _AGE_MIN.search(text)
    if max_match:
        floor = _age_number(min_match) if min_match and min_match.start() != max_match.start() else None
        return {"min": floor, "max": _age_number(max_match), "evidence": max_match.group(0)}
    if min_match:
        return {"min": _age_number(min_match), "max": None, "evidence": min_match.group(0)}
    return {"min": None, "max": None, "evidence": ""}


def _age_cap_notices(age: dict) -> list:
    """One line when the JD states a maximum age. Empty otherwise."""
    if age.get("max") is None:
        return []
    cap = _round_num(age["max"])
    return [
        f"该岗位设有年龄上限（{cap}岁）。与岗位无关的年龄限制可能涉嫌就业歧视，可拨打 12333 人社服务热线咨询或投诉。"
    ]


def parse_title(text: str) -> dict:
    """Normalize a stated title, keeping the original and career-stage words.

    Conservative aliases only; this is not a candidate eligibility filter.
    """
    match = re.search(r"(?m)^\s*(?:岗位(?:名称)?|职位(?:名称)?|招聘岗位|role|job title)\s*[:：]\s*([^\n。；;]+)", text, re.I)
    if not match:
        return {"raw": "", "normalized": "", "family": None}
    raw = match.group(1).strip()
    normalized = re.sub(r"服务端|服务器端|后台", "后端", raw)
    family = "backend" if "后端" in normalized else None
    if not family and re.fullmatch(r"(?:Java|JAVA|java)\s*开发(?:工程师)?(?:实习生|实习)?", normalized):
        family = "java_development"  # Java could be backend, Android, or tooling.
    return {"raw": raw, "normalized": normalized, "family": family}


def parse_cities(text: str, known: set) -> list:
    found = []
    for match in _CITY_LABEL.finditer(text):
        found.extend(_city_tokens(match.group(1), known))
    if not found:
        head = text[:120]
        for match in _HEAD_CITY.finditer(head):
            found.extend(_city_tokens(match.group(1), known))
        # Compact headers often use pipes: 公司 | 岗位 | 上海浦东 | 薪资.
        # Require a whole field to normalize to a known city; no prose scan.
        for field in re.split(r"[|\n]", head):
            norm = _norm_city(field.strip())
            if norm in known:
                found.append(norm)
    if _REMOTE.search(text) and "远程" not in found:
        found.append("远程")
    if _OPEN_LOCATION.search(text) and "不限" not in found:
        found.append("不限")
    return _unique(found)


def parse_hukou(text: str, known: set) -> dict:
    places = []
    preferred = []
    evidence = ""
    for match in _HUKOU.finditer(text):
        kind_at = match.start("kind")
        prefix = match.group("prefix")
        after = text[match.end():match.end() + 6]
        if text[match.end():match.end() + 1] in {"本", "页", "卡"} or after.startswith("所在"):
            continue
        if re.search(r"解决|办理|落户|协助", prefix + after[:2]):
            continue
        if _negated(text, kind_at) or "不限" in prefix or after.startswith("不限"):
            continue
        place = None
        trimmed = re.sub(r"(要求|需要|须|需|有|具备|持有|限|仅|为|的|提供)+$", "", prefix)
        for size in (4, 3, 2):
            chunk = trimmed[-size:]
            if chunk in {"本地", "当地", "本市"}:
                place = "本地"
                break
            norm = _norm_city(chunk)
            if norm in known and norm not in {"全国", "不限", "远程"}:
                place = norm
                break
        target = preferred if ("优先" in after or "优先" in prefix) else places
        target.append(place or "未注明")
        if not evidence:
            evidence = text[max(0, kind_at - 8):match.end() + (2 if "优先" in after else 0)].strip()
    base_required = list(places)
    excluded = []
    alternatives = False
    short_evidence = {"required": [], "preferred": [], "excluded": []}
    for match in _HUKOU_SHORT.finditer(text):
        left, right = _clause_span(text, match.start(), commas=True)
        clause = text[left:right]
        before = text[left:match.start()]
        after = text[match.end():right]
        exclusion = bool(re.search(r"(?:不招|不接受|排除|不要|不考虑|谢绝)\s*$", before))
        rejection = bool(re.match(r"\s*(?:勿投|不招|除外|不要|不考虑|谢绝)", after))
        non = bool(match.group("non"))
        non_rejected = non and (exclusion or rejection)
        short_group = list(_HUKOU_SHORT.finditer(clause))
        open_group = (any(m.group("non") for m in short_group)
                      and any(not m.group("non") for m in short_group)
                      and bool(re.search(r"均可|皆可|都可", clause)))
        # Rejecting non-X applicants requires X; allowing or preferring them
        # does not require X. Keep bare non-X restrictions for manual review.
        if ((_negated(text, match.start()) and not exclusion)
                or re.search(r"(?:不要求|不需要|无需|无须)\s*$", before)
                or re.search(r"不限|不限制|不限定", before)
                or re.match(r"\s*(?:户籍|户口)?\s*(?:不限|不限制|不限定|亦可|也可|可报)", after)
                or (non and not non_rejected
                    and re.match(r"\s*(?:优先|可)", after))
                or open_group):
            continue
        place = _HUKOU_SHORT_PLACES[match.group("place")]
        if not non_rejected and (non or rejection or exclusion):
            excluded.append(place)
            short_evidence["excluded"].append(clause)
            continue
        mode = "preferred" if not non_rejected and ("优先" in after or "优先" in before) else "required"
        if mode == "required" and len(short_group) > 1 and re.search(r"或|/|、|均可|皆可", clause):
            alternatives = True
        (preferred if mode == "preferred" else places).append(place)
        short_evidence[mode].append(clause)
    hard = _unique(places)
    soft = [place for place in _unique(preferred) if place not in hard]
    if excluded or (alternatives and (base_required or len(_unique(short_evidence["required"])) > 1)):
        # Negative or conflicting eligibility cannot be proved from an empty
        # candidate list. Keep it visible for manual review, never hard-reject.
        return {"required": False, "places": hard, "excluded_places": _unique(excluded),
                "mode": "review", "evidence": "；".join(_unique(
                    [evidence] + short_evidence["required"] + short_evidence["excluded"])).strip("；")}
    if hard:
        return {"required": True, "places": hard, "mode": "alternatives" if alternatives else "required",
                "evidence": "；".join(_unique(short_evidence["required"])) or evidence}
    if soft:
        return {"required": False, "places": soft, "mode": "preferred",
                "evidence": "；".join(_unique(short_evidence["preferred"])) or evidence}
    return {"required": False, "places": [], "mode": "none", "evidence": ""}


def _monthly_k(value: float, unit: str, annual: bool):
    unit = unit.lower()
    if unit in {"rmb", "cny"}:
        unit = "元"
    elif unit.endswith("元") and len(unit) > 1:
        unit = unit[:-1]
    if unit == "k":
        amount = value
    elif unit == "千":
        amount = value
    elif unit == "元":
        amount = value / 1000.0
    elif unit in {"万", "w"}:
        amount = value * 10.0
    else:
        return None
    if annual:
        amount = amount / 12.0
    if amount < 0.5 or amount > 500:
        return None
    return amount


def _is_annual(text: str, start: int, period) -> bool:
    if period and period.lower() in {"年", "year"}:
        return True
    if period and period.lower() in {"月", "month"}:
        return False
    before = text[max(0, start - 8):start]
    if any(label in before for label in ("年薪", "年包", "年收入", "包年")):
        return True
    return False


def _months_near(text: str, end: int):
    tail = _MONTHS_TAIL.match(text[end:end + 14])
    if not tail:
        return None, end
    months = int(tail.group("m"))
    if 12 <= months <= 24:
        return months, end + tail.end()
    return None, end


def _variable_pay(text: str) -> bool:
    """Pay context only; ordinary performance bonuses and duties are not pay composition."""
    for clause in re.split(r"[。；;！!？?\n，,]", text):
        for match in _VARIABLE_PAY.finditer(clause):
            if _negated(clause, match.start()):
                continue
            window = clause[max(0, match.start() - 24):match.end() + 24]
            if (_SALARY_SINGLE.search(window) or _SHORT_PAY.search(window)
                    or re.search(r"薪资|薪酬|工资|月薪|年薪|年包", window)
                    or re.search(r"(?:底薪|保底)\s*(?:面议)?\s*\+\s*(?:绩效|提成|佣金)", window)
                    or re.search(r"(?:提成|佣金)\s*(?:另算|另计|另发|按业绩|按月发放)", window)):
                return True
        # 绩效 must explicitly compose monthly pay. 福利：绩效奖金 alone,
        # or a performance-related responsibility, does not satisfy this.
        if ("绩效" in clause and not _negated(clause, clause.index("绩效"))
                and not re.search(r"(?:不含|不包含|不包括|不计入)\s*绩效", clause)):
            if re.search(r"(?:基本工资|固定工资)[^。；;\n]{0,16}\+\s*绩效", clause):
                return True
            if re.search(r"月薪|月工资|月度薪资|每月薪资", clause) and re.search(
                r"(?:含|包含|包括|\+|组成|构成|由)[^。；;\n]{0,16}绩效|绩效[^。；;\n]{0,16}(?:组成|构成|占)", clause
            ):
                return True
    return False


def parse_salary(text: str, original: str | None = None) -> dict:
    empty = {
        "period": None,
        "min_daily": None,
        "max_daily": None,
        "min_hourly": None,
        "max_hourly": None,
        "min_monthly_k": None,
        "max_monthly_k": None,
        "months": None,
        "annual": False,
        "variable_pay": _variable_pay(text),
        "evidence": "",
    }
    source = original if original is not None and len(original) == len(text) else text
    short = [m for m in _SHORT_PAY.finditer(text) if m.group("label") or m.group("period")]
    if short:
        # When daily and hourly alternatives coexist, retain evidence and ask
        # for the applicable band rather than compare incomparable numbers.
        def short_period(match):
            return "hour" if match.group("period") in {"小时", "时"} or match.group("label") == "时薪" else "day"

        periods = {short_period(m) for m in short}
        if len(periods) > 1:
            return {**empty, "period": "mixed", "evidence": "；".join(source[m.start():m.end()].strip() for m in short)}
        period = periods.pop()
        match = max(short, key=lambda m: max(float(m.group("low")), float(m.group("high") or m.group("low"))))
        low, high = sorted((float(match.group("low")), float(match.group("high") or match.group("low"))))
        key = "daily" if period == "day" else "hourly"
        return {**empty, "period": period, f"min_{key}": _round_num(low),
                f"max_{key}": _round_num(high), "evidence": source[match.start():match.end()].strip()}
    # Each candidate is (high or None when open-ended, low, months, annual, start, stop).
    candidates = []
    for match in _SALARY_RANGE.finditer(text):
        unit2 = match.group("u2")
        unit1 = match.group("u1") or unit2
        annual = _is_annual(text, match.start(), match.group("period"))
        low = _monthly_k(float(match.group("min")), unit1, annual)
        high = _monthly_k(float(match.group("max")), unit2, annual)
        if low is None or high is None:
            continue
        if low > high:
            low, high = high, low
        months, stop = _months_near(text, match.end())
        candidates.append((high, low, months, annual, match.start(), stop))
    ranges = [(item[4], item[5]) for item in candidates]
    for match in _SALARY_SINGLE.finditer(text):
        if _overlaps(ranges, match.start(), match.end()):
            continue
        if ranges and not _BASE_PAY.search(text[max(0, match.start() - 12):match.start()]):
            # Preserve the existing preference for salary ranges over other
            # standalone amounts, except when a base needs its own comparison.
            continue
        annual = _is_annual(text, match.start(), match.group("period"))
        amount = _monthly_k(float(match.group("min")), match.group("u"), annual)
        if amount is None:
            continue
        months, stop = _months_near(text, match.end())
        composition = match.group("open") == "+" and re.match(
            r"\s*(?:提成|佣金|绩效|业绩|奖金|补贴|\d)", text[match.end():]
        )
        high = None if match.group("open") and not composition else amount
        if composition and stop == match.end():
            stop -= 1  # '+' introduces the next component, not an open base.
        candidates.append((high, amount, months, annual, match.start(), stop))
    if not candidates:
        if "面议" in text:
            return {**empty, "evidence": "面议"}
        return empty
    # A floor cares about the best stated band, not the probation band.
    def high_key(item):
        return item[0] if item[0] is not None else 10**9

    # A quoted total or commission band must not replace the stated base when
    # checking the floor. Do not add performance/commission amounts to it.
    bases = [item for item in candidates if empty["variable_pay"]
             and _BASE_PAY.search(text[max(0, item[4] - 12):item[4]])]
    _high, low, months, annual, start, stop = max(bases or candidates, key=high_key)
    source = original if original is not None and len(original) == len(text) else text
    if len(candidates) == 1 and months is None:
        found = [int(m.group(1)) for m in _MONTHS_ANY.finditer(text) if 12 <= int(m.group(1)) <= 24]
        if len(set(found)) == 1:
            months = found[0]
            extra = next(
                (m for m in _MONTHS_ANY.finditer(text) if int(m.group(1)) == months and m.end() > stop),
                None,
            )
            if extra:
                stop = extra.end()
    high = _high
    return {
        **empty,
        "period": "year" if annual else "month",
        "min_monthly_k": _round_num(low),
        "max_monthly_k": _round_num(high) if high is not None else None,
        "months": months,
        "annual": annual,
        "evidence": source[start:stop].strip(),
    }


# 400/800 hotlines are 10 digits: 400-996-1234, 4009961234, or with spaces.
# The 996 in the middle is the number, not the work-hour slogan.
_HOTLINE = re.compile(
    r"(?<!\d)\(?\s*(?:400|800)\s*\)?(?:[\s\-]*\d){7,8}(?!\d)"
)


def _in_hotline(text: str, start: int, end: int) -> bool:
    for match in _HOTLINE.finditer(text):
        if match.start() <= start and end <= match.end():
            return True
    return False


def _digit_bounded(text: str, start: int, end: int) -> bool:
    """True when 996/007/995 is slang, not part of a longer number or hotline."""
    before = text[start - 1] if start else ""
    after = text[end] if end < len(text) else ""
    # 1996年: a digit on either side. 400-996-1234: "-" (or a digit) on both sides.
    if before.isdigit() or after.isdigit():
        return False
    if before == "-" and after == "-":
        return False
    return not _in_hotline(text, start, end)


def _overlaps(occupied, start: int, end: int) -> bool:
    return any(not (end <= left or start >= right) for left, right in occupied)


def _clause_span(text: str, index: int, commas: bool = False) -> tuple[int, int]:
    """Sentence/semicolon boundary; commas may join a work-hours statement."""
    separators = "。；;！!？?\n" + ("，," if commas else "")
    left = max((text.rfind(char, 0, index) for char in separators), default=-1) + 1
    right = min((p for char in separators if (p := text.find(char, index)) >= 0), default=len(text))
    return left, right


def _overtime_context(text: str, index: int) -> bool:
    left, right = _clause_span(text, index)
    for match in re.finditer(r"加班|随时待命|随叫随到|996|007|995", text[left:right]):
        start, end = left + match.start(), left + match.end()
        if not _negated(text, start) and (not match[0].isdigit() or _digit_bounded(text, start, end)):
            return True
    return False


def find_jargon(text: str, flexible_work_overtime_only: bool = False) -> list:
    # A negated long phrase also blocks a shorter alias inside it
    # ("不接受抗压能力强" must not still count "抗压能力").
    occupied = []
    hits = []
    for match in _BASE_OPTION.finditer(text):
        occupied.append((match.start(), match.end()))
        if not _negated(text, match.start()):
            hits.append({"phrase": "base+期权", "penalty": 10, "at": match.start()})
    for phrase, penalty in sorted(JARGON, key=lambda item: len(item[0]), reverse=True):
        start = 0
        while True:
            index = text.find(phrase, start)
            if index < 0:
                break
            end = index + len(phrase)
            start = index + 1
            if phrase in _NUMERIC_JARGON and not _digit_bounded(text, index, end):
                continue
            if _overlaps(occupied, index, end):
                continue
            occupied.append((index, end))
            if _negated(text, index):
                continue
            if (flexible_work_overtime_only and phrase in {"弹性工作", "弹性工作制"}
                    and not _overtime_context(text, index)):
                continue
            hits.append({"phrase": phrase, "penalty": penalty, "at": index})
    hits.sort(key=lambda item: item["at"])
    return [{"phrase": item["phrase"], "penalty": item["penalty"]} for item in hits]


def _margin_pay(text: str, index: int) -> bool:
    window = text[max(0, index - 6):index + 8]
    return bool(re.search(r"缴纳|交纳|支付|收取|先交|需交|要交|交满", window))


def _phrase_rank(phrase) -> int:
    if isinstance(phrase, str):
        return len(phrase)
    return 12


def _phrase_hits(text: str, phrase):
    if isinstance(phrase, re.Pattern):
        for match in phrase.finditer(text):
            yield match.start(), match.end(), match.group(0)
        return
    start = 0
    while True:
        index = text.find(phrase, start)
        if index < 0:
            return
        yield index, index + len(phrase), phrase
        start = index + 1


def _fee_demanded(text: str, index: int, end: int) -> bool:
    """True when the applicant is told to pay this fee.

    Looks inside the same clause. "缴纳298元培训资料费" counts; "公司承担体检费"
    and "公司支付体检费" do not. A waived verb ("不收取") does not count either.
    """
    left = index
    floor = max(0, index - 24)
    cursor = index - 1
    while cursor >= floor:
        if text[cursor] in _CLAUSE:
            break
        left = cursor
        cursor -= 1
    right = end
    for i in range(end, min(len(text), end + 16)):
        if text[i] in _CLAUSE:
            break
        right = i + 1
    for match in _FEE_VERB.finditer(text, left, right):
        prefix = text[max(left, match.start() - 8):match.start()]
        if _FEE_COMPANY.search(prefix):
            continue
        if _negated(text, match.start()):
            continue
        return True
    return False


def find_lure(text: str) -> list:
    """Light slang hits. Each item keeps group so 高薪诱导 can require both sides."""
    occupied = []
    hits = []
    ordered = sorted(LURE, key=lambda item: len(item[0]), reverse=True)
    for phrase, penalty, group, pattern in ordered:
        if pattern is not None:
            spans = [(match.start(), match.end()) for match in pattern.finditer(text)]
        else:
            spans = []
            start = 0
            while True:
                index = text.find(phrase, start)
                if index < 0:
                    break
                spans.append((index, index + len(phrase)))
                start = index + 1
        for index, end in spans:
            if _overlaps(occupied, index, end):
                continue
            occupied.append((index, end))
            if _negated(text, index):
                continue
            hits.append({"phrase": phrase, "penalty": penalty, "at": index, "group": group})
    hits.sort(key=lambda item: item["at"])
    return hits


def _lure_scam(hits: list) -> dict | None:
    bait = next((item for item in hits if item["group"] == "bait"), None)
    hook = next((item for item in hits if item["group"] == "hook"), None)
    if not bait or not hook:
        return None
    return {"category": "高薪诱导", "phrase": f"{bait['phrase']}+{hook['phrase']}"}


def find_scams(text: str) -> list:
    hits = []
    seen = set()
    for category, phrases in SCAM:
        # "谨防虚假招聘" negates the long form; "假招聘" sits inside that span.
        # "谨防刷单返利" likewise blocks the inner 返利 / 返佣.
        blocked = []
        found = None
        ordered = sorted(phrases, key=_phrase_rank, reverse=True)
        for phrase in ordered:
            for index, end, label in _phrase_hits(text, phrase):
                if _overlaps(blocked, index, end):
                    continue
                if _negated(text, index):
                    blocked.append((index, end))
                    continue
                if isinstance(phrase, str) and phrase in _PAY_ONLY and not _margin_pay(text, index):
                    continue
                if isinstance(phrase, str) and phrase in _FEE_WORDS and not _fee_demanded(text, index, end):
                    continue
                found = label
                break
            if found:
                break
        if found and category not in seen:
            seen.add(category)
            hits.append({"category": category, "phrase": found})
    return hits


def _row(name, status, evidence="", detail="", codes=None) -> dict:
    return {
        "name": name,
        "status": status,
        "evidence": evidence or "",
        "detail": detail,
        "codes": list(codes or []),
    }


def _labor_student(filters: dict):
    value = _section(filters, "labor").get("candidate_is_student")
    if value is not None and not isinstance(value, bool):
        raise ValueError("labor.candidate_is_student must be a boolean or null")
    return value


def _campus_settings(filters: dict) -> tuple:
    section = _section(filters, "campus")
    mode = section.get("mode", "auto")
    if not isinstance(mode, str) or mode not in {"auto", "campus", "intern", "experienced"}:
        raise ValueError("campus.mode must be auto, campus, intern, or experienced")
    year = section.get("graduation_year")
    if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 2000 <= year <= 2099):
        raise ValueError("campus.graduation_year must be a four-digit integer or null")
    return mode, year


def _round5_settings(filters: dict) -> dict:
    """Validate opt-ins even when a JD has no relevant evidence."""
    settings = {}
    for section, key, default in (("employer", "detect_self_description", False),
                                  ("jargon", "flexible_work_overtime_only", False),
                                  ("salary", "compare_annual_as_monthly", True)):
        value = _section(filters, section).get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"{section}.{key} must be a boolean")
        settings[key] = value
    availability = _section(filters, "availability")
    for section, key in ((availability, "days_per_week"), (availability, "duration_months"),
                         (_section(filters, "salary"), "min_annual_total_k")):
        value = section.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value) or value <= 0):
            raise ValueError(f"{key} must be a positive finite number or null")
        if key == "days_per_week" and value is not None and (value > 7 or int(value) != value):
            raise ValueError("availability.days_per_week must be an integer from 1 to 7 or null")
    start = availability.get("start_date")
    if start is not None:
        try:
            if not isinstance(start, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
                raise ValueError
            date.fromisoformat(start)
        except ValueError as exc:
            raise ValueError("availability.start_date must be YYYY-MM-DD or null") from exc
    return settings


def parse_employer(text: str, enabled: bool) -> dict:
    """Only explicit self-description, never client names, school or ownership guesses."""
    mentions = []
    if enabled:
        pattern = re.compile(
            r"(?:企业性质|单位性质|公司性质|雇主类型)\s*[:：]\s*"
            r"(?P<label>中央企业|国有企业|事业单位|民营企业|外资企业|央企|国企|外企|民企)"
            r"(?!子公司|客户|服务|背景|项目|合作|供应|控股|参股|旗下|投资)"
            r"|(?:本公司|本单位|本企业|我们)\s*(?:是|为|属于|系)\s*(?:一家|一所)?\s*"
            r"(?P<self>中央企业|国有企业|事业单位|民营企业|外资企业|央企|国企|外企|民企)"
            r"(?!子公司|客户|服务|背景|项目|合作|供应|控股|参股|旗下|投资)"
        )
        aliases = {"中央企业": "央企", "国有企业": "国企", "外资企业": "外企", "民营企业": "民企"}
        for match in pattern.finditer(text):
            if _negated(text, match.start()):
                continue
            kind = match.group("label") or match.group("self")
            mentions.append({"type": aliases.get(kind, kind), "status": "info",
                             "evidence": match[0], "verified": False})
    return {"enabled": enabled, "mentions": mentions,
            "note": "仅JD自称，未经核验；不推断编制、签约主体，不评分或筛选"}


def parse_availability(text: str) -> dict:
    patterns = {
        "days_per_week": re.compile(
            rf"每周\s*(?:至少|不少于|不低于|到岗|出勤|实习|工作|保证|可|需|须|要求|[:：]|\s)*"
            rf"(?P<n>{_LABOR_NUMBER})(?:\s*[-~至到]\s*{_LABOR_NUMBER})?\s*天"),
        "duration_months": re.compile(
            rf"(?:实习(?:期|时长|时间)?|持续(?:实习)?|至少实习)\s*"
            rf"(?:至少|不少于|不低于|需|须|要求|为|[:：]|\s)*(?P<n>{_LABOR_NUMBER})"
            rf"(?:\s*[-~至到]\s*{_LABOR_NUMBER})?\s*个?月"),
    }
    result = {key: {"value": None, "evidence": ""} for key in (*patterns, "start_date")}
    for key, pattern in patterns.items():
        hits = [m for m in pattern.finditer(text) if not _negated(text, m.start())
                and not re.match(r"\s*(?:以下|以内|内(?!推))", text[m.end():])]
        if hits:
            # Multiple mentions retain the strictest stated lower bound. The
            # result stays soft because preferences/negotiability need review.
            match = max(hits, key=lambda m: _labor_number(m.group("n")))
            value = _labor_number(match.group("n"))
            if value > 0 and (key != "days_per_week" or value <= 7):
                result[key] = {"value": value, "evidence": match[0]}
    explicit_date = r"(?P<y>20\d{2})[-年/](?P<m>\d{1,2})[-月/](?P<d>\d{1,2})日?"
    pattern = re.compile(r"(?:最晚|不晚于|到岗时间\s*[:：])\s*" + explicit_date
                         + r"(?:\s*(?:前|之前)?\s*到岗)?|" +
                         explicit_date.replace("?P<", "?P<alt_") + r"\s*(?:前|之前)\s*到岗")
    hits = []
    for match in pattern.finditer(text):
        if _negated(text, match.start()):
            continue
        prefix = "" if match.group("y") else "alt_"
        try:
            value = date(*(int(match.group(prefix + part)) for part in ("y", "m", "d"))).isoformat()
        except ValueError:
            continue
        hits.append((value, match[0]))
    if hits:
        value, evidence = min(hits)
        result["start_date"] = {"value": value, "evidence": evidence}
    return result


def _eval_availability(parsed: dict, campus: dict, filters: dict) -> list:
    if campus["mode"] != "intern":
        return []
    section = _section(filters, "availability")
    rows = []
    for key, label in (("days_per_week", "每周到岗天数"), ("duration_months", "持续月数"),
                       ("start_date", "最晚到岗日期")):
        candidate, requirement = section.get(key), parsed[key]["value"]
        if candidate is None:
            continue  # Off by default, no new verdict or score effects.
        status = "unknown" if requirement is None else "pass"
        if requirement is not None and (candidate > requirement if key == "start_date" else candidate < requirement):
            status = "flag"
        rows.append(_row("availability_" + key, status, parsed[key]["evidence"],
                         f"{label}：候选人 {candidate}；JD {requirement}；仅提示，需确认安排",
                         ["availability_mismatch"] if status == "flag" else []))
    return rows


def _eval_annual_total(text: str, filters: dict) -> list:
    floor = _section(filters, "salary").get("min_annual_total_k")
    if floor is None:
        return []
    # Separate explicit annual clauses only. Never multiply a monthly salary,
    # count a bonus as a package, or use the legacy parser's chosen base as total.
    amounts, evidence = [], []
    for clause in re.split(r"[。；;！!？?\n，,]", text):
        occupied = []
        for pattern in (_SALARY_RANGE, _SALARY_SINGLE):
            for match in pattern.finditer(clause):
                if _overlaps(occupied, match.start(), match.end()):
                    continue
                occupied.append((match.start(), match.end()))
                before = clause[:match.start()]
                label = re.search(r"(?:年包|年薪|年度总包|年度总薪酬)\s*[:：为]?\s*$", before)
                explicit = (match.group("period") or "").lower() in {"年", "year"}
                if not (label or explicit) or _negated(clause, label.start() if label else match.start()):
                    continue
                if ((match.group("period") or "").lower() in {"月", "month"}
                        or (label is None and re.search(r"奖金|年终奖|补贴|补助|提成|佣金", before))):
                    continue
                if pattern is _SALARY_RANGE:
                    unit = match.group("u2")
                    # Raw, unrounded conversion avoids annual /12 rounding at a threshold.
                    values = [_monthly_k(float(match.group("min")), match.group("u1") or unit, True),
                              _monthly_k(float(match.group("max")), unit, True)]
                    amount = max(values) if all(v is not None for v in values) else None
                else:
                    if match.group("open"):
                        continue  # No ceiling: cannot declare it below a floor.
                    amount = _monthly_k(float(match.group("min")), match.group("u"), True)
                if amount is not None:
                    amounts.append(amount * 12)
                    evidence.append(clause)
    status = "unknown" if not amounts else "flag" if max(amounts) + 1e-6 < floor else "pass"
    upper = _round_num(max(amounts)) if amounts else "未知"
    return [_row("salary_annual_total", status, "；".join(_unique(evidence)),
                 f"年包上界 {upper}K/年；总额底线 {floor}K/年；含浮动部分也不代表保证收入；仅提示",
                 ["annual_total_below_floor"] if status == "flag" else [])]


def parse_working_hours(text: str) -> list:
    return [{"status": "info", "evidence": m[0], "detail": "JD自述965，需核实实际工时；不加分或抵扣风险"}
            for m in re.finditer("965", text)
            if _digit_bounded(text, m.start(), m.end()) and not _negated(text, m.start())
            and not re.search(r"(?:不|未)(?:实行|采用|执行)\s*$", text[max(0, m.start() - 8):m.start()])]


def _student_mentions(text: str) -> list:
    return [m for m in _STUDENT.finditer(text)
            if not _negated(text, m.start())
            and not re.search(r"(?:不限|不限制|不限定)\s*$", text[max(0, m.start() - 12):m.start()])
            and not re.match(r"(?:身份)?不限", text[m.end():m.end() + 8])]


def parse_campus(text: str, filters: dict) -> dict:
    mode, _year = _campus_settings(filters)
    students = _student_mentions(text)
    cohorts = [m for m in _COHORT.finditer(text) if not _negated(text, m.start())]
    years = []
    for match in cohorts:
        first = int(match.group("first"))
        first = first + 2000 if first < 100 else first
        last = int(match.group("last") or first)
        last = last + 2000 if last < 100 else last
        if match.group("last") and re.search(r"[-~至到]", match.group(0)):
            years.extend(range(min(first, last), max(first, last) + 1))
        else:
            years.extend((first, last))
    if mode == "auto":
        signals = [m for m in re.finditer(r"实习|校招|校园招聘|应届", text) if not _negated(text, m.start())]
        mode = ("intern" if any(m.group(0) == "实习" for m in signals)
                else "campus" if signals or cohorts or students else "experienced")
    def preferred(match):
        return bool(re.match(r"\s*(?:身份)?(?:优先|为佳|加分)", text[match.end():match.end() + 8])
                    or re.search(r"优先(?:考虑|招收)?\s*$", text[max(0, match.start() - 8):match.start()]))

    return {"mode": mode, "student_required": bool(students),
            "student_preferred": bool(students) and all(preferred(m) for m in students),
            "graduation_preferred": bool(cohorts) and all(preferred(m) for m in cohorts),
            "graduation_years": sorted(set(years)),
            "student_evidence": "；".join(m.group(0) for m in students),
            "graduation_evidence": "；".join(m.group(0) for m in cohorts)}


def _eval_campus(parsed: dict, filters: dict) -> list:
    # JD requirements never prove the candidate's eligibility. Missing profile
    # facts remain unknown; a graduation year does not prove current enrollment.
    student = _labor_student(filters)
    _mode, year = _campus_settings(filters)
    required = parsed["student_required"]
    student_status = "unknown" if not required or student is None else "pass" if student else "fail"
    years = parsed["graduation_years"]
    year_status = "unknown" if not years or year is None else "pass" if year in years else "fail"
    if student_status == "fail" and parsed["student_preferred"]:
        student_status = "flag"
    if year_status == "fail" and parsed["graduation_preferred"]:
        year_status = "flag"
    return [
        _row("student_status", student_status, parsed["student_evidence"],
             "JD提及在校身份（优先项仅提示）；以候选人确认的在读状态核对，不推断已毕业者在读" if required else "JD未明确要求在校身份",
             ["student_status_mismatch"] if student_status in {"fail", "flag"} else []),
        _row("graduation_year", year_status, parsed["graduation_evidence"],
             f"JD届别 {years}；候选人毕业年份 {year}；应届资格及毕业时间窗口需向招聘方核对" if years else "JD未明确届别；应届资格需核对",
             ["graduation_year_mismatch"] if year_status in {"fail", "flag"} else []),
    ]


def _labor_number(value: str) -> float:
    value = value.replace("两", "二").replace("〇", "零")
    if value.isascii():
        return float(value)
    total = current = 0
    for char in value:
        if char in "十百":
            total += (current or 1) * (10 if char == "十" else 100)
            current = 0
        else:
            current = _CN_DIGITS.index(char)
    return total + current


def _probation_months(duration: str) -> float:
    duration = re.sub(r"\s+", "", duration)
    if duration.startswith("半"):
        return 6 if duration == "半年" else 0.5
    number = re.match(_LABOR_NUMBER, duration).group(0)
    months = _labor_number(number)
    if "年" in duration:
        return months * 12 + (6 if "半" in duration else 0)
    return months + (0.5 if "半" in duration else 0)


def _labor_hit(name, status, evidence, detail, code, value=None, risk=True) -> dict:
    hit = _row(name, status, evidence, f"{detail}。{LABOR_NOTE}", [code])
    hit["legal_basis"] = LABOR_BASIS[name]
    hit["source_urls"] = dict(LABOR_SOURCES[name])
    hit["risk"] = risk
    if value is not None:
        hit["value"] = _round_num(value)
    return hit


def _eval_labor(text: str, filters: dict) -> list:
    """Evidence-backed hints only. No labor hit can be a hard-filter fail."""
    hits = []
    for match in _PROBATION_MONTHS.finditer(text):
        if _negated(text, match.start()):
            continue
        months = _probation_months(match.group("duration"))
        if months <= 3:
            continue
        over = months > 6
        detail = (
            "试用期表述超过六个月，存在期限风险，建议核对并咨询当地人社部门"
            if over else "试用期超过三个月且不超过六个月，建议核对劳动合同期限"
        )
        hits.append((match.start(), _labor_hit(
            "probation_months", "flag" if over else "info", match.group(0), detail,
            "probation_over_six_months" if over else "probation_check_contract_term", months,
        )))

    anchors = list(_PROBATION.finditer(text))
    for index, anchor in enumerate(anchors):
        if _negated(text, anchor.start()):
            continue
        # Stay near this probation clause. One comma can join its duration and
        # pay ("试用期6个月，打八折"), but unrelated benefits must not supply a ratio.
        stop = min(len(text), anchor.end() + 64)
        if index + 1 < len(anchors):
            stop = min(stop, anchors[index + 1].start())
        boundary = _LABOR_BREAK.search(text, anchor.end(), stop)
        if boundary:
            stop = boundary.start()
        window = text[anchor.end():stop]
        for ratio in _PROBATION_RATIO.finditer(window):
            prefix = window[:ratio.start()]
            if re.search(r"完成率|达标率|出勤率|绩效占比|提成占比", prefix):
                continue
            clauses = re.split(r"[，,]", prefix)
            if len(clauses) > 2:
                continue
            if len(clauses) == 2 and not re.match(
                r"\s*(?:试用期|工资|薪资|薪酬|待遇|打|按|为|\d|[一二三四五六七八九])",
                window[len(clauses[0]) + 1:],
            ):
                continue
            at = anchor.end() + ratio.start()
            if _negated(text, at):
                continue
            if ratio.group("fold"):
                amount = ratio.group("fold")
                # 七五折 is 75%, just as 7.5折 is 75%.
                if not amount.isascii() and len(amount) == 2:
                    value = sum(_CN_DIGITS.index(c) * p for c, p in zip(amount, (10, 1)))
                else:
                    value = _labor_number(amount) * 10
            elif ratio.group("cn_percent"):
                value = _labor_number(ratio.group("cn_percent"))
            else:
                value = float(ratio.group("percent").rstrip("%％ "))
            if value < 80:
                hits.append((anchor.start(), _labor_hit(
                    "probation_pay_ratio", "flag", text[anchor.start():anchor.end() + ratio.end()],
                    "试用期工资比例表述低于80%，建议核对工资约定及当地最低工资标准",
                    "probation_pay_below_eighty", value,
                )))

    student = _labor_student(filters)
    if student is None:
        # A mention of 实习协议 alone says nothing about student status.
        student = bool(_student_mentions(text))
    occupied = []
    for name, status, code, pattern, detail in _LABOR_PHRASES:
        for match in pattern.finditer(text):
            if _overlaps(occupied, match.start(), match.end()):
                continue
            occupied.append((match.start(), match.end()))
            if _negated(text, match.start()):
                continue
            if name == "contract" and student:
                hit = _labor_hit(
                    name, "info", match.group(0),
                    "在校生协议适用需结合实际用工性质核对，不据此判断劳动关系",
                    "student_contract_check",
                )
            else:
                hit = _labor_hit(name, status, match.group(0), detail, code,
                                 risk=code != "insurance_positive")
            hits.append((match.start(), hit))
    hits.sort(key=lambda item: item[0])
    return [hit for _at, hit in hits]


def _labor_row(hits: list) -> dict:
    status = "flag" if any(hit["status"] == "flag" for hit in hits) else "info" if hits else "unknown"
    row = _row(
        "labor", status, "；".join(_unique(hit["evidence"] for hit in hits)),
        LABOR_NOTE if hits else "JD未命中劳动权益提示，不代表用工安排已获核验",
        _unique(code for hit in hits for code in hit["codes"]),
    )
    row["legal_basis"] = "\n".join(_unique(hit["legal_basis"] for hit in hits))
    return row


def _eval_degree(parsed: dict, filters: dict) -> dict:
    section = _section(filters, "degree")
    if not section:
        return _row("degree", "unknown", parsed["evidence"], "未配置学历筛选，请在 config/cn_filters.json 确认 degree.candidate")
    candidate = _canon_degree(section.get("candidate", "none"))
    required = parsed["required"]
    if required is None:
        return _row("degree", "unknown", "", "JD未注明学历，需向招聘方确认")
    if required == "none" or DEGREE_RANK[required] <= DEGREE_RANK[candidate]:
        return _row("degree", "pass", parsed["evidence"], f"要求学历 {required}；候选人学历 {candidate}")
    reject = bool(section.get("reject_if_required_above", True))
    status = "fail" if reject else "flag"
    return _row(
        "degree",
        status,
        parsed["evidence"],
        f"要求学历 {required}；候选人学历 {candidate}",
        ["degree_above_candidate"],
    )


def _eval_school(parsed: dict, filters: dict) -> dict:
    section = _section(filters, "school_tier")
    if not section:
        return _row("school_tier", "unknown", parsed["evidence"], "未配置院校筛选")
    have = _satisfied_tiers(section.get("candidate_tiers") or [])
    if parsed["mode"] == "none":
        return _row("school_tier", "unknown", "", "JD未注明院校层次")
    missing = [tier for tier in parsed["required"] if tier not in have]
    # Required tiers are alternatives (985/211): one match is enough.
    if parsed["mode"] == "preferred":
        detail = f"优先院校 {'/'.join(parsed['required'])}"
        if missing and len(missing) == len(parsed["required"]):
            return _row("school_tier", "flag", parsed["evidence"], detail, ["school_tier_preferred"])
        return _row("school_tier", "pass", parsed["evidence"], detail)
    if not missing or len(missing) < len(parsed["required"]):
        return _row("school_tier", "pass", parsed["evidence"], f"要求院校 {'/'.join(parsed['required'])}")
    reject = bool(section.get("reject_if_required", True))
    status = "fail" if reject else "flag"
    return _row(
        "school_tier",
        status,
        parsed["evidence"],
        f"要求院校 {'/'.join(parsed['required'])}",
        ["school_tier_required"],
    )


def _eval_age(parsed: dict, filters: dict) -> dict:
    section = _section(filters, "age")
    if "candidate" not in section or section.get("candidate") is None:
        return _row("age", "unknown", parsed["evidence"], "未配置候选人年龄，不据此判定资格")
    age = _number(section, "candidate")
    if parsed["min"] is None and parsed["max"] is None:
        return _row("age", "unknown", "", "JD未注明年龄要求")
    codes = []
    if parsed["min"] is not None and age < parsed["min"]:
        codes.append("age_out_of_range")
    if parsed["max"] is not None and age > parsed["max"]:
        codes.append("age_out_of_range")
    # The cap is visible even when the candidate is young enough.
    if parsed["max"] is not None:
        codes.append("age_cap")
    detail = f"候选人年龄 { _round_num(age) }；要求 {parsed['min']}-{parsed['max']}"
    if "age_out_of_range" in codes:
        return _row("age", "fail", parsed["evidence"], detail, codes)
    if "age_cap" in codes:
        return _row("age", "flag", parsed["evidence"], detail, codes)
    return _row("age", "pass", parsed["evidence"], detail)


def _eval_city(cities: list, filters: dict) -> dict:
    section = _section(filters, "city")
    if not section:
        return _row("city", "unknown", "", "未配置城市筛选")
    accept = {place for city in (section.get("accept") or []) for place in _expand_city(str(city))}
    if not cities:
        return _row("city", "unknown", "", "JD未注明可识别城市，需确认工作地点")
    if any(city in {"全国", "不限"} for city in cities):
        return _row("city", "pass", "、".join(cities), "工作地点不限")
    matched = [city for city in cities if city in accept]
    evidence = "、".join(cities)
    if matched:
        return _row("city", "pass", evidence, f"城市匹配 {'、'.join(matched)}")
    if section.get("reject_unlisted", True):
        return _row("city", "fail", evidence, f"{evidence} 不在可接受城市内，请核对 city.accept", ["city_not_accepted"])
    return _row("city", "flag", evidence, f"{evidence} 不在可接受城市内，请核对 city.accept", ["city_not_accepted"])


def _eval_hukou(parsed: dict, cities: list, filters: dict) -> dict:
    section = _section(filters, "hukou")
    if parsed["mode"] == "review":
        return _row("hukou", "flag", parsed["evidence"],
                    "含排除性、冲突或组合条件，需人工核对资格；不从学校或未配置户籍推断",
                    ["hukou_exclusion_review"])
    if not section:
        return _row("hukou", "unknown", parsed["evidence"], "未配置户籍筛选")
    if parsed["mode"] == "none":
        return _row("hukou", "unknown", "", "JD未注明户籍要求")
    def normalize(place):
        value = str(place).strip().removesuffix("籍")
        return _HUKOU_SHORT_PLACES.get(value, _norm_city(value))

    have = {normalize(place) for place in (section.get("has") or [])}
    job_cities = [city for city in cities if city not in {"远程", "全国", "不限"}]

    def holds(place: str) -> bool:
        if place == "未注明":
            return bool(have)
        if place == "本地":
            return bool(job_cities) and all(city in have for city in job_cities) or (not job_cities and bool(have))
        return place in have

    if parsed["mode"] == "preferred":
        return _row("hukou", "flag", parsed["evidence"], f"优先户籍：{'、'.join(parsed['places'])}", ["hukou_preferred"])
    missing = [place for place in parsed["places"] if not holds(place)]
    if not missing or (parsed["mode"] == "alternatives" and len(missing) < len(parsed["places"])):
        return _row("hukou", "pass", parsed["evidence"], f"户籍匹配：{'、'.join(parsed['places'])}")
    reject = bool(section.get("reject_if_required", True))
    status = "fail" if reject else "flag"
    return _row(
        "hukou",
        status,
        parsed["evidence"],
        f"要求户籍：{'、'.join(parsed['places'])}",
        ["hukou_required"],
    )


def _eval_salary(parsed: dict, filters: dict) -> dict:
    row = _eval_salary_thresholds(parsed, filters)
    hints = []
    if parsed["annual"] and parsed["months"] is None:
        row["codes"].append("annual_months_unstated")
        hints.append("年包，未写薪数，建议问清几薪、年终奖是否保底")
    if parsed["variable_pay"]:
        row["codes"].append("base_plus_commission")
        hints.append("底薪+提成：到手不确定，问清底薪、提成规则和发放周期")
    if hints:
        row["detail"] = "；".join([row["detail"], *hints])
        if row["status"] != "fail":
            row["status"] = "flag"
    return row


def _eval_salary_thresholds(parsed: dict, filters: dict) -> dict:
    section = _section(filters, "salary")
    if parsed.get("period") in {"day", "hour", "mixed"}:
        if parsed["period"] != "day":
            return _row("salary", "unknown", parsed["evidence"], "时薪或混合计薪，需确认适用标准；不折算为月薪")
        floor = _number(section, "min_daily")
        if floor is None:
            return _row("salary", "unknown", parsed["evidence"], "日薪已识别，salary.min_daily 未配置；不与月薪或薪数门槛比较")
        failed = parsed["max_daily"] + 1e-6 < floor
        return _row("salary", "fail" if failed else "pass", parsed["evidence"],
                    f"日薪 {parsed['min_daily']}-{parsed['max_daily']}元/天；底线 {_round_num(floor)}元/天；不折算为月薪",
                    ["salary_daily_below_floor"] if failed else [])
    if not section:
        return _row("salary", "unknown", parsed["evidence"], "未配置薪资底线")
    floor = _number(section, "min_monthly_k") if "min_monthly_k" in section else None
    if parsed["annual"] and section.get("compare_annual_as_monthly", True) is False:
        floor = None
    min_months = _number(section, "min_months") if "min_months" in section else None
    if (parsed["annual"] and section.get("compare_annual_as_monthly", True) is False
            and (min_months is None or parsed["months"] is None)):
        return _row("salary", "unknown", parsed["evidence"],
                    "已关闭年包月均与月薪底线比较；年包不等于保证月薪")
    if parsed["min_monthly_k"] is None and parsed["months"] is None:
        evidence = parsed["evidence"] or ""
        detail = "薪资未注明，需确认" if not evidence else f"薪资未注明，需确认 ({evidence})"
        return _row("salary", "unknown", evidence, detail)
    codes = []
    high = parsed["max_monthly_k"]
    low = parsed["min_monthly_k"]
    if floor is not None and high is not None and high + 1e-6 < floor:
        codes.append("salary_below_floor")
    elif floor is not None and high is None and low is not None and low + 1e-6 < floor:
        # "10K以上" states no top. The only number is below the floor.
        codes.append("salary_below_floor")
    if min_months is not None and parsed["months"] is not None and parsed["months"] < min_months:
        codes.append("salary_months_below_floor")
    bits = []
    if parsed["min_monthly_k"] is not None:
        bits.append(f"{parsed['min_monthly_k']}-{parsed['max_monthly_k']}K")
    if parsed["months"] is not None:
        bits.append(f"{parsed['months']}薪")
    if floor is not None:
        bits.append(f"底线 { _round_num(floor) }K")
    if min_months is not None:
        bits.append(f"至少 { _round_num(min_months) }薪")
    status = "fail" if codes else "pass"
    return _row("salary", status, parsed["evidence"], "; ".join(bits), codes)


def _thresholds(filters: dict) -> dict:
    degree = _section(filters, "degree")
    school = _section(filters, "school_tier")
    age = _section(filters, "age")
    city = _section(filters, "city")
    hukou = _section(filters, "hukou")
    salary = _section(filters, "salary")
    return {
        "degree": _canon_degree(degree.get("candidate", "none")) if degree else None,
        "school_tiers": list(school.get("candidate_tiers") or []),
        "age": age.get("candidate"),
        "cities": list(city.get("accept") or []),
        "hukou": list(hukou.get("has") or []),
        "min_monthly_k": salary.get("min_monthly_k"),
        "min_months": salary.get("min_months"),
        "min_daily": salary.get("min_daily"),
        "campus_mode": _section(filters, "campus").get("mode", "auto"),
        "graduation_year": _section(filters, "campus").get("graduation_year"),
        "candidate_is_student": _labor_student(filters),
        "availability": dict(_section(filters, "availability")),
        "min_annual_total_k": salary.get("min_annual_total_k"),
        **_round5_settings(filters),
    }


def check_jd(text: str, filters: dict | None = None, config_path=None) -> dict:
    """Return the JSON-ready report for one pasted JD.

    A filters dict is an explicit custom set: its fails are not softened.
    Otherwise config_path (or the default user-then-example path) is loaded.
    """
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = str(text or "")
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if filters is None:
        config_path, source = resolve_config(config_path)
        filters = load_filters(config_path)
    else:
        # Caller-supplied thresholds are not the example file, so they keep fails.
        source = "custom"
    if not isinstance(filters, dict):
        raise ValueError("filters must be a dict")
    settings = _round5_settings(filters)
    folded = fold(text)
    known = _known_cities(filters)
    degree = parse_degree(folded)
    school = parse_school(folded)
    age = parse_age(folded)
    cities = parse_cities(folded, known)
    hukou = parse_hukou(folded, known)
    salary = parse_salary(folded, text)
    campus = parse_campus(folded, filters)
    availability = parse_availability(folded)
    # Jargon and scam phrases are case-insensitive ("Base + 期权").
    # Salary evidence is sliced from the pasted text, which fold() does not resize.
    lowered = folded.lower()
    jargon = find_jargon(lowered, settings["flexible_work_overtime_only"])
    lure = find_lure(lowered)
    jargon.extend({"phrase": item["phrase"], "penalty": item["penalty"]} for item in lure)
    scams = find_scams(lowered)
    labor = _eval_labor(folded, filters)
    lure_scam = _lure_scam(lure)
    if lure_scam:
        scams.append(lure_scam)
    rows = [
        _eval_degree(degree, filters),
        _eval_school(school, filters),
        _eval_age(age, filters),
        _eval_city(cities, filters),
        _eval_hukou(hukou, cities, filters),
        _eval_salary(salary, filters),
        *_eval_campus(campus, filters),
        *_eval_availability(availability, campus, filters),
        *_eval_annual_total(folded, filters),
        _labor_row(labor),
    ]
    if source == "example":
        for row in rows:
            if row["name"] in _EXAMPLE_SOFT_FILTERS and row["status"] == "fail":
                row["status"] = "flag"
            elif row["name"] == "age" and row["codes"] == ["age_cap"]:
                # Example numbers are hints. Fitting the posted cap is not a
                # miss; age_cap and notices still name the limit.
                row["status"] = "pass"
    notices = _age_cap_notices(age)
    jargon_penalty = sum(item["penalty"] for item in jargon)
    scam_penalty = min(BASE_SCORE, SCAM_PENALTY * len(scams))
    # Repeated wording within one labor dimension must not multiply deductions.
    labor_penalty = LABOR_FLAG_PENALTY * len({hit["name"] for hit in labor if hit["status"] == "flag"})
    hard_fail = any(row["status"] == "fail" for row in rows)
    flagged = any(row["status"] == "flag" for row in rows)
    scam_fail = bool(scams)
    if not text:
        verdict = "empty"
    elif hard_fail or scam_fail:
        verdict = "reject"
    elif flagged or jargon_penalty or notices or any(hit["risk"] for hit in labor):
        verdict = "caution"
    else:
        verdict = "pass"
    score = max(0, BASE_SCORE - jargon_penalty - scam_penalty - labor_penalty)
    report = {
        "ok": verdict == "pass",
        "verdict": verdict,
        "score": score,
        "base_score": BASE_SCORE,
        "hard_fail": hard_fail,
        "scam_fail": scam_fail,
        "empty": text == "",
        "notices": notices,
        "hard_filters": rows,
        "jargon": jargon,
        "jargon_penalty": jargon_penalty,
        "scam": scams,
        "scam_penalty": scam_penalty,
        "labor": labor,
        "labor_penalty": labor_penalty,
        "parsed": {
            "degree": degree,
            "school_tier": school,
            "age": age,
            "cities": cities,
            "title": parse_title(folded),
            "hukou": hukou,
            "salary": salary,
            "campus": campus,
            "availability": availability,
            "employer": parse_employer(folded, settings["detect_self_description"]),
            "working_hours": parse_working_hours(folded),
        },
        "thresholds": _thresholds(filters),
        "thresholds_source": source,
        "note": NOTE,
    }
    if source == "example":
        report["warning"] = EXAMPLE_WARNING
    return report


def _read_input(path: Path | None) -> str:
    if path is not None:
        return path.read_bytes().decode("utf-8-sig")
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        return buffer.read().decode("utf-8-sig")
    return sys.stdin.read()


def main(argv=None) -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(
        prog="cn_jd_check.py",
        description="检查手工粘贴的中文 JD，按本地阈值输出 JSON；不联网、不投递。",
    )
    parser.add_argument("--in", dest="infile", type=Path, default=None, help="UTF-8 JD 文本文件（默认从标准输入读取）")
    parser.add_argument("path", nargs="?", type=Path, help="UTF-8 JD 文件；不填则读取标准输入")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="筛选 JSON：默认 config/cn_filters.json；缺失时使用 example 提示阈值",
    )
    args = parser.parse_args(argv)
    if args.infile is not None and args.path is not None:
        print("cn_jd_check: --in FILE 与位置参数只能选一种；请删除重复文件参数", file=sys.stderr)
        return 2
    source = args.infile or args.path
    try:
        raw = _read_input(source)
    except (OSError, UnicodeError) as exc:
        print(f"cn_jd_check: 无法读取 JD：{exc}；请检查路径和文件权限，并另存为 UTF-8（不要使用 GBK）", file=sys.stderr)
        return 2
    try:
        report = check_jd(raw, config_path=args.config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"cn_jd_check: 配置读取或校验失败：{exc}；请检查 --config 路径、JSON 格式及字段类型，参阅 docs/cn/岗位检查器.md", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
