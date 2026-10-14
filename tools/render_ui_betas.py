"""Render real Qt widgets offscreen; the synthetic archive never touches disk."""
import os
import sys
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QFontDatabase, QFont
from stellasora_toolkit.ui.window import StellaSoraApp
from stellasora_toolkit.ui.beta_styles import VARIANTS


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    # The offscreen platform has no system font discovery on Windows.
    for font in ('msyh.ttc','msyhbd.ttc','bahnschrift.ttf','simsun.ttc'):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/font))
    app.setFont(QFont('Microsoft YaHei UI',10))
    destination = Path(__file__).resolve().parents[1] / 'ui-beta' / 'screenshots'
    destination.mkdir(parents=True,exist_ok=True)
    for variant in VARIANTS:
        window = StellaSoraApp(Path(__file__).resolve().parents[1] / 'exports',variant=variant,demo=True)
        window.resize(1440,1080)
        window.show()
        settle(app)
        window.grab().save(str(destination / f'{variant}-home.png'))
        window.resize(960,760)
        settle(app)
        window.grab().save(str(destination / f'{variant}-compact.png'))
        window.resize(1440,1080)
        settle(app)
        window.open_records('traveler_limited')
        settle(app)
        window.grab().save(str(destination / f'{variant}-records.png'))
        window.navigate(2)
        settle(app)
        window.grab().save(str(destination / f'{variant}-settings.png'))
        window.close()
        window.deleteLater()
        app.processEvents()
        print(f'Rendered {variant}')
    contact_sheet(destination)


def contact_sheet(destination):
    from PIL import Image, ImageDraw, ImageFont
    sheet = Image.new('RGB',(1848,526),'#edf2f6')
    draw = ImageDraw.Draw(sheet)
    font_path = Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'msyh.ttc'
    title_font = ImageFont.truetype(str(font_path),21)
    caption_font = ImageFont.truetype(str(font_path),13)
    descriptions = {'orbit':'深海蓝 / 头像星轨 / 侧栏导航','sky':'冰蓝白 / 清晰统计 / 横向导航','journal':'雾紫纸张 / 相遇照片 / 收藏档案'}
    for i,(key,name) in enumerate(VARIANTS.items()):
        x = 12+i*612
        draw.text((x+8,9),name,font=title_font,fill='#26394a')
        draw.text((x+8,40),descriptions[key],font=caption_font,fill='#718394')
        screenshot = Image.open(destination / f'{key}-home.png').convert('RGB')
        screenshot = screenshot.resize((600,450),Image.Resampling.LANCZOS)
        sheet.paste(screenshot,(x,68))
    sheet.save(destination.parent/'comparison.png')


def settle(app):
    for _ in range(8):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)


if __name__ == '__main__': main()
