import QtQuick
import Quickshell.Io
import "Model.js" as Model

// Owns the helper process and the countdown clock.
Item {
  id: root

  width: 0
  height: 0
  visible: false

  property bool active: false
  property int autoLockSeconds: 0

  readonly property string helperPath: decodeURIComponent(
    String(Qt.resolvedUrl("omafob")).replace("file://", ""))

  readonly property string vaultState: _vaultState
  readonly property var accounts: _accounts
  readonly property double now: _now
  readonly property bool unlocked: _vaultState === Model.VAULT_UNLOCKED

  property string _vaultState: Model.VAULT_STARTING
  property var _accounts: []
  property double _now: 0
  property double _helperNow: 0
  property double _localBase: 0
  property bool _ready: false
  property int _sequence: 0
  property var _pending: ({})
  property var _queue: []

  // -------------------------------------------------------------- commands

  function refreshStatus(callback) {
    send({ cmd: "status" }, callback)
  }

  function refreshCodes(callback) {
    if (!unlocked) return
    send({ cmd: "codes" }, callback)
  }

  function create(passphrase, callback) {
    send({ cmd: "create", passphrase: passphrase }, _thenRefresh(callback))
  }

  function unlock(passphrase, callback) {
    send({ cmd: "unlock", passphrase: passphrase }, _thenRefresh(callback))
  }

  function lock(callback) {
    send({ cmd: "lock" }, callback)
  }

  function scan(callback) {
    send({ cmd: "scan" }, _thenRefresh(callback))
  }

  function add(text, callback) {
    send({ cmd: "add", text: text }, _thenRefresh(callback))
  }

  function remove(id, callback) {
    send({ cmd: "remove", id: id }, _thenRefresh(callback))
  }

  function copy(id, seconds, callback) {
    send({ cmd: "copy", id: id, seconds: seconds }, callback)
  }

  function cameraStart(callback) {
    send({ cmd: "cameraStart" }, callback)
  }

  function cameraStatus(callback) {
    send({ cmd: "cameraStatus" }, callback)
  }

  function cameraStop(callback) {
    send({ cmd: "cameraStop" }, callback)
  }

  function changePassphrase(current, next, callback) {
    send({ cmd: "setPassphrase", current: current, next: next }, callback)
  }

  // `seq` correlates the reply; `id` stays free for account ids.
  function send(payload, callback) {
    _sequence += 1
    payload.seq = _sequence
    if (callback) _pending[_sequence] = callback

    var line = JSON.stringify(payload) + "\n"
    if (_ready) agent.write(line)
    else _queue.push(line)
  }

  // -------------------------------------------------------------- internals

  function _thenRefresh(callback) {
    return function(response) {
      if (response.ok) root.refreshCodes()
      if (callback) callback(response)
    }
  }

  function _consume(line) {
    var response
    try {
      response = JSON.parse(line)
    } catch (error) {
      return
    }

    var callback = null
    if (response.seq !== undefined && _pending[response.seq]) {
      callback = _pending[response.seq]
      delete _pending[response.seq]
    }

    _apply(response)
    if (callback) callback(response)
  }

  function _apply(response) {
    if (typeof response.vault === "string") _vaultState = response.vault

    if (Array.isArray(response.accounts)) {
      _accounts = response.accounts
      _helperNow = Model.number(response.now)
      _localBase = Date.now()
      _tick()
      _scheduleWindowRefresh()
    }

    if (_vaultState !== Model.VAULT_UNLOCKED && _accounts.length > 0) _accounts = []
  }

  function _tick() {
    if (_helperNow <= 0) return
    _now = _helperNow + (Date.now() - _localBase) / 1000
  }

  function _scheduleWindowRefresh() {
    var soonest = Model.soonestExpiry(_accounts)
    if (soonest <= 0) {
      windowTimer.stop()
      return
    }
    windowTimer.interval = Math.max(200, Math.round((soonest - _now) * 1000) + 150)
    windowTimer.restart()
  }

  function _reset(state) {
    _vaultState = state
    _accounts = []
    _pending = ({})
    _queue = []
    windowTimer.stop()
  }

  onAutoLockSecondsChanged: send({ cmd: "setAutoLock", seconds: autoLockSeconds })
  onUnlockedChanged: if (unlocked) refreshCodes()

  Process {
    id: agent
    command: [root.helperPath, "agent"]
    running: true
    stdinEnabled: true

    stdout: SplitParser {
      onRead: function(line) { root._consume(line) }
    }

    onStarted: {
      root._ready = true
      var queued = root._queue
      root._queue = []
      for (var i = 0; i < queued.length; i++) agent.write(queued[i])
      root.send({ cmd: "setAutoLock", seconds: root.autoLockSeconds })
      root.refreshStatus()
    }

    onExited: {
      root._ready = false
      root._reset(Model.VAULT_UNAVAILABLE)
      restartTimer.restart()
    }
  }

  Timer {
    interval: root.active ? 100 : 1000
    repeat: true
    running: root.unlocked
    onTriggered: root._tick()
  }

  Timer {
    id: windowTimer
    repeat: false
    onTriggered: root.refreshCodes()
  }

  Timer {
    id: restartTimer
    interval: 2000
    repeat: false
    onTriggered: agent.running = true
  }
}
