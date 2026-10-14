"""Native beta screens. All displayed statistics come from the existing engine."""
from datetime import datetime

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QPixmap, QPainterPath
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout,
    QScrollArea, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
)

from ..catalog import same_item_name, gacha_item_name, is_five_star_item
from ..gacha_stats import build_banner_stats_with_shared_pity
from ..official_banners import official_pool_info
from .constants import GACHA_CATEGORY_ORDER, GACHA_CATEGORY_NAMES, GACHA_CATEGORY_PITY_LIMITS, OFFICIAL_LIMITED_POOL_INFO
from .beta_model import overview, categories, is_up
from .theme import get_palette
from .widgets import Card, PityBar, AvatarLabel, mk_label, mk_divider, FlowLayout
from .views import clear_layout, _up_average, _fortune_today, _load_fortune, _save_fortune, _fortune_eval, _luck_rank


def button(text, callback, role='ghost'):
    b = QPushButton(text)
    b.setProperty('role', role)
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(callback)
    return b


def scroll(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return area


def label(text, size=None, color=None, bold=False, role='body'):
    w = mk_label(text, role, wrap=False)
    declarations = []
    if size: declarations.append(f'font-size:{size}px')
    if color: declarations.append(f'color:{color}')
    if bold: declarations.append('font-weight:700')
    if declarations: w.setStyleSheet(';'.join(declarations))
    return w


def date(ts):
    return datetime.fromtimestamp(ts).strftime('%Y.%m.%d') if ts else '暂无日期'


def badge(text, color=None):
    p = get_palette()
    w = label(text, 10, color or p.PRIMARY, True)
    w.setStyleSheet(f'color:{color or p.PRIMARY};background:{p.SURFACE2};border-radius:4px;padding:3px 7px;font-size:10px;font-weight:700;')
    w.setFixedHeight(22)
    return w


class StarMap(QWidget):
    """A constellation made from actual recent five-star results."""
    def __init__(self, pulls, variant):
        super().__init__()
        self.pulls, self.variant = pulls[:4], variant
        self.setMinimumWidth(280)
        self.setFixedHeight(108)

    def paintEvent(self, event):
        p = get_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if self.variant == 'orbit':
            painter.setPen(QPen(QColor(p.LINE), 1))
            painter.drawEllipse(QRectF(w * .25, 8, w * .55, 110))
            painter.drawEllipse(QRectF(w * .34, 22, w * .38, 80))
            coords = [(w*.24, h*.66), (w*.45,h*.34), (w*.66,h*.65), (w*.86,h*.30)]
            for a, b in zip(coords, coords[1:]):
                painter.drawLine(int(a[0]), int(a[1]), int(b[0]), int(b[1]))
            for i in range(22):
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(p.MUTED if i % 3 else p.ACCENT))
                x, y = (i * 67 + 9) % max(1, w-5), (i * 43 + 11) % (h-8)
                painter.drawEllipse(QRectF(x,y,2,2))
            for (x,y), pull in zip(coords,self.pulls):
                self._portrait(painter,pull,QRectF(x-23,y-23,46,46),True)
        else:
            for i, pull in enumerate(self.pulls):
                x = 12 + i * (w-22)/4
                painter.save()
                painter.translate(x+36,h/2)
                painter.rotate([-6,3,-3,6][i] if self.variant == 'journal' else 0)
                box = QRectF(-34,-47,68,94)
                painter.setPen(QPen(QColor(p.LINE),1))
                painter.setBrush(QColor(p.SURFACE))
                painter.drawRoundedRect(box,4,4)
                self._portrait(painter,pull,QRectF(-29,-42,58,58),False)
                painter.setPen(QColor(p.PRIMARY))
                painter.setFont(QFont('Microsoft YaHei UI',8))
                painter.drawText(QRectF(-34,22,68,18),Qt.AlignCenter,pull.name[:5])
                painter.restore()
        painter.end()

    @staticmethod
    def _portrait(painter,pull,rect,circle):
        pix = QPixmap(AvatarLabel.resource_path(pull.item_id,pull.kind))
        painter.save()
        path = QPainterPath()
        if circle: path.addEllipse(rect)
        else: path.addRoundedRect(rect,4,4)
        painter.setClipPath(path)
        painter.fillRect(rect,QColor(get_palette().SURFACE2))
        if not pix.isNull(): painter.drawPixmap(rect,pix,QRectF(pix.rect()))
        painter.restore()
        painter.setPen(QPen(QColor(get_palette().PRIMARY),1))
        painter.setBrush(Qt.NoBrush)
        if circle: painter.drawEllipse(rect)


class PoolCard(Card):
    def __init__(self, cat, stats, variant, open_records):
        super().__init__(pad=18)
        self.body().setContentsMargins(16,14,16,14)
        self.body().setSpacing(6)
        p = get_palette()
        self.cat, self.stats = cat, stats
        self.setMinimumWidth(215)
        self.setMinimumHeight(160 if variant != 'journal' else 280)
        top = QHBoxLayout()
        name = GACHA_CATEGORY_NAMES[cat].replace('招募','')
        top.addWidget(label(name,15,p.TEXT,True))
        top.addStretch()
        top.addWidget(badge('限时' if 'limited' in cat else '常驻'))
        self.body().addLayout(top)
        numbers = QHBoxLayout()
        total = stats.total_pulls if stats else 0
        five = len(stats.five_stars) if stats else 0
        numbers.addWidget(label(f'{total:,}',30,p.TEXT,True))
        numbers.addWidget(label('抽',12,p.MUTED),0,Qt.AlignBottom)
        numbers.addStretch()
        numbers.addWidget(label(f'五星  {five}',12,p.MUTED))
        self.body().addLayout(numbers)
        if variant == 'journal':
            self.add(mk_divider())
            hits = QHBoxLayout()
            for pull in (stats.five_stars[:3] if stats else []):
                portrait = AvatarLabel(pull.item_id,pull.kind,56)
                portrait.setToolTip(f'{pull.name} · {pull.pity} 抽')
                hits.addWidget(portrait)
            hits.addStretch()
            self.body().addLayout(hits)
            self.add(label('最近的相遇',11,p.MUTED))
            self.body().addStretch()
        limit = GACHA_CATEGORY_PITY_LIMITS[cat]
        pity = stats.current_pity if stats else 0
        row = QHBoxLayout()
        row.addWidget(label(f'当前垫抽  {pity}',12,p.PRIMARY,True))
        row.addStretch()
        row.addWidget(label(f'/ {limit}',11,p.MUTED))
        self.body().addLayout(row)
        bar = PityBar(height=5)
        bar.set_stat(pity,limit)
        self.add(bar)
        foot = QHBoxLayout()
        avg = (_up_average(stats) if 'limited' in cat else stats.average_pulls) if stats else None
        foot.addWidget(label(('UP 平均' if 'limited' in cat else '五星平均') + f'  {avg if avg is not None else "—"} 抽',11,p.MUTED))
        foot.addStretch()
        link = button('查看记录  →',lambda:open_records(cat),'ghost')
        link.setStyleSheet(f'border:0;padding:3px;color:{p.PRIMARY};font-size:11px;')
        foot.addWidget(link)
        self.body().addLayout(foot)
        if not stats: self.setToolTip('先在游戏中打开此类招募记录，再刷新游戏数据。')


class HomeView(QWidget):
    def __init__(self, variant, open_records, demo=False):
        super().__init__()
        self.variant, self.open_records, self.demo = variant, open_records, demo
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        wrap = QWidget()
        self.col = QVBoxLayout(wrap)
        self.col.setContentsMargins(28,24,28,24)
        self.col.setSpacing(14)
        self.col.setAlignment(Qt.AlignTop)
        root.addWidget(scroll(wrap))
        self.cards = []

    def render(self, records):
        clear_layout(self.col)
        self.cards = []
        p = get_palette()
        stats = overview(records)
        pulls = sorted([pull for s in stats.category_stats.values() if s for pull in s.five_stars],key=lambda pull:pull.timestamp,reverse=True)
        title_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title_col.addWidget(label('招募总览' if self.variant != 'journal' else '我的相遇手札',25,p.TEXT,True))
        title_col.addWidget(label('四类卡池 · 本地归档 · 每一次相遇都有迹可循',12,p.MUTED))
        title_row.addLayout(title_col)
        title_row.addStretch()
        title_row.addWidget(badge('演示记录' if self.demo else '本地记录'))
        self.col.addLayout(title_row)
        hero = Card(pad=20)
        hero.setObjectName('Hero')
        if self.variant == 'orbit': hero.setStyleSheet(f'QFrame#Hero {{background:#203452;border:1px solid {p.LINE};border-radius:16px;}}')
        hero_row = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(8)
        text.addWidget(label({'orbit':'STELLA SORA / YOUR CONSTELLATION','sky':'STELLA SORA / RECRUITMENT ARCHIVE','journal':'STELLA SORA / MEMORIES OF ENCOUNTERS'}[self.variant],role='eyebrow'))
        title = label({'orbit':'把每一次相遇，留在星轨里。','sky':'你的招募，一目了然。','journal':'每次相遇，都值得收藏。'}[self.variant],24,p.TEXT,True)
        if self.variant == 'journal': title.setStyleSheet(f'font-family:"SimSun";font-size:25px;color:{p.TEXT};font-weight:700;')
        title.setWordWrap(True)
        text.addWidget(title)
        latest = pulls[0] if pulls else None
        text.addWidget(label(f'最近获得  {latest.name}   ·   {date(latest.timestamp)}' if latest else '先在游戏中打开招募记录，再点击「刷新游戏数据」。',12,p.MUTED))
        rank = _luck_rank(stats.total_pulls/stats.total_five if stats.total_five else None)[0]
        fortune_row = QHBoxLayout()
        fortune_row.addWidget(badge(f'欧气评级 · {rank}',p.ACCENT))
        fortune_row.addWidget(button('查看今日运势',self.reveal_fortune,'ghost'))
        fortune_row.addStretch()
        text.addLayout(fortune_row)
        hero_row.addLayout(text,3)
        self.star_map = StarMap(pulls,self.variant)
        self.star_map.setVisible(self.width() >= 850)
        hero_row.addWidget(self.star_map,2)
        hero.body().addLayout(hero_row)
        self.col.addWidget(hero)
        metrics = QHBoxLayout()
        metrics.setSpacing(0)
        summary = Card(pad=16)
        rate = f'{stats.total_five/stats.total_pulls*100:.2f}%' if stats.total_pulls else '—'
        avg = f'{stats.total_pulls/stats.total_five:.1f}' if stats.total_five else '—'
        for i,(value,caption) in enumerate([(f'{stats.total_pulls:,}','累计招募'),(str(stats.total_five),'五星记录'),(avg,'每个五星平均抽数'),(rate,'五星占比')]):
            metric = QWidget()
            ml = QVBoxLayout(metric)
            ml.setContentsMargins(14,0,14,0)
            ml.setSpacing(2)
            ml.addWidget(label(value,28,p.TEXT,True))
            ml.addWidget(label(caption,11,p.MUTED))
            metrics.addWidget(metric,1)
        summary.body().addLayout(metrics)
        self.col.addWidget(summary)
        section = QHBoxLayout()
        section.addWidget(label('卡池档案' if self.variant == 'journal' else '卡池概览',16,p.TEXT,True))
        section.addStretch()
        section.addWidget(label(f'{sum(s is not None for s in stats.category_stats.values())} / 4 类已有归档',11,p.MUTED))
        self.col.addLayout(section)
        self.grid = QGridLayout()
        self.grid.setSpacing(16)
        for cat in GACHA_CATEGORY_ORDER:
            card = PoolCard(cat,stats.category_stats[cat],self.variant,self.open_records)
            self.cards.append(card)
        self._columns = 0
        self._reflow()
        self.col.addLayout(self.grid)
        if stats.well_banners:
            names = '、'.join(info[3] for gid in stats.well_banners if (info:=official_pool_info(gid)))
            self.col.addWidget(label(f'UP 必得 · 120 抽达成   {names or "已达成的限时卡池"}',12,p.ACCENT))
        recent = Card(pad=16)
        row = QHBoxLayout()
        row.addWidget(label('最近的五星相遇',14,p.TEXT,True))
        row.addStretch()
        row.addWidget(button('全部记录 →',lambda:self.open_records('all'),'ghost'))
        recent.body().addLayout(row)
        flow = FlowLayout(spacing=18)
        for pull in pulls[:5]:
            tile = QWidget()
            tl = QHBoxLayout(tile)
            tl.setContentsMargins(0,0,0,0)
            tl.addWidget(AvatarLabel(pull.item_id,pull.kind,44))
            names = QVBoxLayout()
            names.setSpacing(3)
            names.addWidget(label(pull.name,12,p.TEXT,True))
            names.addWidget(label(f'{pull.pity} 抽 · {date(pull.timestamp)}',10,p.MUTED))
            tl.addLayout(names)
            flow.addWidget(tile)
        if not pulls: flow.addWidget(label('暂无五星记录，刷新后会显示在这里。',12,p.MUTED))
        fw = QWidget(); fw.setLayout(flow)
        recent.add(fw)
        self.col.addWidget(recent)

    def _reflow(self):
        if not self.cards: return
        columns = 4 if self.variant == 'journal' and self.width() >= 1080 else 2 if self.width() >= 650 else 1
        if columns == self._columns: return
        for card in self.cards: self.grid.removeWidget(card)
        for i,card in enumerate(self.cards): self.grid.addWidget(card,i//columns,i%columns)
        self._columns = columns

    def resizeEvent(self,event):
        if hasattr(self,'star_map'): self.star_map.setVisible(self.width() >= 850)
        self._reflow()
        super().resizeEvent(event)

    def reveal_fortune(self):
        import random
        from PySide6.QtWidgets import QMessageBox
        day = _fortune_today()
        # Demo stays read-only, including fortune storage.
        score = 76 if self.demo else _load_fortune(day)
        if score is None:
            score = random.randint(0,100)
            _save_fortune(score,day)
        title,desc,_ = _fortune_eval(score)
        QMessageBox.information(self,'今日运势',f'{title} · {score} 分\n{desc}\n\n运势仅供娱乐，与实际抽卡概率无关。')


class RecordsView(QWidget):
    def __init__(self):
        super().__init__()
        self.records, self.current, self.query, self.all_pulls = [], 'all', '', False
        col = QVBoxLayout(self)
        col.setContentsMargins(28,24,28,20)
        col.setSpacing(16)
        top = QHBoxLayout()
        top.addWidget(label('招募记录',25,bold=True))
        top.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索旅人、秘纹或卡池名称')
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(300)
        self.search.textChanged.connect(self.set_query)
        top.addWidget(self.search)
        self.mode = button('查看全部抽卡',self.toggle_mode)
        top.addWidget(self.mode)
        col.addLayout(top)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.filters = {}
        for cat,name in [('all','全部卡池')]+[(c,GACHA_CATEGORY_NAMES[c].replace('招募','')) for c in GACHA_CATEGORY_ORDER]:
            b = button(name,lambda _,c=cat:self.set_filter(c),'filter')
            b.setCheckable(True)
            self.filters[cat] = b
            filters.addWidget(b)
        filters.addStretch()
        col.addLayout(filters)
        self.summary = label('',12,get_palette().MUTED)
        col.addWidget(self.summary)
        wrap = QWidget()
        self.content = QVBoxLayout(wrap)
        self.content.setContentsMargins(0,0,0,0)
        self.content.setSpacing(16)
        self.content.setAlignment(Qt.AlignTop)
        col.addWidget(scroll(wrap),1)

    def set_filter(self,category):
        self.current = category
        self.render(self.records)

    def set_query(self,value):
        self.query = value.casefold().strip()
        self.render(self.records)

    def toggle_mode(self):
        self.all_pulls = not self.all_pulls
        self.mode.setText('查看五星记录' if self.all_pulls else '查看全部抽卡')
        self.render(self.records)

    def render(self,records):
        self.records = records
        clear_layout(self.content)
        for key,b in self.filters.items(): b.setChecked(key == self.current)
        grouped = categories(records)
        selected = GACHA_CATEGORY_ORDER if self.current == 'all' else [self.current]
        self.summary.setText('按时间倒序 · 限时卡池垫抽跨池继承 · UP 与歪分别标注')
        if self.all_pulls:
            self._table(grouped,selected)
            return
        count = 0
        p = get_palette()
        for cat in selected:
            pools = build_banner_stats_with_shared_pity(grouped[cat],is_up=is_up if 'limited' in cat else None)
            for pool in pools:
                info = official_pool_info(pool.gid)
                name = info[0] if info else GACHA_CATEGORY_NAMES[cat] if pool.gid in (1,2) else f'卡池 {pool.gid}'
                match_pool = self.query in name.casefold()
                hits = [pull for pull in pool.five_stars if not self.query or match_pool or self.query in pull.name.casefold()]
                if self.query and not hits and not match_pool: continue
                card = Card(pad=20)
                top = QHBoxLayout()
                names = QVBoxLayout()
                names.setSpacing(5)
                names.addWidget(label(name,17,p.TEXT,True))
                names.addWidget(label(f'{info[1]} — {info[2]}  ·  {GACHA_CATEGORY_NAMES[cat]}' if info else f'{date(pool.start_time)} — {date(pool.end_time)}  ·  ID {pool.gid}',11,p.MUTED))
                top.addLayout(names,1)
                if pool.gid in overview(records).well_banners: top.addWidget(badge('井 · 120 抽达成',p.ACCENT))
                top.addWidget(badge(f'{pool.total_pulls} 抽 / {len(pool.five_stars)} 五星'))
                card.body().addLayout(top)
                card.add(mk_divider())
                flow = FlowLayout(spacing=16)
                for pull in hits:
                    tile = QFrame()
                    tile.setMinimumWidth(236)
                    tl = QHBoxLayout(tile)
                    tl.setContentsMargins(0,6,12,6)
                    tl.addWidget(AvatarLabel(pull.item_id,pull.kind,56))
                    names = QVBoxLayout()
                    names.addWidget(label(pull.name,13,p.TEXT,True))
                    names.addWidget(label(f'{pull.pity} 抽 · {date(pull.timestamp)}',11,p.MUTED))
                    tl.addLayout(names,1)
                    if info: tl.addWidget(badge('UP' if same_item_name(pull.name,info[3]) else '歪',p.PRIMARY if same_item_name(pull.name,info[3]) else p.DANGER))
                    flow.addWidget(tile)
                fw = QWidget(); fw.setLayout(flow)
                if not hits: card.add(label('此卡池已有归档，暂未获得五星。',12,p.MUTED))
                else: card.add(fw)
                self.content.addWidget(card)
                count += 1
        if not count:
            self.content.addWidget(label('没有符合条件的记录。清除搜索，或先在游戏中打开招募记录再刷新。',13,p.MUTED))

    def _table(self,grouped,selected):
        rows = []
        for cat in selected:
            for group in sorted(grouped[cat],key=lambda g:g.get('Time',0),reverse=True):
                gid = group.get('Gid',0)
                info = official_pool_info(gid)
                pool_name = info[0] if info else GACHA_CATEGORY_NAMES[cat] if gid in (1,2) else f'卡池 {gid}'
                for iid in reversed(group.get('Ids',[])):
                    name = gacha_item_name(iid)
                    if self.query and self.query not in (name+pool_name).casefold(): continue
                    star = is_five_star_item(iid)
                    result = 'UP' if star and info and same_item_name(name,info[3]) else '歪' if star and info else '—'
                    rows.append((date(group.get('Time',0)),name,'五星' if star else '普通',pool_name,result))
        table = QTableWidget(len(rows),5)
        table.setHorizontalHeaderLabels(['日期','旅人 / 秘纹','稀有度','所属卡池','结果'])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for i,row in enumerate(rows):
            for j,value in enumerate(row): table.setItem(i,j,QTableWidgetItem(value))
        table.setMinimumHeight(450)
        table.setSortingEnabled(True)
        self.content.addWidget(table)
        self.summary.setText(f'全部抽卡明细 · 当前筛选 {len(rows):,} 条 · 点击表头可排序')
