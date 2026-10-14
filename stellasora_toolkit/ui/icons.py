"""Small vector icons rendered by Qt, independent of installed symbol fonts."""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QIcon, QPainterPath


def icon(name,color,size=18):
    pix = QPixmap(size,size); pix.fill(Qt.transparent)
    p = QPainter(pix); p.setRenderHint(QPainter.Antialiasing)
    p.scale(size/20,size/20)
    p.setPen(QPen(QColor(color),1.5,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    if name == 'home':
        for x,y in ((3,3),(12,3),(3,12),(12,12)): p.drawRoundedRect(QRectF(x,y,5,5),1,1)
    elif name == 'records':
        p.drawRoundedRect(QRectF(4,2,12,16),2,2)
        for y in (6,10,14): p.drawLine(7,y,13,y)
    elif name == 'settings':
        for y,x in ((4,8),(10,13),(16,6)):
            p.drawLine(2,y,18,y)
            p.setBrush(QColor(color)); p.drawEllipse(QPointF(x,y),2,2); p.setBrush(Qt.NoBrush)
    elif name == 'help':
        p.drawEllipse(QRectF(2,2,16,16))
        p.drawLine(10,9,10,14); p.drawPoint(10,6)
    elif name == 'refresh':
        p.drawArc(QRectF(3,3,14,14),35*16,290*16)
        path = QPainterPath(); path.moveTo(16,2); path.lineTo(17,7); path.lineTo(12,6)
        p.drawPath(path)
    p.end()
    return QIcon(pix)
