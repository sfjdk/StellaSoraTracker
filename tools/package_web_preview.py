"""Create a standalone shareable HTML, including all screenshots inline."""
import base64
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    template = (root/'ui-beta/index.html').read_text(encoding='utf-8')
    images = {}
    for variant in ('orbit','sky','journal'):
        for page in ('home','records','settings','compact'):
            key = f'{variant}-{page}'
            data = (root/f'ui-beta/screenshots/{key}.png').read_bytes()
            images[key] = 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')
    html = template.replace('const screenshotSources={};',
                            'const screenshotSources='+json.dumps(images,separators=(',',':'))+';')
    html = html.replace('src="screenshots/orbit-home.png"','src="'+images['orbit-home']+'"')
    html = html.replace('href="screenshots/orbit-home.png"','href="'+images['orbit-home']+'"')
    # A data URL can be downloaded reliably by file:// and HTTPS browsers alike.
    # Top-level navigation to data URLs is restricted in several browsers.
    html = html.replace('id="full"','id="full" download="StellaSora-UI-Beta.png"')
    html = html.replace('查看原尺寸 ↗','下载原尺寸图片 ↓')
    html = html.replace('点击“查看原尺寸”可放大查看细节。','点击“下载原尺寸图片”可保存大图，放大查看细节。')
    html = html.replace("link.href=image.src;link.target='_blank';", "link.href=image.src;link.download=`StellaSora-${key}-${page}.png`;link.target='_blank';")
    for target in (root/'release/StellaSora-UI-Beta-Preview.html',):
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(html,encoding='utf-8',newline='\n')
        print(f'{target}: {target.stat().st_size:,} bytes / {len(images)} embedded screenshots')


if __name__ == '__main__': main()
