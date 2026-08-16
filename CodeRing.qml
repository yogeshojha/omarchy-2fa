import QtQuick
import qs.Commons

// `progress` is the fraction of the window remaining.
Canvas {
  id: root

  property real progress: 0
  property color ringColor: Color.accent
  property color trackColor: Util.alpha(Color.foreground, 0.16)
  property real thickness: Math.max(1, Math.round(Math.min(width, height) * 0.16))

  antialiasing: true

  onProgressChanged: requestPaint()
  onRingColorChanged: requestPaint()
  onTrackColorChanged: requestPaint()
  onThicknessChanged: requestPaint()
  onWidthChanged: requestPaint()
  onHeightChanged: requestPaint()

  onPaint: {
    var context = getContext("2d")
    context.clearRect(0, 0, width, height)

    var radius = Math.min(width, height) / 2 - thickness / 2
    if (radius <= 0) return

    var centerX = width / 2
    var centerY = height / 2
    var start = -Math.PI / 2

    context.lineWidth = thickness
    context.lineCap = "butt"

    context.beginPath()
    context.arc(centerX, centerY, radius, 0, Math.PI * 2)
    context.strokeStyle = trackColor
    context.stroke()

    var sweep = Math.PI * 2 * Math.max(0, Math.min(1, progress))
    if (sweep <= 0) return

    context.beginPath()
    context.arc(centerX, centerY, radius, start, start + sweep)
    context.strokeStyle = ringColor
    context.stroke()
  }
}
