import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root

  moduleName: "yogeshojha.twofa"
  ipcTarget: "yogeshojha.twofa"

  implicitWidth: barSlot.implicitWidth
  implicitHeight: barSlot.implicitHeight

  property bool settingsOpen: false
  property bool passphraseFormOpen: false
  property bool cameraScanning: false
  property string filter: ""
  property int cursor: 0
  property string notice: ""
  property bool noticeIsError: false
  property var pendingRemoval: null
  property var focusField: null
  property var importField: null

  readonly property color foreground: Color.popups.text
  readonly property color accent: Color.accent
  readonly property color urgent: Color.urgent
  readonly property color dim: Color.muted
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property string barDisplay: Model.barDisplay(setting("barDisplay", "Icon"))
  readonly property string autoLock: Model.oneOf(setting("autoLock", "Never"), Model.AUTO_LOCK_OPTIONS)
  readonly property string clipboardWipe: Model.oneOf(setting("clipboardWipe", "30 seconds"), Model.CLIPBOARD_OPTIONS)
  readonly property bool groupDigits: Model.boolean(setting("groupDigits", true), true)
  readonly property string pinnedQuery: String(setting("pinned", "") || "")

  readonly property var accounts: vault.accounts
  readonly property var visibleAccounts: Model.filterAccounts(accounts, filter)
  readonly property var selected: visibleAccounts.length > 0
    ? visibleAccounts[Math.max(0, Math.min(cursor, visibleAccounts.length - 1))]
    : null
  readonly property var pinned: Model.findPinned(accounts, pinnedQuery)
  readonly property bool removalOpen: !!pendingRemoval
  readonly property string vaultState: vault.vaultState
  readonly property bool vaultUnlocked: vault.unlocked
  readonly property double vaultNow: vault.now

  readonly property int rowHeight: Style.space(46)
  readonly property int maxVisibleRows: 7

  readonly property string view: {
    if (vault.vaultState === Model.VAULT_UNAVAILABLE) return "unavailable"
    if (vault.vaultState === Model.VAULT_STARTING) return "starting"
    if (vault.vaultState === Model.VAULT_MISSING) return "create"
    if (vault.vaultState === Model.VAULT_LOCKED) return "unlock"
    if (cameraScanning) return "camera"
    if (settingsOpen) return "settings"
    return accounts.length > 0 ? "list" : "empty"
  }

  // ------------------------------------------------------------- actions

  function setFilter(next) {
    filter = next
    cursor = 0
  }

  function moveCursor(delta) {
    if (visibleAccounts.length === 0) return
    cursor = Math.max(0, Math.min(visibleAccounts.length - 1, cursor + delta))
  }

  function setNotice(text, isError) {
    notice = text
    noticeIsError = !!isError
    noticeTimer.restart()
  }

  function clearNotice() {
    notice = ""
    noticeIsError = false
    noticeTimer.stop()
  }

  function copyAccount(account) {
    if (!account) return
    if (!account.supported) {
      setNotice("Counter-based accounts cannot be copied yet", true)
      return
    }
    vault.copy(account.id, Model.clipboardSeconds(clipboardWipe), function(response) {
      if (!response.ok) {
        setNotice(Model.errorText(response), true)
        return
      }
      var seconds = Model.clipboardSeconds(root.clipboardWipe)
      setNotice("Copied " + Model.accountTitle(account)
        + (seconds > 0 ? " · clears in " + seconds + "s" : ""), false)
    })
  }

  function pinAccount(account) {
    if (!account) return
    persist({ pinned: Model.accountTitle(account) })
    setNotice("Pinned " + Model.accountTitle(account), false)
  }

  function requestRemoval(account) {
    if (!account) return
    // ConfirmDialog defaults to the destructive button.
    removalDialog.selectedIndex = 0
    pendingRemoval = account
  }

  function cancelRemoval() {
    pendingRemoval = null
  }

  function confirmRemoval() {
    var account = pendingRemoval
    pendingRemoval = null
    if (!account) return
    vault.remove(account.id, function(response) {
      setNotice(response.ok ? "Removed " + Model.accountTitle(account) : Model.errorText(response), !response.ok)
    })
  }

  function announceImport(response) {
    setNotice(Model.importSummary(response), Model.number(response.added) === 0)
  }

  function reportImport(response) {
    if (response.ok) {
      announceImport(response)
      return
    }
    if (response.error !== "cancelled") setNotice(Model.errorText(response), true)
  }

  // The panel covers the QR.
  function scanRegion() {
    close()
    vault.scan(function(response) {
      root.reportImport(response)
      root.open()
    })
  }

  function startCamera() {
    clearNotice()
    vault.cameraStart(function(response) {
      if (!response.ok) {
        root.setNotice(Model.errorText(response), true)
        return
      }
      root.cameraScanning = true
      cameraPoll.restart()
    })
  }

  function stopCamera() {
    if (!cameraScanning) return
    cameraScanning = false
    cameraPoll.stop()
    vault.cameraStop()
  }

  function finishCamera(response) {
    cameraScanning = false
    cameraPoll.stop()
    if (response.cancelled) return
    if (response.message) {
      setNotice(Model.sentence(response.message), true)
      return
    }
    announceImport(response)
    if (Model.number(response.added) > 0) vault.refreshCodes()
  }

  function addFromText(text) {
    var trimmed = String(text || "").trim()
    if (!trimmed) return
    vault.add(trimmed, function(response) {
      root.reportImport(response)
      if (response.ok && root.importField) root.importField.clear()
    })
  }

  function unlockWith(passphrase) {
    vault.unlock(passphrase, function(response) {
      if (response.ok) root.clearNotice()
      else setNotice(Model.errorText(response), true)
    })
  }

  function createWith(passphrase, repeated) {
    if (passphrase !== repeated) {
      setNotice("The passphrases do not match", true)
      return
    }
    vault.create(passphrase, function(response) {
      if (response.ok) setNotice("Vault created — import your accounts", false)
      else setNotice(Model.errorText(response), true)
    })
  }

  function changePassphrase(current, next, repeated) {
    if (next !== repeated) {
      setNotice("The new passphrases do not match", true)
      return
    }
    vault.changePassphrase(current, next, function(response) {
      if (!response.ok) {
        setNotice(Model.errorText(response), true)
        return
      }
      root.passphraseFormOpen = false
      setNotice("Passphrase changed", false)
    })
  }

  function lockNow() {
    settingsOpen = false
    setFilter("")
    vault.lock()
  }

  // The panel claims focus itself once its surface maps.
  function refocus() {
    Qt.callLater(function() {
      if (!root.opened) return
      if (root.focusField && root.focusField.forceActiveFocus) root.focusField.forceActiveFocus()
      else keys.forceActiveFocus()
    })
  }

  function persist(values) {
    var entry = { id: root.moduleName }
    var current = root.settings || ({})
    for (var existing in current) if (existing !== "id") entry[existing] = current[existing]
    for (var key in values) entry[key] = values[key]

    root.settings = entry
    if (root.bar && root.bar.shell && typeof root.bar.shell.updateEntryInline === "function")
      root.bar.shell.updateEntryInline(root.moduleName, entry)
  }

  // ------------------------------------------------------------- keyboard

  // Letters go to the filter, so no shortcut is a bare letter.
  function handleKey(event) {
    // The confirmation takes every key, Tab included.
    if (removalOpen) {
      if (removalDialog.handleKey(event)) event.accepted = true
      return
    }

    if (event.key === Qt.Key_Escape) {
      if (cameraScanning) stopCamera()
      else if (passphraseFormOpen) passphraseFormOpen = false
      else if (settingsOpen) settingsOpen = false
      else if (filter) setFilter("")
      else close()
      event.accepted = true
      return
    }

    if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
      switchPanel((event.modifiers & Qt.ShiftModifier) || event.key === Qt.Key_Backtab ? -1 : 1)
      event.accepted = true
      return
    }

    // Ctrl+U still has to reach the filter editor below.
    if (event.modifiers & Qt.ControlModifier) {
      if (vaultUnlocked && event.key === Qt.Key_L) { lockNow(); event.accepted = true; return }
      if (vaultUnlocked && event.key === Qt.Key_S) { settingsOpen = !settingsOpen; event.accepted = true; return }
      if (vaultUnlocked && event.key === Qt.Key_I) { scanRegion(); event.accepted = true; return }
      if (vaultUnlocked && event.key === Qt.Key_W) { startCamera(); event.accepted = true; return }
      if (view === "list" && event.key === Qt.Key_P) { pinAccount(selected); event.accepted = true; return }
    }

    if (view !== "list") return

    if (event.key === Qt.Key_Down) { moveCursor(1); event.accepted = true; return }
    if (event.key === Qt.Key_Up) { moveCursor(-1); event.accepted = true; return }
    if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
      copyAccount(selected)
      event.accepted = true
      return
    }
    if (event.key === Qt.Key_Delete) {
      requestRemoval(selected)
      event.accepted = true
      return
    }

    if (Util.editsFilter(event, filter)) {
      setFilter(Util.editedFilter(event, filter))
      event.accepted = true
      return
    }

    if (event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)) return
    if (event.text && event.text.length === 1 && event.text.charCodeAt(0) >= 32) {
      setFilter(filter + event.text)
      event.accepted = true
    }
  }

  onOpenedChanged: {
    stopCamera()
    setFilter("")
    settingsOpen = false
    passphraseFormOpen = false
    pendingRemoval = null
    clearNotice()
    if (opened) {
      vault.refreshCodes()
      refocus()
    }
  }

  onViewChanged: refocus()

  onVisibleAccountsChanged: cursor = Math.max(0, Math.min(cursor, Math.max(0, visibleAccounts.length - 1)))

  VaultController {
    id: vault
    active: root.opened
    autoLockSeconds: Model.autoLockSeconds(root.autoLock)
  }

  Timer {
    id: cameraPoll
    interval: 400
    repeat: true
    onTriggered: vault.cameraStatus(function(response) {
      if (!response.ok) {
        root.stopCamera()
        root.setNotice(Model.errorText(response), true)
        return
      }
      if (response.done) root.finishCamera(response)
    })
  }

  Timer {
    id: noticeTimer
    interval: 4000
    repeat: false
    onTriggered: root.clearNotice()
  }

  BarSlot {
    id: barSlot
    anchors.fill: parent
    panel: root
  }

  KeyboardPanel {
    id: panel

    anchorItem: barSlot
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: root.focusField || keys
    centerOnBar: false
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(body.implicitHeight, Style.space(620))

    Item {
      id: keys

      anchors.fill: parent
      focus: true
      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function(event) { root.handleKey(event) }

      Column {
        id: body

        width: parent.width
        spacing: Style.spacing.md

        Item {
          width: parent.width
          height: header.implicitHeight

          Row {
            id: header
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.spacing.sm

            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: "\uf132"
              color: root.accent
              font.family: root.fontFamily
              font.pixelSize: Style.font.subtitle
            }

            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: "2FA"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.subtitle
              font.bold: true
            }

            Text {
              anchors.verticalCenter: parent.verticalCenter
              visible: root.vaultUnlocked && root.accounts.length > 0
              text: Model.pluralAccounts(root.accounts.length)
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.spacing.xxs

            PanelActionButton {
              visible: root.vaultUnlocked
              iconText: "\uf023"
              tooltipText: "Lock the vault"
              foreground: root.foreground
              hoverColor: root.accent
              fontFamily: root.fontFamily
              onClicked: root.lockNow()
            }

            PanelActionButton {
              visible: root.vaultUnlocked
              iconText: "\uf013"
              tooltipText: root.settingsOpen ? "Back to codes" : "Settings"
              foreground: root.settingsOpen ? root.accent : root.foreground
              hoverColor: root.accent
              fontFamily: root.fontFamily
              onClicked: root.settingsOpen = !root.settingsOpen
            }
          }
        }

        Text {
          width: parent.width
          visible: root.notice !== ""
          text: root.notice
          color: root.noticeIsError ? root.urgent : root.accent
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        PanelSeparator { foreground: root.foreground }

        Loader {
          id: content
          width: parent.width
          sourceComponent: {
            switch (root.view) {
              case "unavailable": return unavailableView
              case "starting": return startingView
              case "create": return createView
              case "unlock": return unlockView
              case "settings": return settingsView
              case "empty": return emptyView
              case "camera": return cameraView
            }
            return listView
          }
        }
      }

      ConfirmDialog {
        id: removalDialog
        anchors.fill: parent
        z: 20
        opened: root.removalOpen
        message: root.pendingRemoval
          ? "Remove " + Model.accountTitle(root.pendingRemoval) + "?"
            + "\n" + (root.pendingRemoval.label || root.pendingRemoval.issuer)
            + "\nYou will need to set this account up again to get codes for it."
          : ""
        confirmText: "Remove"
        background: Color.popups.background
        foreground: root.foreground
        selectedText: root.accent
        fontFamily: root.fontFamily
        cornerRadius: Style.cornerRadius
        onCanceled: root.cancelRemoval()
        onConfirmed: root.confirmRemoval()
      }
    }
  }

  // ------------------------------------------------------------- views

  Component {
    id: startingView

    Text {
      text: "Starting…"
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
    }
  }

  Component {
    id: unavailableView

    Column {
      spacing: Style.spacing.sm

      Text {
        text: "Cannot reach the 2FA helper"
        color: root.urgent
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }

      Text {
        width: parent.width
        text: "The omarchy-2fa file in the plugin folder may not be executable.\nFix that, then run: omarchy-shell shell rescanPlugins"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }
  }

  Component {
    id: createView

    Column {
      spacing: Style.spacing.lg

      PanelSectionHeader { foreground: root.foreground; fontFamily: root.fontFamily; text: "NEW VAULT" }

      Text {
        width: parent.width
        text: "This passphrase is the only key to your accounts. You enter it "
          + "once per session. It cannot be reset or recovered."
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      PassphraseField {
        id: newPassphrase
        panel: root
        claimsFocus: true
        placeholderText: "New passphrase"
        onAccepted: repeatPassphrase.forceActiveFocus()
      }

      PassphraseField {
        id: repeatPassphrase
        panel: root
        placeholderText: "Repeat passphrase"
        onAccepted: root.createWith(newPassphrase.text, repeatPassphrase.text)
      }

      Button {
        text: "Create vault"
        foreground: root.foreground
        accent: root.accent
        fontFamily: root.fontFamily
        bordered: true
        onClicked: root.createWith(newPassphrase.text, repeatPassphrase.text)
      }
    }
  }

  Component {
    id: unlockView

    Column {
      spacing: Style.spacing.lg

      PanelSectionHeader { foreground: root.foreground; fontFamily: root.fontFamily; text: "LOCKED" }

      PassphraseField {
        id: passphrase
        panel: root
        claimsFocus: true
        placeholderText: "Vault passphrase"
        onAccepted: root.unlockWith(passphrase.text)
      }

      Button {
        text: "Unlock"
        foreground: root.foreground
        accent: root.accent
        fontFamily: root.fontFamily
        bordered: true
        onClicked: root.unlockWith(passphrase.text)
      }
    }
  }

  Component {
    id: emptyView

    Column {
      spacing: Style.spacing.lg

      PanelSectionHeader { foreground: root.foreground; fontFamily: root.fontFamily; text: "IMPORT" }

      Text {
        width: parent.width
        text: "In Google Authenticator: ⋮ → Transfer accounts → Export accounts. "
          + "That one QR holds every account. Hold it up to your camera, or put "
          + "it on this screen and drag a box over it."
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      Row {
        width: parent.width
        spacing: Style.spacing.sm

        Button {
          text: "Scan the screen"
          iconText: "\uf029"
          foreground: root.foreground
          accent: root.accent
          fontFamily: root.fontFamily
          bordered: true
          onClicked: root.scanRegion()
        }

        Button {
          text: "Use the camera"
          iconText: "\uf030"
          foreground: root.foreground
          accent: root.accent
          fontFamily: root.fontFamily
          bordered: true
          onClicked: root.startCamera()
        }
      }

      TextField {
        id: manual
        width: parent.width
        placeholderText: "…or paste an otpauth:// link or image path"
        foreground: root.foreground
        accent: root.accent
        onAccepted: root.addFromText(manual.text)
        Component.onCompleted: {
          root.importField = this
          root.focusField = this
          forceActiveFocus()
        }
        Component.onDestruction: {
          if (root.importField === this) root.importField = null
          if (root.focusField === this) root.focusField = null
        }
      }

      Text {
        width: parent.width
        text: "^I scan  ^W camera  ↵ import pasted  ^S settings  ^L lock"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }
  }

  Component {
    id: cameraView

    Column {
      spacing: Style.spacing.lg

      Item {
        width: parent.width
        height: Style.space(84)

        Item {
          id: scanMark
          width: Style.space(64)
          height: width
          anchors.centerIn: parent

          CodeRing {
            anchors.fill: parent
            progress: 0.3
            ringColor: root.accent
            trackColor: Util.alpha(root.foreground, 0.12)

            RotationAnimation on rotation {
              from: 0
              to: 360
              duration: 1400
              loops: Animation.Infinite
              running: root.cameraScanning
            }
          }

          Text {
            anchors.centerIn: parent
            text: "\uf030"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
          }
        }
      }

      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: "Hold the export QR up to your camera"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }

      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: "Esc to stop"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }

  Component {
    id: settingsView

    SettingsView {
      panel: root
    }
  }

  Component {
    id: listView

    Column {
      spacing: Style.spacing.sm

      Row {
        width: parent.width
        spacing: Style.spacing.sm

        Text {
          anchors.verticalCenter: parent.verticalCenter
          text: "\uf002"
          color: root.filter ? root.accent : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }

        Text {
          anchors.verticalCenter: parent.verticalCenter
          text: root.filter || "Type to filter"
          color: root.filter ? root.foreground : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
        }
      }

      ListView {
        id: rows

        width: parent.width
        height: Math.max(root.rowHeight, Math.min(root.visibleAccounts.length, root.maxVisibleRows) * root.rowHeight)
        model: root.visibleAccounts
        currentIndex: root.cursor
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        highlightMoveDuration: 0
        onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)

        delegate: AccountRow {
          required property var modelData
          required property int index

          width: rows.width
          height: root.rowHeight
          account: modelData
          selected: index === root.cursor
          panel: root
          onActivated: root.copyAccount(modelData)
          onHovered: root.cursor = index
          onPinRequested: root.pinAccount(modelData)
          onRemoveRequested: root.requestRemoval(modelData)
        }
      }

      Text {
        width: parent.width
        visible: root.visibleAccounts.length === 0
        text: "No account matches “" + root.filter + "”"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      PanelSeparator { foreground: root.foreground }

      Text {
        width: parent.width
        text: "↵ copy  ↑↓ move  Del remove  ^P pin  ^I import  ^S settings  ^L lock"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }
  }

}
