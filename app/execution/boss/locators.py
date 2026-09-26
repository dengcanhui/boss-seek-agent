"""BOSS 求职页面定位器与接口地址。

已确认的接口来自 ``data/boss.json``。页面选择器集中放在这里，后续页面结构变化时
只需要改这一处，不要把 CSS/XPath 散落到执行流程中。
"""

JOB_LIST_API = "/wapi/zpgeek/search/joblist.json"
JOB_DETAIL_API = "/wapi/zpgeek/job/detail.json"

# 这两个选择器来自当前 BOSS 搜索页常见结构；如果现场页面有变化，只改这里。
JOB_LIST_CONTAINER = ".job-list-container"
JOB_CARD = ".job-list-container .job-card-box"

# “立即沟通/打招呼”按钮，以及打招呼后弹窗的关闭按钮。
GREET_BUTTON = ".job-detail-header a.op-btn-chat"
GREET_DIALOG_CLOSE = ".greet-boss-dialog .icon-close"
GREET_STAY_PAGE = ".greet-boss-dialog .cancel-btn"
