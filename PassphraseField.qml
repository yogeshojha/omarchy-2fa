import QtQuick
import qs.Commons
import qs.Ui

// `claimsFocus` makes this the panel's keyboard target.
TextField {
  id: root

  property QtObject panel: null
  property bool claimsFocus: false

  width: parent ? parent.width : implicitWidth
  password: true
  foreground: panel ? panel.foreground : Color.foreground
  accent: panel ? panel.accent : Color.accent

  Component.onCompleted: {
    if (!claimsFocus || !panel) return
    panel.focusField = this
    forceActiveFocus()
  }

  Component.onDestruction: {
    if (panel && panel.focusField === this) panel.focusField = null
  }
}
